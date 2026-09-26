#!/usr/bin/env python3
"""UI51 synthetic browser: observed defaults, single scoped reset, tap-grip/drag, #103."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
from aiohttp import web
from playwright.async_api import async_playwright
import accept_ui_build42_editor_browser as old
import accept_ui_build50_browser as prior
import build_first_party_ui_build51 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
ASSETS={name.removeprefix(PREFIX):body
    for name,body in candidate._package_files(ROOT).items() if name.startswith(PREFIX)}

class MultiFixture(old.Fixture):
    def __init__(self):
        super().__init__()
        self.site=prior.real_site()
        self.site["objects"][0]["components"][0]["metrics"].update({
            "storage_used_percent":64,"ethernet_utilization_percent":15,
            "rx_bytes":99999999,"interface_speed_mbps":10000,
        })
        turnberry={"id":"turnberry","label":"Turnberry","state":"healthy",
            "agents":[],"objects":[{"id":"apollo","label":"Apollo","kind":"host",
            "homepage_origin":"operator","explicit_front_page":True,
            "front_page":True,"state":"healthy","summary":"Healthy",
            "components":[{"id":"host","label":"Host","state":"healthy",
            "metrics":{"cpu_usage_percent":21,"memory_used_percent":35}}]}],
            "cards":[{"id":"internet","family":"internet","kind":"dashboard_card",
            "label":"Internet","state":"healthy","summary":"Healthy","components":[]}],
            "power":{"state":"healthy","ups":{}}}
        self.sites=[self.site,turnberry]
        self.entry=prior.legacy()
    def current(self,_):
        if not self.session:raise web.HTTPUnauthorized()
        return web.json_response({"revision":self.revision,"content_hash":self.hash,
            "config":{"sites":[{"id":s["id"],"label":s["label"]} for s in self.sites],
                      "module_preferences":{"com.sickicarus.monitorbox.ui":self.entry}
                      if self.entry is not None else {}}})
    def state(self,_):
        return web.json_response({"title":"MonitorBox","overall":"healthy",
            "sites":self.sites})

async def serve():
    fixture=MultiFixture()
    old.ASSETS=ASSETS
    app=web.Application()
    async def html(_,name):
        return web.Response(body=ASSETS[name],content_type="text/html")
    async def asset(request):
        name=request.match_info["name"]
        if name not in ASSETS:raise web.HTTPNotFound()
        kind="text/javascript" if name.endswith(".js") else (
          "text/css" if name.endswith(".css") else "application/octet-stream")
        return web.Response(body=ASSETS[name],content_type=kind)
    app.router.add_get("/",lambda req:html(req,"dashboard.html"))
    app.router.add_get("/settings/cards",lambda req:html(req,"card-layout-editor.html"))
    app.router.add_get("/static/{name}",asset)
    app.router.add_get("/api/v2/config/status",fixture.status)
    app.router.add_get("/api/v2/config/session",fixture.session_status)
    app.router.add_post("/api/v2/config/auth/login",fixture.login)
    app.router.add_get("/api/v2/config/current",fixture.current)
    app.router.add_get("/api/v2/state",fixture.state)
    app.router.add_get("/api/v2/dashboard/config",fixture.dashboard_config)
    app.router.add_get("/api/v2/build",lambda _:web.json_response(
        {"core":{"version":"2.6.0","build":992}}))
    app.router.add_get("/api/v2/live",lambda _:web.json_response(
        {"active":True,"series":[]}))
    app.router.add_put("/api/v2/config/module-preferences/{module}",fixture.put)
    runner=web.AppRunner(app);await runner.setup()
    endpoint=web.TCPSite(runner,"127.0.0.1",0);await endpoint.start()
    return fixture,runner,f"http://127.0.0.1:{endpoint._server.sockets[0].getsockname()[1]}"

async def case(browser,fixture,base,width,height):
    fixture.session=False;fixture.revision=10;fixture.hash="fixture-hash-10"
    fixture.entry=None;fixture.saved.clear();fixture.body_log.clear()
    context=await browser.new_context(viewport={"width":width,"height":height},
        has_touch=True,is_mobile=width<650)
    page=await context.new_page()
    errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
    # A genuinely new post-bootstrap installation receives CURRENT curated
    # defaults, not UI50's old empty native host cards.
    await page.goto(base+"/",wait_until="domcontentloaded")
    await page.locator(".mb-card-column").first.wait_for(timeout=15000)
    a2=page.locator('[data-mb-site="home"] [data-object="arrrrr2"]')
    await a2.locator(".mb-card-item").first.wait_for(timeout=10000)
    assert await a2.locator(".mb-card-item").count()==4
    assert "CPU" in await a2.inner_text() and "memory" in (await a2.inner_text()).lower()
    assert await page.locator(
        '[data-mb-site="home"] [data-object="goliath"] .mb-card-item').count()==2
    assert await page.locator('[data-mb-site="home"] [data-object="edge0"]').count()==0
    # Installing UI51 over an existing v4 custom snapshot DOES NOT change it.
    fixture.entry=prior.legacy()
    await page.reload()
    await page.locator(".mb-card-column").first.wait_for()
    assert "Legacy manually built" in await page.locator("#core-grid").inner_text()
    editor=await context.new_page()
    editor.on("pageerror",lambda error:errors.append(str(error)))
    await editor.goto(base+"/settings/cards",wait_until="domcontentloaded")
    await editor.locator("#password").fill("test-secret")
    await editor.locator("#loginButton").click()
    await editor.locator("#selected .layout-row").first.wait_for()
    assert await editor.locator("#regenerate").count()==1
    assert await editor.locator("#reset,#rebuildBootstrap").count()==0
    assert await editor.locator("#regenScope").is_visible()
    assert await editor.locator("#regenAll").is_checked() is False
    editor.once("dialog",lambda dialog:asyncio.create_task(dialog.accept()))
    await editor.locator("#regenerate").click()
    assert fixture.entry==prior.legacy(),"Regenerate must only stage a draft"
    await editor.locator("#validate").click()
    assert "automatic columns" in await editor.locator("#previewSummary").inner_text()
    await editor.locator("#apply").click()
    await editor.locator("#preview").wait_for(state="hidden")
    assert fixture.revision==11 and len(fixture.saved)==1
    saved=deepcopy(fixture.entry)
    assert set(saved["data"]["sites"])=={"home"}
    home=saved["data"]["sites"]["home"]
    assert home["mode"]=="auto" and home.get("arranged") is not True
    assert all("placement" not in row for row in home["cards"])
    assert all(not row["id"].startswith("custom:") for row in home["cards"])
    host=next(row for row in home["cards"] if row["id"]=="host:arrrrr2")
    assert len(host["presentation"]["items"])==4,host
    assert len(next(row for row in home["cards"]
        if row["id"]=="host:goliath")["presentation"]["items"])==2
    # Rebuild all sites only when the additional scope is explicitly checked.
    await editor.locator("#regenAll").check()
    editor.once("dialog",lambda dialog:asyncio.create_task(dialog.accept()))
    await editor.locator("#regenerate").click()
    assert fixture.entry==saved
    await editor.locator("#validate").click()
    await editor.locator("#apply").click()
    await editor.locator("#preview").wait_for(state="hidden")
    assert fixture.revision==12 and len(fixture.saved)==2
    multi=deepcopy(fixture.entry)
    assert set(multi["data"]["sites"])=={"home","turnberry"}
    assert len(next(row for row in multi["data"]["sites"]["turnberry"]["cards"]
        if row["id"]=="host:apollo")["presentation"]["items"])==2
    # Same native homepage renderer in the editor, no second pseudo card.
    await editor.locator("#arrange").click()
    frame=editor.frame_locator("#mb-arrange-actual-homepage")
    await frame.locator(".mb-arrange-frame-card").first.wait_for(timeout=15000)
    await editor.wait_for_function(
        "() => document.querySelector('#arrangeStatus')?.textContent.includes('ready')")
    assert await frame.locator(".mb-arrange-menu-button").count()==0
    assert await frame.locator(".mb-arrange-handle").count()==6
    cols=3 if width>980 else 2 if width>650 else 1
    assert await frame.locator(
        '.mb-masonry-site[data-mb-site="home"] .mb-card-column'
    ).count()==cols
    # Native card's first pixel lies AFTER editor-only toolbar and handle.
    grip=frame.locator(
        '.mb-arrange-frame-card[data-mb-arrange-card="host:arrrrr2"] '
        '.mb-arrange-handle')
    before=await grip.bounding_box()
    card=await frame.locator(
        '.mb-arrange-frame-card[data-mb-arrange-card="host:arrrrr2"] '
        '.mb-card-shell').bounding_box()
    assert before and card and before["y"]+before["height"]<=card["y"]+2,(
        "Grip overlaps native card title/health",before,card)
    # Tap the SAME grip for accessible fallback, not a second Move button.
    power='.mb-arrange-frame-card[data-mb-arrange-card="family:power"]'
    handle=frame.locator(power+" .mb-arrange-handle")
    await handle.click()
    assert await handle.get_attribute("aria-expanded")=="true"
    if width>980:
        initial=await frame.locator(power).evaluate(
            "(node)=>Number(node.closest('.mb-card-column').dataset.mbArrangeColumn)")
        away=(initial+1)%3
        await frame.get_by_label("Move Power to column").select_option(str(away))
        await frame.locator(
            '.mb-card-column[data-mb-arrange-column="'+str(away)+'"] '+power
        ).wait_for(timeout=15000)
        await editor.locator("#undoArrange").click()
        assert fixture.entry==multi,"Undo did not remain draft only"
    await editor.locator("#cancelArrange").click()
    assert fixture.entry==multi
    # A retained v4 layout remains bitwise the same after restoring it:
    # regeneration is NEVER a load-time side effect.
    fixture.entry=prior.legacy();fixture.revision=13;fixture.hash="fixture-hash-13"
    await editor.reload()
    await editor.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry==prior.legacy()
    assert "Legacy manually built" in await editor.locator("#selected").inner_text()
    assert not errors,errors
    await context.close()
    print(f"UI51 {width}x{height}: curated fresh bootstrap, scoped/all-site "
          "one-button regenerate, one tap grip, native preview and v4 protection PASS")

async def main():
    fixture,runner,base=await serve()
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True)
            try:
                for width,height in ((1366,1000),(820,1100),(500,900)):
                    await case(browser,fixture,base,width,height)
                fixture.session=False
                await prior.ui49.header_case(browser,base)
            finally:await browser.close()
    finally:await runner.cleanup()

if __name__=="__main__":asyncio.run(main())
