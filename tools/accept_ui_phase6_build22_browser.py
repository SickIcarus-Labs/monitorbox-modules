#!/usr/bin/env python3
"""Browser regression against the accepted Core Advanced contract + v1-parity dashboard."""
from __future__ import annotations
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, Route

ADVANCED_CONFIG={
  "sites":[{"id":"broadleaf","label":"Broad Leaf","agents":[{"id":"monitor"}],"objects":[
    {"id":"monitor","label":"MonitorBox","kind":"host","capabilities":[]},
    {"id":"arrrrr2","label":"Arrrrr2","kind":"host","capabilities":[]},
    {"id":"network_ups","label":"Network UPS","kind":"ups","depends_on":[],"capabilities":[]},
    {"id":"server_ups","label":"Server UPS","kind":"ups","depends_on":["arrrrr2"],"capabilities":[]},
  ],"actions":[]}],
  "runtime":{"local_agent":{"site_id":"broadleaf","credential_secret_refs":{}}}
}
WORKSPACE={
  "systems":[{"id":"monitor","label":"MonitorBox","kind":"host"},{"id":"arrrrr2","label":"Arrrrr2","kind":"host"}],
  "connections":[
    {"id":"nut-local","label":"NUT · MonitorBox","adapter":"nut","endpoint":"192.168.3.5:3493","parent_ids":["monitor"],"exposes_object_ids":["network_ups"]},
    {"id":"nut-a2","label":"NUT · Arrrrr2","adapter":"nut","endpoint":"192.168.3.9:3493","parent_ids":["arrrrr2"],"exposes_object_ids":["server_ups"]},
  ],
  "objects":[
    {"id":"network_ups","label":"Network UPS","kind":"ups","depends_on":[]},
    {"id":"server_ups","label":"Server UPS","kind":"ups","depends_on":["arrrrr2"]},
  ]
}
DASHBOARD_STATE={
  "title":"MonitorBox","overall":"healthy","global":{"state":"healthy","summary":"Everything is fine","conditions":[]},
  "sites":[{"id":"broadleaf","label":"Broad Leaf","state":"healthy","agents":[],"objects":[{
    "id":"database_host","label":"Database Host","kind":"host","state":"healthy","summary":"1 check(s) reporting normally","front_page":True,
    "components":[{"id":"db_maintenance","label":"Database maintenance","adapter":"synthetic","enabled":True,"state":"healthy","summary":"Routine maintenance active","metadata":{"maintenance":{"provider":"synthetic-provider","kind":"database_reindex","state":"Rebuilding","health_neutral":True}},"metrics":{}}]
  }]}]
}

FIXTURE_CORE_COMMIT="a6ace91753f196ffc1ec4966880ca4bf839d0d74"
FIXTURE_CORE_BLOB="934267f49a9794addffbf721556dbf5c241c1a2e"

def load_builder(path:Path):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location("phase6_build22",path)
    module=importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

def append_scripts(markup:str,scripts:list[str])->str:
    payload="\n".join(f"<script>{source}</script>" for source in scripts)
    return markup.replace("</body>",payload+"</body>")

async def advanced_case(page,root:Path,assets:dict[str,bytes])->None:
    fixture_path=root/"tests/fixtures/phase6/core-a6ace917-advanced.html"
    base=fixture_path.read_text(encoding="utf-8")
    assert FIXTURE_CORE_COMMIT in base and FIXTURE_CORE_BLOB in base
    scripts=[
      assets["phase6-convergence.js"].decode(),
      assets["phase6-physical-convergence.js"].decode(),
    ]
    html=append_scripts(base,scripts)
    async def route(route:Route)->None:
        path=urlsplit(route.request.url).path
        payload={
          "/api/v2/config/status":{"authenticated":True,"setup_complete":True},
          "/api/v2/config/session":{"csrf_token":"test"},
          "/api/v2/config/current":{"revision":9,"config":ADVANCED_CONFIG},
          "/api/v2/config/catalog":{"object_kinds":["host","ups"],"supported_adapters":["nut"],"capabilities":[]},
          "/api/v2/config/secrets":{"secrets":[]},
          "/api/v2/config/workspace/state":WORKSPACE,
        }.get(path)
        if path=="/settings/advanced": await route.fulfill(status=200,content_type="text/html",body=html)
        elif payload is not None: await route.fulfill(status=200,content_type="application/json",body=json.dumps(payload))
        else: await route.fulfill(status=404,body="not found")
    await page.route("http://monitorbox.test/**",route)
    await page.goto("http://monitorbox.test/settings/advanced")
    await page.locator("#phase6AdvancedSummary").wait_for()
    summary=await page.locator("#phase6AdvancedSummary").inner_text()
    assert "Connections 2" in summary and "UPS 2" in summary,summary

    systems=page.locator('#phase6AdvancedIndex [data-phase6-category="systems"]')
    connections=page.locator('#phase6AdvancedIndex [data-phase6-category="connections"]')
    ups=page.locator('#phase6AdvancedIndex [data-phase6-category="ups"]')
    assert "Systems (2)" in await systems.locator("summary").inner_text()
    assert "Connections (2)" in await connections.locator("summary").inner_text()
    assert "Objects · UPS (2)" in await ups.locator("summary").inner_text()
    assert await connections.locator('.phase6-advanced-connection').count()==2
    assert await ups.get_by_text("Network UPS",exact=True).count()==1
    assert await ups.get_by_text("Server UPS",exact=True).count()==1

    # Exercise the index like an operator. The canonical groups are collapsed
    # by default, so visible relationship assertions must open their groups.
    await systems.locator("summary").click()
    a2=systems.locator('[data-phase6-system="arrrrr2"]')
    a2_text=await a2.inner_text()
    assert "NUT · Arrrrr2" in a2_text and "Server UPS" in a2_text,a2_text
    local=systems.locator('[data-phase6-system="monitor"]')
    local_text=await local.inner_text()
    assert "NUT · MonitorBox" in local_text and "Network UPS" in local_text,local_text

    await connections.locator("summary").click()
    connection_text=await connections.inner_text()
    assert "NUT · MonitorBox" in connection_text and "Network UPS" in connection_text,connection_text
    assert "NUT · Arrrrr2" in connection_text and "Server UPS" in connection_text,connection_text

    await ups.locator("summary").click()
    assert await ups.get_by_text("Network UPS",exact=True).is_visible()
    assert await ups.get_by_text("Server UPS",exact=True).is_visible()

    # Prove build22 displaced the physically wrong native root-only tree.
    assert await page.locator("#objects").get_attribute("aria-hidden")=="true"
    assert await page.locator("#advancedSemanticIndex").is_hidden()
    await ups.locator('[data-phase6-advanced-id="server_ups"]').click()
    assert await page.locator("#editor h2").inner_text()=="Server UPS"

async def dashboard_case(page,assets:dict[str,bytes])->None:
    html=assets["dashboard.html"].decode()
    html=re.sub(r'<script\s+src="[^"]+"\s+defer></script>','',html)
    scripts=[assets[name].decode() for name in (
      "phase6-convergence.js","dashboard.js","conceptual-presentation.js","service-presentation.js","v1-parity.js","phase6-physical-convergence.js"
    )]
    html=append_scripts(html,scripts)
    async def route(route:Route)->None:
        path=urlsplit(route.request.url).path
        if path=="/": await route.fulfill(status=200,content_type="text/html",body=html)
        elif path=="/api/v2/state": await route.fulfill(status=200,content_type="application/json",body=json.dumps(DASHBOARD_STATE))
        else: await route.fulfill(status=404,body="not found")
    await page.route("http://dashboard.test/**",route)
    await page.goto("http://dashboard.test/")
    card=page.locator('#core-grid [data-object="database_host"]')
    await card.wait_for()
    text=await card.inner_text()
    assert "Maintenance" in text and "database reindex: Rebuilding" in text,text
    assert "Healthy" in text,text
    assert await card.get_attribute("class") and "healthy" in (await card.get_attribute("class"))

async def main()->None:
    root=Path(__file__).resolve().parent.parent
    builder=load_builder(root/"tools/build_first_party_ui_build22.py")
    assets=builder._build22_assets(root)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        advanced=await browser.new_page(viewport={"width":1400,"height":1000})
        await advanced_case(advanced,root,assets)
        dashboard=await browser.new_page(viewport={"width":1400,"height":1000})
        await dashboard_case(dashboard,assets)
        await browser.close()
    print("UI Phase-6 build-22 browser acceptance: PASS (pinned Core Advanced contract + v1-parity paths)")

if __name__=="__main__": asyncio.run(main())
