#!/usr/bin/env python3
"""Chromium acceptance for P2 Phase-1 shell and Modules UX at desktop/iPad sizes."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import build_first_party_ui_build24 as candidate

ORIGIN = "http://monitorbox.test"

MODULE_MODEL = {
    "installation_fingerprint": "sha256:test",
    "capabilities": {
        "catalog_refresh": True,
        "package_install": True,
        "module_mutation": True,
        "repository_mutation": True,
    },
    "repository_error": None,
    "repositories": [
        {"repository_id": "dev", "display_name": "dev", "index_url": "https://dev.invalid", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
        {"repository_id": "beta", "display_name": "beta", "index_url": "https://beta.invalid", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
        {"repository_id": "stable", "display_name": "stable", "index_url": "https://stable.invalid", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
    ],
    "modules": [
        {
            "module_id": "example.optional",
            "display_name": "Optional Example",
            "description": "A module-owned description carried through generic authority.",
            "installed": {"version": "1.0.0", "build": 4, "source_repository_id": "dev", "artifact_identity": "sha256:one", "digest_sha256": "1" * 64, "lifecycle_policy": "optional", "lifecycle_state": "active", "enabled": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "previous": {"version": "0.9.0", "build": 3, "source_repository_id": "dev", "artifact_identity": "sha256:previous"},
            "available": {"version": "1.1.0", "build": 5, "repository_id": "beta", "digest_sha256": "2" * 64, "signature_identity": "test", "update_available": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "actions": ["update", "rollback", "remove"],
        },
        {
            "module_id": "example.required",
            "display_name": "Required Example",
            "description": None,
            "installed": {"version": "2.0.0", "build": 9, "source_repository_id": "stable", "artifact_identity": "sha256:required", "digest_sha256": "3" * 64, "lifecycle_policy": "required", "lifecycle_state": "active", "enabled": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "previous": None,
            "available": {"version": "2.1.0", "build": 10, "repository_id": "stable", "digest_sha256": "4" * 64, "signature_identity": "test", "update_available": True},
            "actions": ["update"],
        },
        {
            "module_id": "example.available",
            "display_name": "Available Example",
            "description": "Not installed yet.",
            "installed": None,
            "previous": None,
            "available": {"version": "3.0.0", "build": 1, "repository_id": "dev", "digest_sha256": "5" * 64, "signature_identity": "test", "update_available": False},
            "actions": ["install"],
        },
    ],
}


def shellify(markup: str) -> str:
    style = '<link rel="stylesheet" href="/static/app-shell.css?v=1.1.14-24">'
    icon = '<link rel="apple-touch-icon" sizes="180x180" href="/static/monitorbox-apple-180.png?v=1.1.14-24">'
    script = '<script src="/static/app-shell.js?v=1.1.14-24" defer></script>'
    return markup.replace("</head>", style + icon + "</head>").replace("</body>", script + "</body>")


def run_case(browser, assets: dict[str, bytes], viewport: dict[str, int]) -> None:
    page = browser.new_page(viewport=viewport)

    def route(route):
        url = route.request.url
        path = url.removeprefix(ORIGIN).split("?", 1)[0]
        if path == "/modules":
            route.fulfill(status=200, content_type="text/html", body=shellify(assets["modules.html"].decode()))
        elif path == "/":
            route.fulfill(status=200, content_type="text/html", body=shellify(assets["dashboard.html"].decode()))
        elif path == "/settings":
            route.fulfill(status=200, content_type="text/html", body=shellify("<!doctype html><html><head><title>Configuration</title></head><body><header class='top'><a href='/'>Home</a><h1>Configuration</h1><button id='local-action'>Local action</button></header><main><h2>Settings fixture</h2></main></body></html>"))
        elif path.startswith("/static/"):
            name = path.rsplit("/", 1)[-1]
            payload = assets.get(name)
            if payload is None:
                route.fulfill(status=404, body="missing")
            else:
                content_type = "text/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "image/png" if name.endswith(".png") else "image/svg+xml" if name.endswith(".svg") else "application/manifest+json"
                route.fulfill(status=200, content_type=content_type, body=payload)
        elif path == "/api/v2/modules":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(MODULE_MODEL))
        elif path == "/api/v2/config/status":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"authenticated": True}))
        elif path == "/api/v2/config/session":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"csrf_token": "test-token", "actor": "acceptance"}))
        elif path == "/api/v2/build":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"version": "2.3.1", "build": "0612", "channel": "dev"}))
        elif path == "/api/v2/state":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"sites": [{"id": "broadleaf", "label": "Broad Leaf", "state": "healthy"}]}))
        else:
            route.fulfill(status=404, body="not found")

    page.route(f"{ORIGIN}/**", route)
    page.goto(f"{ORIGIN}/modules", wait_until="networkidle")

    # #289/#290 shell identity survives the managed Modules page and exposes Home.
    assert page.locator("#mb-app-shell").count() == 1
    assert page.locator(".mb-shell-home").get_attribute("href") == "/"
    assert "v2.3.1" in page.locator("#mb-shell-core").inner_text()
    assert "build 0612" in page.locator("#mb-shell-core").inner_text()
    assert "dev" in page.locator("#mb-shell-core").inner_text()
    assert "Broad Leaf" in page.locator("#mb-shell-site").inner_text()

    # #286 healthy repositories are one-line; details remain collapsed.
    assert page.locator(".modules-repository-one-line").inner_text() == "Repositories enabled: dev, beta, stable"
    assert not page.locator(".modules-repository-details").evaluate("el => el.open")

    installed = page.locator('.modules-group[data-group="installed"]')
    available = page.locator('.modules-group[data-group="available"]')
    assert installed.evaluate("el => el.open")
    assert not available.evaluate("el => el.open")
    assert "Installed Modules (2)" in installed.locator(":scope > summary").inner_text()
    assert "Available Modules (1)" in available.locator(":scope > summary").inner_text()
    assert page.locator('[data-module-id="example.optional"]').count() == 1

    # #287 dividend: Update, Roll Back and Remove all coexist for one optional module.
    optional = page.locator('[data-module-id="example.optional"]')
    optional.locator(":scope > summary").click()
    actions = optional.locator("[data-module-action]").evaluate_all("els => els.map(el => el.dataset.moduleAction)")
    assert actions == ["update", "rollback", "remove"], actions

    required = page.locator('[data-module-id="example.required"]')
    required.locator(":scope > summary").click()
    required_actions = required.locator("[data-module-action]").evaluate_all("els => els.map(el => el.dataset.moduleAction)")
    assert required_actions == ["update"], required_actions
    assert "No module description is published." in required.locator(".modules-description").inner_text()

    available.locator(":scope > summary").click()
    assert page.locator('[data-module-id="example.available"]').count() == 1

    # Shared shell must also replace legacy settings chrome without swallowing page-local controls.
    page.goto(f"{ORIGIN}/settings", wait_until="networkidle")
    assert page.locator("#mb-app-shell").count() == 1
    assert page.locator("header.top").count() == 0
    assert page.locator("#local-action").count() == 1
    assert page.locator(".mb-page-actions #local-action").count() == 1
    page.close()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build24_assets(root)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run_case(browser, assets, {"width": 1366, "height": 900})
            run_case(browser, assets, {"width": 1024, "height": 1366})
        finally:
            browser.close()
    print("P2 Phase-1 UI build24 desktop+iPad browser acceptance: PASS")


if __name__ == "__main__":
    main()
