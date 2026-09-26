#!/usr/bin/env python3
"""Disposable UI47 iPad/desktop picker and genuine one-second DOM repaint tests."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

import accept_ui_build42_editor_browser as fixture_server
import accept_ui_build43_editor_browser as previous
import build_first_party_ui_build47 as candidate

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


def site47():
    site=base_site()
    host=next(o for o in site["objects"] if o["id"]=="arrrrr2")
    host["components"].append({
        "id":"host-eth","label":"Ethernet statistics","state":"healthy",
        "metrics":{"enp51s0 speed mbps":10000},
    })
    cpu=next(c for c in host["components"] if c["id"]=="host-cpu")
    ram=next(c for c in host["components"] if c["id"]=="host-ram")
    cpu["metrics"]["cpu idle percent"]=93
    ram["metrics"].update({
        "memory total kib":65322832,
        "memory available kib":55322832,
    })
    return site


fixture_server.fixture_site=site47


def key(check,series):
    return json.dumps(["object","arrrrr2","live",check,series],separators=(",",":"))


async def choose(page,term,label):
    await page.locator("#pickerSearch").fill(term)
    option=page.locator("#pickerGroups label.member-option").filter(has_text=label)
    assert await option.count()==1,(term,label,await option.all_inner_texts())
    await option.locator("input").check()


async def editor_accept(browser,base,fixture,width,height):
    fixture.entry=deepcopy(previous.LEGACY_V2)
    fixture.site=site47()
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
    host=page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
    await host.get_by_role("button",name="Edit contents").click()
    await page.locator("#liveCatalogStatus:has-text('3 live series available')").wait_for()
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
    print(f"UI47 live grouped picker, iPad/desktop v2→v3 and full A/B selected-item restoration: PASS {width}x{height}")


async def live_card_accept(browser,width,height):
    context=await browser.new_context(viewport={"width":width,"height":height})
    page=await context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    await page.set_content('<!doctype html><html><body><main id="core-grid" class="parity-core-grid"></main></body></html>')
    await page.add_style_tag(content=ASSETS["v1-parity.css"].decode())
    await page.add_style_tag(content=ASSETS["card-composer.css"].decode())
    setup=r"""
      const app={state:{sites:[]},liveTelemetry:{series:[]}};
      let selected=null,openCount=0;
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
      function openDrawer(siteId,objectId){openCount++;selected=siteId+'/'+objectId;}
      function bindCards(){document.querySelectorAll('[data-object]').forEach(node=>{
        node.onclick=()=>openDrawer(node.dataset.site,node.dataset.object);
      });}
      function parityCoreObjects(site){return site.objects;}
      function parityCoreMarkup(){return '';}
      globalThis.hostSelections=[
        {key:JSON.stringify(['object','arrrrr2','live','host-cpu','cpu-live']),mode:'value'},
        {key:JSON.stringify(['object','arrrrr2','live','host-ram','memory-live']),mode:'value'},
        {key:JSON.stringify(['object','arrrrr2','live','host-eth','ethernet-live']),mode:'list'},
      ];
    """
    await page.add_script_tag(content=setup)
    await page.add_script_tag(content=ASSETS["card-item-registry.js"].decode())
    await page.add_script_tag(content=r"""
      globalThis.MonitorBoxCardLayout={
        displayFor(_site,id){
          return id==='host:arrrrr2'?{
            items:globalThis.hostSelections,
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
      bindCards();
    }""",{"site":site47(),"series":live_series()})
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
    assert await card.locator("button").count()==0, "No nested per-row buttons"
    assert await card.get_attribute("data-object")=="arrrrr2"
    assert await page.locator("#core-grid [data-object]").count()==1
    label_font=await card.locator(".mb-card-item-label").first.evaluate(
        "(el)=>getComputedStyle(el).fontFamily"
    )
    canonical_font=await card.locator(".parity-card-copy").evaluate(
        "(el)=>getComputedStyle(el).fontFamily"
    )
    assert label_font==canonical_font,(label_font,canonical_font)
    border=await card.locator(".mb-card-item").first.evaluate(
        "(el)=>getComputedStyle(el).borderTopStyle"
    )
    assert border=="none",border
    await card.locator(".mb-card-item").first.click()
    assert await page.evaluate("selected")=="home/arrrrr2"
    assert await page.evaluate("openCount")==1
    await card.focus()
    await card.press("Enter")
    assert await page.evaluate("openCount")==2
    await page.evaluate("""()=>{
      for(const series of app.liveTelemetry.series)
        series.points[0].timestamp=new Date(Date.now()-9000).toISOString();
    }""")
    await page.wait_for_function("""()=>
      [...document.querySelectorAll('.mb-card-item-value')]
        .map(el=>el.textContent).join('|')==='7%|15.3%|Live source delayed'
    """,timeout=2800)
    assert await card.locator(".mb-card-item-meta:has-text('STATE FALLBACK')").count()==2
    assert "Last live sample" in await card.inner_text()
    # Exact physical regression: 24 host readings may grow Arrrrr2 but must
    # not force Goliath, Internet, Network, Cameras, Power to the same height.
    long_site=site47()
    host=next(o for o in long_site["objects"] if o["id"]=="arrrrr2")
    cpu=next(c for c in host["components"] if c["id"]=="host-cpu")
    for i in range(24):cpu["metrics"][f"diagnostic {i+1}"]=i+1
    long_site["objects"]=[host]+[
        {"id":key,"label":name,"kind":kind,"family":family,
         "state":"healthy","components":[]}
        for key,name,kind,family in [
            ("goliath","Goliath","host",""),
            ("internet","Internet","dashboard_card","internet"),
            ("network","Network","dashboard_card","network"),
            ("cameras","Cameras","dashboard_card","cameras"),
            ("power","Power","dashboard_card","power"),
        ]
    ]
    await page.evaluate("""site=>{
      globalThis.hostSelections=Array.from({length:24},(_,i)=>({
        key:JSON.stringify(['object','arrrrr2','metric','host-cpu',
          'diagnostic '+(i+1)]),mode:'list'
      }));
      app.state.sites=[site];
      document.querySelector('#core-grid').innerHTML=parityCoreMarkup();
      bindCards();
    }""",long_site)
    expected_columns=2 if width<=980 else 3
    assert await page.locator(".mb-card-column").count()==expected_columns
    host_card=page.locator(".mb-card-shell")
    assert await host_card.locator(".mb-card-native>.mb-card-item").count()==24
    # Ordinary one-line metric rows must share the native Network-card
    # ~20px rhythm, not reserve four empty source/detail/meta grid tracks.
    row_boxes=[
        await host_card.locator(".mb-card-native>.mb-card-item").nth(i).bounding_box()
        for i in range(5)
    ]
    assert all(17<=row["height"]<=26 for row in row_boxes),row_boxes
    gaps=[
        row_boxes[i+1]["y"]-row_boxes[i]["y"]
        for i in range(4)
    ]
    assert all(17<=gap<=27 for gap in gaps),gaps
    # Check the rendered cascade, including the older extended-card selector.
    computed=await host_card.locator(".mb-card-native>.mb-card-item").first.evaluate(
        "(el)=>({rowGap:getComputedStyle(el).rowGap,"
        "areas:getComputedStyle(el).gridTemplateAreas,"
        "padding:getComputedStyle(el).paddingTop})"
    )
    assert computed["rowGap"]=="0px",computed
    assert computed["padding"]=="2px",computed

    host_box=await host_card.bounding_box()
    goliath=page.locator(".mb-card-column").nth(1).locator(
        ".parity-card",has_text="Goliath"
    )
    goliath_box=await goliath.bounding_box()
    assert goliath_box["height"]<host_box["height"]/3,(goliath_box,host_box)
    assert abs(goliath_box["y"]-host_box["y"])<8
    network=page.locator(".parity-card",has_text="Network")
    network_box=await network.bounding_box()
    assert network_box["y"]<host_box["y"]+host_box["height"],(
        network_box,host_box
    )
    assert not errors,errors
    print(f"UI47 iPad/desktop 24-item natural-height columns, exact NIC, "
          f"delayed-live fallback and independent drilldowns: PASS {width}x{height}")
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
