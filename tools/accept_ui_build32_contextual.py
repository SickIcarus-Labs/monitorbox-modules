#!/usr/bin/env python3
"""Desktop/iPad acceptance for #315 contextual canonical configuration links."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

import build_first_party_ui_build32 as candidate

ORIGIN = "http://monitorbox.test"

CONTEXTS = {
    "service-a": {
        "resource": {
            "role": "resource",
            "id": "service-a",
            "label": "Service A",
            "editor_ref": "mbx1/resource/lab/service-a",
            "href": "/settings/configuration/editor?ref=mbx1%2Fresource%2Flab%2Fservice-a",
        },
        "connections": [
            {
                "role": "connection",
                "id": "connection_http_a",
                "label": "HTTP(S)",
                "editor_ref": "mbx1/connection/lab/connection_http_a",
                "href": "/settings/configuration/editor?ref=mbx1%2Fconnection%2Flab%2Fconnection_http_a",
            },
            {
                "role": "connection",
                "id": "connection_tcp_a",
                "label": "TCP",
                "editor_ref": "mbx1/connection/lab/connection_tcp_a",
                "href": "/settings/configuration/editor?ref=mbx1%2Fconnection%2Flab%2Fconnection_tcp_a",
            },
        ],
        "systems": [
            {
                "role": "system",
                "id": "host-a",
                "label": "Host A",
                "editor_ref": "mbx1/system/lab/host-a",
                "href": "/settings/configuration/editor?ref=mbx1%2Fsystem%2Flab%2Fhost-a",
            }
        ],
    },
    "direct-a": {
        "resource": {
            "role": "resource",
            "id": "direct-a",
            "label": "Direct A",
            "editor_ref": "mbx1/resource/lab/direct-a",
            "href": "/settings/configuration/editor?ref=mbx1%2Fresource%2Flab%2Fdirect-a",
        },
        "connections": [],
        "systems": [],
    },
}


def package_assets(root: Path) -> tuple[dict[str, bytes], str]:
    files = candidate._package_files(root)
    prefix = "monitorbox_ui_b32/"
    assert all(path.startswith(prefix) for path in files), sorted(files)[:5]
    init = files[prefix + "__init__.py"].decode("utf-8")
    assets = {
        path.removeprefix(prefix + "assets/"): payload
        for path, payload in files.items()
        if path.startswith(prefix + "assets/")
    }
    assert candidate.UI_GENERATION in init
    assert candidate.PARENT_GENERATION not in init
    assert "contextual-configuration.js" in init
    assert "contextual-configuration.css" in init
    js = assets["contextual-configuration.js"].decode("utf-8")
    css = assets["contextual-configuration.css"].decode("utf-8")
    assert "/api/v2/config/context?resource_id=" in js
    assert "/settings/configuration/editor?ref=" in js
    assert "#drawer-body" in js
    assert "min-height:44px" in css
    assert "data-object" not in js
    for provider in ("portainer", "scrypted", "unifi", "nut"):
        assert provider not in js.casefold(), provider
    return assets, init


def fixture() -> str:
    cards = "".join(
        f'<button class="card" id="{object_id}-card" data-object="{object_id}" type="button">{label}</button>'
        for object_id, label in (
            ("service-a", "Service A"),
            ("direct-a", "Direct A"),
            ("missing-a", "Missing A"),
        )
    )
    return f"""<!doctype html><html><head>
<link rel="stylesheet" href="/static/contextual-configuration.css">
<script src="/static/contextual-configuration.js" defer></script>
</head><body>
<div id="cards">{cards}</div>
<div id="drawer-body"></div>
<script>
for (const card of document.querySelectorAll('[data-object]')) {{
  card.addEventListener('click', () => {{
    history.replaceState(null, '', `#lab/${{encodeURIComponent(card.dataset.object)}}`);
    document.querySelector('#drawer-body').innerHTML =
      '<section class="detail-section"><h3>Current state</h3></section>' +
      '<section class="detail-section"><h3>History</h3></section>';
  }});
}}
</script>
</body></html>"""


def install_routes(page, assets: dict[str, bytes], seen: list[str]) -> None:
    def route(route):
        parsed = urlparse(route.request.url)
        if parsed.path == "/":
            route.fulfill(status=200, content_type="text/html", body=fixture())
            return
        if parsed.path.startswith("/static/"):
            name = parsed.path.rsplit("/", 1)[-1]
            payload = assets.get(name)
            if payload is None:
                route.fulfill(status=404, body="missing")
                return
            content_type = "text/javascript" if name.endswith(".js") else "text/css"
            route.fulfill(status=200, content_type=content_type, body=payload)
            return
        if parsed.path == "/api/v2/config/context":
            resource_id = parse_qs(parsed.query).get("resource_id", [""])[0]
            seen.append(resource_id)
            payload = CONTEXTS.get(resource_id)
            if payload is None:
                route.fulfill(status=404, body="unresolved")
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload),
                )
            return
        if parsed.path == "/settings/configuration/editor":
            route.fulfill(status=200, content_type="text/html", body="<h1>Canonical editor</h1>")
            return
        route.fulfill(status=404, body="not found")

    page.route(f"{ORIGIN}/**", route)


def assert_contextual_flow(browser, assets: dict[str, bytes], viewport: dict[str, int]) -> None:
    page = browser.new_page(viewport=viewport)
    seen: list[str] = []
    install_routes(page, assets, seen)
    page.goto(ORIGIN + "/", wait_until="networkidle")

    # Dense operational collection remains untouched: no row Configure control.
    assert page.locator("[data-contextual-configuration]").count() == 0
    assert page.locator("#service-a-card a").count() == 0
    assert "⚙" not in page.locator("#cards").inner_text()

    # Tap 1: drill into the Resource. The contextual block appears in detail only.
    page.locator("#service-a-card").click()
    section = page.locator("[data-contextual-configuration]")
    section.wait_for(state="visible")
    assert seen[-1] == "service-a"
    assert section.locator("h3").inner_text() == "Configuration"
    links = section.locator("a").all_inner_texts()
    assert len(links) == 4, links
    assert links[0] == "Configure Service A", links
    assert set(links[1:]) == {
        "Configure Connection · HTTP(S)",
        "Configure Connection · TCP",
        "Configure System · Host A",
    }, links
    assert page.locator("#drawer-body > .detail-section").all_inner_texts()[-1] == "History"
    for box in section.locator("a").evaluate_all("els => els.map(el => el.getBoundingClientRect())"):
        assert box["height"] >= 44, box

    # Tap 2: the selected Resource enters #313's canonical editor directly.
    section.locator("a").first.click()
    page.wait_for_url("**/settings/configuration/editor?ref=**")
    assert page.locator("h1").inner_text() == "Canonical editor"
    page.close()


def assert_fail_closed(browser, assets: dict[str, bytes]) -> None:
    page = browser.new_page(viewport={"width": 1024, "height": 1366})
    seen: list[str] = []
    install_routes(page, assets, seen)
    page.goto(ORIGIN + "/", wait_until="networkidle")

    page.locator("#direct-a-card").click()
    section = page.locator("[data-contextual-configuration]")
    section.wait_for(state="visible")
    assert section.locator("a").all_inner_texts() == ["Configure Direct A"]
    assert "Connection" not in section.inner_text()
    assert "Hosting / dependency Systems" not in section.inner_text()

    page.locator("#missing-a-card").click()
    page.wait_for_timeout(150)
    assert seen[-1] == "missing-a"
    assert page.locator("[data-contextual-configuration]").count() == 0
    page.close()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets, _init = package_assets(root)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            assert_contextual_flow(browser, assets, {"width": 1366, "height": 900})
            assert_contextual_flow(browser, assets, {"width": 1024, "height": 1366})
            assert_fail_closed(browser, assets)
        finally:
            browser.close()
    print("UI v1.2.0 build32 #315 contextual configuration acceptance: PASS")


if __name__ == "__main__":
    main()
