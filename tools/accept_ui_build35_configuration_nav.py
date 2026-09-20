#!/usr/bin/env python3
"""Browser acceptance for #346 UI-owned Configuration peer navigation."""
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

import build_first_party_ui_build34 as parent
import build_first_party_ui_build35 as candidate

ROOT = Path(__file__).resolve().parent.parent
PEERS = [
    ("Configuration", "/settings"),
    ("Appliance", "/settings/appliance"),
    ("Quick Add", "/settings/quick-add"),
    ("Monitoring", "/settings/discover"),
    ("Policies", "/settings/configuration/policies"),
    ("Dashboard", "/settings/dashboard"),
    ("Recovery", "/settings/recovery"),
]
LEGACY_APPLIANCE = {
    "/settings/quick-add",
    "/settings",
    "/settings/policy",
    "/settings/dashboard",
    "/settings/recovery",
}


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
        "    display = 'v2.5.2 · build 0828 · dev'\n"
        "    def as_dict(self):\n"
        "        return {'version':'2.5.2','build':'0828','channel':'dev'}\n"
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
    assert b"configuration_peer_navigation_presentation" in init
    assert b"configuration-peer-navigation.js" in init
    assert b"configuration-peer-navigation.css" in init
    assert "configuration-peer-navigation.js" in assets
    assert "configuration-peer-navigation.css" in assets

    parent_files = parent._package_files(ROOT)
    for name in (
        "settings-shell.js",
        "settings-shell.css",
        "contextual-configuration.js",
        "contextual-configuration.css",
        "app-shell.js",
        "app-shell.css",
        "global-debug.js",
        "global-debug.css",
    ):
        expected = parent_files[f"{parent.TARGET_IMPORT_PACKAGE}/assets/{name}"].replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(),
            candidate.TARGET_IMPORT_PACKAGE.encode(),
        )
        assert assets[name] == expected, name

    js = assets["configuration-peer-navigation.js"].decode("utf-8")
    css = assets["configuration-peer-navigation.css"].decode("utf-8")
    for label, href in PEERS:
        assert label in js and href in js
    assert "/settings/policy" in js
    assert "LEGACY_APPLIANCE_LINKS" in js
    assert "aria-current" in js
    assert "min-height:44px" in css
    assert "overflow-x:auto" in css


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
                    "sites": [{"id": "broadleaf", "label": "Broad Leaf", "state": "healthy", "agents": [], "objects": [], "power": {"state": "not_configured", "ups": {}}}],
                })

            async def debug_config(_: web.Request) -> web.Response:
                return web.json_response({"enabled": True, "buffer_limit": 1000})

            async def discovery_summary(_: web.Request) -> web.Response:
                return web.json_response({"pending_count": 0, "visibility_impaired": False})

            def markup(path: str) -> str:
                title = next((label for label, href in PEERS if href == path), "Configuration")
                if path == "/settings/appliance":
                    header = (
                        '<header class="top">'
                        '<a class="button" href="/">← Dashboard</a>'
                        '<a class="button" href="/settings/quick-add">Quick Add</a>'
                        '<a class="button" href="/settings">Configuration</a>'
                        '<a class="button" href="/settings/policy">Actions & policy</a>'
                        '<a class="button" href="/settings/dashboard">Graphs</a>'
                        '<a class="button" href="/settings/recovery">Recovery</a>'
                        '<h1>Appliance & Credentials</h1></header>'
                    )
                else:
                    header = f'<header class="top"><a href="/">← Dashboard</a><h1>{title}</h1></header>'
                return (
                    "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<style>:root{--line:#293b55;--text:#eef5ff;--muted:#98a9c0;--bg:#07111f}"
                    "body{margin:0;background:#07111f;color:#eef5ff;font-family:system-ui}.top{padding:12px}</style>"
                    "</head><body data-mb-page-title='" + title + "'>" + header + "<main>Body</main></body></html>"
                )

            async def settings(request: web.Request) -> web.Response:
                return web.Response(text=markup(request.path), content_type="text/html")

            async def editor(_: web.Request) -> web.Response:
                return web.Response(
                    text=(
                        "<!doctype html><html><head><title>Editor</title></head>"
                        "<body data-mb-page-title='Configuration editor' data-mb-up-href='/settings' data-mb-up-label='Configuration'>"
                        "<header><h1>Editor</h1></header><main>Editor</main></body></html>"
                    ),
                    content_type="text/html",
                )

            async def api_fallback(_: web.Request) -> web.Response:
                return web.json_response({})

            async def boot():
                app = web.Application()
                app.router.add_get("/api/v2/state", state)
                app.router.add_get("/api/v2/debug/config", debug_config)
                app.router.add_get("/api/v2/config/discovery/runtime/summary", discovery_summary)
                for _, href in PEERS:
                    app.router.add_get(href, settings)
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

        self.thread = threading.Thread(target=run, daemon=True)
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


def browser_contract() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        ui = write_runtime_package(root)
        server = TestServer(ui)
        server.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for viewport in ({"width": 1440, "height": 900}, {"width": 700, "height": 900}):
                    page = browser.new_page(viewport=viewport)
                    for label, href in PEERS:
                        page.goto(f"http://127.0.0.1:{server.port}{href}", wait_until="networkidle")
                        nav = page.locator("#mb-configuration-peer-nav")
                        assert nav.count() == 1, (href, viewport)
                        links = nav.locator("a")
                        assert links.count() == len(PEERS)
                        active = nav.locator('a[aria-current="page"]')
                        assert active.count() == 1
                        assert active.inner_text() == label
                        for index in range(links.count()):
                            box = links.nth(index).bounding_box()
                            assert box and box["height"] >= 44, (href, viewport, index, box)

                        if href == "/settings/appliance":
                            header = page.locator("header.top")
                            for legacy in LEGACY_APPLIANCE:
                                assert header.locator(f'a[href="{legacy}"]').count() == 0
                            # Home semantics are owned by the existing global UI shell;
                            # #346 must not replace or duplicate that authority.
                            assert page.locator('.mb-shell-home[href="/"]').count() == 1

                    page.goto(f"http://127.0.0.1:{server.port}/settings/configuration/editor", wait_until="networkidle")
                    assert page.locator('#mb-configuration-peer-nav a[aria-current="page"]').inner_text() == "Configuration"

                    if viewport["width"] == 700:
                        page.goto(f"http://127.0.0.1:{server.port}/settings", wait_until="networkidle")
                        nav = page.locator("#mb-configuration-peer-nav")
                        assert nav.evaluate("(el) => el.scrollWidth >= el.clientWidth")
                        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

                    page.goto(f"http://127.0.0.1:{server.port}/settings", wait_until="networkidle")
                    page.locator('#mb-configuration-peer-nav a[href="/settings/appliance"]').click()
                    page.wait_for_url("**/settings/appliance")
                    page.go_back(wait_until="networkidle")
                    assert page.url.endswith("/settings")
                    page.close()
                browser.close()
        finally:
            server.stop()
            sys.path.remove(str(root))
            for name in list(sys.modules):
                if name == candidate.TARGET_IMPORT_PACKAGE or name.startswith(candidate.TARGET_IMPORT_PACKAGE + "."):
                    sys.modules.pop(name, None)


def main() -> None:
    package_contract()
    browser_contract()
    print("UI build35 Configuration peer navigation acceptance: PASS")


if __name__ == "__main__":
    main()
