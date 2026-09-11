#!/usr/bin/env python3
"""Real HTTP/Chromium acceptance for Phase-1 UI build 26.

Exercises the generated standalone managed UI, not a hand-built shell fixture: generation
URLs/cache headers, repeated warm Home navigation with static delivery deliberately
unavailable, the adopted Debug control, representative warm-page latency, and non-blocking
shell hydration under deliberately slow build/state APIs.
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
WARM_NAVIGATION_LIMIT_SECONDS = 0.5
HOME_STRESS_ITERATIONS = 110


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


def static_request_snapshot(counter: Counter[str]) -> dict[str, int]:
    return {
        raw_path: count
        for raw_path, count in counter.items()
        if raw_path.startswith("/static/")
        and urlparse(raw_path).path.endswith((".css", ".js"))
    }


def request_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        path: after.get(path, 0) - before.get(path, 0)
        for path in sorted(set(before) | set(after))
        if after.get(path, 0) != before.get(path, 0)
    }


def assert_styled_shell(page) -> None:
    shell = page.locator("#mb-app-shell")
    shell.wait_for(state="visible")
    shell_style = shell.evaluate(
        "el => ({position:getComputedStyle(el).position, background:getComputedStyle(el).backgroundColor})"
    )
    assert shell_style["position"] == "sticky", shell_style
    assert shell_style["background"] not in {"rgba(0, 0, 0, 0)", "transparent"}, shell_style


def timed_navigation(page, url: str) -> float:
    started = time.perf_counter()
    response = page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.ok, url
    assert_styled_shell(page)
    return time.perf_counter() - started


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

                # Cold Dashboard load verifies exact-generation static URLs, immutable
                # cache headers, generation diagnostics, and the real Debug control.
                response = page.goto(origin + "/", wait_until="networkidle")
                assert response is not None and response.ok
                assert response.headers.get("x-monitorbox-ui-generation") == GENERATION
                assert_styled_shell(page)
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

                representative = (
                    ("Dashboard", "/"),
                    ("Modules", "/modules"),
                    ("Discoveries", "/settings/discover"),
                    ("Settings", "/settings/probe"),
                )

                # Warm every representative surface before simulating static delivery loss.
                # Settings-only compatibility scripts are not Dashboard assets and cannot be
                # expected in cache until a settings page has actually been visited once.
                for _, path in representative:
                    timed_navigation(page, origin + path)
                before_stress = static_request_snapshot(server.requests)
                assert sum(before_stress.values()) > 5, before_stress

                # #303 stress: with all participating surface assets now in this exact
                # generation's cache, make server CSS/JS delivery fail and perform >100
                # settings-page -> Home round trips. A warm generation must neither
                # revalidate nor fall back to a raw/default-styled Dashboard.
                server.controls["fail_static"] = True
                for iteration in range(HOME_STRESS_ITERATIONS):
                    away = page.goto(origin + "/settings/probe", wait_until="domcontentloaded")
                    assert away is not None and away.ok, iteration
                    assert_styled_shell(page)
                    home = page.goto(origin + "/", wait_until="domcontentloaded")
                    assert home is not None and home.ok, iteration
                    assert_styled_shell(page)
                    page.locator(".mb-shell-debug").wait_for(state="visible")
                after_stress = static_request_snapshot(server.requests)
                delta = request_delta(before_stress, after_stress)
                assert not delta, {
                    "unexpected_warm_static_requests": delta,
                    "before": before_stress,
                    "after": after_stress,
                }

                # #304 representative warm-navigation budget. All route-specific managed
                # assets have already been loaded above; shell visibility is included.
                server.controls["fail_static"] = False
                server.controls["slow_shell"] = False
                timings: dict[str, float] = {}
                for label, path in representative:
                    elapsed = timed_navigation(page, origin + path)
                    timings[label] = elapsed
                    assert elapsed < WARM_NAVIGATION_LIMIT_SECONDS, (label, elapsed, timings)

                # Shell build/state hydration is deliberately much slower than the page.
                # It is post-load/idle work and must not become a serial page dependency.
                server.controls["slow_shell"] = True
                started = time.perf_counter()
                probe = page.goto(origin + "/settings/probe", wait_until="domcontentloaded")
                elapsed = time.perf_counter() - started
                assert probe is not None and probe.ok
                assert elapsed < 0.75, elapsed
                assert page.locator("#probe").inner_text() == "Ready"
                assert_styled_shell(page)
                assert page.locator("#mb-shell-core").inner_text()

                print(
                    "build26 warm timings: "
                    + ", ".join(f"{label}={seconds * 1000:.1f}ms" for label, seconds in timings.items())
                )
                context.close()
                browser.close()
        finally:
            server.stop()
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    print(
        f"P2 Phase-1 UI build26 real-server acceptance: PASS "
        f"({HOME_STRESS_ITERATIONS} warmed settings-page/Home stress cycles)"
    )


if __name__ == "__main__":
    main()
