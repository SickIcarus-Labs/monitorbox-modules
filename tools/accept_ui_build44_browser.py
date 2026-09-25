#!/usr/bin/env python3
"""Disposable UI44 iPad/desktop picker and genuine one-second DOM repaint tests."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

import accept_ui_build42_editor_browser as fixture_server
import accept_ui_build43_editor_browser as previous
import build_first_party_ui_build44 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
ASSETS={
    path[len(PREFIX):]: data
    for path,data in candidate._package_files(ROOT).items()
    if path.startswith(PREFIX)
}
fixture_server.ASSETS=ASSETS
base_site=previous.composed_site


def current():
    return datetime.now(timezone.utc).isoformat()


def live_series(*,cpu:float=41,memory:float=33,rx:float=2e9,tx:float=3e8,
                valid:bool=True):
    timestamp=current()
    return [
        {"id":"cpu-live","site_id":"home","object_id":"arrrrr2",
         "check_id":"host-cpu","label":"CPU usage","kind":"gauge",
         "unit":"%","maximum":100,"points":[
             {"timestamp":timestamp,"valid":valid,"value":cpu}]},
        {"id":"memory-live","site_id":"home","object_id":"arrrrr2",
         "check_id":"host-ram","label":"Memory used","kind":"gauge",
         "unit":"%","maximum":100,"points":[
             {"timestamp":timestamp,"valid":valid,"value":memory}]},
        {"id":"ethernet-live","site_id":"home","object_id":"arrrrr2",
         "check_id":"host-eth","label":"Ethernet enp51s0","kind":"counter_pair",
         "unit":"bit/s","maximum":2e9,"points":[
             {"timestamp":timestamp,"valid":valid,"rx":rx,"tx":tx}]},
    ]


def site44():
    site=base_site()
    host=next(o for o in site["objects"] if o["id"]=="arrrrr2")
    host["components"].append({
        "id":"host-eth","label":"Ethernet statistics","state":"healthy",
        "metrics":{"link_speed_mbps":10000},
    })
    return site


fixture_server.fixture_site=site44


def key(check,series):
    return json.dumps(["object","arrrrr2","live",check,series],separators=(",",":"))


async def choose(page,term,label):
    await page.locator("#pickerSearch").fill(term)
    option=page.locator("#pickerGroups label.member-option").filter(has_text=label)
    assert await option.count()==1,(term,label,await option.all_inner_texts())
    await option.locator("input").check()


async def editor_accept(browser,base,fixture,width,height):
    fixture.entry=deepcopy(previous.LEGACY_V2)
    fixture.site=site44()
    fixture.session=False
    fixture.revision=10
    fixture.hash="fixture-hash-10"
    fixture.saved.clear()
    context=await browser.new_context(viewport={"width":width,"height":height})
    page=await context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))

    async def telemetry(route):
        await route.fulfill(status=200,json={"active":True,"series":live_series()})
    await page.route("**/api/v2/live?*",telemetry)
    await page.goto(base+"/settings/cards")
    await page.locator("#password").fill("test-secret")
    await page.locator("#loginButton").click()
    await page.locator("#selected .layout-row").first.wait_for()
    await page.locator("#liveCatalogStatus").get_by_text(
        "3 live series available",exact=False).wait_for()
    host=page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
    await host.get_by_role("button",name="Edit contents").click()
    await page.locator("#addContentItem").click()
    for term,label in [
        ("CPU usage","CPU usage · live"),
        ("Memory used","Memory used · live"),
        ("Ethernet enp51s0","Ethernet enp51s0 · throughput"),
    ]:
        await choose(page,term,label)
    await page.locator("#donePicker").click()
    choices=page.locator("#contentSelectedItems .mb-selected-item")
    assert await choices.count()==3
    assert [item["mode"] for item in
        (await page.evaluate("() => [...document.querySelectorAll('#contentSelectedItems select')].map(el=>({mode:el.value}))"))
    ]==["value","value","value"]
    await page.locator("#saveContents").click()
    await page.locator("#validate").click()
    await page.locator("#preview").wait_for(state="visible")
    await page.locator("#apply").click()
    await page.locator("#preview").wait_for(state="hidden")
    assert fixture.entry["schema_version"]==3
    card=next(r for r in fixture.entry["data"]["sites"]["home"]["cards"]
              if r["id"]=="host:arrrrr2")
    assert [x["key"] for x in card["presentation"]["items"]]==[
        key("host-cpu","cpu-live"),key("host-ram","memory-live"),
        key("host-eth","ethernet-live"),
    ]
    network=next(r for r in fixture.entry["data"]["sites"]["home"]["cards"]
                 if r["id"]=="family:network")
    assert network["presentation"]["hidden_member_ids"]==["aggregation"]
    latest=deepcopy(fixture.entry)
    fixture.entry=deepcopy(previous.LEGACY_V2)
    await page.reload()
    await page.locator("#selected .layout-row").first.wait_for()
    assert fixture.entry["schema_version"]==2
    fixture.entry=latest
    fixture.revision+=1
    fixture.hash=f"fixture-hash-{fixture.revision}"
    await page.reload()
    await page.locator("#selected .layout-row").first.wait_for()
    host=page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
    await host.get_by_role("button",name="Edit contents").click()
    assert await page.locator("#contentSelectedItems .mb-selected-item").count()==3
    assert not errors,errors
    await context.close()
    print(f"UI44 live grouped picker, iPad/desktop v2→v3 and full A/B selected-item restoration: PASS {width}x{height}")


async def live_card_accept(browser,width,height):
    context=await browser.new_context(viewport={"width":width,"height":height})
    page=await context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    await page.set_content('<!doctype html><html><body><main id="core-grid"></main></body></html>')
    await page.add_style_tag(content=ASSETS["v1-parity.css"].decode())
    await page.add_style_tag(content=ASSETS["card-composer.css"].decode())
    setup=r"""
      const app={state:{sites:[]},liveTelemetry:{series:[]}};
      let selected=null;
      function esc(value){
        return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;')
          .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
      }
      function parityCoreCard(site,object){
        return '<button class="parity-card" type="button" data-object="'+
          esc(object.id)+'"><span class="parity-card-head"><strong>'+
          esc(object.label)+'</strong></span><span class="parity-card-copy">'+
          esc(object.summary||'4 checks reporting normally')+'</span></button>';
      }
      function openDrawer(siteId,objectId){selected=siteId+'/'+objectId;}
    """
    await page.add_script_tag(content=setup)
    await page.add_script_tag(content=ASSETS["card-item-registry.js"].decode())
    await page.add_script_tag(content=r"""
      globalThis.MonitorBoxCardLayout={
        displayFor(_site,id){
          return id==='host:arrrrr2'?{
            items:[
              {key:JSON.stringify(['object','arrrrr2','live','host-cpu','cpu-live']),mode:'value'},
              {key:JSON.stringify(['object','arrrrr2','live','host-ram','memory-live']),mode:'value'},
              {key:JSON.stringify(['object','arrrrr2','live','host-eth','ethernet-live']),mode:'list'},
            ],
          }:null;
        },
      };
    """)
    await page.add_script_tag(content=ASSETS["card-composer-renderer.js"].decode())
    await page.evaluate("""({site,series})=>{
      app.state.sites=[site];
      app.liveTelemetry={series};
      document.querySelector('#core-grid').innerHTML=
        parityCoreCard(site,site.objects.find(o=>o.id==='arrrrr2'));
    }""",{"site":site44(),"series":live_series()})
    card=page.locator("#core-grid .mb-card-shell")
    assert await card.count()==1
    assert await card.locator(".parity-card").count()==1
    assert await card.locator(".mb-card-native>.mb-card-item").count()==3
    values=await card.locator(".mb-card-item-value").all_inner_texts()
    assert values==["41%","33%","20%"],values
    assert "of reported link speed" in await card.inner_text()
    # A new ephemeral sample changes ONLY the text, not the saved preference
    # or canonical card markup, within the same one-second repaint cadence.
    await page.evaluate("""()=>{
      for(const series of app.liveTelemetry.series){
        const point=series.points[0];
        point.timestamp=new Date().toISOString();
        if(series.id==='cpu-live')point.value=50;
        if(series.id==='memory-live')point.value=35;
        if(series.id==='ethernet-live')point.rx=4e9;
      }
    }""")
    await page.wait_for_function("""()=>
      [...document.querySelectorAll('.mb-card-item-value')]
        .map(el=>el.textContent).join('|')==='50%|35%|40%'
    """,timeout=2800)
    first=card.locator("[data-mb-source-object]").first
    await first.click()
    assert await page.evaluate("selected")=="home/arrrrr2"
    await page.evaluate("""()=>{
      for(const series of app.liveTelemetry.series)
        series.points[0].timestamp=new Date(Date.now()-9000).toISOString();
    }""")
    await page.wait_for_function("""()=>[...document.querySelectorAll(
      '.mb-card-native>.mb-card-item'
    )].every(node=>node.classList.contains('unavailable'))""",timeout=2800)
    assert "stale" in (await card.inner_text()).lower()
    assert not errors,errors
    print(f"UI44 homepage single visual card, live 1Hz CPU/memory/Ethernet, stale fail-closed, separate drilldowns: PASS {width}x{height}")
    await context.close()


async def main():
    fixture,runner,base=await fixture_server.serve()
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True)
            try:
                for width,height in ((820,1100),(1366,900)):
                    await editor_accept(browser,base,fixture,width,height)
                    await live_card_accept(browser,width,height)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()


if __name__=="__main__":
    asyncio.run(main())
