#!/usr/bin/env python3
"""Browser regression against the real Advanced editor and v1-parity dashboard paths."""
from __future__ import annotations
import ast
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

def extract_constant(path:Path,name:str)->str:
    tree=ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if any(isinstance(target,ast.Name) and target.id==name for target in targets):
                return ast.literal_eval(node.value)
    raise RuntimeError(f"{name} not found in {path}")

def load_builder(path:Path):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location("phase6_build22",path)
    module=importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

def append_scripts(markup:str,scripts:list[str])->str:
    payload="\n".join(f"<script>{source}</script>" for source in scripts)
    return markup.replace("</body>",payload+"</body>")

async def advanced_case(page,core_root:Path,assets:dict[str,bytes])->None:
    base=extract_constant(core_root/"src/monitorbox/v2/config_ui.py","_SETTINGS_HTML")
    scripts=[
      assets["followup-beta-polish.js"].decode(),
      assets["advanced-v22-polish.js"].decode(),
      assets["advanced-dirty-state.js"].decode(),
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
    assert await page.locator('#phase6AdvancedIndex [data-phase6-category="connections"] .phase6-advanced-connection').count()==2
    ups=page.locator('#phase6AdvancedIndex [data-phase6-category="ups"]')
    assert "Objects · UPS (2)" in await ups.locator("summary").inner_text()
    assert await ups.get_by_text("Network UPS",exact=True).count()==1
    assert await ups.get_by_text("Server UPS",exact=True).count()==1
    a2=page.locator('#phase6AdvancedIndex [data-phase6-system="arrrrr2"]')
    assert "NUT · Arrrrr2" in await a2.inner_text() and "Server UPS" in await a2.inner_text()
    local=page.locator('#phase6AdvancedIndex [data-phase6-system="monitor"]')
    assert "NUT · MonitorBox" in await local.inner_text() and "Network UPS" in await local.inner_text()
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
    core_root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root.parent/"monitorbox-core"
    builder=load_builder(root/"tools/build_first_party_ui_build22.py")
    assets=builder._build22_assets(root)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        advanced=await browser.new_page(viewport={"width":1400,"height":1000})
        await advanced_case(advanced,core_root,assets)
        dashboard=await browser.new_page(viewport={"width":1400,"height":1000})
        await dashboard_case(dashboard,assets)
        await browser.close()
    print("UI Phase-6 build-22 browser acceptance: PASS (actual Advanced + v1-parity paths)")

if __name__=="__main__": asyncio.run(main())
