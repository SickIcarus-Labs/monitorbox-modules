#!/usr/bin/env python3
"""Browser regression for #51 and #276 on the build-21 convergence helper."""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

MODEL={
  "systems":[{"id":"monitor","label":"MonitorBox"},{"id":"arrrrr2","label":"Arrrrr2"}],
  "connections":[
    {"id":"nut-monitor","label":"NUT · MonitorBox","adapter":"nut","parent_ids":["network_ups"],"exposes_object_ids":["network_ups"]},
    {"id":"nut-a2","label":"NUT · Arrrrr2","adapter":"nut","parent_ids":["server_ups"],"exposes_object_ids":["server_ups"]},
  ],
  "objects":[
    {"id":"network_ups","label":"Network UPS","kind":"ups","depends_on":["monitor"]},
    {"id":"server_ups","label":"Server UPS","kind":"ups","depends_on":["arrrrr2"]},
  ]
}
HTML='''<!doctype html><html><body>
<div id="systemRows"><div class="item" data-workspace-system="monitor"><div><strong>MonitorBox</strong></div></div><div class="item" data-workspace-system="arrrrr2"><div><strong>Arrrrr2</strong></div></div></div>
<div id="connectionRows"><div class="item" data-workspace-connection="nut-monitor"><div><strong>NUT · MonitorBox</strong></div></div><div class="item" data-workspace-connection="nut-a2"><div><strong>NUT · Arrrrr2</strong></div></div></div>
<div id="objectRows"><div class="item" data-workspace-object="network_ups"><div><strong>Network UPS</strong></div></div><div class="item" data-workspace-object="server_ups"><div><strong>Server UPS</strong></div></div></div>
<div id="card"></div>
</body></html>'''

async def main()->None:
    root=Path(__file__).resolve().parent.parent
    source=(root/'sources/ui/1.1.13-build21/phase6-convergence.js').read_text()
    async with async_playwright() as p:
        browser=await p.chromium.launch(); page=await browser.new_page(viewport={"width":1024,"height":1366})
        await page.set_content(HTML); await page.add_script_tag(content=source)
        await page.evaluate('(model)=>MonitorBoxPhase6Convergence.decorateWorkspace(model,document)',MODEL)
        assert await page.locator('[data-workspace-object]').count()==2
        assert await page.locator('[data-workspace-object="network_ups"]').count()==1
        assert await page.locator('[data-workspace-object="server_ups"]').count()==1
        assert await page.locator('[data-phase6-category="ups"] [data-phase6-kind="object"]').count()==2
        assert 'Power / UPS (2)' in await page.locator('[data-phase6-category="ups"]').inner_text()
        assert await page.locator('[data-workspace-system="monitor"] [data-phase6-id="nut-monitor"]').count()==1
        assert await page.locator('[data-workspace-system="monitor"] [data-phase6-id="network_ups"]').count()==1
        assert await page.locator('[data-workspace-system="arrrrr2"] [data-phase6-id="nut-a2"]').count()==1
        assert await page.locator('[data-workspace-system="arrrrr2"] [data-phase6-id="server_ups"]').count()==1
        assert await page.locator('[data-workspace-connection="nut-monitor"] [data-phase6-id="network_ups"]').count()==1
        assert await page.locator('[data-workspace-connection="nut-a2"] [data-phase6-id="server_ups"]').count()==1
        maintenance={"state":"healthy","components":[{"metadata":{"maintenance":{"provider":"synthetic-provider","kind":"index_rebuild","state":"Rebuilding","health_neutral":True}}}]}
        text=await page.evaluate('(obj)=>MonitorBoxPhase6Convergence.maintenanceMarkup(obj)',maintenance)
        await page.locator('#card').evaluate('(node,html)=>node.innerHTML=html',text)
        assert await page.locator('#card').get_attribute('class') in (None,'')
        assert 'Maintenance' in await page.locator('#card').inner_text()
        assert 'Rebuilding' in await page.locator('#card').inner_text()
        await browser.close()
    print('UI Phase-6 build-21 browser acceptance: PASS')

if __name__=='__main__': asyncio.run(main())
