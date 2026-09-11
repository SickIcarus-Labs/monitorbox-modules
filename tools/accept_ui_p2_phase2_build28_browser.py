#!/usr/bin/env python3
"""Chromium acceptance for P2 Phase-2 UI build 28 (#297/#209/#268)."""
from __future__ import annotations
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DISCOVERY = ROOT / "sources" / "ui" / "1.1.15-build28" / "discovery-coverage.js"
CONNECTIONS = ROOT / "sources" / "ui" / "1.1.15-build28" / "phase2-p2-connections.js"

DISCOVERY_HTML = """<!doctype html><html><body>
<p id='resultSummary'></p><button id='selectNew'></button><div id='results'></div>
<script>
let candidates=[];
function row(item){
 const root=document.createElement('div'); root.className='candidate'; root.dataset.candidate=item.candidate_id;
 root.innerHTML=`<label><input type='checkbox' data-id='${item.candidate_id}' ${item.monitor_default?'checked':''}></label>`+
 `<div class='identity'><strong>${item.label}</strong> <span class='pill'>${item.state}</span></div>`+
 `<input data-label-for='${item.candidate_id}' value='${item.label}'>`+
 `<div class='wide'><select><option selected>Optional</option><option>Required</option></select></div>`;
 return root;
}
function render(){const root=document.getElementById('results');root.replaceChildren(...candidates.map(row));}
function summarize(){document.getElementById('resultSummary').textContent='factory';}
</script></body></html>"""

CONNECTION_HTML = """<!doctype html><html><body>
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


def texts(locator):
    return [locator.nth(i).inner_text() for i in range(locator.count())]


def main() -> None:
    assert DISCOVERY.is_file() and CONNECTIONS.is_file()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1024, "height": 900})
        page.set_content(DISCOVERY_HTML)
        items = [
            {"candidate_id":"r2","label":"Zulu uplink","state":"recommended","monitor_default":True,"recommendation_reason":"Authoritative physical peer link"},
            {"candidate_id":"o1","label":"Beta printer","state":"new","monitor_default":False},
            {"candidate_id":"r1","label":"Alpha uplink","state":"recommended","monitor_default":True,"review_descriptor":{"recommendation_reason":"Provider relationship evidence"}},
            {"candidate_id":"c1","label":"Existing camera","state":"already_monitored","monitor_default":True,"configured_object_id":"camera-1"},
        ]
        page.evaluate("items => { candidates=items; render(); summarize(); }", items)
        page.add_script_tag(path=str(DISCOVERY))

        recommended = page.locator('[data-discovery-subsection="recommended"]')
        other = page.locator('[data-discovery-subsection="other"]')
        assert recommended.count() == 1 and other.count() == 1
        assert recommended.get_attribute('open') is not None
        assert other.get_attribute('open') is None
        rec_rows = recommended.locator('.candidate .identity strong')
        assert texts(rec_rows) == ['Alpha uplink', 'Zulu uplink']
        assert 'Provider relationship evidence' in recommended.inner_text()
        assert 'Authoritative physical peer link' in recommended.inner_text()
        assert 'Beta printer' in (other.text_content() or '')

        existing = page.locator('[data-candidate="c1"]')
        assert 'Keep monitoring' in (existing.text_content() or '')
        existing_checkbox = existing.locator('input[type="checkbox"][data-id]')
        existing_checkbox.uncheck()
        assert 'Stop monitoring' in (existing.text_content() or '')
        assert '1 configuration change selected' in page.locator('#resultSummary').inner_text()

        # Re-render while a disclosure state has been changed; grouping must not alter candidate identity.
        other.locator('summary').click()
        assert other.get_attribute('open') is not None
        before_ids = page.locator('#results .candidate').evaluate_all("els => els.map(e => e.dataset.candidate).sort()")
        page.evaluate('summarize()')
        after_ids = page.locator('#results .candidate').evaluate_all("els => els.map(e => e.dataset.candidate).sort()")
        assert before_ids == after_ids == ['c1','o1','r1','r2']
        assert page.locator('[data-discovery-subsection="other"]').get_attribute('open') is not None

        page.set_content(CONNECTION_HTML)
        page.add_script_tag(path=str(CONNECTIONS))
        connections = [
            {"id":"n-z","name":"Zulu Service","existing":False},
            {"id":"e-z","name":"Zulu Existing","existing":True},
            {"id":"n-a","name":"alpha service","existing":False},
            {"id":"e-a","name":"Alpha Existing","existing":True},
            {"id":"n-b","name":"Beta 10","existing":False},
            {"id":"n-b2","name":"Beta 2","existing":False},
        ]
        page.evaluate('items => renderConnections(items)', connections)
        new_names = texts(page.locator('#newConnections .connection strong'))
        existing_names = texts(page.locator('#alreadyConfiguredConnections .connection strong'))
        assert new_names == ['alpha service','Beta 2','Beta 10','Zulu Service'], new_names
        assert existing_names == ['Alpha Existing','Zulu Existing'], existing_names
        new_ids = page.locator('#newConnections .connection').evaluate_all("els => els.map(e => e.dataset.connectionId)")
        existing_ids = page.locator('#alreadyConfiguredConnections .connection').evaluate_all("els => els.map(e => e.dataset.connectionId)")
        assert set(new_ids) == {'n-z','n-a','n-b','n-b2'}
        assert set(existing_ids) == {'e-z','e-a'}

        browser.close()
    print('P2 Phase-2 UI build28 Chromium acceptance: PASS')


if __name__ == '__main__':
    main()
