#!/usr/bin/env python3
"""UI49 disposable Chromium: spatial editor/snapshot and header race.

This is synthetic Core/Chromium, not physical iPad or real managed-loader proof.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from playwright.async_api import async_playwright
import accept_ui_build42_editor_browser as server
import build_first_party_ui_build49 as candidate

ROOT = Path(__file__).resolve().parent.parent
PREFIX = candidate.TARGET_IMPORT_PACKAGE + "/assets/"
ASSETS = {p[len(PREFIX):]: body for p, body in candidate._package_files(ROOT).items()
          if p.startswith(PREFIX)}
server.ASSETS = ASSETS
LEGACY = {"schema_version":3,"data":{"sites":{"home":{"mode":"custom","cards":[
    {"id":"host:arrrrr2","visible":True},
    {"id":"family:network","visible":True},
    {"id":"family:cameras","visible":True},
    {"id":"host:goliath","visible":True},
    {"id":"family:power","visible":True},
]}}}}


async def editor_case(browser, fixture, base, width, height):
    fixture.entry = deepcopy(LEGACY)
    fixture.session = False
    fixture.revision = 10
    fixture.hash = "fixture-hash-10"
    fixture.saved.clear()
    fixture.body_log.clear()
    fixture.site = server.fixture_site()
    context = await browser.new_context(viewport={"width":width,"height":height})
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    await page.route("**/api/v2/live?*", lambda route: route.fulfill(
        status=200,json={"active":True,"series":[]}))
    await page.goto(base+"/settings/cards")
    await page.locator("#password").fill("test-secret")
    await page.locator("#loginButton").click()
    await page.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry == LEGACY, "historical read silently rewrote a snapshot"
    await page.locator("#arrange").click()
    assert await page.locator(".mb-arrange-column").count()==3
    assert await page.locator(".mb-arrange-card").count()==5
    assert await page.locator("#validate").is_disabled()
    # Reachable 44px handles are the only pointer drag initiation surface.
    handle = page.locator('.mb-arrange-card[data-mb-arrange-card="family:power"] .mb-arrange-handle')
    assert await handle.count() == 1
    assert (await handle.bounding_box())["height"] >= 41
    # Deterministic keyboard/touch alternative. Placement is staged, not applied.
    await page.get_by_label("Move Power to column").select_option("0")
    power = page.locator('.mb-arrange-column[data-mb-arrange-column="0"] '
                         '.mb-arrange-card[data-mb-arrange-card="family:power"]')
    assert await power.count() == 1
    assert fixture.entry == LEGACY, "arrangement mutated canonical configuration"
    await page.locator("#undoArrange").click()
    assert await page.locator('.mb-arrange-column[data-mb-arrange-column="0"] '
                              '.mb-arrange-card[data-mb-arrange-card="family:power"]').count()==0
    await page.get_by_label("Move Power to column").select_option("0")
    await page.locator("#doneArrange").click()
    await page.locator("#validate").click()
    assert "spatial columns" in await page.locator("#previewSummary").inner_text()
    await page.locator("#apply").click()
    await page.locator("#preview").wait_for(state="hidden")
    saved = deepcopy(fixture.entry)
    assert saved["schema_version"] == 4
    assert saved["data"]["sites"]["home"]["arranged"] is True
    cards = saved["data"]["sites"]["home"]["cards"]
    assert all(row["placement"]["column"] in (0,1,2) for row in cards)
    assert next(row for row in cards if row["id"]=="family:power")["placement"]["column"]==0
    assert len(fixture.saved)==1 and fixture.revision==11, (
        "Apply must write exactly one recoverable canonical revision")
    # A/B read compatibility: legacy auto/custom snapshot is never rewritten
    # by a reload, and placement returns intact when the saved revision returns.
    fixture.entry = deepcopy(LEGACY)
    fixture.revision += 1
    fixture.hash = "fixture-hash-12"
    await page.reload()
    await page.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry == LEGACY
    fixture.entry = saved
    fixture.revision += 1
    fixture.hash = "fixture-hash-13"
    await page.reload()
    await page.locator("#selected .layout-row").first.wait_for()
    await page.locator("#arrange").click()
    assert await page.locator('.mb-arrange-column[data-mb-arrange-column="0"] '
                              '.mb-arrange-card[data-mb-arrange-card="family:power"]').count()==1
    # Cancel must discard only the current arrangement session, not the prior
    # successfully saved configuration revision.
    await page.get_by_label("Move Power to column").select_option("2")
    await page.locator("#cancelArrange").click()
    assert fixture.entry == saved
    assert not errors, errors
    await context.close()
    print(f"UI49 {width}x{height}: legacy v3, move/undo/cancel, one Apply,"
          " A/B restored placement, accessible fallback PASS")


async def header_case(browser, base):
    context=await browser.new_context(viewport={"width":1366,"height":900})
    page=await context.new_page()
    errors=[]
    page.on("pageerror",lambda err:errors.append(str(err)))
    started=asyncio.Event()
    release=asyncio.Event()
    async def delayed_state(route):
        started.set()
        await release.wait()
        await route.fulfill(status=200,json={"sites":[{
            "id":"home","label":"Broad Leaf","state":"unknown"}]})
    await page.route("**/api/v2/state",delayed_state)
    await page.route("**/api/v2/build",lambda route:route.fulfill(
        status=200,json={"core":{"version":"2.6.0","build":999}}))
    await page.goto(base+"/settings/cards")
    await page.add_script_tag(content=ASSETS["app-shell.js"].decode())
    await asyncio.wait_for(started.wait(),timeout=8)
    await page.evaluate("""()=>{
      document.dispatchEvent(new CustomEvent('monitorbox:state',{
        detail:{sites:[{id:'home',label:'Broad Leaf',state:'healthy'}]}
      }));
    }""")
    await page.locator("#mb-shell-site:has-text('Broad Leaf · Healthy')").wait_for()
    release.set()
    await page.wait_for_timeout(220)
    assert await page.locator("#mb-shell-site").inner_text()=="Broad Leaf · Healthy", (
        "stale shell hydration overwrote newer canonical homepage status")
    await page.evaluate("""()=>{
      document.dispatchEvent(new CustomEvent('monitorbox:state',{
        detail:{sites:[{id:'home',label:'Broad Leaf',state:'failed'}]}
      }));
    }""")
    assert await page.locator("#mb-shell-site").inner_text()=="Broad Leaf · Critical", (
        "failed canonical site status was normalized to Unknown")
    assert not errors,errors
    await context.close()
    print("UI49 #103: newer canonical health beats delayed unknown shell response PASS")


async def main():
    fixture,runner,base=await server.serve()
    try:
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True)
            try:
                for width,height in ((1366,900),(820,1100),(500,900)):
                    await editor_case(browser,fixture,base,width,height)
                fixture.session=False  # avoid editor's parallel status request
                await header_case(browser,base)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()


if __name__=="__main__":
    asyncio.run(main())
