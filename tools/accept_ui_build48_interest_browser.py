#!/usr/bin/env python3
"""UI48: actual Chromium verifies one existing live fetch carries bounded card interests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

import build_first_party_ui_build48 as ui

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ui._package_files(ROOT)
PREFIX = ui.TARGET_IMPORT_PACKAGE + "/assets/"


def asset(name: str) -> str:
    return PACKAGE[PREFIX + name].decode("utf-8")


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for width, height in ((820, 1100), (1366, 900)):
                ctx = await browser.new_context(viewport={"width": width, "height": height})
                page = await ctx.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                await page.set_content(
                    '<!doctype html><main id="core-grid"></main><div id="drawer"></div>'
                )
                await page.add_script_tag(content="""
                    const app = {
                      state:{sites:[{id:'home',label:'Home',objects:[
                        {id:'a2',label:'Arrrrr2',kind:'host',state:'healthy',components:[]},
                        {id:'g',label:'Goliath',kind:'host',state:'healthy',components:[]},
                      ]}]},
                      selected:null,liveTrafficSelection:null,
                      liveTelemetry:{series:[]},liveTelemetryViewer:'browser-test'
                    };
                    const requests=[];
                    function esc(value){return String(value).replace(/&/g,'&amp;')
                      .replace(/"/g,'&quot;').replace(/</g,'&lt;');}
                    function parityCoreCard(site,object){
                      return '<button class="parity-card" type="button" data-site="'+
                        esc(site.id)+'" data-object="'+esc(object.id)+'">'+
                        esc(object.label)+'</button>';
                    }
                    function parityCoreObjects(site){return site.objects;}
                    function parityCoreMarkup(){return '';}
                    function openDrawer(siteId,objectId){app.selected={siteId,objectId};}
                    function $(selector){return document.querySelector(selector);}
                    async function api(path,options){
                      requests.push({path,viewer:options?.headers?.['X-MonitorBox-Viewer']});
                      return {active:true,series:[]};
                    }
                    function repaintLiveTelemetry(){}
                """)
                await page.add_script_tag(content=asset("card-item-registry.js"))
                await page.add_script_tag(content="""
                    globalThis.MonitorBoxCardLayout={
                      displayFor(_site,key){
                        const make=(obj,check,metric)=>({
                          key:JSON.stringify(['object',obj,'live',check,metric]),
                          mode:'value'
                        });
                        if(key==='host:a2')return {items:[
                          make('a2','cpu','cpu-live'),
                          make('a2','memory','mem-live')
                        ]};
                        if(key==='host:g')return {items:[
                          make('g','cpu','cpu-live')
                        ]};
                        return null;
                      }
                    };
                """)
                await page.add_script_tag(content=asset("card-composer-renderer.js"))
                await page.evaluate("""()=>{
                  const site=app.state.sites[0];
                  document.querySelector('#core-grid').innerHTML=
                    site.objects.map(o=>parityCoreCard(site,o)).join('');
                }""")
                tail = asset("live-telemetry.js").split(
                    "let liveTelemetryRefreshRunning=false;", 1
                )
                assert len(tail) == 2
                await page.add_script_tag(
                    content="let liveTelemetryRefreshRunning=false;" + tail[1]
                )
                await page.wait_for_function("() => requests.length >= 1")
                data = await page.evaluate("requests[0]")
                query = parse_qs(urlsplit(data["path"]).query)
                assert query["detail"] == ["home/a2", "home/g"], query
                assert data["viewer"] == "browser-test"
                assert query["window"] == ["300"]
                assert await page.evaluate(
                    "MonitorBoxCardComposer.visibleLiveDetails()"
                ) == ["home/a2", "home/g"]

                await page.evaluate("""()=>{
                  app.selected={siteId:'home',objectId:'a2'};
                  document.querySelector('#core-grid').insertAdjacentHTML(
                    'beforeend','<span data-mb-composer-site="outside" '+
                    'data-mb-composer-key="'+
                    JSON.stringify(['object','g','live','cpu','other'])
                      .replace(/"/g,'&quot;')+'"></span>'
                  );
                  requests.length=0;
                }""")
                await page.evaluate("refreshLiveTelemetry()")
                data = await page.evaluate("requests[0]")
                query = parse_qs(urlsplit(data["path"]).query)
                assert query["detail"] == ["home/a2", "home/g"]
                assert query["window"] == ["900"]
                await page.evaluate("""()=>{
                  Object.defineProperty(document,'hidden',{
                    configurable:true,get:()=>true
                  });
                  requests.length=0;
                }""")
                await page.evaluate("refreshLiveTelemetry()")
                assert await page.evaluate("requests.length") == 0
                await page.evaluate("""()=>{
                  Object.defineProperty(document,'hidden',{
                    configurable:true,get:()=>false
                  });
                  document.dispatchEvent(new Event('visibilitychange'));
                }""")
                await page.wait_for_function("requests.length >= 1")
                assert not errors, errors
                await ctx.close()
                print(
                    f"UI48 {width}x{height}: single 1Hz request, two distinct "
                    "live cards, drawer deduplication, site isolation and "
                    "hidden-tab lease expiry: PASS"
                )
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
