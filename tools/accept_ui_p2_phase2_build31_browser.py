#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from playwright.sync_api import sync_playwright

import build_first_party_ui_build31 as candidate

ROOT = Path(__file__).resolve().parent.parent

HTML = """<!doctype html><html><body>
<p id='resultSummary'></p><button id='selectNew'></button><div id='results'></div>
<script>
let candidates=[];
function row(item){
 const root=document.createElement('div');root.className='candidate';
 root.innerHTML=`<label class='factory-action'><input type='checkbox' data-id='${item.candidate_id}' ${item.monitor_default?'checked':''}></label>`+
 `<div class='identity'><strong>${item.label}</strong> <span class='pill'>${item.state}</span></div>`+
 `<label class='factory-label'><input data-label-for='${item.candidate_id}' value='${item.label}'></label>`+
 `<div class='wide'><div class='ability-heading'>MONITOR ABILITIES</div><label class='factory-ability'><input type='checkbox' checked> Ability</label><select><option selected>Optional</option><option>Required</option></select><button type='button'>Not now</button></div>`;
 return root;
}
function render(){document.getElementById('results').replaceChildren(...candidates.map(row));}
function summarize(){document.getElementById('resultSummary').textContent='factory';}
</script></body></html>"""

COVERAGE = {"status":"covered","kind":"provider_inventory","source_label":"Portainer"}


def provider(candidate_id: str, label: str, *, monitored: bool) -> dict:
    return {
        "candidate_id":candidate_id,
        "label":label,
        "state":"new",
        "monitor_default":False,
        "monitoring_state":"monitored" if monitored else "not_monitored",
        "monitoring_suppressed":not monitored,
        "provider_monitoring_coverage":True,
        "evidence":[{"source":"portainer","source_id":f"env:stack:{candidate_id}","metadata":{"monitoring_coverage":COVERAGE}}],
    }


def main() -> None:
    discovery = candidate._build31_assets(ROOT)["discovery-coverage.js"].decode("utf-8")
    items = [
        {"candidate_id":"c1","label":"Existing camera","state":"already_monitored","monitor_default":True,"configured_object_id":"camera-1"},
        provider("p1", "Bazarr", monitored=True),
        provider("p2", "Agent", monitored=False),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width":1024,"height":900})
        page.set_content(HTML)
        page.add_script_tag(content=discovery)
        page.evaluate("items=>{candidates=items;render();summarize();}", items)

        covered = page.locator('[data-coverage-section="covered"]')
        covered.locator('summary').click()

        canonical = page.locator('input[data-id="c1"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        assert "Keep monitoring" in canonical.inner_text()
        canonical.locator('input[data-id="c1"]').uncheck()
        assert "Stop monitoring" in canonical.inner_text()

        monitored = page.locator('input[data-id="p1"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        box = monitored.locator('input[data-id="p1"]')
        assert box.is_enabled()
        assert box.is_checked()
        assert box.is_visible()
        assert "Keep monitoring" in monitored.inner_text()
        assert "Already monitored via Portainer" in monitored.inner_text()
        for forbidden in ("Keep existing coverage", "Add configured monitor", "MONITOR ABILITIES", "Ability"):
            assert forbidden not in monitored.inner_text(), forbidden
        before = page.locator('#resultSummary').inner_text()
        box.uncheck()
        assert "Stop monitoring" in monitored.inner_text()
        after = page.locator('#resultSummary').inner_text()
        assert after != before

        # A stopped provider-backed item is classified as New / not yet monitored,
        # remains present there, and exposes the ordinary Start monitoring path.
        not_monitored = page.locator('input[data-id="p2"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        start_box = not_monitored.locator('input[data-id="p2"]')
        assert not_monitored.get_attribute('data-discovery-coverage-section') == 'new'
        stopped_section = page.locator('[data-coverage-section="new"]')
        assert stopped_section.locator('input[data-id="p2"]').count() == 1
        stopped_section.evaluate('(el)=>{el.open=true}')
        assert start_box.is_enabled()
        assert not start_box.is_checked()
        assert start_box.is_visible()
        start_box.check()
        assert "Start monitoring" in not_monitored.inner_text()

        # Production rerender must preserve the normalized state model rather than
        # resurrect the retired provider-specific static/adoption presentation.
        page.evaluate("summarize()")
        monitored = page.locator('input[data-id="p1"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        assert monitored.locator('input[data-id="p1"]').is_enabled()
        assert "Keep existing coverage" not in monitored.inner_text()
        assert "Add configured monitor" not in monitored.inner_text()
        browser.close()

    print("P2 Phase-2 UI build31 source-independent monitoring Chromium acceptance: PASS")


if __name__ == "__main__":
    main()
