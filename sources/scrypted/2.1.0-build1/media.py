from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import aiohttp

from ...plugin_api import MediaExecutionRequest, MediaSnapshotResult, RuntimeExecutionContext
from .runtime import ScryptedRuntimeExecutor

MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
SNAPSHOT_CHUNK_BYTES = 64 * 1024
MAX_LIVE_MESSAGE_BYTES = 1024 * 1024
LIVE_READY_TIMEOUT_SECONDS = 10.0


def _camera_id(request: MediaExecutionRequest) -> str:
    value = request.options.get("camera_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Scrypted media check requires camera_id")
    return value.strip()


async def _read_bounded(content: Any, limit: int = MAX_SNAPSHOT_BYTES) -> bytes:
    body = bytearray()
    async for chunk in content.iter_chunked(SNAPSHOT_CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > limit:
            raise RuntimeError("Scrypted snapshot exceeded relay safety limit")
    return bytes(body)


def _signal_shape(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return {"message_type": "non_json"}
    if not isinstance(value, dict):
        return {"message_type": type(value).__name__}
    result: dict[str, Any] = {"message_type": str(value.get("type", "unknown"))[:40]}
    if value.get("method"):
        result["method"] = str(value["method"])[:80]
    if value.get("callId") is not None:
        result["call_id"] = str(value["callId"])[:40]
    if "trickle" in value:
        result["trickle"] = bool(value["trickle"])
    if value.get("error"):
        result["has_error"] = True
    return result


class _ScryptedLiveSession:
    def __init__(self, socket: str, camera_id: str, send: Callable[[str], Awaitable[None]]) -> None:
        self.socket = socket
        self.camera_id = camera_id
        self.send = send
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=64)
        self.task: asyncio.Task[None] | None = None
        self.ready: asyncio.Future[None] | None = None

    async def _debug(self, stage: str, **fields: Any) -> None:
        value = {
            "type": "debug",
            "source": "provider-media-relay",
            "provider": "scrypted",
            "stage": stage[:120],
            **fields,
        }
        with suppress(Exception):
            await self.send(json.dumps(value, separators=(",", ":")))

    async def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("Scrypted live session already started")
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run(), name=f"scrypted-media:{self.camera_id}")
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), timeout=LIVE_READY_TIMEOUT_SECONDS)
        except Exception:
            await self.close()
            raise

    async def input(self, payload: str) -> None:
        if len(payload.encode("utf-8")) > MAX_LIVE_MESSAGE_BYTES:
            raise RuntimeError("live relay message exceeded safety limit")
        if self.task is None or self.task.done():
            raise RuntimeError("Scrypted live session is unavailable")
        await self.queue.put(payload)

    async def close(self) -> None:
        task = self.task
        self.task = None
        with suppress(asyncio.QueueFull):
            self.queue.put_nowait(None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        connector = aiohttp.UnixConnector(path=self.socket)
        opened = False
        await self._debug("connecting", camera_id=self.camera_id)
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.ws_connect(
                    f"http://localhost/v1/cameras/{quote(self.camera_id, safe='')}/live",
                    max_msg_size=MAX_LIVE_MESSAGE_BYTES,
                ) as bridge:
                    opened = True
                    if self.ready is not None and not self.ready.done():
                        self.ready.set_result(None)
                    await self._debug("open")

                    async def bridge_to_core() -> None:
                        async for message in bridge:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                text = str(message.data)
                                await self.send(text)
                                await self._debug("provider_to_browser", **_signal_shape(text))
                            elif message.type in {
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            }:
                                break

                    async def core_to_bridge() -> None:
                        while not bridge.closed:
                            payload = await self.queue.get()
                            if payload is None:
                                await bridge.close()
                                return
                            await bridge.send_str(payload)
                            await self._debug("browser_to_provider", **_signal_shape(payload))

                    reader = asyncio.create_task(bridge_to_core())
                    writer = asyncio.create_task(core_to_bridge())
                    done, pending = await asyncio.wait(
                        {reader, writer}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*done, *pending, return_exceptions=True)
        except asyncio.CancelledError:
            if self.ready is not None and not self.ready.done():
                self.ready.cancel()
            raise
        except Exception as exc:
            if self.ready is not None and not self.ready.done():
                self.ready.set_exception(exc)
            elif opened:
                with suppress(Exception):
                    await self.send(
                        json.dumps(
                            {"type": "error", "error": f"{type(exc).__name__}: {exc}"[:240]},
                            separators=(",", ":"),
                        )
                    )
        finally:
            if self.ready is not None and not self.ready.done():
                self.ready.set_exception(RuntimeError("Scrypted live relay ended before ready"))


class ScryptedMediaExecutor:
    """Provider-owned snapshot and browser-live media bridge."""

    def __init__(self, runtime: ScryptedRuntimeExecutor) -> None:
        self.runtime = runtime

    def supports(self, request: MediaExecutionRequest, operation: str) -> bool:
        if request.adapter != "scrypted" or not request.options.get("camera_id"):
            return False
        configured = str(request.options.get("operation", ""))
        if operation == "snapshot":
            return configured == "snapshot"
        if operation == "live":
            return configured == "stream"
        return False

    async def snapshot(
        self,
        request: MediaExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> MediaSnapshotResult:
        del context
        camera_id = _camera_id(request)
        socket = await self.runtime._bridge.ensure(request.options, wait_for_control=True)
        connector = aiohttp.UnixConnector(path=socket)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                f"http://localhost/v1/cameras/{quote(camera_id, safe='')}/snapshot"
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise RuntimeError(
                        f"Scrypted snapshot returned HTTP {response.status}: {text[:160]}"
                    )
                if response.content_length is not None and response.content_length > MAX_SNAPSHOT_BYTES:
                    raise RuntimeError("Scrypted snapshot exceeded relay safety limit")
                body = await _read_bounded(response.content)
                return MediaSnapshotResult(
                    content_type=response.headers.get("Content-Type", "image/jpeg"),
                    data=body,
                )

    async def open_live(
        self,
        request: MediaExecutionRequest,
        context: RuntimeExecutionContext,
        send: Callable[[str], Awaitable[None]],
    ) -> _ScryptedLiveSession:
        del context
        camera_id = _camera_id(request)
        socket = await self.runtime._bridge.ensure(request.options, wait_for_control=True)
        relay = _ScryptedLiveSession(socket, camera_id, send)
        await relay.start()
        return relay
