#!/usr/bin/env python3
"""Disposable Chromium UI41 editor: auth, 30-device promotion, conflict and restore.

Synthetic server deliberately does not claim real Core/managed-loader acceptance;
the paired private-Core CI gate exercises that separate contract.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

from aiohttp import web
from playwright.async_api import async_playwright

import build_first_party_ui_build41 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
ARCHIVE_FILES=candidate._package_files(ROOT)
ASSETS={path[len(PREFIX):]:payload for path,payload in ARCHIVE_FILES.items()
        if path.startswith(PREFIX)}
assert "card-layout-editor.html" in ASSETS

def fixture_site():
    objects=[
        {"id":"arrrrr2","label":"Arrrrr2","kind":"host","homepage_origin":"operator"},
        {"id":"goliath","label":"Goliath","kind":"host","homepage_origin":"operator"},
        {"id":"router","label":"Site router","kind":"network_device",
         "homepage_origin":"discovered","system_role":"site_gateway"},
        {"id":"monitor","label":"Monitor","kind":"host","homepage_origin":"operator"},
    ]
    objects.extend({
        "id":f"edge-{i:02d}","label":f"Edge {i:02d}",
        "kind":"host" if i%3 else "network_device",
        "homepage_origin":"module" if i%2 else "discovered",
        "front_page":True,
    } for i in range(1,31))
    cards=[{"id":name,"family":name,"kind":"dashboard_card","label":name.title()}
           for name in ("internet","network","cameras","power","services","solar","zigbee")]
    return {"id":"home","label":"Home","objects":objects,"cards":cards}

class Fixture:
    def __init__(self):
        self.site=fixture_site()
        self.revision=10
        self.hash="fixture-hash-10"
        self.entry=None
        self.saved=[]
        self.session=False
        self.body_log=[]
        self.csrf="fixture-csrf"
    def status(self,_):
        return web.json_response({"authenticated":self.session,"setup_complete":True})
    def session_status(self,_):
        if not self.session:raise web.HTTPUnauthorized()
        return web.json_response({"csrf_token":self.csrf})
    async def login(self,request):
        body=await request.json()
        if body.get("password")!="test-secret":raise web.HTTPUnauthorized()
        self.session=True
        return web.json_response({"csrf_token":self.csrf})
    def current(self,_):
        if not self.session:raise web.HTTPUnauthorized()
        return web.json_response({
            "revision":self.revision,"content_hash":self.hash,
            "config":{"sites":[{"id":"home","label":"Home"}],
                      "module_preferences":({"com.sickicarus.monitorbox.ui":self.entry}
                       if self.entry else {})},
        })
    def state(self,_):
        return web.json_response({"title":"MonitorBox","sites":[self.site]})
    def dashboard_config(self,_):
        return web.json_response({"configured":True,"revision":self.revision,
                                  "ui_preferences":self.entry})
    async def put(self,request):
        if not self.session:raise web.HTTPUnauthorized()
        if request.headers.get("X-MonitorBox-CSRF")!=self.csrf:raise web.HTTPForbidden()
        payload=await request.json()
        self.body_log.append(payload)
        if payload.get("revision")!=self.revision or payload.get("content_hash")!=self.hash:
            raise web.HTTPConflict(text="stale canonical revision")
        self.entry=deepcopy(payload["preferences"])
        self.saved.append(deepcopy(self.entry))
        self.revision+=1
        self.hash=f"fixture-hash-{self.revision}"
        return web.json_response({"revision":self.revision,"content_hash":self.hash})
    async def family(self,_):
        self.site["cards"].append({"id":"battery","family":"battery","kind":"dashboard_card","label":"Battery"})
        return web.json_response({"ok":True})
    async def conflict(self,_):
        self.revision+=1
        self.hash=f"fixture-hash-{self.revision}"
        return web.json_response({"ok":True})
    async def restore(self,request):
        index=int(request.match_info["index"])
        self.entry=deepcopy(self.saved[index])
        self.revision+=1
        self.hash=f"fixture-hash-{self.revision}"
        return web.json_response({"revision":self.revision})

async def serve():
    fixture=Fixture()
    app=web.Application()
    async def editor(_):
        return web.Response(body=ASSETS["card-layout-editor.html"],content_type="text/html")
    async def asset(request):
        name=request.match_info["name"]
        if name not in ASSETS:raise web.HTTPNotFound()
        mime=("text/javascript" if name.endswith(".js") else
              "text/css" if name.endswith(".css") else "text/html")
        return web.Response(body=ASSETS[name],content_type=mime)
    app.router.add_get("/settings/cards",editor)
    app.router.add_get("/static/{name}",asset)
    app.router.add_get("/api/v2/config/status",fixture.status)
    app.router.add_get("/api/v2/config/session",fixture.session_status)
    app.router.add_post("/api/v2/config/auth/login",fixture.login)
    app.router.add_get("/api/v2/config/current",fixture.current)
    app.router.add_get("/api/v2/state",fixture.state)
    app.router.add_get("/api/v2/dashboard/config",fixture.dashboard_config)
    app.router.add_put("/api/v2/config/module-preferences/{module}",fixture.put)
    app.router.add_post("/_fixture/family",fixture.family)
    app.router.add_post("/_fixture/conflict",fixture.conflict)
    app.router.add_post("/_fixture/restore/{index}",fixture.restore)
    runner=web.AppRunner(app)
    await runner.setup()
    site=web.TCPSite(runner,"127.0.0.1",0)
    await site.start()
    origin=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    return fixture,runner,origin

async def accept():
    fixture,runner,base=await serve()
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True)
            try:
                for width,height in ((1366,900),(820,1100)):
                    fixture.session=False
                    fixture.revision=10
                    fixture.hash="fixture-hash-10"
                    fixture.entry=None
                    fixture.saved.clear()
                    fixture.body_log.clear()
                    fixture.site=fixture_site()
                    context=await browser.new_context(viewport={"width":width,"height":height})
                    page=await context.new_page()
                    errors=[]
                    page.on("pageerror",lambda e:errors.append(str(e)))
                    response=await page.goto(base+"/settings/cards",wait_until="networkidle")
                    assert response and response.ok
                    assert await page.locator("#login").is_visible()
                    await page.locator("#password").fill("test-secret")
                    await page.locator("#loginButton").click()
                    await page.locator("#selected .layout-row").first.wait_for()
                    labels=await page.locator("#selected .layout-row strong").all_inner_texts()
                    assert labels[:3]==["Arrrrr2","Goliath","Site router"],labels
                    assert "Internet" in labels and "Solar" in labels
                    assert not any(text.startswith("Edge") for text in labels)
                    assert await page.locator("#available .available-item").count()>=30

                    await page.locator("#search").fill("edge-01")
                    add=page.locator("#available .available-item").filter(has_text="Edge 01")
                    await add.locator("button").click()
                    assert "Edge 01" in await page.locator("#selected").inner_text()
                    await page.locator('#selected input[aria-label="Show Cameras"]').uncheck()
                    await page.locator("#validate").click()
                    await page.locator("#preview").wait_for(state="visible")
                    assert "configuration revision" in await page.locator("#previewSummary").inner_text()
                    await page.locator("#apply").click()
                    await page.locator("#preview").wait_for(state="hidden")
                    assert fixture.body_log[-1]["content_hash"].startswith("fixture-hash-")
                    saved=fixture.saved[-1]
                    cards=saved["data"]["sites"]["home"]["cards"]
                    assert {"id":"host:edge-01","visible":True} in cards
                    assert {"id":"family:cameras","visible":False} in cards
                    assert saved["data"]["sites"]["home"]["mode"]=="custom"

                    await page.reload(wait_until="networkidle")
                    await page.locator("#selected .layout-row").first.wait_for()
                    assert "Edge 01" in await page.locator("#selected").inner_text()

                    await page.request.post(base+"/_fixture/family")
                    await page.locator("#reload").click()
                    await page.locator("#available").get_by_text("Battery",exact=True).wait_for()
                    assert "Battery" not in await page.locator("#selected").inner_text()
                    await page.locator("#available .available-item").filter(
                        has_text="Battery").locator("button").click()
                    await page.locator("#validate").click()
                    await page.locator("#preview").wait_for(state="visible")
                    await page.request.post(base+"/_fixture/conflict")
                    await page.locator("#apply").click()
                    await page.locator("#preview").wait_for(state="hidden")
                    assert "reload" in (await page.locator("#layoutStatus").inner_text()).lower()
                    assert len(fixture.saved)>=1

                    # Synthetic server-side retained-revision restore mirrors
                    # the editor's refresh semantics. Real Core restore is
                    # separately exercised in paired Core CI.
                    await page.request.post(base+"/_fixture/restore/0")
                    await page.reload(wait_until="networkidle")
                    await page.locator("#selected .layout-row").first.wait_for()
                    assert "Edge 01" in await page.locator("#selected").inner_text()
                    assert "Battery" in await page.locator("#available").inner_text()
                    assert not errors,errors
                    await context.close()
                print("UI41 desktop/iPad Chromium editor, CSRF, 30-node, 409 and restored layout: PASS")
            finally:
                await browser.close()
    finally:
        await runner.cleanup()

if __name__=="__main__":
    asyncio.run(accept())
