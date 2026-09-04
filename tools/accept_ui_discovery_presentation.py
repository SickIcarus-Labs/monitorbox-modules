#!/usr/bin/env python3
"""Browser acceptance for provider-scale Discoveries presentation (UI 1.0.2 build 7)."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "sources" / "ui" / "1.0.2-build7" / "discovery-presentation.css"
PROVENANCE = ROOT / "sources" / "ui" / "1.0.0-build4" / "provider-provenance-snippet.js"
SCREENSHOT = Path(os.environ.get("UI_DISCOVERY_SCREENSHOT", "/tmp/ui-discovery-presentation.png"))

BASE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
:root { --line:#cbd5e1; --muted:#64748b; --panel:#fff; --text:#0f172a; }
* { box-sizing:border-box; }
body { margin:0; padding:22px; font:14px/1.4 system-ui,sans-serif; color:var(--text); background:#f8fafc; }
#results { max-width:980px; margin:0 auto; }
.candidate { display:grid; grid-template-columns:32px minmax(0,1fr); gap:14px; margin:12px 0; padding:18px; border:1px solid var(--line); border-radius:12px; background:var(--panel); }
.wide { min-width:0; }
.candidate-title { font-weight:700; margin-bottom:6px; }
.muted { color:var(--muted); }
.row { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-top:9px; }
button,.button,select,input { font:inherit; }
button,.button,select { min-height:44px; padding:8px 11px; border:1px solid var(--line); border-radius:8px; background:#fff; }
</style></head><body><main id="results"></main></body></html>"""


def candidate_markup(index: int) -> str:
    checked = " checked" if index % 3 else ""
    return f"""
    <div class="candidate" data-candidate="candidate-{index}">
      <label aria-label="Select candidate {index}"><input type="checkbox"{checked}></label>
      <div class="wide">
        <div class="candidate-title">Service {index:02d}</div>
        <div class="muted">HTTP service · 192.168.3.{20 + index}:8080 · recommended monitor</div>
        <div class="row">
          <select aria-label="Disposition {index}"><option>Monitor</option><option>Ignore</option></select>
          <select aria-label="Expectation {index}"><option>Expected up</option><option>Optional</option></select>
          <button type="button">Configure</button>
        </div>
      </div>
    </div>"""


def main() -> None:
    if not CSS.is_file() or not PROVENANCE.is_file():
        raise SystemExit("discovery presentation acceptance sources are missing")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1024, "height": 768}, device_scale_factor=1)
        page.set_content(BASE_HTML + "<script></script>")
        page.locator("#results").evaluate(
            "(root, rows) => { root.innerHTML = rows.join(''); }",
            [candidate_markup(i) for i in range(1, 47)],
        )
        page.add_style_tag(path=str(CSS))
        page.add_script_tag(content=PROVENANCE.read_text(encoding="utf-8"))

        candidates = []
        for index in range(1, 47):
            candidates.append(
                {
                    "candidate_id": f"candidate-{index}",
                    "evidence": [
                        {
                            "metadata": {
                                "environment_name": "Broad Leaf - Goliath" if index <= 24 else "Broad Leaf - Arrrrr2",
                                "environment_key": "private-provider-key-must-not-render",
                                "environment_url": "https://private-provider-url.invalid:9443",
                                "compose_project": f"stack_{(index - 1) // 4 + 1:02d}",
                                "compose_service": f"service_{index:02d}",
                                "deployment_kind": "compose",
                                "provider_id": 9999,
                                "arbitrary_secret_metadata": "must-not-render",
                            }
                        }
                    ],
                }
            )

        page.evaluate(
            """items => {
              for (const item of items) {
                const row = document.querySelector(`[data-candidate="${item.candidate_id}"]`);
                renderProviderProvenance(row, item);
              }
            }""",
            candidates,
        )

        rows = page.locator("#results .candidate")
        assert rows.count() == 46, "provider-scale fixture must retain all 46 candidates"

        first_text = rows.first.inner_text()
        assert "Environment/System · Broad Leaf - Goliath" in first_text
        assert "Stack · stack_01" in first_text
        assert "Service · service_01" in first_text
        assert "private-provider-key-must-not-render" not in page.locator("body").inner_text()
        assert "private-provider-url.invalid" not in page.locator("body").inner_text()
        assert "must-not-render" not in page.locator("body").inner_text()

        # Provider provenance remains compact but visible on every provider-derived row.
        assert page.locator(".provider-provenance").count() == 46
        heights = rows.evaluate_all("els => els.map(el => el.getBoundingClientRect().height)")
        assert max(heights) <= 125, f"candidate row grew beyond compact bound: max={max(heights):.1f}px"
        assert sum(heights) <= 5600, f"46-row review remains too tall: total={sum(heights):.1f}px"

        # Preserve practical iPad/touch targets while reducing card padding.
        for selector in ("button", "select"):
            controls = rows.first.locator(selector)
            for control_index in range(controls.count()):
                box = controls.nth(control_index).bounding_box()
                assert box and box["height"] >= 40, f"{selector} touch target fell below 40px"
        checkbox = rows.first.locator('input[type="checkbox"]').bounding_box()
        assert checkbox and checkbox["width"] >= 20 and checkbox["height"] >= 20

        # At iPad width, provenance is visually subordinate to the candidate title.
        title_size = float(rows.first.locator(".candidate-title").evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
        provenance_size = float(rows.first.locator(".provider-provenance").evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
        assert provenance_size <= title_size

        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()

    print(
        "UI 1.0.2 build 7 discovery presentation acceptance: PASS "
        "(46 candidates + Environment/System + Compose provenance + bounded metadata + compact density + touch targets)"
    )
    print(f"screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
