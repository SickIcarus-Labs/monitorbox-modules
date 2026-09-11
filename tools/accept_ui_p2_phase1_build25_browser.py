#!/usr/bin/env python3
"""Chromium acceptance for the P2 Phase-1 build-25 Broad Leaf corrections."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import build_first_party_ui_build25 as candidate

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
    # Deliberately reverse normal channel priority and use physical first-party labels;
    # the compact summary must still render dev, beta, stable.
    "repositories": [
        {"repository_id": "official", "display_name": "MonitorBox Official", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
        {"repository_id": "official-beta", "display_name": "MonitorBox Official Beta", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
        {"repository_id": "official-dev", "display_name": "MonitorBox Official Dev", "official": True, "enabled": True, "catalog_fetched_at": "2026-09-10T00:00:00Z", "actions": []},
    ],
    "modules": [
        {
            "module_id": "example.optional",
            "display_name": "Backup / Restore",
            "description": "A module-owned description carried through generic authority.",
            "installed": {"version": "1.0.3", "build": 4, "source_repository_id": "official-beta", "artifact_identity": "sha256:one", "digest_sha256": "1" * 64, "lifecycle_policy": "optional", "lifecycle_state": "active", "enabled": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "previous": {"version": "1.0.2", "build": 3, "source_repository_id": "official-beta", "artifact_identity": "sha256:previous"},
            "available": {"version": "1.0.4", "build": 5, "repository_id": "official-dev", "digest_sha256": "2" * 64, "signature_identity": "test", "update_available": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "actions": ["update", "rollback", "remove"],
        },
        {
            "module_id": "example.required",
            "display_name": "Configuration / Bootstrap With A Longer Name",
            "description": None,
            "installed": {"version": "1.0.4", "build": 5, "source_repository_id": "official-dev", "artifact_identity": "sha256:required", "digest_sha256": "3" * 64, "lifecycle_policy": "required", "lifecycle_state": "active", "enabled": True, "requires_core": ">=2.3.1 <3.0.0", "requires_runtime_api": ">=1 <2"},
            "previous": None,
            "available": {"version": "1.0.5", "build": 6, "repository_id": "official-dev", "digest_sha256": "4" * 64, "signature_identity": "test", "update_available": True},
            "actions": ["update"],
        },
        {
            "module_id": "example.available",
            "display_name": "Available Example",
            "description": "Not installed yet.",
            "installed": None,
            "previous": None,
            "available": {"version": "3.0.0", "build": 1, "repository_id": "official", "digest_sha256": "5" * 64, "signature_identity": "test", "update_available": False},
            "actions": ["install"],
        },
    ],
}


def shellify(markup: str) -> str:
    style = '<link rel="stylesheet" href="/static/app-shell.css?v=1.1.14-25">'
    icon = '<link rel="apple-touch-icon" sizes="180x180" href="/static/monitorbox-apple-180.png?v=1.1.14-25">'
    script = '<script src="/static/app-shell.js?v=1.1.14-25" defer></script>'
    return markup.replace("</head>", style + icon + "</head>").replace("</body>", script + "</body>")


def legacy_settings_fixture(title: str, local_id: str) -> str:
    return shellify(f"""<!doctype html><html><head><title>{title}</title></head><body>
<header class='top'>
  <button id='settingsV22MenuButton' class='settings-v22-menu-button' aria-label='Open MonitorBox navigation'>☰</button>
  <a id='settingsProductHome' href='/'>MonitorBox</a>
  <a id='settingsBackToMonitoring' href='/'>Back to Main Dashboard</a>
  <button id='{local_id}' type='button'>Reload</button>
  <span id='settingsV22Spacer' class='spacer'></span>
  <a id='settingsSiteHome' href='/'>Broad Leaf</a>
</header>
<nav id='settingsV22Menu'><a href='/settings'>Configure</a></nav>
<main><h1>{title}</h1><p>fixture</p></main>
</body></html>""")


def install_routes(page, assets: dict[str, bytes]) -> None:
    fixtures = {
        "/settings/policy": ("Actions & policy", "policy-local-action"),
        "/settings/dashboard": ("Dashboard / Graphs", "graphs-local-action"),
        "/settings/discover": ("Discoveries", "discover-local-action"),
        "/settings/recovery": ("Backup & Restore", "recovery-local-action"),
    }

    def route(route):
        url = route.request.url
        path = url.removeprefix(ORIGIN).split("?", 1)[0]
        if path == "/modules":
            route.fulfill(status=200, content_type="text/html", body=shellify(assets["modules.html"].decode()))
        elif path in fixtures:
            title, local_id = fixtures[path]
            route.fulfill(status=200, content_type="text/html", body=legacy_settings_fixture(title, local_id))
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
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"authenticated": True, "setup_complete": True}))
        elif path == "/api/v2/config/session":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"csrf_token": "test-token", "actor": "admin"}))
        elif path == "/api/v2/build":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"version": "2.4.0", "build": "0650", "channel": "dev"}))
        elif path == "/api/v2/state":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"sites": [{"id": "broadleaf", "label": "Broad Leaf", "state": "healthy"}]}))
        else:
            route.fulfill(status=404, body="not found")

    page.route(f"{ORIGIN}/**", route)


def assert_modules(page) -> None:
    page.goto(f"{ORIGIN}/modules", wait_until="networkidle")
    assert page.locator("#mb-app-shell").count() == 1
    assert "v2.4.0" in page.locator("#mb-shell-core").inner_text()

    # Physical #286 findings: compact first-party channel summary and healthy auth.
    assert page.locator(".modules-repository-one-line").inner_text() == "Repositories enabled: dev, beta, stable"
    auth_height = page.locator("#modules-auth").bounding_box()["height"]
    assert auth_height < 65, auth_height
    assert page.locator("#modules-login-form").is_hidden()

    installed = page.locator('.modules-group[data-group="installed"]')
    available = page.locator('.modules-group[data-group="available"]')
    assert installed.evaluate("el => el.open")
    assert not available.evaluate("el => el.open")

    # Every disclosure gets an explicit chevron, and orientation changes with state.
    available_summary = available.locator(":scope > summary")
    content = available_summary.evaluate("el => getComputedStyle(el, '::before').content")
    closed_transform = available_summary.evaluate("el => getComputedStyle(el, '::before').transform")
    assert "›" in content, content
    available_summary.click()
    assert available.evaluate("el => el.open")
    open_transform = available_summary.evaluate("el => getComputedStyle(el, '::before').transform")
    assert open_transform != closed_transform, (closed_transform, open_transform)

    # Release/source columns must align even when module names and badges differ.
    release_x = installed.locator(".modules-release").evaluate_all("els => els.map(el => el.getBoundingClientRect().left)")
    source_x = installed.locator(".modules-source").evaluate_all("els => els.map(el => el.getBoundingClientRect().left)")
    assert max(release_x) - min(release_x) < 2, release_x
    assert max(source_x) - min(source_x) < 2, source_x
    assert installed.locator('[data-module-id="example.optional"] .modules-source').inner_text() == "beta"
    assert installed.locator('[data-module-id="example.required"] .modules-source').inner_text() == "dev"

    # #287 remains intact after the physical-polish pass.
    optional = page.locator('[data-module-id="example.optional"]')
    optional.locator(":scope > summary").click()
    actions = optional.locator("[data-module-action]").evaluate_all("els => els.map(el => el.dataset.moduleAction)")
    assert actions == ["update", "rollback", "remove"], actions
    required = page.locator('[data-module-id="example.required"]')
    required.locator(":scope > summary").click()
    required_actions = required.locator("[data-module-action]").evaluate_all("els => els.map(el => el.dataset.moduleAction)")
    assert required_actions == ["update"], required_actions


def assert_single_shell_menu(page) -> None:
    for path, local_id in (
        ("/settings/policy", "policy-local-action"),
        ("/settings/dashboard", "graphs-local-action"),
        ("/settings/discover", "discover-local-action"),
        ("/settings/recovery", "recovery-local-action"),
    ):
        page.goto(f"{ORIGIN}{path}", wait_until="networkidle")
        assert page.locator("#mb-app-shell").count() == 1, path
        assert page.locator(".mb-shell-menu").count() == 1, path
        assert page.locator("#settingsV22MenuButton").count() == 0, path
        assert page.locator("#settingsV22Menu").count() == 0, path
        assert page.locator(f".mb-page-actions #{local_id}").count() == 1, path
        assert "☰" not in page.locator(".mb-page-actions").inner_text(), path


def run_case(browser, assets: dict[str, bytes], viewport: dict[str, int]) -> None:
    page = browser.new_page(viewport=viewport)
    install_routes(page, assets)
    assert_modules(page)
    assert_single_shell_menu(page)
    page.close()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build25_assets(root)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run_case(browser, assets, {"width": 1366, "height": 900})
            run_case(browser, assets, {"width": 1024, "height": 1366})
        finally:
            browser.close()
    print("P2 Phase-1 UI build25 Broad Leaf correction desktop+iPad acceptance: PASS")


if __name__ == "__main__":
    main()
