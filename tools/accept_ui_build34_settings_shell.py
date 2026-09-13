#!/usr/bin/env python3
"""Desktop/iPad/mobile browser acceptance for #316 plus #305 dividend."""
from __future__ import annotations

import asyncio
import importlib
import queue
import sys
import tempfile
import threading
from pathlib import Path

from aiohttp import web
from playwright.sync_api import sync_playwright

import build_first_party_ui_build33 as parent
import build_first_party_ui_build34 as candidate

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_LINKS = [
    ("Configuration", "/settings"),
    ("Modules", "/modules"),
    ("Backup & Restore", "/settings/recovery"),
]


class TestServer:
    def __init__(self, ui_module) -> None:
        self.ui_module = ui_module
        self.loop = None
        self.runner = None
        self.thread = None
        self.port = 0

    def start(self) -> None:
        ready = queue.Queue()

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def state(_: web.Request) -> web.Response:
                return web.json_response({
                    "title": "MonitorBox",
                    "overall": "healthy",
                    "sites": [{
                        "id": "broadleaf",
                        "label": "Broad Leaf",
                        "state": "healthy",
                        "agents": [],
                        "objects": [],
                        "power": {"state": "not_configured", "ups": {}},
                    }],
                })

            async def debug_config(_: web.Request) -> web.Response:
                return web.json_response({"enabled": True, "buffer_limit": 1000})

            async def discovery_summary(_: web.Request) -> web.Response:
                return web.json_response({"pending_count": 0, "visibility_impaired": False})

            async def surface(request: web.Request) -> web.Response:
                title = {
                    "/surface/service": "Service A",
                    "/surface/system": "System A",
                    "/surface/detail": "Detail",
                }.get(request.path, "Surface")
                return web.Response(
                    text=(
                        "<!doctype html><html><head><title>" + title + "</title></head>"
                        "<body data-mb-page-title='" + title + "'>"
                        "<main><h1>" + title + "</h1></main></body></html>"
                    ),
                    content_type="text/html",
                )

            async def recovery(_: web.Request) -> web.Response:
                return web.Response(
                    text="<!doctype html><html><head><title>Backup & Restore</title></head>"
                         "<body><main><h1>Backup & Restore</h1></main></body></html>",
                    content_type="text/html",
                )

            async def editor(_: web.Request) -> web.Response:
                return web.Response(
                    text="<!doctype html><html><head><title>Configuration editor</title></head>"
                         "<body data-mb-page-title='Configuration editor' "
                         "data-mb-up-href='/settings' data-mb-up-label='Configuration'>"
                         "<main><h1>Configuration editor</h1></main></body></html>",
                    content_type="text/html",
                )

            async def api_fallback(_: web.Request) -> web.Response:
                return web.json_response({})

            async def boot():
                app = web.Application()
                app.router.add_get("/api/v2/state", state)
                app.router.add_get("/api/v2/debug/config", debug_config)
                app.router.add_get("/api/v2/config/discovery/runtime/summary", discovery_summary)
                app.router.add_get("/surface/service", surface)
                app.router.add_get("/surface/system", surface)
                app.router.add_get("/surface/detail", surface)
                app.router.add_get("/settings/recovery", recovery)
                app.router.add_get("/settings/configuration/editor", editor)
                self.ui_module.install(app)
                app.router.add_route("*", "/api/v2/{tail:.*}", api_fallback)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                return runner, int(site._server.sockets[0].getsockname()[1])

            try:
                runner, port = loop.run_until_complete(boot())
                ready.put((port, loop, runner))
                loop.run_forever()
            except BaseException as exc:
                ready.put(exc)
            finally:
                loop.close()

        self.thread = threading.Thread(target=run, name="build34-ui-test-server", daemon=True)
        self.thread.start()
        result = ready.get(timeout=15)
        if isinstance(result, BaseException):
            raise result
        self.port, self.loop, self.runner = result

    def stop(self) -> None:
        if self.loop is None or self.runner is None:
            return
        future = asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop)
        future.result(timeout=10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=10)


def write_runtime_package(root: Path):
    files = candidate._package_files(ROOT)
    prefix = candidate.TARGET_IMPORT_PACKAGE + "/"
    for path, payload in files.items():
        assert path.startswith(prefix), path
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    monitorbox = root / "monitorbox"
    (monitorbox / "v2").mkdir(parents=True)
    (monitorbox / "__init__.py").write_text("", encoding="utf-8")
    (monitorbox / "v2" / "__init__.py").write_text("", encoding="utf-8")
    (monitorbox / "v2" / "build_info.py").write_text(
        "class Identity:\n"
        "    display = 'v2.4.1 · build 1000 · dev'\n"
        "    def as_dict(self):\n"
        "        return {'version':'2.4.1','build':'1000','channel':'dev'}\n"
        "def current_build_identity():\n"
        "    return Identity()\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    return importlib.import_module(candidate.TARGET_IMPORT_PACKAGE)


def package_contract() -> None:
    files = candidate._package_files(ROOT)
    prefix = candidate.TARGET_IMPORT_PACKAGE + "/"
    assets = {
        path.removeprefix(prefix + "assets/"): payload
        for path, payload in files.items()
        if path.startswith(prefix + "assets/")
    }
    init = files[prefix + "__init__.py"]
    assert candidate.UI_GENERATION.encode() in init
    assert candidate.PARENT_GENERATION.encode() not in init
    assert b"settings_shell_presentation" in init
    assert b"global_debug_presentation" in init
    assert b"_canonical_global_debug_fragments" in init
    assert b"settings-shell.js" in init and b"settings-shell.css" in init
    assert "settings-shell.js" in assets and "settings-shell.css" in assets

    parent_files = parent._package_files(ROOT)
    parent_prefix = parent.TARGET_IMPORT_PACKAGE + "/assets/"
    for name in ("global-debug.js", "global-debug.css", "dashboard.html"):
        assert name in assets, name
        assert parent_prefix + name in parent_files, name
        expected = parent_files[parent_prefix + name].replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(), candidate.TARGET_IMPORT_PACKAGE.encode()
        )
        assert assets[name] == expected, name

    assert assets["contextual-configuration.js"] == parent_files[
        f"{parent.TARGET_IMPORT_PACKAGE}/assets/contextual-configuration.js"
    ]
    assert assets["contextual-configuration.css"] == parent_files[
        f"{parent.TARGET_IMPORT_PACKAGE}/assets/contextual-configuration.css"
    ]

    js = assets["settings-shell.js"].decode("utf-8")
    css = assets["settings-shell.css"].decode("utf-8")
    for label, href in EXPECTED_LINKS:
        assert label in js and href in js
    assert "mb-shell-menu" in js and "mb-shell-nav" in js
    assert "Debug" in js and "DBG" not in js
    assert 'content:">_"' in css
    assert r'content:"\2699"' in css
    assert "min-width:44px" in css and "min-height:44px" in css
    for forbidden in ("portainer", "scrypted", "unifi", "nut", "data-object-gear"):
        assert forbidden not in js.casefold(), forbidden


def assert_shell(page, *, narrow: bool) -> None:
    shell = page.locator("#mb-app-shell.mb-settings-shell")
    shell.wait_for(state="visible")
    assert page.locator(".mb-shell-menu").count() == 0
    assert page.locator("#mb-shell-nav").count() == 0
    assert page.locator("#mb-shell-settings").count() == 1
    assert page.locator("#mb-settings-menu").count() == 1
    assert page.locator("#debug-toggle").count() == 1
    assert page.locator("#debug-console").count() == 1
    assert page.locator('script[src*="/static/global-debug.js"]').count() == 1
    assert page.locator('link[href*="/static/global-debug.css"]').count() == 1
    assert page.evaluate("typeof globalThis.monitorboxDebug === 'object'")

    home = page.locator(".mb-shell-home")
    settings = page.locator("#mb-shell-settings")
    assert home.get_attribute("href") == "/"
    assert home.get_attribute("aria-label") == "MonitorBox Home"
    assert settings.get_attribute("aria-label") == "Settings"
    assert settings.get_attribute("title") == "Settings"

    hbox = home.bounding_box()
    sbox = settings.bounding_box()
    shellbox = shell.bounding_box()
    assert hbox and sbox and shellbox
    assert hbox["width"] >= 44 and hbox["height"] >= 44, hbox
    assert sbox["width"] >= 44 and sbox["height"] >= 44, sbox
    assert hbox["x"] < sbox["x"], (hbox, sbox)
    assert sbox["x"] + sbox["width"] <= shellbox["x"] + shellbox["width"] + 1, (sbox, shellbox)

    debug = page.locator("#debug-toggle")
    dbox = debug.bounding_box()
    assert dbox and dbox["width"] >= 44 and dbox["height"] >= 44, dbox
    assert debug.get_attribute("aria-label") == "Debug"
    assert debug.get_attribute("title") == "Debug"
    assert debug.inner_text() == "Debug"
    if narrow:
        pseudo = debug.evaluate("el => getComputedStyle(el, '::before').content")
        assert ">_" in pseudo, pseudo
        assert debug.evaluate("el => getComputedStyle(el).fontSize") == "0px"
    else:
        assert debug.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") > 0

    settings.click()
    menu = page.locator("#mb-settings-menu")
    assert menu.is_visible()
    links = menu.locator("a")
    assert links.count() == len(EXPECTED_LINKS)
    actual = [(links.nth(i).inner_text(), links.nth(i).get_attribute("href")) for i in range(links.count())]
    assert actual == EXPECTED_LINKS, actual
    assert "Debug" not in menu.inner_text()
    for i in range(links.count()):
        box = links.nth(i).bounding_box()
        assert box and box["height"] >= 44, (i, box)
    page.keyboard.press("Escape")
    assert menu.is_hidden()

    assert page.locator("[data-object-gear]").count() == 0
    assert page.locator("#mb-shell-core").inner_text()
    page.locator("#mb-shell-site").wait_for(state="visible")


def main() -> None:
    package_contract()
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui-b34-") as directory:
        root = Path(directory)
        ui_module = write_runtime_package(root)
        server = TestServer(ui_module)
        server.start()
        origin = f"http://127.0.0.1:{server.port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                fixtures = [
                    ("desktop", {"width": 1366, "height": 900}, False),
                    ("ipad-landscape", {"width": 1366, "height": 1024}, False),
                    ("ipad-portrait", {"width": 1024, "height": 1366}, False),
                    ("mobile", {"width": 390, "height": 844}, True),
                ]
                surfaces = [
                    "/",
                    "/modules",
                    "/surface/service",
                    "/surface/system",
                    "/surface/detail",
                    "/settings/recovery",
                    "/settings/configuration/editor?ref=mbx1%2Fresource%2Flab%2Fservice-a",
                ]

                for name, viewport, narrow in fixtures:
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    for path in surfaces:
                        response = page.goto(origin + path, wait_until="networkidle")
                        assert response is not None and response.ok, (name, path)
                        assert_shell(page, narrow=narrow)

                    response = page.goto(
                        origin + "/settings/configuration/editor?ref=mbx1%2Fresource%2Flab%2Fservice-a",
                        wait_until="networkidle",
                    )
                    assert response is not None and response.ok
                    assert page.locator(".mb-shell-title").inner_text() == "Configuration editor"
                    up = page.locator(".mb-shell-up")
                    assert up.get_attribute("href") == "/settings"
                    assert "Configuration" in up.inner_text()

                    with page.expect_navigation():
                        page.locator(".mb-shell-home").click()
                    assert page.url.rstrip("/") == origin
                    assert_shell(page, narrow=narrow)

                    page.locator("#debug-console").wait_for(state="hidden")
                    page.locator("#debug-toggle").click()
                    assert page.locator("#debug-console").is_visible()
                    page.locator("#debug-close").click()
                    assert page.locator("#debug-console").is_hidden()
                    context.close()

                browser.close()
        finally:
            server.stop()
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    print("UI build34 Settings-shell acceptance: PASS (desktop, iPad landscape/portrait, mobile)")


if __name__ == "__main__":
    main()
