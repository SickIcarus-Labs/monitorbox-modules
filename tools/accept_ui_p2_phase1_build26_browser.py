#!/usr/bin/env python3
"""Real HTTP/Chromium acceptance for Phase-1 UI build 26.

Exercises the generated standalone managed UI, not a hand-built shell fixture: generation
URLs/cache headers, warm navigation with static delivery deliberately unavailable, the
adopted Debug control, and non-blocking shell hydration under slow build/state APIs.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import queue
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from playwright.sync_api import sync_playwright

import build_first_party_ui_build26 as candidate

GENERATION = "1.1.14-26"


class TestServer:
    def __init__(self, ui_module) -> None:
        self.ui_module = ui_module
        self.controls = {"fail_static": False, "slow_shell": False}
        self.requests: Counter[str] = Counter()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None
        self.thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> None:
        ready: queue.Queue[tuple[int, asyncio.AbstractEventLoop, web.AppRunner] | BaseException] = queue.Queue()

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            @web.middleware
            async def observe(request: web.Request, handler):
                self.requests[request.raw_path] += 1
                if self.controls["slow_shell"] and request.path in {"/api/v2/build", "/api/v2/state"}:
                    await asyncio.sleep(1.5)
                if self.controls["fail_static"] and request.path.startswith("/static/") and request.path.endswith((".css", ".js")):
                    return web.Response(status=503, text="simulated static outage")
                return await handler(request)

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

            async def probe(_: web.Request) -> web.Response:
                return web.Response(
                    text="<!doctype html><html><head><title>Probe</title></head>"
                         "<body data-mb-page-title='Performance probe'><main id='probe'>Ready</main></body></html>",
                    content_type="text/html",
                )

            async def api_fallback(_: web.Request) -> web.Response:
                return web.json_response({})

            async def boot() -> tuple[web.AppRunner, int]:
                app = web.Application(middlewares=[observe])
                app.router.add_get("/api/v2/state", state)
                app.router.add_get("/api/v2/debug/config", debug_config)
                app.router.add_get("/api/v2/config/discovery/runtime/summary", discovery_summary)
                app.router.add_get("/settings/probe", probe)
                self.ui_module.install(app)
                app.router.add_route("*", "/api/v2/{tail:.*}", api_fallback)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                sockets = site._server.sockets  # test-only bound-port discovery
                return runner, int(sockets[0].getsockname()[1])

            try:
                runner, port = loop.run_until_complete(boot())
                ready.put((port, loop, runner))
                loop.run_forever()
            except BaseException as exc:  # pragma: no cover - propagated to caller
                ready.put(exc)
            finally:
                loop.close()

        self.thread = threading.Thread(target=run, name="build26-ui-test-server", daemon=True)
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


def write_runtime_package(root: Path) -> object:
    assets = candidate._build26_assets(Path(__file__).resolve().parent.parent)

    # Stub only the generic Core build-info dependency required by the standalone UI.
    monitorbox = root / "monitorbox"
    (monitorbox / "v2").mkdir(parents=True)
    (monitorbox / "__init__.py").write_text("", encoding="utf-8")
    (monitorbox / "v2" / "__init__.py").write_text("", encoding="utf-8")
    (monitorbox / "v2" / "build_info.py").write_text(
        "class Identity:\n"
        "    display = 'v2.4.0 · build 9999 · dev'\n"
        "    def as_dict(self):\n"
        "        return {'version':'2.4.0','build':'9999','channel':'dev'}\n"
        "def current_build_identity():\n"
        "    return Identity()\n",
        encoding="utf-8",
    )

    package = root / "monitorbox_ui_b26"
    (package / "assets").mkdir(parents=True)
    (package / "__init__.py").write_bytes(candidate._standalone_application())
    for name, payload in assets.items():
        (package / "assets" / name).write_bytes(payload)

    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    return importlib.import_module("monitorbox_ui_b26")


def static_script_style_requests(counter: Counter[str]) -> int:
    return sum(
        count
        for raw_path, count in counter.items()
        if raw_path.startswith("/static/")
        and urlparse(raw_path).path.endswith((".css", ".js"))
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-ui-b26-") as directory:
        root = Path(directory)
        ui_module = write_runtime_package(root)
        server = TestServer(ui_module)
        server.start()
        origin = f"http://127.0.0.1:{server.port}"

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1024, "height": 1366})
                page = context.new_page()
                static_headers: list[tuple[str, str, str]] = []

                def capture(response) -> None:
                    parsed = urlparse(response.url)
                    if parsed.path.startswith("/static/") and parsed.path.endswith((".css", ".js")):
                        static_headers.append((
                            response.url,
                            response.headers.get("cache-control", ""),
                            response.headers.get("x-monitorbox-ui-generation", ""),
                        ))

                page.on("response", capture)

                # Cold load: generated HTML must point every managed CSS/JS request at
                # the exact generation, and matching responses are immutable.
                response = page.goto(origin + "/", wait_until="networkidle")
                assert response is not None and response.ok
                assert response.headers.get("x-monitorbox-ui-generation") == GENERATION
                page.locator("#mb-app-shell").wait_for(state="visible")
                page.locator(".mb-shell-debug").wait_for(state="visible")
                assert page.locator(".mb-shell-debug").get_attribute("id") == "debug-toggle"
                assert page.locator("#debug-console").is_hidden()
                page.locator(".mb-shell-debug").click()
                assert page.locator("#debug-console").is_visible()
                page.locator("#debug-close").click()

                assert static_headers, "no managed CSS/JS responses observed"
                for url, cache_control, generation in static_headers:
                    assert f"v={GENERATION}" in url, url
                    assert "max-age=31536000" in cache_control and "immutable" in cache_control, (url, cache_control)
                    assert generation == GENERATION, (url, generation)

                first_static_count = static_script_style_requests(server.requests)
                assert first_static_count > 5, first_static_count

                # Warm navigation: make CSS/JS delivery fail at the server. A coherent
                # immutable generation should require no revalidation and still return a
                # fully styled, scripted Dashboard rather than the raw #303 failure mode.
                page.goto("about:blank")
                server.controls["fail_static"] = True
                second = page.goto(origin + "/", wait_until="domcontentloaded")
                assert second is not None and second.ok
                shell = page.locator("#mb-app-shell")
                shell.wait_for(state="visible")
                page.locator(".mb-shell-debug").wait_for(state="visible")
                shell_style = shell.evaluate(
                    "el => ({position:getComputedStyle(el).position, background:getComputedStyle(el).backgroundColor})"
                )
                assert shell_style["position"] == "sticky", shell_style
                assert shell_style["background"] not in {"rgba(0, 0, 0, 0)", "transparent"}, shell_style
                second_static_count = static_script_style_requests(server.requests)
                assert second_static_count == first_static_count, (first_static_count, second_static_count)

                # #304: shell health/build requests may be slow, but they are scheduled
                # after load/idle and must not hold an ordinary shell-managed page hostage.
                server.controls["fail_static"] = False
                server.controls["slow_shell"] = True
                started = time.perf_counter()
                probe = page.goto(origin + "/settings/probe", wait_until="domcontentloaded")
                elapsed = time.perf_counter() - started
                assert probe is not None and probe.ok
                assert elapsed < 0.75, elapsed
                assert page.locator("#probe").inner_text() == "Ready"
                page.locator("#mb-app-shell").wait_for(state="visible")
                assert page.locator("#mb-shell-core").inner_text()

                context.close()
                browser.close()
        finally:
            server.stop()
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    print("P2 Phase-1 UI build26 real-server cache/debug/performance acceptance: PASS")


if __name__ == "__main__":
    main()
