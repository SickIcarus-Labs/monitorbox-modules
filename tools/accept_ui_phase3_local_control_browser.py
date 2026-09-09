#!/usr/bin/env python3
"""Browser acceptance for #253 path-loss and debug-copy behavior."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

LOCAL_URL = "http://192.168.3.5:8080"
FRIENDLY_HTTP = "http://monitor.sickicarus.com"
FRIENDLY_HTTPS = "https://monitor.sickicarus.com"

HTML = """<!doctype html>
<html><body>
<nav id="v22-menu"></nav>
<button id="global" class="global healthy"><span id="global-title">Everything is fine</span><span id="global-copy">All configured objects are reporting normally.</span><span id="global-state" class="state-pill healthy">Healthy</span></button>
<div id="preserved-card">Cached service card remains visible</div>
<span id="sync-label">Controller online</span>
<button id="debug-copy" type="button">Copy log</button>
<pre id="debug-log">21:23:10.810 · INTEGRATION · cached event one\n21:23:11.087 · CHECKS · cached event two</pre>
<div id="toast"></div>
<script>
window.app={state:{sites:[{id:'broadleaf'}]}};
window.shouldFail=false;
window.toastMessages=[];
window.toast=message=>window.toastMessages.push(String(message));
window.renderOffline=()=>{document.getElementById('global-title').textContent='MonitorBox is unreachable';};
window.loadState=async()=>{
  if(window.shouldFail)throw new TypeError('Failed to fetch');
  return window.app.state;
};
</script>
</body></html>"""


async def _assert_touch_target(locator, label: str) -> None:
    box = await locator.bounding_box()
    assert box is not None, f"{label} has no rendered bounding box"
    assert box["height"] >= 44, f"{label} height is {box['height']}, expected >= 44"
    assert box["width"] >= 44, f"{label} width is {box['width']}, expected >= 44"


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = (root / "sources/ui/1.1.12-build20/phase3-local-control.js").read_text()
    style = (root / "sources/ui/1.1.12-build20/phase3-local-control.css").read_text()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1024, "height": 1366})

        async def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/api/v2/config/local-access":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "available": True,
                            "role": "local-control-plane",
                            "local_url": LOCAL_URL,
                            "source": "canonical-self-object",
                        }
                    ),
                )
            else:
                await route.fulfill(status=200, content_type="text/html", body=HTML)

        await context.route("**/*", route_request)

        # Friendly HTTP: learn/cache local authority while healthy, then prove a
        # same-origin transport failure does not become a false appliance failure.
        page = await context.new_page()
        await page.goto(FRIENDLY_HTTP + "/")
        await page.add_style_tag(content=style)
        await page.add_script_tag(content=source)
        await page.wait_for_function(
            "document.querySelector('#v22-local-access')?.href === 'http://192.168.3.5:8080/'"
        )
        await page.evaluate("window.loadState()")
        await page.evaluate("window.shouldFail=true")
        await page.evaluate("window.loadState().catch(()=>null)")

        assert await page.locator("#global-title").inner_text() == "Connection path unavailable"
        copy = await page.locator("#global-copy").inner_text()
        assert "Last canonical state was" in copy, copy
        assert "controller health is not proven failed" in copy, copy
        assert await page.locator("#global-state").inner_text() == "Path unavailable"
        assert await page.locator("#sync-label").inner_text() == "Browser path unavailable"
        assert await page.locator("#preserved-card").inner_text() == "Cached service card remains visible"
        recovery = page.locator("#mb-local-recovery a")
        assert await recovery.get_attribute("href") == LOCAL_URL
        assert await page.locator("#mb-local-recovery").is_visible()
        await _assert_touch_target(recovery, "local recovery link")

        # Raw HTTP/insecure context: Copy log freezes the current rendered text in
        # a stable textarea instead of selecting the rapidly mutating live <pre>.
        assert await page.evaluate("window.isSecureContext") is False
        original = await page.locator("#debug-log").inner_text()
        await page.locator("#debug-copy").click()
        dialog = page.locator("#debug-copy-fallback")
        assert await dialog.is_visible()
        field = dialog.locator("textarea")
        assert await field.input_value() == original
        await page.locator("#debug-log").evaluate(
            "node=>node.textContent='new live event that must not mutate the frozen snapshot'"
        )
        assert await field.input_value() == original
        await _assert_touch_target(dialog.locator("[data-copy-select]"), "frozen-copy Select all")
        await _assert_touch_target(dialog.locator("button[value=close]").last, "frozen-copy Close")
        await _assert_touch_target(dialog.locator("button.icon-button"), "frozen-copy close icon")
        await dialog.locator("button[value=close]").last.click()

        # Direct LAN origin remains the normal same-origin control plane and marks
        # the advertised local URL as the address currently in use.
        direct = await context.new_page()
        await direct.goto(LOCAL_URL + "/")
        await direct.add_style_tag(content=style)
        await direct.add_script_tag(content=source)
        await direct.wait_for_function(
            "document.querySelector('#v22-local-access')?.textContent === 'Local access · this address'"
        )
        assert await direct.evaluate("window.loadState().then(()=>true)") is True

        # HTTPS path keeps one-tap clipboard behavior; the manual dialog is only a
        # fallback when the browser denies/unavailable Clipboard API.
        secure = await context.new_page()
        await secure.goto(FRIENDLY_HTTPS + "/")
        await secure.add_style_tag(content=style)
        await secure.evaluate(
            """() => {
              window.copiedText='';
              Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedText=text;}}});
            }"""
        )
        await secure.add_script_tag(content=source)
        assert await secure.evaluate("window.isSecureContext") is True
        secure_text = await secure.locator("#debug-log").inner_text()
        await secure.locator("#debug-copy").click()
        await secure.wait_for_function("window.copiedText.length > 0")
        assert await secure.evaluate("window.copiedText") == secure_text
        assert await secure.locator("#debug-copy-fallback").count() == 0

        await context.close()
        await browser.close()

    print(
        "UI Phase-3 local-control browser acceptance: PASS "
        "(stale path-loss UX + local recovery + 44px iPad controls + frozen HTTP copy + HTTPS clipboard)"
    )


if __name__ == "__main__":
    asyncio.run(main())
