#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from playwright.sync_api import sync_playwright

import build_first_party_ui_build30 as candidate

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
 `<div class='wide'><label class='factory-ability'><input type='checkbox' checked> Ability</label><select><option selected>Optional</option><option>Required</option></select><button type='button'>Not now</button></div>`;
 return root;
}
function render(){document.getElementById('results').replaceChildren(...candidates.map(row));}
function summarize(){document.getElementById('resultSummary').textContent='factory';}
</script></body></html>"""


def main() -> None:
    discovery = candidate._build30_assets(ROOT)["discovery-coverage.js"].decode("utf-8")
    items = [
        {
            "candidate_id":"r1","label":"Aggregation · Port 7","state":"recommended","monitor_default":True,
            "recommendation_reason":"provider:unifi",
            "evidence":[{"metadata":{"recommendation_relationship":{"kind":"uplink","peer_device":"Broad Leaf","peer_port":"SFP+ 1"}}}],
        },
        {"candidate_id":"o1","label":"Printer","state":"new","monitor_default":False},
        {"candidate_id":"c1","label":"Existing camera","state":"already_monitored","monitor_default":True,"configured_object_id":"camera-1"},
        {
            "candidate_id":"p1","label":"Bazarr","state":"new","monitor_default":False,
            "evidence":[{"metadata":{"monitoring_coverage":{"status":"covered","kind":"provider","source_label":"Portainer"}}}],
        },
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width":1024,"height":900})
        page.set_content(HTML)
        page.add_script_tag(content=discovery)

        # Match the production completion order: render first, then summarize.
        page.evaluate("items=>{candidates=items;render();summarize();}", items)

        recommended = page.locator('[data-discovery-subsection="recommended"]')
        assert recommended.count() == 1
        assert "Uplink to Broad Leaf · SFP+ 1" in recommended.inner_text()
        assert "provider:unifi" not in recommended.inner_text()

        covered = page.locator('[data-coverage-section="covered"]')
        covered.locator('summary').click()
        canonical = page.locator('input[data-id="c1"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        assert "Keep monitoring" in canonical.inner_text()
        canonical.locator('input[data-id="c1"]').uncheck()
        assert "Stop monitoring" in canonical.inner_text()

        provider = page.locator('input[data-id="p1"]').locator('xpath=ancestor::div[contains(@class,"candidate")]')
        provider_text = provider.inner_text()
        assert "Monitored" in provider_text
        assert "Already monitored via Portainer" in provider_text
        for forbidden in ("Keep existing coverage", "Add configured monitor", "Not now", "Ability"):
            assert forbidden not in provider_text, forbidden
        provider_box = provider.locator('input[data-id="p1"]')
        assert provider_box.is_disabled()
        size = provider_box.bounding_box()
        assert size is None or (size["width"] == 0 and size["height"] == 0)

        # Re-running summary must not resurrect the old build-29 presentation.
        page.evaluate("summarize()")
        provider_text = provider.inner_text()
        assert "Monitored" in provider_text
        assert "Keep existing coverage" not in provider_text
        assert "Uplink to Broad Leaf · SFP+ 1" in recommended.inner_text()
        assert "provider:unifi" not in recommended.inner_text()
        browser.close()

    print("P2 Phase-2 UI build30 production-order Chromium acceptance: PASS")


if __name__ == "__main__":
    main()
