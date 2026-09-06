#!/usr/bin/env python3
"""Behavioral acceptance for Scrypted 2.1 managed media execution."""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from aiohttp import web

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.scrypted-2.1.0-build1.zip"
IMPORT_PACKAGE = "monitorbox_scrypted_v21_b1"


def _install_media_contracts(plugin_api) -> None:
    @dataclass(frozen=True)
    class RuntimeExecutionContext:
        module_id: str
        package_root: str
        state_root: str

    @dataclass(frozen=True)
    class RuntimeExecutionRequest:
        check_id: str
        object_id: str
        adapter: str
        timeout_seconds: float
        options: Mapping[str, Any] = field(default_factory=dict)
        agent_id: str | None = None
        capability_id: str | None = None
        capability_kind: str | None = None

    @dataclass(frozen=True)
    class RuntimeExecutionResult:
        state: str
        summary: str
        duration_ms: float
        metrics: Mapping[str, float] = field(default_factory=dict)
        metadata: Mapping[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class MediaExecutionRequest:
        check_id: str
        object_id: str
        adapter: str
        options: Mapping[str, Any] = field(default_factory=dict)
        agent_id: str | None = None

    @dataclass(frozen=True)
    class MediaSnapshotResult:
        content_type: str
        data: bytes

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: Any
        connection_kinds: tuple[str, ...] = ()
        runtime_adapter_kinds: tuple[str, ...] = ()
        discovery: Any = None
        connection: Any = None
        validation: Any = None
        identity: Any = None
        inventory: Any = None
        presentation: Any = None
        runtime: Any = None
        runtime_executor: Any = None
        media_executor: Any = None
        action_executor: Any = None
        candidate_adoption: Any = None
        candidate_review: Any = None

    for value in (
        RuntimeExecutionContext,
        RuntimeExecutionRequest,
        RuntimeExecutionResult,
        MediaExecutionRequest,
        MediaSnapshotResult,
        IntegrationDefinition,
    ):
        setattr(plugin_api, value.__name__, value)


def _request(plugin_api, socket: Path, operation: str):
    configured = "snapshot" if operation == "snapshot" else "stream"
    return plugin_api.MediaExecutionRequest(
        check_id=f"front_door_{configured}",
        object_id="front-door",
        adapter="scrypted",
        agent_id="monitor",
        options={
            "socket": str(socket),
            "operation": configured,
            "camera_id": "front-door",
        },
    )


async def _serve(socket: Path):
    async def snapshot(request):
        if request.match_info["camera_id"] != "front-door":
            raise web.HTTPNotFound()
        return web.Response(body=b"synthetic-jpeg", content_type="image/jpeg")

    async def live(request):
        if request.match_info["camera_id"] != "front-door":
            raise web.HTTPNotFound()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str('{"type":"provider-ready"}')
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                await ws.send_str('{"type":"provider-echo","payload":' + repr(str(message.data)).replace("'", '"') + '}')
        return ws

    app = web.Application()
    app.router.add_get("/v1/cameras/{camera_id}/snapshot", snapshot)
    app.router.add_get("/v1/cameras/{camera_id}/live", live)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.UnixSite(runner, str(socket))
    await site.start()
    return runner


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed Scrypted media package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_media_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("2.1.0", 1):
        raise AssertionError("managed Scrypted media release identity changed")
    if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
        raise AssertionError("Scrypted media release must require the Core 2.3.1 media contract")
    media = managed.PLUGIN.media_executor
    if media is None:
        raise AssertionError("Scrypted 2.1 did not register its managed media executor")

    with tempfile.TemporaryDirectory(prefix="monitorbox-scrypted-media-") as raw:
        temp = Path(raw)
        socket = temp / "camera.sock"
        runner = await _serve(socket)
        original_ensure = media.runtime._bridge.ensure

        async def ensure(options, *, wait_for_control):
            del options, wait_for_control
            return str(socket)

        media.runtime._bridge.ensure = ensure
        context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root=str(temp / "package"),
            state_root=str(temp / "state"),
        )
        try:
            snapshot_request = _request(plugin_api, socket, "snapshot")
            live_request = _request(plugin_api, socket, "live")
            if not media.supports(snapshot_request, "snapshot"):
                raise AssertionError("Scrypted media facet rejected its snapshot check")
            if not media.supports(live_request, "live"):
                raise AssertionError("Scrypted media facet rejected its live check")
            if media.supports(snapshot_request, "live"):
                raise AssertionError("Scrypted media facet confused snapshot and live ownership")

            result = await media.snapshot(snapshot_request, context)
            if result.content_type.split(";", 1)[0] != "image/jpeg":
                raise AssertionError(f"unexpected snapshot content type: {result.content_type}")
            if result.data != b"synthetic-jpeg":
                raise AssertionError("managed Scrypted media snapshot bytes changed")

            received: list[str] = []
            received_event = asyncio.Event()

            async def send(payload: str) -> None:
                received.append(payload)
                if "provider-echo" in payload:
                    received_event.set()

            session = await media.open_live(live_request, context, send)
            try:
                await session.input('{"type":"browser-hello"}')
                await asyncio.wait_for(received_event.wait(), timeout=2.0)
            finally:
                await session.close()
            if not any("provider-ready" in item for item in received):
                raise AssertionError("managed Scrypted live relay dropped provider signaling")
            if not any("provider-echo" in item for item in received):
                raise AssertionError("managed Scrypted live relay dropped browser signaling")
        finally:
            media.runtime._bridge.ensure = original_ensure
            await runner.cleanup()

    print(
        "Managed Scrypted 2.1.0 build 1: snapshot + live media facet boundary: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
