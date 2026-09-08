#!/usr/bin/env python3
"""Browser acceptance for the Phase-3 Discoveries disclosure-state dividend."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    css = (root / "sources" / "ui" / "1.1.11-build19" / "phase3-p1.css").read_text()
    html = f"""
    <!doctype html>
    <style>
      :root{{--line:#777;--panel:#fff;--muted:#555;--text:#111}}
      body{{margin:0;padding:24px;font:16px system-ui}}
      #results .discovery-coverage-section{{width:100%;border:1px solid var(--line)}}
      #results .discovery-coverage-section > summary{{min-height:46px;padding:10px 12px;display:flex;align-items:center;gap:9px;cursor:pointer}}
      {css}
    </style>
    <div id="results">
      <details class="discovery-coverage-section discovery-coverage-covered">
        <summary><strong>Already monitored</strong><span class="discovery-section-count">46</span></summary>
        <div class="discovery-section-rows"><p>fixture row</p></div>
      </details>
    </div>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 1366})
        page.set_content(html)
        details = page.locator("details")
        summary = page.locator("summary")

        assert not details.evaluate("node => node.open")
        assert summary.evaluate("node => node.tagName") == "SUMMARY"
        assert summary.evaluate("node => getComputedStyle(node, '::before').content") in {'"›"', "'›'"}
        collapsed = summary.evaluate("node => getComputedStyle(node, '::before').transform")
        summary_box = summary.bounding_box()
        details_box = details.bounding_box()
        assert summary_box and details_box
        assert summary_box["width"] >= details_box["width"] - 2, "whole summary must remain the touch target"

        summary.click()
        page.wait_for_timeout(160)
        assert details.evaluate("node => node.open")
        expanded = summary.evaluate("node => getComputedStyle(node, '::before').transform")
        assert expanded != collapsed, "disclosure indicator must visibly reflect open state"

        summary.focus()
        page.keyboard.press("Enter")
        assert not details.evaluate("node => node.open"), "native keyboard disclosure operation changed"
        page.keyboard.press("Enter")
        assert details.evaluate("node => node.open")

        browser.close()

    print(
        "UI Phase-3 disclosure acceptance: PASS "
        "(1024x1366 iPad viewport + visible open/closed state + full touch target + keyboard semantics)"
    )


if __name__ == "__main__":
    main()
