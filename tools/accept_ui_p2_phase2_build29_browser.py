#!/usr/bin/env python3
"""Chromium acceptance for P2 Phase-2 UI build 29 physical corrections."""
from __future__ import annotations
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
DISCOVERY=ROOT/"sources"/"ui"/"1.1.15-build28"/"discovery-coverage.js"
FIXES=ROOT/"sources"/"ui"/"1.1.16-build29"/"phase2-physical-fixes.js"
CONNECTIONS=ROOT/"sources"/"ui"/"1.1.15-build28"/"phase2-p2-connections.js"

DISCOVERY_HTML="""<!doctype html><html><body>
<p id='resultSummary'></p><button id='selectNew'></button><div id='results'></div>
<script>
let candidates=[];
function row(item){
 const root=document.createElement('div');root.className='candidate';root.dataset.candidate=item.candidate_id;
 root.innerHTML=`<label><input type='checkbox' data-id='${item.candidate_id}' ${item.monitor_default?'checked':''}></label>`+
 `<div class='identity'><strong>${item.label}</strong> <span class='pill'>${item.state}</span></div>`+
 `<label><input data-label-for='${item.candidate_id}' value='${item.label}'></label>`+
 `<div class='wide'><label><input type='checkbox' checked> Ability</label><select><option selected>Optional</option><option>Required</option></select><button type='button'>Not now</button></div>`;
 return root;
}
function render(){const root=document.getElementById('results');root.replaceChildren(...candidates.map(row));}
function summarize(){document.getElementById('resultSummary').textContent='factory';}
</script></body></html>"""

CONNECTION_HTML="""<!doctype html><html><body>
<section id='newConnections'><div data-v22-new-list></div></section>
<section id='alreadyConfiguredConnections'><div data-v22-existing-list></div></section>
<script>
function card(item){const el=document.createElement('div');el.className='connection';el.dataset.connectionId=item.id;el.innerHTML=`<div class='connection-head'><strong>${item.name}</strong></div>`;return el;}
function renderConnections(items){
 const fresh=document.querySelector('#newConnections [data-v22-new-list]');
 const existing=document.querySelector('#alreadyConfiguredConnections [data-v22-existing-list]');
 fresh.replaceChildren(...items.filter(x=>!x.existing).map(card));
 existing.replaceChildren(...items.filter(x=>x.existing).map(card));
}
</script></body></html>"""

def texts(locator): return [locator.nth(i).inner_text() for i in range(locator.count())]

def main()->None:
    assert DISCOVERY.is_file() and FIXES.is_file() and CONNECTIONS.is_file()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={"width":1024,"height":900})
        page.set_content(DISCOVERY_HTML)
        items=[
          {"candidate_id":"r1","label":"Aggregation · Port 7","state":"recommended","monitor_default":True,"recommendation_reason":"provider:unifi","evidence":[{"metadata":{"recommendation_reason":"Uplink to Broad Leaf · SFP+ 1"}}]},
          {"candidate_id":"o1","label":"Printer","state":"new","monitor_default":False},
          {"candidate_id":"c1","label":"Existing camera","state":"already_monitored","monitor_default":True,"configured_object_id":"camera-1"},
          {"candidate_id":"p1","label":"Bazarr","state":"new","monitor_default":False,"evidence":[{"metadata":{"monitoring_coverage":{"status":"covered","kind":"provider","source_label":"Portainer"}}}]},
        ]
        page.evaluate("items=>{candidates=items;render();summarize();}",items)
        page.add_script_tag(path=str(DISCOVERY))
        page.add_script_tag(path=str(FIXES))

        recommended=page.locator('[data-discovery-subsection="recommended"]')
        assert recommended.count()==1
        assert 'Uplink to Broad Leaf · SFP+ 1' in recommended.inner_text()
        assert 'provider:unifi' not in recommended.inner_text()

        canonical=page.locator('[data-candidate="c1"]')
        covered=page.locator('[data-coverage-section="covered"]')
        covered.locator('summary').click()
        assert 'Keep monitoring' in canonical.inner_text()
        canonical_box=canonical.locator('input[type="checkbox"][data-id]')
        canonical_box.uncheck()
        assert 'Stop monitoring' in canonical.inner_text()

        provider=page.locator('[data-candidate="p1"]')
        provider_box=provider.locator('input[type="checkbox"][data-id]')
        assert provider_box.is_disabled()
        assert provider_box.is_hidden()
        assert 'Monitored' in provider.inner_text()
        assert 'Already monitored via Portainer' in provider.inner_text()
        assert 'Add configured monitor' not in provider.inner_text()
        assert 'Keep existing coverage' not in provider.inner_text()
        assert provider.locator('button',has_text='Not now').is_hidden()

        page.set_content(CONNECTION_HTML)
        page.add_script_tag(path=str(CONNECTIONS))
        connections=[
          {"id":"n-z","name":"Zulu Service","existing":False},{"id":"e-z","name":"Zulu Existing","existing":True},
          {"id":"n-a","name":"alpha service","existing":False},{"id":"e-a","name":"Alpha Existing","existing":True},
          {"id":"n-b","name":"Beta 10","existing":False},{"id":"n-b2","name":"Beta 2","existing":False},
        ]
        page.evaluate('items=>renderConnections(items)',connections)
        assert texts(page.locator('#newConnections .connection strong'))==['alpha service','Beta 2','Beta 10','Zulu Service']
        assert texts(page.locator('#alreadyConfiguredConnections .connection strong'))==['Alpha Existing','Zulu Existing']
        browser.close()
    print('P2 Phase-2 UI build29 Chromium acceptance: PASS')

if __name__=='__main__': main()
