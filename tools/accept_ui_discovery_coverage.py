#!/usr/bin/env python3
"""Browser acceptance for UI v1.1.0 build 8 discovery coverage/action grouping."""

from __future__ import annotations

import html
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BUILD7_CSS = ROOT / "sources" / "ui" / "1.0.2-build7" / "discovery-presentation.css"
BUILD8_CSS = ROOT / "sources" / "ui" / "1.1.0-build8" / "discovery-coverage.css"
BUILD8_JS = ROOT / "sources" / "ui" / "1.1.0-build8" / "discovery-coverage.js"
SCREENSHOT = Path(os.environ.get("UI_DISCOVERY_COVERAGE_SCREENSHOT", "/tmp/ui-discovery-coverage.png"))

BASE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
:root { --line:#334155; --muted:#94a3b8; --panel:#0f1e31; --text:#e5edf8; }
* { box-sizing:border-box; }
body { margin:0; padding:22px; font:16px/1.4 system-ui,sans-serif; color:var(--text); background:#07111f; }
main { max-width:1220px; margin:0 auto; }
#resultSummary { margin:0 0 10px; color:var(--muted); }
#results { max-width:1220px; }
.candidate { display:grid; grid-template-columns:150px minmax(180px,1fr) minmax(260px,1fr) minmax(380px,1.2fr); gap:12px; margin:12px 0; padding:18px; border:1px solid var(--line); border-radius:12px; background:var(--panel); }
.identity { min-width:0; font-weight:700; }
.identity .pill { margin-left:6px; }
.pill { display:inline-block; padding:2px 8px; border:1px solid #48617e; border-radius:999px; color:var(--muted); font-size:13px; font-weight:500; }
.pill.good { border-color:#277653; color:#5ee1a3; }
.pill.bad { border-color:#9f3f4d; color:#ff8a9a; }
.pill.warn { border-color:#8f6b31; color:#ffd27d; }
.wide { min-width:0; }
.tags { margin-bottom:6px; }
.tags .pill { margin:0 4px 4px 0; }
.ability-title { margin:5px 0; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.ability { display:inline-flex; align-items:center; gap:6px; min-height:40px; padding:7px 10px; margin-bottom:7px; border:1px solid var(--line); border-radius:8px; }
.provider-provenance { color:var(--muted); margin-top:7px; }
.connection-suggestion { margin-top:8px; padding:8px; border:1px solid var(--line); border-radius:9px; }
button,.button,select,input { font:inherit; }
select,input[type=text] { min-height:44px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; color:var(--text); background:#091727; }
select { width:100%; margin-top:6px; }
input[type=text] { width:100%; }
input[type=checkbox] { width:20px; height:20px; }
</style></head><body><main>
<p id="resultSummary"></p>
<button id="selectNew" type="button">Monitor all new</button>
<div id="results"></div>
</main><script>
let candidates=[];
function render(){}
function summarize(){ document.getElementById('resultSummary').textContent='factory summary'; }
</script></body></html>"""


def row_markup(item: dict) -> str:
    candidate_id = html.escape(item["candidate_id"], quote=True)
    label = html.escape(item["label"])
    state = item["state"]
    checked = " checked" if item.get("monitor_default") else ""
    disabled = " disabled" if state in {"auxiliary", "needs_review"} else ""
    state_label = {
        "already_monitored": "Already monitored",
        "recommended": "Recommended",
        "new": "New",
        "needs_review": "Needs review",
        "auxiliary": "Auxiliary",
    }[state]
    environment = html.escape(item.get("environment", "Broad Leaf - Goliath"))
    return f"""
<div class="candidate" data-candidate="{candidate_id}">
  <label><input type="checkbox" data-id="{candidate_id}"{checked}{disabled}></label>
  <div class="identity"><strong>{label}</strong> <span class="pill">{state_label}</span></div>
  <input type="text" data-label-for="{candidate_id}" value="{label}">
  <div class="wide">
    <div class="tags"><span class="pill">portainer</span><span class="pill">docker_workload</span></div>
    <div class="ability-title">Monitor abilities</div>
    <label class="ability"><input type="checkbox" checked> Docker workload</label>
    <select data-policy-for="{candidate_id}"><option selected>Optional</option><option>Required</option></select>
    <select aria-label="Durable disposition"><option selected>No durable disposition</option><option>Ignore future discovery</option></select>
    <div class="provider-provenance">Environment/System · {environment} · Stack · {label} · Service · {label}</div>
    <div class="connection-suggestion"><strong>Suggested Connection · HTTP(S)</strong><div>Nothing will be added until configured and reviewed.</div></div>
  </div>
</div>"""


def provider_item(index: int) -> dict:
    label = f"workload-{index:02d}"
    return {
        "candidate_id": f"covered-{index:02d}",
        "label": label,
        "state": "recommended",
        "monitor_default": True,
        "evidence": [{
            "metadata": {
                "monitoring_coverage": {
                    "status": "covered",
                    "kind": "provider_inventory",
                    "source_label": "Portainer",
                },
                "environment_name": "Broad Leaf - Goliath" if index <= 24 else "Broad Leaf - Arrrrr2",
            }
        }],
        "environment": "Broad Leaf - Goliath" if index <= 24 else "Broad Leaf - Arrrrr2",
    }


def main() -> None:
    for path in (BUILD7_CSS, BUILD8_CSS, BUILD8_JS):
        if not path.is_file():
            raise SystemExit(f"missing acceptance source: {path}")

    covered = [provider_item(index) for index in range(1, 47)]
    canonical = [
        {
            "candidate_id": f"canonical-{index}",
            "label": f"camera-{index}",
            "state": "already_monitored",
            "monitor_default": True,
            "configured_object_id": f"camera-{index}",
            "evidence": [],
        }
        for index in range(1, 4)
    ]
    new = [
        {
            "candidate_id": f"new-{index}",
            "label": f"new-service-{index}",
            "state": "recommended" if index <= 4 else "new",
            "monitor_default": index <= 4,
            "evidence": [],
        }
        for index in range(1, 7)
    ]
    attention = [
        {
            "candidate_id": "review-1",
            "label": "ambiguous-device",
            "state": "needs_review",
            "monitor_default": False,
            "evidence": [],
        },
        {
            "candidate_id": "aux-1",
            "label": "auxiliary-evidence",
            "state": "auxiliary",
            "monitor_default": False,
            "evidence": [],
        },
    ]
    items = covered + canonical + new + attention

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1180, "height": 820}, device_scale_factor=1)
        page.set_content(BASE_HTML)
        page.evaluate("items => { candidates=items; }", items)
        page.locator("#results").evaluate(
            "(root, rows) => { root.innerHTML=rows.join(''); }",
            [row_markup(item) for item in items],
        )
        page.add_style_tag(path=str(BUILD7_CSS))
        page.add_style_tag(path=str(BUILD8_CSS))
        page.add_script_tag(path=str(BUILD8_JS))

        new_section = page.locator('[data-coverage-section="new"]')
        covered_section = page.locator('[data-coverage-section="covered"]')
        attention_section = page.locator('[data-coverage-section="attention"]')
        assert new_section.count() == covered_section.count() == attention_section.count() == 1
        assert new_section.get_attribute("open") is not None, "new inventory must be expanded by default"
        assert covered_section.get_attribute("open") is None, "already-monitored inventory must be collapsed by default"
        assert attention_section.get_attribute("open") is not None, "needs-review evidence must remain visible"
        assert new_section.locator('.discovery-section-count').inner_text() == "6"
        assert covered_section.locator('.discovery-section-count').inner_text() == "49"
        assert attention_section.locator('.discovery-section-count').inner_text() == "2"

        # Portainer's generic provider coverage must override a context-free
        # server recommendation without provider-specific UI branching. The
        # section is intentionally collapsed here, so inspect DOM text rather
        # than rendered innerText.
        first_covered = covered_section.locator('.candidate').first
        covered_checkbox = first_covered.locator('input[type="checkbox"][data-id]')
        assert not covered_checkbox.is_checked(), "provider-covered workload must default to no canonical change"
        assert "Already monitored via Portainer" in (first_covered.text_content() or "")
        assert "No change" in (first_covered.locator('.discovery-proposed-action').text_content() or "")

        # Recommendation remains a separate concept from monitoring coverage.
        first_new = new_section.locator('.candidate').first
        first_new_text = first_new.inner_text()
        assert "Not monitored" in first_new_text
        assert "Recommended" in first_new_text
        assert "Start monitoring" in first_new.locator('.discovery-proposed-action').inner_text()

        summary = page.locator('#resultSummary').inner_text()
        assert summary.startswith("57 discovered · 49 already monitored · 6 not yet monitored · 2 auxiliary/needs review · 4 configuration changes selected")
        assert "Canonical configuration is unchanged." in summary
        assert page.locator('#selectNew').inner_text() == "Select all not yet monitored"

        # Collapsing already-covered provider inventory must reduce the default
        # review surface without touching any candidate action state.
        default_height = page.locator('#results').bounding_box()["height"]
        assert default_height < 2400, f"default discovery surface remains too tall: {default_height:.1f}px"
        assert not covered_checkbox.is_checked()
        covered_section.locator('summary').click()
        assert covered_section.get_attribute("open") is not None
        expanded_height = page.locator('#results').bounding_box()["height"]
        assert expanded_height > default_height * 3, "coverage collapse is not materially reducing provider-scale review height"
        assert not covered_checkbox.is_checked(), "section disclosure must never stage a configuration change"

        # The explicit action control is the only thing that turns provider
        # coverage into an adoption proposal.
        covered_checkbox.check()
        assert "Add configured monitor" in first_covered.locator('.discovery-proposed-action').inner_text()
        assert "5 configuration changes selected" in page.locator('#resultSummary').inner_text()
        covered_checkbox.uncheck()
        covered_section.locator('summary').click()
        assert covered_section.get_attribute("open") is None
        assert "4 configuration changes selected" in page.locator('#resultSummary').inner_text()

        # Keep production-like controls touchable while placing paired selects
        # side-by-side at iPad/desktop width.
        summary_box = new_section.locator('summary').bounding_box()
        assert summary_box and summary_box["height"] >= 44
        selects = first_new.locator('.wide > select')
        assert selects.count() == 2
        first_box = selects.nth(0).bounding_box()
        second_box = selects.nth(1).bounding_box()
        assert first_box and second_box
        assert first_box["height"] >= 40 and second_box["height"] >= 40
        assert abs(first_box["y"] - second_box["y"]) < 5, "paired production selects should share a row at iPad width"

        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()

    print(
        "UI v1.1.0 build 8 discovery coverage acceptance: PASS "
        "(provider coverage + proposed action separation + 46-row collapsed group + expanded new group + production controls)"
    )
    print(f"screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
