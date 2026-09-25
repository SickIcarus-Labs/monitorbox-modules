#!/usr/bin/env python3
"""#219 exact candidate: real Core state, installed managed UI42, Chromium and revisions.

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
import build_first_party_ui_build42 as ui_builder  # noqa:E402
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
    site=SiteConfig(
        id="lab",label="Synthetic Lab",agents=(AgentDefinition("monitor","Monitor"),),
        objects=tuple(objects),checks=tuple(checks),generation="paired-ui42",
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
    meta=ui_stage.ENTRY["manifest"]
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
        artifact_filename=ui_builder.RELEASE41.filename,
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
                assert installed.active.manifest.build==41
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
                assert (activation.version,activation.build)==("1.5.0",41)
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


def browser_contract(server:PairedServer):
    base=f"http://127.0.0.1:{server.port}"
    # The real UI42 module must have registered and atomically persisted its
    # first-use default BEFORE HTTP serves even the first homepage request.
    initial=CanonicalConfigStore(server.root).load()
    automatic={"schema_version":1,"data":{"sites":{"lab":{
        "mode":"auto",
        "cards":[{"id":card,"visible":True} for card in (
            "host:arrrrr2","host:goliath","host:router",
            "family:internet","family:network","family:cameras",
            "family:power","family:solar","family:zigbee",
        )],
    }}}}
    assert initial.data["module_preferences"][UI_ID] == automatic
    assert "restored_preference_ids" not in initial.data["metadata"]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            context=browser.new_context(viewport={"width":820,"height":1050})
            page=context.new_page()
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.MonitorBoxCardLayout?.state().loaded===true",timeout=20000
            )
            text=page.locator("#core-grid").inner_text()
            for expected in ("Arrrrr2","Goliath","Site router","Internet",
                             "Network","Cameras","Power","Solar","Zigbee"):
                assert expected in text,(expected,text)
            for missing in ("Edge 01","Edge 30","Docker via"):
                assert missing not in text,(missing,text)
            card_ids=page.evaluate(
                "() => MonitorBoxCardLayout.effectiveCards(app.state.sites[0]).map(row=>row.id)"
            )
            assert len(card_ids)==9,card_ids
            assert page.locator("#card-layout-edit").count()==0
            page.goto(base+"/settings/dashboard",wait_until="networkidle")
            assert page.locator("#mb-dashboard-editor-tabs a").count()==2
            page.locator("#mb-dashboard-editor-tabs").get_by_text("Cards").click()
            page.wait_for_url("**/settings/cards")
            page.locator("#password").fill(PASSWORD)
            page.locator("#loginButton").click()
            page.locator("#selected .layout-row").first.wait_for(timeout=10000)
            assert "Arrrrr2" in page.locator("#selected").inner_text()
            assert page.locator("#available .available-item").count()==0
            assert "discovered" in page.locator("#discoveredCount").inner_text()
            page.locator("#showDiscovered").check()
            page.locator("#search").fill("edge-01")
            available=page.locator("#available .available-item").filter(has_text="Edge 01")
            available.locator("button").click()
            page.locator('#selected input[aria-label="Show Cameras"]').uncheck()
            network=page.locator("#selected .layout-row").filter(has_text="Network").first
            network.get_by_role("button",name="Edit contents").click()
            page.locator("#contentTitle").fill("My LAN")
            page.locator("#contentMembers .member-option").filter(
                has_text="Edge 03").locator("input").uncheck()
            page.locator("#saveContents").click()
            assert page.locator("#selected").get_by_text("My LAN",exact=True).count()==1
            page.locator("#validate").click()
            page.locator("#preview").wait_for(state="visible")
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden")
            first=CanonicalConfigStore(server.root).load()
            first_entry=first.data["module_preferences"][UI_ID]
            assert {"id":"host:edge-01","visible":True} in first_entry["data"]["sites"]["lab"]["cards"]
            assert {"id":"family:cameras","visible":False} in first_entry["data"]["sites"]["lab"]["cards"]
            network_saved=next(row for row in first_entry["data"]["sites"]["lab"]["cards"]
                               if row["id"]=="family:network")
            assert network_saved["presentation"]=={
                "schema_version":1,"title":"My LAN","hidden_member_ids":["edge-03"],
            }
            assert first.revision>=1
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.MonitorBoxCardLayout?.state().loaded===true",timeout=20000
            )
            text=page.locator("#core-grid").inner_text()
            assert "Edge 01" in text and "Cameras" not in text,text
            assert "My LAN" in text,text
            lan=page.locator("#core-grid .parity-card").filter(has_text="My LAN")
            assert "Edge 03" not in lan.inner_text()
            # Homepage selection does not remove the canonical child or its checks.
            assert any(o["id"]=="edge-03" for o in server.projection["objects"])
            assert "Edge 02" not in text and "Edge 30" not in text,text
            # Create a second true UI-only revision, then revert using the
            # standard retained-revision product path, not local browser state.
            page.goto(base+"/settings/cards",wait_until="networkidle")
            page.locator("#selected .layout-row").first.wait_for()
            page.locator('#selected input[aria-label="Show Cameras"]').check()
            page.locator("#validate").click()
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden")
            second=CanonicalConfigStore(server.root).load()
            assert second.revision==first.revision+1
            first_name=f"{first.revision:08d}-{first.content_hash[:16]}.yaml"
            restored=RecoveryManager(server.root).restore_revision(first_name)
            assert restored.preferences_restored is True
            after=CanonicalConfigStore(server.root).load()
            assert after.data["module_preferences"][UI_ID]==first_entry
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.MonitorBoxCardLayout?.state().loaded===true",timeout=20000
            )
            assert "Cameras" not in page.locator("#core-grid").inner_text()
            assert "Edge 01" in page.locator("#core-grid").inner_text()
            assert "My LAN" in page.locator("#core-grid").inner_text()
            # Untouched *post-installation* automatic A is a real revision,
            # unlike historical pre-layout revisions. Restoring A after B
            # must produce A's automatic homepage, never inherit B.
            # A new contributed family becomes available after A was saved.
            # It is discoverable, but restoring A must not silently promote it.
            server.projection["cards"].append({
                "id":"battery","family":"battery","kind":"dashboard_card",
                "label":"Battery","state":"healthy","summary":"Synthetic battery",
                "components":[],"member_object_ids":[],"contributors":[],
            })
            automatic_name=f"{initial.revision:08d}-{initial.content_hash[:16]}.yaml"
            auto_result=RecoveryManager(server.root).restore_revision(automatic_name)
            assert auto_result.preferences_restored is True
            assert CanonicalConfigStore(server.root).load().data[
                "module_preferences"
            ][UI_ID]==automatic
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.MonitorBoxCardLayout?.state().loaded===true",timeout=20000
            )
            current_text=page.locator("#core-grid").inner_text()
            assert "Cameras" in current_text and "Edge 01" not in current_text,current_text
            assert "My LAN" not in current_text and "Network" in current_text,current_text
            assert "Battery" not in current_text,current_text
            pinned=CanonicalConfigStore(server.root).load()
            assert UI_ID in pinned.data["metadata"]["restored_preference_ids"]
            # Explicit Reset to Defaults is a DIFFERENT operation from
            # restoring A. It deliberately uses the current family registry.
            page.goto(base+"/settings/cards",wait_until="domcontentloaded")
            page.locator("#selected .layout-row").first.wait_for(timeout=10000)
            assert "Battery" in page.locator("#available").inner_text()
            page.locator("#reset").click()
            page.locator("#validate").click()
            page.locator("#preview").wait_for(state="visible")
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden")
            reset=CanonicalConfigStore(server.root).load()
            assert UI_ID not in reset.data["metadata"].get("restored_preference_ids",[])
            assert "family:battery" in [
                item["id"] for item in
                reset.data["module_preferences"][UI_ID]["data"]["sites"]["lab"]["cards"]
            ]
            page.goto(base+"/",wait_until="domcontentloaded")
            page.wait_for_function(
                "() => window.MonitorBoxCardLayout?.state().loaded===true",timeout=20000
            )
            assert "Battery" in page.locator("#core-grid").inner_text()
            assert not errors,errors
            context.close()
            print("UI42 paired real Core/managed loader/iPad Chromium/content+layout snapshots: PASS")
        finally:
            browser.close()


def main():
    from monitorbox import __version__
    assert __version__=="2.6.0", "paired test requires exact Core 2.6.0 candidate"
    blob,artifact,digest=archive()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui42-paired-") as temp:
        root=Path(temp)
        prepare(root)
        server=PairedServer(root,blob,artifact)
        server.start()
        try:browser_contract(server)
        finally:server.stop()
    print("UI42 exact source sha256="+digest)


if __name__=="__main__":
    main()
