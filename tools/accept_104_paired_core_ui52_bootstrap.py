#!/usr/bin/env python3
"""#104 exact UI51 candidate: real accepted Core 2.6.0, managed UI, Chromium and retained revisions.

Uses only disposable CI roots, loopback HTTP and documentation addresses. The
UI package is generated from an exact pinned Modules checkout in CI.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import queue
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from playwright.sync_api import sync_playwright

from monitorbox.v2.canonical_store import CanonicalConfigStore
from monitorbox.v2.config import AgentDefinition, CheckConfig, ObjectConfig, SiteConfig
from monitorbox.v2.config_platform import ConfigPlatform
from monitorbox.v2.dashboard_config_api import DashboardConfigApi
from monitorbox.v2.module_management_runtime import ModuleManagementRuntime
from monitorbox.v2.module_preferences import replace_preference
from monitorbox.v2.onboarding_commit import FirstBootAuthorityCommitter
from monitorbox.v2.onboarding_generator import GeneratedAuthority
from monitorbox.v2.plugin_api.module_management import ManagedArtifact, VerificationRecord
from monitorbox.v2.plugin_api.module_runtime import ModuleManifest
from monitorbox.v2.presentation import build_site_snapshot
from monitorbox.v2.live_telemetry import ControllerLiveTelemetry
from monitorbox.v2.recovery import RecoveryManager
from monitorbox.v2.recovery_api import RecoveryApi
from monitorbox.v2.ui_module_host import install as install_ui

MODULES_ROOT=Path(os.environ["MONITORBOX_PAIRED_MODULES_ROOT"]).resolve()
sys.path.insert(0,str(MODULES_ROOT/"tools"))
import build_first_party_ui_build52 as ui_builder  # noqa:E402
import stage_104_ui_build51 as ui_stage  # noqa:E402

# Self-contained public Core-fixture helpers. Qualification checks out only
# the exact published Core image source, not an unrelated draft test branch.
def check(identifier: str, owner: str, adapter: str, *, family: str | None = None,
          role: str | None = None) -> CheckConfig:
    options: dict[str, str] = {}
    if family is not None:
        options["card_family"] = family
    if role is not None:
        options["diagnostic_role"] = role
    return CheckConfig(
        id=identifier, object_id=owner, label=identifier, adapter=adapter,
        interval_seconds=30, timeout_seconds=3, enabled=True, options=options,
        agent_id="monitor",
    )

def observation(identifier: str, owner: str, state: str, now: datetime,
                *, metadata: dict | None = None) -> dict:
    return {
        "event_id": "paired-" + identifier, "site_id": "lab", "agent_id": "monitor",
        "boot_id": "paired-ci", "sequence": 1, "config_generation": "paired-ci",
        "object_id": owner, "check_id": identifier,
        "observed_at": now.isoformat(), "received_at": now.isoformat(),
        "duration_ms": 1, "state": state, "summary": state,
        "metrics": {}, "metadata": metadata or {},
    }

UI_ID="com.sickicarus.monitorbox.ui"
PASSWORD="synthetic-admin-password"


def site_snapshot():
    now=datetime.now(timezone.utc)
    objects=[
        ObjectConfig("monitor","MonitorBox","appliance"),
        ObjectConfig("arrrrr2","Arrrrr2","host",homepage_origin="operator"),
        ObjectConfig("goliath","Goliath","host",homepage_origin="operator"),
        ObjectConfig("aggregation","Aggregation","network_device",homepage_origin="discovered"),
        # Historical same-ID Network aggregate suppresses the derived
        # front_page flag for child devices. This must not suppress a
        # deliberately designated gateway card.
        ObjectConfig("network","Legacy Network","integration"),
        ObjectConfig("router","Site router","network_device",
                     homepage_origin="discovered",system_role="site_gateway"),
        ObjectConfig("network-owner","Network owner","network_device",homepage_origin="discovered"),
        ObjectConfig("camera-one","Front camera","camera",homepage_origin="discovered"),
        ObjectConfig("power-one","UPS","ups",homepage_origin="module"),
        ObjectConfig("workloads","Workload inventory","integration",homepage_origin="module"),
    ]
    objects.extend(
        ObjectConfig(
            f"edge-{i:02d}",f"Edge {i:02d}",
            "host" if i%3 else "network_device",
            homepage_origin="module" if i%2 else "discovered",
            legacy_front_page=True,
        ) for i in range(1,31)
    )
    checks=[
        check("wan","monitor","icmp",family="internet",role="wan_direct_ip"),
        check("a2-cpu","arrrrr2","synthetic-host"),
        check("a2-memory","arrrrr2","synthetic-host"),
        check("goliath-pool","goliath","synthetic-storage"),
        check("aggregation-health","aggregation","icmp",family="network"),
        check("network-check","network-owner","icmp",family="network"),
        check("camera-check","camera-one","synthetic-camera",family="cameras"),
        check("power-check","power-one","synthetic-power",family="power"),
        check("workload-check","workloads","synthetic-inventory",family="services"),
        check("solar-check","monitor","synthetic-solar",family="solar"),
        check("zigbee-check","monitor","synthetic-zigbee",family="zigbee"),
    ]
    evidence={
        (("lab",item.id)):
          observation(item.id,item.object_id,"healthy",now)
        for item in checks
    }
    for check_id, values in {
        "a2-cpu": {"cpu.usage": 41, "cpu.temperature_c": 55, "cpu idle percent":93},
        "a2-memory": {"memory.used_percent": 62, "memory total kib":65322832, "memory available kib":55322832},
        "goliath-pool": {"pool.free_bytes": 123456789},
        "power-check": {"battery.charge": 85},
    }.items():
        evidence[("lab",check_id)]["metrics"]=values
    site=SiteConfig(
        id="lab",label="Synthetic Lab",agents=(AgentDefinition("monitor","Monitor"),),
        objects=tuple(objects),checks=tuple(checks),generation="paired-ui48",
    )
    projection=build_site_snapshot(
        site,evidence,connected_agents={"monitor"},now=now,
    )
    assert projection["cards"],"Core public site.cards did not materialize"
    found={row["id"]:row for row in projection["objects"]}
    assert found["edge-01"]["homepage_origin"]=="module"
    assert found["edge-03"]["homepage_origin"]=="module"
    assert found["router"]["system_role"]=="site_gateway"
    assert found["router"]["front_page"] is False
    assert found["router"]["explicit_front_page"] is None
    return projection


def prepare(root:Path):
    generated=GeneratedAuthority.fresh(
        site_label="Synthetic Lab",site_id="lab",local_address="192.0.2.5",
        token_factory=lambda:"synthetic-disposable-token",
        epoch_factory=lambda:"synthetic-disposable-epoch",
    )
    FirstBootAuthorityCommitter(root).commit(generated,admin_password=PASSWORD)


def archive():
    payload=ui_builder.stable._zip_bytes(ui_builder._package_files(MODULES_ROOT))
    digest=hashlib.sha256(payload).hexdigest()
    meta={**ui_stage.ENTRY["manifest"],"version":"1.16.0","build":52,
          "entrypoints":{"webui":"monitorbox_ui_b52:install"}}
    manifest=ModuleManifest(
        module_id=meta["module_id"],display_name=meta["display_name"],
        version=meta["version"],build=meta["build"],
        module_type=meta["module_type"],entrypoints=meta["entrypoints"],
        requires_core=meta["requires_core"],requires_runtime_api=meta["requires_runtime_api"],
        schema=meta["schema"],state_schema=meta["state_schema"],
        dependencies=tuple(meta["dependencies"]),publisher_id=meta["publisher_id"],
        permissions=tuple(meta["permissions"]),lifecycle_policy=meta["lifecycle_policy"],
        description=meta["description"],
    )
    artifact=ManagedArtifact(
        manifest=manifest,source_repository_id="exact-source-paired-ci",
        verification=VerificationRecord(
            digest_sha256=digest,verified=True,verifier="exact-source-paired-ci",
        ),
        artifact_filename=ui_builder.RELEASE52.filename,
    )
    return payload,artifact,digest


class PairedServer:
    def __init__(self,root:Path,blob:bytes,artifact:ManagedArtifact):
        self.root=root
        self.blob=blob
        self.artifact=artifact
        self.loop=None
        self.thread=None
        self.runner=None
        self.port=0
        self.projection=site_snapshot()
        self.interest_messages=[]
        self.defer_live_until_bound=False
        self.live_bridge=None
        self.live_payload=None
        self.live_metadata=[]

    def start(self):
        result=queue.Queue()
        def run():
            loop=asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async def boot():
                runtime=ModuleManagementRuntime.for_root(self.root)
                installed=runtime.install_verified(self.artifact,self.blob)
                assert installed.active.manifest.build==52
                app=web.Application()
                class SyntheticSession:
                    websocket=SimpleNamespace(closed=False)
                    async def send(_,message):
                        self.interest_messages.append(message)
                bridge=ControllerLiveTelemetry(SimpleNamespace(
                    sessions={"synthetic-monitor":SyntheticSession()},
                ))
                bridge.install(app)
                stamp=datetime.now(timezone.utc).isoformat()
                live_payload={"points":[
                    {"series_id":"a2-cpu-live","check_id":"a2-cpu",
                     "object_id":"arrrrr2","label":"CPU live",
                     "kind":"gauge","unit":"%","timestamp":stamp,
                     "valid":True,"value":41},
                    {"series_id":"goliath-pool-live","check_id":"goliath-pool",
                     "object_id":"goliath","label":"Pool live",
                     "kind":"gauge","unit":"%","timestamp":stamp,
                     "valid":True,"value":62},
                ]}
                self.live_bridge=bridge
                self.live_payload=live_payload
                if not self.defer_live_until_bound:
                    bridge.ingest("lab","monitor",live_payload)
                # The test-only hook returns current advertised series at
                # startup. Production Core presently exposes no such hook.
                app["monitorbox.ui_live_series_snapshot"] = (
                    lambda: [dict(row) for row in bridge.metadata.values()]
                )
                self.live_metadata=[dict(row) for row in bridge.metadata.values()]
                app["monitorbox.public_state_snapshot"] = lambda: {
                    "sites": [self.projection]
                }
                async def state(_):
                    return web.json_response({
                        "title":"MonitorBox","overall":self.projection["state"],
                        "sites":[self.projection],
                    },headers={"Cache-Control":"no-store"})
                async def debug(_):
                    return web.json_response({"enabled":False,"buffer_limit":200})
                async def fallback(_):
                    return web.json_response({
                        "loaded":True,"configured":False,"sites":{},"pending_count":0,
                        "visibility_impaired":False,
                    })
                app.router.add_get("/api/v2/state",state)
                app.router.add_get("/api/v2/debug/config",debug)
                platform=ConfigPlatform(self.root)
                platform.install(app)
                DashboardConfigApi(self.root).install(app)
                RecoveryApi(platform).install(app)
                activation=install_ui(app,source=runtime.installed_source())
                assert activation.healthy,activation.public()
                assert (activation.version,activation.build)==("1.16.0",52)
                assert any(
                    route.resource.canonical=="/settings/cards"
                    for route in app.router.routes()
                )
                app.router.add_route("*","/api/v2/{tail:.*}",fallback)
                runner=web.AppRunner(app)
                await runner.setup()
                sock=web.TCPSite(runner,"127.0.0.1",0)
                await sock.start()
                return runner,int(sock._server.sockets[0].getsockname()[1])
            try:
                runner,port=loop.run_until_complete(boot())
                result.put((runner,port,loop))
                loop.run_forever()
            except BaseException as error:
                result.put(error)
            finally:
                loop.close()
        self.thread=threading.Thread(target=run,daemon=True)
        self.thread.start()
        value=result.get(timeout=30)
        if isinstance(value,BaseException):raise value
        self.runner,self.port,self.loop=value

    def advertise_late(self):
        """Deliver the FIRST live advertisement only AFTER the HTTP bind."""
        if not self.defer_live_until_bound or self.loop is None:
            raise RuntimeError("The late-LIVE test needs a bound, deferred server")
        completed=threading.Event()
        def deliver():
            try:
                assert self.live_bridge is not None and self.live_payload is not None
                payload={**self.live_payload,"points":[
                    {**p,"timestamp":datetime.now(timezone.utc).isoformat()}
                    for p in self.live_payload["points"]]}
                self.live_bridge.ingest("lab","monitor",payload)
                self.live_metadata=[dict(row) for row in self.live_bridge.metadata.values()]
            finally:
                completed.set()
        self.loop.call_soon_threadsafe(deliver)
        if not completed.wait(timeout=5):
            raise RuntimeError("Late LIVE publisher did not run")
        assert self.live_metadata,"Late LIVE publisher exposed no metadata"

    def stop(self):
        if self.runner and self.loop:
            future=asyncio.run_coroutine_threadsafe(self.runner.cleanup(),self.loop)
            future.result(timeout=15)
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:self.thread.join(timeout=15)


def _choose(page, search, label):
    page.locator("#pickerSearch").fill(search)
    option=page.locator("#pickerGroups label.member-option").filter(has_text=label)
    assert option.count()==1, (search,label,option.count())
    option.locator("input").check()


def _save(page):
    page.locator("#saveContents").click()
    assert not page.locator("#contents").is_visible()
    page.locator("#validate").click()
    try:
        page.locator("#preview").wait_for(state="visible",timeout=10000)
    except Exception as error:
        raise AssertionError(
            "UI48 validation: "+page.locator("#layoutStatus").inner_text()
        ) from error
    page.locator("#apply").click()
    page.locator("#preview").wait_for(state="hidden",timeout=10000)




def browser_contract(server:PairedServer):
    """Actual Core first-boot->module activation->v5 revision, then scoped reset."""
    from copy import deepcopy
    from importlib.util import module_from_spec, spec_from_file_location

    base=f"http://127.0.0.1:{server.port}"
    store=CanonicalConfigStore(server.root)
    initial=store.load()
    automatic=deepcopy(initial.data["module_preferences"][UI_ID])
    assert automatic["schema_version"]==5,automatic
    site=automatic["data"]["sites"]["lab"]
    assert site["mode"]=="auto" and len(site["cards"])>=5
    assert all(r.get("presentation",{}).get("schema_version")==3
               for r in site["cards"])
    cards={row["id"]:row for row in site["cards"]}
    assert "host:arrrrr2" in cards and "host:goliath" in cards
    assert len(cards["family:network"]["presentation"]["member_ids"])>=2
    assert "network-owner" in cards["family:network"]["presentation"]["member_ids"]
    assert "power-one" in cards["family:power"]["presentation"]["member_ids"]
    assert cards["family:internet"]["presentation"]["native_sections"]==["diagnosis"]
    assert "custom:legacy" not in str(automatic)

    # This is the same source published inside the verified module package.
    spec=spec_from_file_location(
        "ui52_bootstrap",MODULES_ROOT/"sources/ui/1.16.0-build52/bootstrap.py")
    generator=module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(generator)
    expected=generator.generate(server.projection,server.live_metadata)
    assert site["cards"]==expected,("Core preference provider produced divergent "
        "first-launch cards",site["cards"],expected)
    print("UI52 real accepted Core: first authority->managed UI activation "
          "persisted exact schema-v5 current-capability cards PASS")

    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={"width":1366,"height":1000})
        page=context.new_page()
        errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        try:
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function("""()=>globalThis.MonitorBoxCardLayout?.state().loaded===true &&
                app.liveTelemetry?.series?.length>=2""",timeout=20000)
            computed=page.evaluate("""site=>{
              MonitorBoxCardItems.setLiveSeries(app.liveTelemetry);
              return MonitorBoxCardPolicy.defaults(site,site.objects);
            }""",server.projection)
            assert computed==expected,("Actual Core startup and actual JS Reset "
                "disagree with the exact same current inventory/LIVE input",
                computed,expected)
            assert store.load().data["module_preferences"][UI_ID]==automatic,(
                "Public homepage read must never write preferences")
            network=page.locator('[data-object="network"] [data-mb-member]')
            assert network.count()==len(cards["family:network"][
                "presentation"]["member_ids"])
            assert page.locator('[data-object="power"] [data-mb-member]').count()==1

            # A real Core legacy operator layout survives a module upgrade
            # and is replaced ONLY by explicit authenticated user Reset.
            legacy_site=deepcopy(site)
            legacy_site["mode"]="custom"
            legacy_site["arranged"]=True
            for index,row in enumerate(legacy_site["cards"]):
                row.pop("presentation",None)
                row["placement"]={"column":index%3}
            legacy_site["cards"].append({
                "id":"custom:legacy","visible":True,
                "placement":{"column":2},
                "presentation":{"schema_version":2,
                    "title":"Historical custom","items":[]}})
            historical={"schema_version":4,"data":{"sites":{"lab":legacy_site}}}
            dirty=store.commit(replace_preference(
                store.load().data,UI_ID,historical)).document
            page.goto(base+"/settings/cards",wait_until="domcontentloaded")
            page.locator("#password").fill(PASSWORD)
            page.locator("#loginButton").click()
            page.locator("#selected .layout-row").first.wait_for(timeout=15000)
            assert "Historical custom" in page.locator("#selected").inner_text()
            assert page.locator("#regenerate").count()==1
            page.once("dialog",lambda dialog:dialog.accept())
            page.locator("#regenerate").click()
            assert store.load().data["module_preferences"][UI_ID]==historical,(
                "Staging a fresh dashboard may not mutate canonical authority")
            page.locator("#validate").click()
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden",timeout=15000)
            after=store.load()
            assert after.revision==dirty.revision+1
            reset=deepcopy(after.data["module_preferences"][UI_ID])
            assert reset["schema_version"]==5
            assert reset["data"]["sites"]["lab"]["cards"]==expected,(
                "Explicit Reset and post-bootstrap write must share exact generator")
            assert after.data["sites"]==dirty.data["sites"]
            assert "Historical custom" not in str(reset)

            # This proves exact stored old/new layouts, not merely a current
            # DOM rendering that might silently regenerate after restore.
            def restore(document,want):
                filename=f"{document.revision:08d}-{document.content_hash[:16]}.yaml"
                operation=RecoveryManager(server.root).restore_revision(filename)
                assert operation.preferences_restored is True
                assert store.load().data["module_preferences"][UI_ID]==want
            restore(initial,automatic)
            restore(dirty,historical)
            restore(after,reset)
            assert not errors,errors
            print("UI52 real Core: identical first-ready and authenticated "
                "Reset bytes, one-revision Apply, exact v4/v5 A/B restore PASS")
        finally:
            context.close()
            browser.close()


def main():
    from monitorbox import __version__
    assert __version__=="2.6.0","Pin accepted Core 2.6.0"
    blob,artifact,digest=archive()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui52-paired-") as temp:
        root=Path(temp)
        prepare(root)
        server=PairedServer(root,blob,artifact)
        server.start()
        try:browser_contract(server)
        finally:server.stop()
    print("UI52 TEST ONLY package sha256="+digest)
if __name__=="__main__":main()
