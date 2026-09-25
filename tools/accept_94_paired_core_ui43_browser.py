#!/usr/bin/env python3
"""#219 exact candidate: real Core state, installed managed UI43, Chromium and revisions.

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
from monitorbox.v2.recovery import RecoveryManager
from monitorbox.v2.recovery_api import RecoveryApi
from monitorbox.v2.ui_module_host import install as install_ui

MODULES_ROOT=Path(os.environ["MONITORBOX_PAIRED_MODULES_ROOT"]).resolve()
sys.path.insert(0,str(MODULES_ROOT/"tools"))
import build_first_party_ui_build43 as ui_builder  # noqa:E402
import stage_91_ui_build42 as ui_stage  # noqa:E402

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
        "a2-cpu": {"cpu.usage": 41, "cpu.temperature_c": 55},
        "a2-memory": {"memory.used_percent": 62},
        "goliath-pool": {"pool.free_bytes": 123456789},
        "power-check": {"battery.charge": 85},
    }.items():
        evidence[("lab",check_id)]["metrics"]=values
    site=SiteConfig(
        id="lab",label="Synthetic Lab",agents=(AgentDefinition("monitor","Monitor"),),
        objects=tuple(objects),checks=tuple(checks),generation="paired-ui43",
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
    meta={**ui_stage.ENTRY["manifest"],"version":"1.7.0","build":43,
          "entrypoints":{"webui":"monitorbox_ui_b43:install"}}
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
        artifact_filename=ui_builder.RELEASE43.filename,
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

    def start(self):
        result=queue.Queue()
        def run():
            loop=asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async def boot():
                runtime=ModuleManagementRuntime.for_root(self.root)
                installed=runtime.install_verified(self.artifact,self.blob)
                assert installed.active.manifest.build==43
                app=web.Application()
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
                assert (activation.version,activation.build)==("1.7.0",43)
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
            "UI43 validation: "+page.locator("#layoutStatus").inner_text()
        ) from error
    page.locator("#apply").click()
    page.locator("#preview").wait_for(state="hidden",timeout=10000)


def browser_contract(server:PairedServer):
    base=f"http://127.0.0.1:{server.port}"
    store=CanonicalConfigStore(server.root)
    initial=store.load()
    original=initial.data["module_preferences"][UI_ID]
    assert original["schema_version"]==3,original
    assert original["data"]["sites"]["lab"]["mode"]=="auto"
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for width,height in ((820,1050),(1366,900)):
                # Independent browser contexts against the same disposable Core.
                context=browser.new_context(viewport={"width":width,"height":height})
                page=context.new_page()
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(base+"/",wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => window.MonitorBoxCardLayout?.state().loaded===true",
                    timeout=20000,
                )
                homepage=page.locator("#core-grid").inner_text()
                for expected in ("Arrrrr2","Goliath","Network","Cameras","Power"):
                    assert expected in homepage,(expected,homepage)
                assert "Edge 01" not in homepage
                assert page.locator("#card-layout-edit").count()==0
                # Registry must expose the ACTUAL Core observation metrics,
                # not values invented in a disposable UI mock.
                metrics=page.evaluate("""() => {
                  const site=app.state.sites[0], cat=MonitorBoxCardItems.catalog(site);
                  return cat.groups.flatMap(g=>g.sources.flatMap(s=>s.items))
                    .filter(item=>item.type==='metric')
                    .map(item=>({source:item.sourceId,metric:item.metricKey,
                      observed:MonitorBoxCardItems.display(site,item.key,cat.items).value}));
                }""")
                for source,metric,value in (
                    ("arrrrr2","cpu.usage",41),
                    ("arrrrr2","memory.used_percent",62),
                    ("goliath","pool.free_bytes",123456789),
                    ("power-one","battery.charge",85),
                ):
                    assert any(item["source"]==source and
                        item["metric"]==metric and item["observed"]==value
                        for item in metrics),(source,metric,metrics)

                page.goto(base+"/settings/cards",wait_until="networkidle")
                page.locator("#password").fill(PASSWORD)
                page.locator("#loginButton").click()
                page.locator("#selected .layout-row").first.wait_for(timeout=10000)
                assert page.locator("#showDiscovered").count()==0
                assert page.locator("#available .available-item").count()==0

                host=page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
                host.get_by_role("button",name="Edit contents").click()
                page.locator("#addContentItem").click()
                _choose(page,"cpu.usage","cpu · usage")
                _choose(page,"memory.used_percent","memory · used percent")
                page.locator("#donePicker").click()
                assert page.locator("#contentSelectedItems .mb-selected-item").count()==2
                _save(page)
                first=store.load()
                first_entry=first.data["module_preferences"][UI_ID]
                assert first_entry["schema_version"]==3
                host_row=next(row for row in first_entry["data"]["sites"]["lab"]["cards"]
                              if row["id"]=="host:arrrrr2")
                assert len(host_row["presentation"]["items"])==2

                page.locator("#createCustom").click()
                page.locator("#newCardTitle").fill("Infrastructure")
                page.locator("#saveNewCard").click()
                page.locator("#addContentItem").click()
                _choose(page,"cpu.usage","cpu · usage")
                _choose(page,"pool.free_bytes","pool · free bytes")
                _choose(page,"Aggregation","Aggregation · status")
                _choose(page,"battery.charge","battery · charge")
                page.locator("#donePicker").click()
                assert page.locator("#contentSelectedItems .mb-selected-item").count()==4
                _save(page)
                second=store.load()
                assert second.revision==first.revision+1
                final_entry=second.data["module_preferences"][UI_ID]
                custom=next(row for row in final_entry["data"]["sites"]["lab"]["cards"]
                            if row["id"].startswith("custom:"))
                assert custom["presentation"]["title"]=="Infrastructure"
                assert len(custom["presentation"]["items"])==4
                page.goto(base+"/",wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => window.MonitorBoxCardLayout?.state().loaded===true",
                    timeout=20000,
                )
                rendered=page.locator("#core-grid").inner_text()
                assert "Infrastructure" in rendered,rendered
                assert "41" in rendered and "85" in rendered,rendered

                first_name=f"{first.revision:08d}-{first.content_hash[:16]}.yaml"
                restored=RecoveryManager(server.root).restore_revision(first_name)
                assert restored.preferences_restored is True
                assert store.load().data["module_preferences"][UI_ID]==first_entry
                page.goto(base+"/",wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => window.MonitorBoxCardLayout?.state().loaded===true",
                    timeout=20000,
                )
                assert "Infrastructure" not in page.locator("#core-grid").inner_text()
                second_name=f"{second.revision:08d}-{second.content_hash[:16]}.yaml"
                restored=RecoveryManager(server.root).restore_revision(second_name)
                assert restored.preferences_restored is True
                assert store.load().data["module_preferences"][UI_ID]==final_entry
                page.goto(base+"/",wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => window.MonitorBoxCardLayout?.state().loaded===true",
                    timeout=20000,
                )
                assert "Infrastructure" in page.locator("#core-grid").inner_text()
                assert not errors,errors
                context.close()
                print(f"UI43 real Core/managed UI + observed cross-provider metrics "
                      f"and A/B snapshots: PASS {width}x{height}")
                # Each device-size run begins with a new exact automatic
                # preference revision, preserving append-only Core history.
                store.commit(replace_preference(store.load().data,UI_ID,original))
                page.close()

            # Historical UI43-v2 rows, including hidden Network members,
            # upgrade only on explicit edit and restore without mutation.
            v2={"schema_version":2,"data":{"sites":{"lab":{"mode":"custom",
                "cards":[{"id":"host:arrrrr2","visible":True},
                         {"id":"family:network","visible":True,
                          "presentation":{"schema_version":1,
                              "hidden_member_ids":["aggregation"]}}]}}}}
            legacy=store.commit(replace_preference(store.load().data,UI_ID,v2)).document
            context=browser.new_context(viewport={"width":820,"height":1100})
            page=context.new_page()
            page.goto(base+"/settings/cards",wait_until="domcontentloaded")
            page.locator("#selected .layout-row").first.wait_for(timeout=10000)
            host=page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
            host.get_by_role("button",name="Edit contents").click()
            page.locator("#addContentItem").click()
            _choose(page,"cpu.usage","cpu · usage")
            page.locator("#donePicker").click()
            _save(page)
            migrated=store.load().data["module_preferences"][UI_ID]
            assert migrated["schema_version"]==3
            network=next(r for r in migrated["data"]["sites"]["lab"]["cards"]
                         if r["id"]=="family:network")
            assert network["presentation"]["hidden_member_ids"]==["aggregation"]
            legacy_name=f"{legacy.revision:08d}-{legacy.content_hash[:16]}.yaml"
            assert RecoveryManager(server.root).restore_revision(
                legacy_name).preferences_restored is True
            assert store.load().data["module_preferences"][UI_ID]==v2
            context.close()
            print("UI43 exact historical UI43-v2 migration and rollback: PASS")
        finally:
            browser.close()

def main():
    from monitorbox import __version__
    assert __version__=="2.6.0", "paired test requires exact Core 2.6.0 candidate"
    blob,artifact,digest=archive()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui43-paired-") as temp:
        root=Path(temp)
        prepare(root)
        server=PairedServer(root,blob,artifact)
        server.start()
        try:browser_contract(server)
        finally:server.stop()
    print("UI43 exact source sha256="+digest)


if __name__=="__main__":
    main()
