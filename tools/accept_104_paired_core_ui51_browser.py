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
import build_first_party_ui_build51 as ui_builder  # noqa:E402
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
    meta={**ui_stage.ENTRY["manifest"],"version":"1.15.0","build":51,
          "entrypoints":{"webui":"monitorbox_ui_b51:install"}}
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
        artifact_filename=ui_builder.RELEASE51.filename,
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

    def start(self):
        result=queue.Queue()
        def run():
            loop=asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            async def boot():
                runtime=ModuleManagementRuntime.for_root(self.root)
                installed=runtime.install_verified(self.artifact,self.blob)
                assert installed.active.manifest.build==51
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
                bridge.ingest("lab","monitor",{"points":[
                    {"series_id":"a2-cpu-live","check_id":"a2-cpu",
                     "object_id":"arrrrr2","label":"CPU live",
                     "kind":"gauge","unit":"%","timestamp":stamp,
                     "valid":True,"value":41},
                    {"series_id":"goliath-pool-live","check_id":"goliath-pool",
                     "object_id":"goliath","label":"Pool live",
                     "kind":"gauge","unit":"%","timestamp":stamp,
                     "valid":True,"value":62},
                ]})
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
                assert (activation.version,activation.build)==("1.15.0",51)
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
            "UI48 validation: "+page.locator("#layoutStatus").inner_text()
        ) from error
    page.locator("#apply").click()
    page.locator("#preview").wait_for(state="hidden",timeout=10000)



def browser_contract(server: PairedServer):
    """Install real managed UI51 on real Core and round-trip real revisions.

    The test intentionally creates legacy operator-selected cards in a
    disposable Core first: the operator's one-time clean-bootstrap command
    must discard all those card preferences, not monitored resources.
    """
    from copy import deepcopy

    base = f"http://127.0.0.1:{server.port}"
    store = CanonicalConfigStore(server.root)
    initial = store.load()
    original = deepcopy(initial.data["module_preferences"][UI_ID])
    assert original["schema_version"] in (1, 2, 3, 4), original
    old_site = deepcopy(original["data"]["sites"]["lab"])
    assert old_site["cards"], "real Core failed to project initial UI defaults"
    old_site["mode"] = "custom"
    old_site["arranged"] = True
    for index, row in enumerate(old_site["cards"]):
        row["placement"] = {"column": index % 3}
    a2 = next(row for row in old_site["cards"] if row["id"] == "host:arrrrr2")
    a2["presentation"] = {"schema_version": 2, "title": "Manual Arrrrr2",
                          "items": [{
                              "key": '["object","arrrrr2","metric","a2-cpu","cpu.usage"]',
                              "mode": "value",
                          }]}
    old_site["cards"].append({
        "id": "custom:legacy", "visible": True, "placement": {"column": 2},
        "presentation": {"schema_version": 2, "title": "Manual legacy",
                         "items": []},
    })
    legacy = {"schema_version": 4, "data": {"sites": {"lab": old_site}}}
    dirty = store.commit(replace_preference(store.load().data, UI_ID, legacy)).document
    assert dirty.data["module_preferences"][UI_ID] == legacy
    assert len(dirty.data["sites"]) == 1
    print("UI51 paired real Core: synthetic legacy custom contents/placement staged")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 960})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(base + "/", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => MonitorBoxCardLayout?.state().loaded===true",
                timeout=20000,
            )
            assert "Manual legacy" in page.locator("#core-grid").inner_text()
            page.goto(base + "/settings/cards", wait_until="domcontentloaded")
            page.locator("#password").fill(PASSWORD)
            page.locator("#loginButton").click()
            page.locator("#selected .layout-row").first.wait_for(timeout=15000)
            assert page.locator("#selected .layout-row").count() == len(old_site["cards"])
            assert page.locator("#selected").get_by_text("Manual legacy").count() == 1
            expected = page.evaluate(
                "(site)=>MonitorBoxCardPolicy.defaults(site,site.objects).map(row=>row.id)",
                server.projection,
            )
            assert expected and "custom:legacy" not in expected
            # Real Core's observed numeric metrics drive the SAME default
            # curation used at fresh bootstrap and explicit regeneration.
            observed=page.evaluate("""site=>{
              const pref=MonitorBoxCardPolicy.defaults(site,site.objects);
              const index=MonitorBoxCardItems.catalog(site).items;
              return Object.fromEntries(pref.filter(row=>row.id.startsWith('host:'))
                .map(row=>[row.id,(row.presentation?.items||[])
                  .map(x=>MonitorBoxCardItems.display(site,x.key,index))
                  .map(x=>({metric:x.metricKey,value:x.value,available:x.available}))]));
            }""",server.projection)
            for key,metric,value in (
                ("host:arrrrr2","cpu.usage",41),
                ("host:arrrrr2","memory.used_percent",62),
                ("host:goliath","pool.free_bytes",123456789),
            ):
                assert any(x["metric"]==metric and x["available"] and
                    x["value"]==value for x in observed[key]),(key,metric,observed)
            # The operator's explicit destructive command is only a DRAFT.
            page.once("dialog", lambda dialog: dialog.accept())
            assert page.locator("#regenerate").count()==1
            assert not page.locator("#regenScope").is_visible()
            assert page.locator("#reset,#rebuildBootstrap").count()==0
            page.locator("#regenerate").click()
            assert store.load().data["module_preferences"][UI_ID] == legacy, (
                "Unapplied clean bootstrap mutated canonical config")
            staged = page.locator("#selected .layout-row strong").all_inner_texts()
            assert len(staged) == len(expected) and "Manual legacy" not in staged, staged
            page.locator("#validate").click()
            assert "automatic columns" in page.locator("#previewSummary").inner_text()
            assert "recoverable configuration revision" in (
                page.locator("#previewSummary").inner_text()
            )
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden", timeout=15000)
            clean = store.load()
            assert clean.revision == dirty.revision + 1
            rebuilt = deepcopy(clean.data["module_preferences"][UI_ID])
            assert rebuilt["schema_version"] == 4
            site = rebuilt["data"]["sites"]["lab"]
            assert site["mode"] == "auto" and site.get("arranged") is not True
            assert [row["id"] for row in site["cards"]] == expected
            assert all("placement" not in row for row in site["cards"])
            assert len(next(x for x in site["cards"]
                if x["id"]=="host:arrrrr2")["presentation"]["items"])>=2
            assert any("pool.free_bytes" in x["key"] for x in next(
                item for item in site["cards"] if item["id"]=="host:goliath"
            )["presentation"]["items"])
            assert "custom:legacy" not in str(rebuilt)
            # The initial site, observed metrics and live stream survive.
            assert site_snapshot()["cards"], "real Core projection disappeared"
            assert store.load().data["sites"] == dirty.data["sites"]
            page.goto(base + "/", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => MonitorBoxCardLayout?.state().loaded===true",
                timeout=20000,
            )
            rendered = page.locator("#core-grid").inner_text()
            assert "Manual legacy" not in rendered
            for expected_card in ("Arrrrr2", "Goliath", "Network", "Cameras", "Power"):
                assert expected_card in rendered, (expected_card, rendered)
            assert "Edge 01" not in rendered, (
                "Discovered module-owned children exploded into new host cards")

            # Same real managed-homepage renderer at exactly the same width.
            page.goto(base + "/settings/cards", wait_until="domcontentloaded")
            page.locator("#selected .layout-row").first.wait_for(timeout=15000)
            page.locator("#arrange").click()
            frame = page.frame_locator("#mb-arrange-actual-homepage")
            frame.locator(".mb-arrange-frame-card").first.wait_for(timeout=15000)
            home = context.new_page()
            home.on("pageerror", lambda err: errors.append(str(err)))
            home.goto(base + "/", wait_until="domcontentloaded")
            home.locator(".mb-card-column").first.wait_for(timeout=15000)
            identity = """nodes=>Object.fromEntries(nodes.map(n=>{
              const card=n.matches('.mb-arrange-frame-card')
                ?n.querySelector('.parity-card,.mb-card-shell'):n;
              const id=card.dataset.object ||
                card.querySelector('[data-object]')?.dataset.object ||
                card.dataset.mbCustomCardId;
              return [id,card.innerText.trim()];
            }))"""
            actual = home.locator(
                ".mb-card-column > .parity-card, .mb-card-column > .mb-card-shell"
            ).evaluate_all(identity)
            preview = frame.locator(".mb-arrange-frame-card").evaluate_all(identity)
            assert preview == actual, (preview, actual)
            assert len(preview) == len(expected)
            assert frame.locator(".mb-arrange-menu-button").count()==0
            page.wait_for_function(
                "() => document.querySelector('#arrangeStatus')?.textContent.includes('ready')")
            grip=frame.locator(
                '.mb-arrange-frame-card[data-mb-arrange-card="host:arrrrr2"] '
                '.mb-arrange-handle').bounding_box()
            native=frame.locator(
                '.mb-arrange-frame-card[data-mb-arrange-card="host:arrrrr2"] '
                '.mb-card-shell').bounding_box()
            assert grip and native and grip["y"]+grip["height"]<=native["y"]+2,(
                "Grip overlaps host title or health",grip,native)
            # Explicit staging and Undo cannot mutate the real Core snapshot.
            # A clean bootstrap may ALREADY place Power in the left
            # column. Never claim a no-op is evidence that Undo works.
            power_card = (
                '.mb-arrange-frame-card[data-mb-arrange-card="family:power"]'
            )
            power_menu = power_card + ' .mb-arrange-handle'
            first_lane = frame.locator(power_card).evaluate(
                "(el)=>Number(el.closest('.mb-card-column').dataset.mbArrangeColumn)")
            away = (first_lane + 1) % 3
            frame.locator(power_menu).click()
            frame.get_by_label("Move Power to column").select_option(str(away))
            frame.locator(
                '.mb-card-column[data-mb-arrange-column="' + str(away) + '"] ' +
                power_card
            ).wait_for()
            assert page.locator("#undoArrange").is_enabled(), (
                "An actual cross-lane move must be undoable")
            page.locator("#undoArrange").click()
            frame.locator(
                '.mb-card-column[data-mb-arrange-column="' + str(first_lane) +
                '"] ' + power_card
            ).wait_for()
            assert store.load().data["module_preferences"][UI_ID] == rebuilt

            # Exercise a real move ending in column 0 even when the automatic
            # baseline put Power there already. Any intermediate layout
            # remains draft-only until the single canonical Apply below.
            if first_lane == 0:
                frame.locator(power_menu).click()
                frame.get_by_label("Move Power to column").select_option(str(away))
                frame.locator(
                    '.mb-card-column[data-mb-arrange-column="' + str(away) + '"] ' +
                    power_card
                ).wait_for()
            frame.locator(power_menu).click()
            frame.get_by_label("Move Power to column").select_option("0")
            frame.locator(
                '.mb-card-column[data-mb-arrange-column="0"] ' + power_card
            ).wait_for()
            page.locator("#doneArrange").click()
            page.locator("#validate").click()
            page.locator("#apply").click()
            page.locator("#preview").wait_for(state="hidden", timeout=15000)
            arranged_doc = store.load()
            assert arranged_doc.revision == clean.revision + 1
            arranged = deepcopy(arranged_doc.data["module_preferences"][UI_ID])
            arrangement = arranged["data"]["sites"]["lab"]
            assert arrangement["arranged"] is True
            assert all(row.get("placement") for row in arrangement["cards"])
            assert next(row for row in arrangement["cards"]
                        if row["id"] == "family:power")["placement"]["column"] == 0

            # Real RecoveryManager, retained YAML and canonical Core state:
            # A/B restore must recover both *old* and new layout bytes.
            def restore(doc, expected_prefs):
                filename = f"{doc.revision:08d}-{doc.content_hash[:16]}.yaml"
                operation = RecoveryManager(server.root).restore_revision(filename)
                assert operation.preferences_restored is True
                actual_pref = store.load().data["module_preferences"][UI_ID]
                assert actual_pref == expected_prefs, (filename, actual_pref)
            restore(clean, rebuilt)
            restore(arranged_doc, arranged)
            restore(dirty, legacy)
            page.reload(wait_until="domcontentloaded")
            page.locator("#selected .layout-row").first.wait_for(timeout=15000)
            assert "Manual legacy" in page.locator("#selected").inner_text(), (
                "Legacy snapshot was silently reset to bootstrap defaults")
            assert not errors, errors
            home.close()
            context.close()
            print("UI51 real Core 2.6.0: managed loader, one-revision "
                  "destructive operator draft, exact homepage preview, "
                  "A/B and legacy retained snapshot restore PASS")
        finally:
            browser.close()


def main():
    from monitorbox import __version__
    assert __version__ == "2.6.0", "pin accepted Core v2.6.0 for paired qualification"
    blob, artifact, digest = archive()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui51-paired-") as temp:
        root = Path(temp)
        prepare(root)
        server = PairedServer(root, blob, artifact)
        server.start()
        try:
            browser_contract(server)
        finally:
            server.stop()
    print("UI51 exact package sha256=" + digest)


if __name__ == "__main__":
    main()
