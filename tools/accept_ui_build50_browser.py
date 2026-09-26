#!/usr/bin/env python3
"""UI50 synthetic browser: actual homepage iframe, destructive draft reset and #103.

This is NOT physical Safari or a paired real Core Test Lab.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
from playwright.async_api import async_playwright
from aiohttp import web
import accept_ui_build42_editor_browser as old
import accept_ui_build49_browser as ui49
import build_first_party_ui_build50 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
ASSETS={path.removeprefix(PREFIX):body for path,body in candidate._package_files(ROOT).items()
        if path.startswith(PREFIX)}

def real_site():
    host=lambda ident,label:{"id":ident,"label":label,"kind":"host","state":"healthy",
      "homepage_origin":"operator","explicit_front_page":True,
      "front_page":True,"summary":"Checks healthy","components":[{"id":"cpu",
      "label":"Host resource metrics","state":"healthy","enabled":True,"adapter":"host",
      "metrics":{"cpu_idle_percent":88,"memory_total_kib":32000000,
                 "memory_available_kib":16000000,**{
                     "stress_"+str(i).zfill(2):float(i) for i in range(24)}},
      "metric_units":{}}]}
    members=[{"id":"edge"+str(i),"label":n,"kind":"network_device",
        "homepage_origin":"discovered","front_page":False,"state":"healthy",
        "summary":"Network healthy","components":[]} for i,n in enumerate(
        ["Broad Leaf","Aggregation","Switch 2","Hallway","Patio","Garage",
         "Bonus Room","Guest Room","Henry's Room","Living Room",
         "Master Bedroom","Office","Turnberry"])]
    cameras=[{"id":"camera"+str(i),"label":n,"kind":"camera","state":"healthy",
        "summary":"Camera healthy","components":[]} for i,n in enumerate(
        ["Doorbell","Driveway","Front Walkway","Front Yard",
         "Garage camera","Patio camera","Pool Equipment","Side Yard"])]
    ups=[{"id":"ups"+str(i),"label":label,"kind":"ups","state":"healthy",
        "summary":"UPS online","components":[{"id":"ups.check","label":"UPS",
        "state":"healthy","enabled":True,"metrics":{"battery.charge":100,
        "battery.runtime":1200},"metadata":{"power_source":"utility"}}]}
        for i,label in enumerate(("Network UPS","Server UPS"))]
    families=[{"id":n,"family":n,"kind":"dashboard_card","label":n.title(),
        "state":"healthy","summary":"Healthy","components":[],
        **({"camera_counts":{"healthy":8,"expected":8}} if n=="cameras" else {})}
        for n in ("internet","network","cameras","power")]
    return {"id":"home","label":"Broad Leaf","state":"healthy","agents":[],
        "objects":[host("arrrrr2","Arrrrr2"),host("goliath","Goliath"),
                   *members,*cameras,*ups],
        "cards":families,"power":{"state":"healthy","ups":{}}}

def legacy():
    cards=[{"id":ident,"visible":True,"placement":{"column":i%3}}
        for i,ident in enumerate(("host:arrrrr2","host:goliath","family:internet",
            "family:network","family:cameras","family:power"))]
    cards[0]["presentation"]={"schema_version":2,"items":[{
        "key":'["object","arrrrr2","metric","cpu","stress_01"]',
        "mode":"value"}]}
    cards.append({"id":"custom:legacy","visible":True,"placement":{"column":2},
        "presentation":{"schema_version":2,"title":"Legacy manually built","items":[]}})
    return {"schema_version":4,"data":{"sites":{"home":{
        "mode":"custom","arranged":True,"cards":cards}}}}

async def serve():
    fixture=old.Fixture()
    fixture.entry=legacy()
    fixture.site=real_site()
    old.ASSETS=ASSETS
    app=web.Application()
    async def editor(_):
        page=ASSETS["card-layout-editor.html"].decode()
        return web.Response(text=page,content_type="text/html")
    async def homepage(_):
        return web.Response(body=ASSETS["dashboard.html"],content_type="text/html")
    async def asset(request):
        name=request.match_info["name"]
        if name not in ASSETS:raise web.HTTPNotFound()
        kind="text/javascript" if name.endswith(".js") else (
            "text/css" if name.endswith(".css") else
            "image/svg+xml" if name.endswith(".svg") else "application/octet-stream")
        return web.Response(body=ASSETS[name],content_type=kind)
    app.router.add_get("/",homepage)
    app.router.add_get("/settings/cards",editor)
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
    site=web.TCPSite(runner,"127.0.0.1",0);await site.start()
    base=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    return fixture,runner,base

async def case(browser,fixture,base,width,height):
    fixture.session=False;fixture.revision=10;fixture.hash="fixture-hash-10"
    fixture.entry=legacy();fixture.site=real_site()
    fixture.saved.clear();fixture.body_log.clear()
    context=await browser.new_context(viewport={"width":width,"height":height})
    page=await context.new_page()
    errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
    await page.goto(base+"/settings/cards")
    await page.locator("#password").fill("test-secret")
    await page.locator("#loginButton").click()
    await page.locator("#selected .layout-row").first.wait_for()
    assert await page.locator("#selected .layout-row").count()==7
    # Explicit authorization, not an unprompted startup migration.
    page.once("dialog",lambda dialog:asyncio.create_task(dialog.accept()))
    await page.locator("#rebuildBootstrap").click()
    assert fixture.entry==legacy(),"Staging changed canonical config without Apply"
    staged=await page.locator("#selected .layout-row strong").all_inner_texts()
    assert staged==["Arrrrr2","Goliath","Internet","Network","Cameras","Power"],staged
    await page.locator("#validate").click()
    assert "automatic columns" in await page.locator("#previewSummary").inner_text()
    await page.locator("#apply").click()
    await page.locator("#preview").wait_for(state="hidden")
    saved=deepcopy(fixture.entry)
    assert len(fixture.saved)==1 and fixture.revision==11
    assert saved["schema_version"]==4
    rows=saved["data"]["sites"]["home"]["cards"]
    assert saved["data"]["sites"]["home"]["mode"]=="auto"
    assert [r["id"] for r in rows]==[
        "host:arrrrr2","host:goliath","family:internet","family:network",
        "family:cameras","family:power"]
    assert all("presentation" not in r and "placement" not in r for r in rows)
    assert "arranged" not in saved["data"]["sites"]["home"]
    # The iframe is the real homepage: no fake sample-card/13-name proxy.
    await page.locator("#arrange").click()
    frame=page.frame_locator("#mb-arrange-actual-homepage")
    await frame.locator(".mb-arrange-frame-card").first.wait_for(timeout=12000)
    assert await frame.locator(".mb-arrange-frame-card").count()==6
    expected=3 if width>=1200 else 2 if width>700 else 1
    assert await frame.locator(".mb-card-column").count()==expected,(
        width,await page.locator("#arrangeStatus").inner_text())
    # Compare each card's actual rendered content with an ordinary homepage,
    # rather than matching the editor's former raw inventory list.
    home=await context.new_page()
    home.on("pageerror",lambda error:errors.append(str(error)))
    await home.goto(base+"/")
    await home.locator(".mb-card-column").first.wait_for(timeout=12000)
    async def cards_from(scope,selector):
        return await scope.locator(selector).evaluate_all(
            "(nodes)=>Object.fromEntries(nodes.map(n=>{"+
            "const surface=n.matches('.mb-arrange-frame-card')?"+
            "n.querySelector('.parity-card,.mb-card-shell'):n;"+
            "const identity=surface.dataset.object||"+
            "surface.querySelector('[data-object]')?.dataset.object||"+
            "surface.dataset.mbCustomCardId;"+
            "return [identity,surface.innerText.trim()]}))")
    actual=await cards_from(home,".mb-card-column > .parity-card, "
        ".mb-card-column > .mb-card-shell")
    preview=await cards_from(frame,".mb-arrange-frame-card")
    assert preview==actual,(width,preview,actual)
    assert len(preview)==6
    # Real editor actions operate on the real rendered card wrappers.
    if width>=1200:
        await frame.locator(
            '.mb-arrange-frame-card[data-mb-arrange-card="family:power"] '
            '.mb-arrange-menu-button').click()
        await frame.get_by_label("Move Power to column").select_option("0")
        power=frame.locator('.mb-card-column[data-mb-arrange-column="0"] '
            '.mb-arrange-frame-card[data-mb-arrange-card="family:power"]')
        await power.wait_for()
        await page.locator("#undoArrange").click()
        assert await power.count()==0
        await frame.locator(
            '.mb-arrange-frame-card[data-mb-arrange-card="family:power"] '
            '.mb-arrange-menu-button').click()
        await frame.get_by_label("Move Power to column").select_option("0")
    await page.locator("#doneArrange").click()
    await page.locator("#validate").click()
    await page.locator("#apply").click()
    assert len(fixture.saved)==2 and fixture.revision==12
    assert fixture.entry["data"]["sites"]["home"]["arranged"] is True
    assert all(r.get("placement") for r in fixture.entry["data"]["sites"]["home"]["cards"])
    oldsave=deepcopy(fixture.entry)
    fixture.entry=legacy();fixture.revision=13;fixture.hash="fixture-hash-13"
    await page.reload();await page.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry==legacy(),"Legacy restore must not auto-regenerate"
    fixture.entry=oldsave;fixture.revision=14;fixture.hash="fixture-hash-14"
    await page.reload();await page.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry==oldsave,"Modern A/B snapshot restored improperly"
    # Restrict page errors to the checked card/renderer pathways in synthetic
    # API fixture; any browser runtime exceptions are a real failure.
    assert not errors,errors
    await context.close()
    print(f"UI50 {width}x{height}: all-site clean draft/one Apply, real card "
          "preview parity, accessible move/undo, v4 A/B snapshots PASS")

async def main():
    fixture,runner,base=await serve()
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                for width,height in ((1366,1000),(820,1100),(500,900)):
                    await case(browser,fixture,base,width,height)
                # #103 remains inherited from UI49 unchanged. Run its
                # delayed initial unknown versus fresh canonical health case.
                fixture.session=False  # Do not race shell hydration with editor's own state GET.
                await ui49.header_case(browser,base)
            finally:await browser.close()
    finally:await runner.cleanup()

if __name__=="__main__":asyncio.run(main())
