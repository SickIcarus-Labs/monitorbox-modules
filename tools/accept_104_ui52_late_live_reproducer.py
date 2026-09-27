#!/usr/bin/env python3
"""#410 known-gap reproducer: actual Core startup before LIVE is advertised.

PASS means the first-start late-LIVE difference was faithfully reproduced,
NOT that production first-ready finalization exists. Do not treat this test
as satisfying UI52's release gate.
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

import accept_104_paired_core_ui52_bootstrap as paired
from monitorbox.v2.canonical_store import CanonicalConfigStore


def main() -> None:
    blob,artifact,digest=paired.archive()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui52-late-live-") as temp:
        root=Path(temp)
        paired.prepare(root)  # REAL accepted-Core first-authority commit
        server=paired.PairedServer(root,blob,artifact)
        server.defer_live_until_bound=True
        server.start()
        try:
            store=CanonicalConfigStore(root)
            initial=store.load()
            old=copy.deepcopy(initial.data["module_preferences"][paired.UI_ID])
            assert old["schema_version"]==5
            rows=old["data"]["sites"]["lab"]["cards"]
            saved_a2=next(r for r in rows if r["id"]=="host:arrrrr2")
            assert saved_a2["presentation"]["items"],saved_a2
            assert not any('"live"' in item["key"]
                for item in saved_a2["presentation"]["items"]),(
                "The test accidentally advertised LIVE before Core startup")
            assert not server.live_metadata

            # First actual agent series advertisement happens AFTER bind and
            # AFTER Core's pre-serve module preference initializer has run.
            server.advertise_late()
            assert len(server.live_metadata)==2
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                page=browser.new_page(viewport={"width":1366,"height":950})
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                try:
                    page.goto(f"http://127.0.0.1:{server.port}/",
                              wait_until="domcontentloaded")
                    page.wait_for_function("""()=>globalThis.MonitorBoxCardLayout?.state().loaded===true &&
                        app.liveTelemetry?.series?.length>=2""",timeout=20000)
                    current=page.evaluate("""site=>{
                      MonitorBoxCardItems.setLiveSeries(app.liveTelemetry);
                      return MonitorBoxCardPolicy.defaults(site,site.objects);
                    }""",server.projection)
                    now_a2=next(r for r in current if r["id"]=="host:arrrrr2")
                    assert any('"live"' in x["key"]
                        for x in now_a2["presentation"]["items"]),now_a2
                    assert old["data"]["sites"]["lab"]["cards"]!=current,(
                        "Expected the known Core first-ready lifecycle mismatch")
                    assert [x["id"] for x in rows]==[x["id"] for x in current],(
                        "Actual structural site inventory unexpectedly changed")
                    page.wait_for_timeout(1200)
                    assert store.load().data["module_preferences"][paired.UI_ID]==old,(
                        "A public LIVE sample unexpectedly mutated canonical authority")
                    print("REPRODUCED #410: accepted-Core pre-serve initializer "
                          "saves truthful state-only schema-v5 defaults; "
                          "LIVE CPU is advertised only after server bind, "
                          "but the recorded automatic snapshot is not finalized.")

                    # Reset MUST work without rerunning the wizard or touching
                    # modules, credentials, checks, graphs or other sites.
                    page.goto(f"http://127.0.0.1:{server.port}/settings/cards",
                              wait_until="domcontentloaded")
                    page.locator("#password").fill(paired.PASSWORD)
                    page.locator("#loginButton").click()
                    page.locator("#selected .layout-row").first.wait_for(timeout=15000)
                    page.once("dialog",lambda d:d.accept())
                    page.locator("#regenerate").click()
                    assert store.load().data["module_preferences"][paired.UI_ID]==old
                    page.locator("#validate").click()
                    page.locator("#apply").click()
                    page.locator("#preview").wait_for(state="hidden",timeout=15000)
                    after=store.load()
                    assert after.revision==initial.revision+1
                    reset=after.data["module_preferences"][paired.UI_ID]
                    assert reset["data"]["sites"]["lab"]["cards"]==current,(
                        "The explicit Reset must use exactly the now-ready generator")
                    assert after.data["sites"]==initial.data["sites"]
                    assert not errors,errors
                    print("UI52 workaround only: user-initiated authenticated "
                          "Regenerate after LIVE availability yields the right "
                          "cards in ONE canonical revision, without wizard rerun.")
                finally:
                    browser.close()
        finally:
            server.stop()
    print("KNOWN BLOCKER remains: no production first-ready automatic "
          "finalization contract; signed dev publication forbidden.")


if __name__=="__main__":
    main()
