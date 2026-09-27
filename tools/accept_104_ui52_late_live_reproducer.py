#!/usr/bin/env python3
"""#410 production Core first-ready: REAL late agent metadata, one CAS finalize.

Disposable first authority, genuine managed UI52, actual Core 2.7.0 draft
preference lifecycle; no Broad Leaf devices or secrets. This test succeeds
ONLY if startup and later Reset converge automatically when LIVE arrives.
"""
from __future__ import annotations

import copy
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import accept_104_paired_core_ui52_bootstrap as paired
from monitorbox.v2.canonical_store import CanonicalConfigStore
from monitorbox.v2.module_preferences import replace_preference


def wait_for_revision(store,base,deadline=6):
    end=time.monotonic()+deadline
    while time.monotonic()<end:
        current=store.load()
        if current.revision>base:return current
        time.sleep(.04)
    raise AssertionError("Core never finalized the unchanged provisional preference")


def scenario_late(blob,artifact):
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui52-first-ready-") as d:
        root=Path(d)
        paired.prepare(root)
        server=paired.PairedServer(root,blob,artifact)
        server.defer_live_until_bound=True
        server.start()
        try:
            store=CanonicalConfigStore(root)
            initial=store.load()
            provisional=copy.deepcopy(initial.data["module_preferences"][paired.UI_ID])
            assert provisional["schema_version"]==5
            assert provisional["data"]["bootstrap_pending"] is True
            initial_cards=provisional["data"]["sites"]["lab"]["cards"]
            a2=next(row for row in initial_cards if row["id"]=="host:arrrrr2")
            assert not any('"live"' in x["key"]
                           for x in a2["presentation"]["items"])
            assert not server.live_metadata
            server.advertise_late()  # after real Core AppRunner HTTP bind
            assert len(server.live_metadata)==2
            finished=wait_for_revision(store,initial.revision)
            finalized=finished.data["module_preferences"][paired.UI_ID]
            assert finished.revision==initial.revision+1
            assert finalized["schema_version"]==5
            assert "bootstrap_pending" not in finalized["data"]
            ready_a2=next(row for row in finalized["data"]["sites"]["lab"]["cards"]
                          if row["id"]=="host:arrrrr2")
            assert any('"live"' in x["key"]
                       for x in ready_a2["presentation"]["items"])
            assert finished.data["sites"]==initial.data["sites"]
            print("UI52 Core #410: late LIVE after bind finalized automatic "
                  "v5 cards in EXACTLY one recoverable revision PASS")

            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                page=browser.new_page(viewport={"width":1366,"height":950})
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                try:
                    page.goto(f"http://127.0.0.1:{server.port}/",
                              wait_until="domcontentloaded")
                    page.wait_for_function("""()=>globalThis.MonitorBoxCardLayout?.state().loaded===true &&
                        app.liveTelemetry?.series?.length>=2""",timeout=20000)
                    expected=page.evaluate("""site=>{
                      MonitorBoxCardItems.setLiveSeries(app.liveTelemetry);
                      return MonitorBoxCardPolicy.defaults(site,site.objects);
                    }""",server.projection)
                    assert finalized["data"]["sites"]["lab"]["cards"]==expected,(
                        "First-ready autosaved defaults differ from same-site Reset")
                    # One more telemetry sample must never create another
                    # snapshot/repack or mutate canonical preference bytes.
                    server.advertise_late()
                    page.wait_for_timeout(200)
                    assert store.load().content_hash==finished.content_hash

                    # Deliberate manual choices remain editable; Reset does
                    # NOT rerun wizard or touch credentials/check definitions.
                    custom=copy.deepcopy(finalized)
                    custom["data"]["sites"]["lab"]["mode"]="custom"
                    custom["data"]["sites"]["lab"]["cards"][0][
                        "presentation"]["title"]="Manual dashboard"
                    edited=store.commit(replace_preference(
                        store.load().data,paired.UI_ID,custom)).document
                    page.goto(f"http://127.0.0.1:{server.port}/settings/cards",
                              wait_until="domcontentloaded")
                    page.locator("#password").fill(paired.PASSWORD)
                    page.locator("#loginButton").click()
                    page.locator("#selected .layout-row").first.wait_for(timeout=15000)
                    page.once("dialog",lambda dialog:dialog.accept())
                    page.locator("#regenerate").click()
                    assert store.load().content_hash==edited.content_hash
                    page.locator("#validate").click()
                    page.locator("#apply").click()
                    page.locator("#preview").wait_for(state="hidden",timeout=15000)
                    reset=store.load()
                    assert reset.revision==edited.revision+1
                    assert reset.data["module_preferences"][paired.UI_ID][
                        "data"]["sites"]["lab"]["cards"]==expected
                    assert "bootstrap_pending" not in reset.data[
                        "module_preferences"][paired.UI_ID]["data"]
                    assert reset.data["sites"]==initial.data["sites"]
                    assert not errors,errors
                    print("UI52 Core #410: first-ready = deliberate Reset on "
                          "populated site, one authenticated revision PASS")
                finally:
                    browser.close()
        finally:
            server.stop()


def scenario_no_producer(blob,artifact):
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui52-no-producer-") as d:
        root=Path(d);paired.prepare(root)
        server=paired.PairedServer(root,blob,artifact)
        server.defer_live_until_bound=True
        server.start()
        try:
            store=CanonicalConfigStore(root)
            initial=store.load()
            assert initial.data["module_preferences"][paired.UI_ID]["data"][
                "bootstrap_pending"] is True
            finished=wait_for_revision(store,initial.revision)
            assert finished.revision==initial.revision+1
            assert "bootstrap_pending" not in finished.data[
                "module_preferences"][paired.UI_ID]["data"]
            assert not any('"live"' in x["key"] for row in finished.data[
                "module_preferences"][paired.UI_ID]["data"]["sites"]["lab"]["cards"]
                for x in row["presentation"]["items"])
            server.advertise_late()
            time.sleep(.28)
            assert store.load().content_hash==finished.content_hash
            print("UI52 Core #410: bounded no-producer timeout preserved "
                  "state-only evidence and never rewrote on later samples PASS")
        finally:
            server.stop()


def scenario_operator_preempts(blob,artifact):
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui52-concurrent-") as d:
        root=Path(d);paired.prepare(root)
        server=paired.PairedServer(root,blob,artifact)
        server.defer_live_until_bound=True
        server.start()
        try:
            store=CanonicalConfigStore(root)
            provisional=store.load()
            entry=copy.deepcopy(provisional.data["module_preferences"][paired.UI_ID])
            assert entry["data"]["bootstrap_pending"] is True
            # Explicit owner action claims preference before readiness.
            entry["data"].pop("bootstrap_pending")
            entry["data"]["sites"]["lab"]["mode"]="custom"
            own=store.commit(replace_preference(
                provisional.data,paired.UI_ID,entry)).document
            server.advertise_late()
            time.sleep(.3)
            assert store.load().content_hash==own.content_hash
            assert store.load().data["module_preferences"][paired.UI_ID]==entry
            print("UI52 Core #410: intervening operator revision cancelled "
                  "first-ready mutation PASS")
        finally:
            server.stop()


def main():
    blob,artifact,digest=paired.archive()
    scenario_late(blob,artifact)
    scenario_no_producer(blob,artifact)
    scenario_operator_preempts(blob,artifact)
    print("UI52 Core #410 late readiness and reset acceptance PASS; "
          "candidate package sha256="+digest)


if __name__=="__main__":
    main()
