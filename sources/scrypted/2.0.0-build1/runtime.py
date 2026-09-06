from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import aiohttp

from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult

MODULE_ID = "com.sickicarus.monitorbox.scrypted"
MODULE_VERSION = "2.0.0"
MODULE_BUILD = 1

_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"
_STARTUP_TIMEOUT_SECONDS = 8.0
_CONTROL_WAIT_SECONDS = 4.0


def _elapsed(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _result(
    start: float,
    state: str,
    summary: str,
    metrics: Mapping[str, float] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeExecutionResult:
    return RuntimeExecutionResult(
        state=state,
        summary=summary,
        duration_ms=_elapsed(start),
        metrics=dict(metrics or {}),
        metadata=dict(metadata or {}),
    )


def _camera_discovery_evidence(raw_cameras: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cameras, list):
        return []
    cameras = [item for item in raw_cameras if isinstance(item, dict)]
    doorbells = [
        str(item.get("name", "")).casefold()
        for item in cameras
        if str(item.get("type", "")).casefold() == "doorbell"
    ]
    result: list[dict[str, Any]] = []
    for camera in cameras:
        camera_id = camera.get("id")
        name = str(camera.get("name") or camera_id or "Camera").strip()
        if not isinstance(camera_id, str) or not camera_id.strip():
            continue
        folded = name.casefold()
        auxiliary = any(token in folded for token in ("package", "parcel"))
        if not auxiliary and str(camera.get("type", "")).casefold() == "camera":
            auxiliary = any(
                doorbell
                and doorbell in folded
                and any(token in folded for token in ("package", "parcel"))
                for doorbell in doorbells
            )
        metadata = {
            "camera_id": camera_id,
            "type": camera.get("type"),
            "native_id": camera.get("nativeId"),
            "plugin_id": camera.get("pluginId"),
            "provider_id": camera.get("providerId"),
            "provider": camera.get("provider"),
            "online": camera.get("online"),
            "interfaces": camera.get("interfaces", []),
            "auxiliary": auxiliary,
        }
        if auxiliary:
            metadata["auxiliary_reason"] = "package/parcel camera stream"
        result.append(
            {
                "source": "scrypted",
                "source_id": camera_id,
                "kind": "camera",
                "label": name,
                "confidence": 90,
                "addresses": [],
                "suggested_capabilities": ["camera_state", "snapshot", "live_view"],
                "metadata": metadata,
            }
        )
    return result


def _required_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _environment_secret(name: Any, where: str) -> tuple[str, str]:
    environment_name = _required_text(name, where)
    value = os.environ.get(environment_name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"credential environment {environment_name} is unavailable")
    return environment_name, value


def _excluded_names(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return tuple(item.strip() for item in value if item.strip())
    raise ValueError("excluded_camera_names must be a string list")


@dataclass(frozen=True, slots=True)
class _WorkerConfig:
    base_url: str
    username_env: str
    username: str
    password_env: str
    password: str
    socket: str
    excluded_camera_names: tuple[str, ...]

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> "_WorkerConfig | None":
        control_present = any(
            options.get(key) not in (None, "")
            for key in ("base_url", "username_env", "password_env")
        )
        if not control_present:
            return None
        base_url = _required_text(options.get("base_url"), "Scrypted base_url").rstrip("/")
        if not base_url.casefold().startswith(("http://", "https://")):
            raise ValueError("Scrypted base_url must use http:// or https://")
        username_env, username = _environment_secret(
            options.get("username_env"), "Scrypted username_env"
        )
        password_env, password = _environment_secret(
            options.get("password_env"), "Scrypted password_env"
        )
        socket = _required_text(options.get("socket", _DEFAULT_SOCKET), "Scrypted socket")
        if not socket.startswith("/"):
            raise ValueError("Scrypted socket must be an absolute path")
        return cls(
            base_url=base_url,
            username_env=username_env,
            username=username,
            password_env=password_env,
            password=password,
            socket=socket,
            excluded_camera_names=_excluded_names(options.get("excluded_camera_names")),
        )

    def signature(self) -> str:
        digest = hashlib.sha256()
        for value in (
            self.base_url,
            self.username_env,
            self.username,
            self.password_env,
            self.password,
            self.socket,
            *self.excluded_camera_names,
        ):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()


class _BridgeWorker:
    """Provider-owned lifecycle for the packaged Scrypted Node bridge."""

    def __init__(self) -> None:
        self._resource_context: Any = None
        self._bridge_root: Path | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._signature: str | None = None
        self._socket: str | None = None
        self._last_config: _WorkerConfig | None = None
        self._lock = asyncio.Lock()
        self._configured = asyncio.Event()

    async def start(self) -> None:
        if self._bridge_root is not None:
            return
        traversable = resources.files(__package__).joinpath("bridge")
        self._resource_context = resources.as_file(traversable)
        self._bridge_root = Path(self._resource_context.__enter__())
        worker = self._bridge_root / "server.mjs"
        if not worker.is_file():
            self._release_resources()
            raise RuntimeError("packaged Scrypted bridge worker is missing")

    async def close(self) -> None:
        async with self._lock:
            await self._stop_locked()
            self._last_config = None
            self._configured.clear()
            self._release_resources()

    def _release_resources(self) -> None:
        context = self._resource_context
        self._resource_context = None
        self._bridge_root = None
        if context is not None:
            context.__exit__(None, None, None)

    async def ensure(self, options: Mapping[str, Any], *, wait_for_control: bool) -> str:
        config = _WorkerConfig.from_options(options)
        if config is None:
            if self._last_config is None and wait_for_control:
                try:
                    await asyncio.wait_for(self._configured.wait(), timeout=_CONTROL_WAIT_SECONDS)
                except TimeoutError as exc:
                    raise RuntimeError(
                        "Scrypted worker has not received inventory control configuration"
                    ) from exc
            config = self._last_config
            if config is None:
                raise RuntimeError("Scrypted worker control configuration is unavailable")
            requested_socket = options.get("socket")
            if requested_socket not in (None, "") and str(requested_socket) != config.socket:
                raise RuntimeError("Scrypted camera socket does not match active worker configuration")

        async with self._lock:
            await self._ensure_locked(config)
            return config.socket

    async def _ensure_locked(self, config: _WorkerConfig) -> None:
        if self._bridge_root is None:
            await self.start()
        assert self._bridge_root is not None
        signature = config.signature()
        if (
            self._process is not None
            and self._process.returncode is None
            and self._signature == signature
            and Path(config.socket).exists()
        ):
            self._last_config = config
            self._configured.set()
            return

        await self._stop_locked()
        socket_path = Path(config.socket)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.is_symlink():
            raise RuntimeError("refusing symlink Scrypted bridge socket")
        socket_path.unlink(missing_ok=True)

        node = shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))
        if node is None:
            raise RuntimeError("Node.js runtime is unavailable for the Scrypted module")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": "/nonexistent",
            "SCRYPTED_URL": config.base_url,
            "SCRYPTED_USERNAME": config.username,
            "SCRYPTED_PASSWORD": config.password,
            "SCRYPTED_EXCLUDED_CAMERA_NAMES": ",".join(config.excluded_camera_names),
            "SCRYPTED_BRIDGE_SOCKET": config.socket,
        }
        process = await asyncio.create_subprocess_exec(
            node,
            str(self._bridge_root / "server.mjs"),
            cwd=str(self._bridge_root),
            env=environment,
        )
        self._process = process
        self._signature = signature
        self._socket = config.socket
        try:
            await self._wait_ready(process, socket_path)
        except Exception:
            await self._stop_locked()
            raise
        self._last_config = config
        self._configured.set()

    async def _wait_ready(self, process: asyncio.subprocess.Process, socket_path: Path) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _STARTUP_TIMEOUT_SECONDS
        while loop.time() < deadline:
            if process.returncode is not None:
                raise RuntimeError(
                    f"Scrypted bridge worker exited with status {process.returncode} before ready"
                )
            if socket_path.exists():
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("Scrypted bridge worker did not become ready in time")

    async def _stop_locked(self) -> None:
        process = self._process
        socket = self._socket
        self._process = None
        self._signature = None
        self._socket = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        if socket:
            Path(socket).unlink(missing_ok=True)


class ScryptedRuntimeExecutor:
    """Self-contained managed Scrypted provider executor.

    The signed module owns the Scrypted RPC implementation and Node dependencies.
    Core supplies only the admitted module lifecycle and the already-generic managed
    credential environment. No Scrypted implementation or factory worker is needed
    in the Core distribution.
    """

    def __init__(self) -> None:
        self._bridge = _BridgeWorker()

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context
        await self._bridge.start()

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context
        await self._bridge.close()

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        del context
        if request.adapter != "scrypted":
            raise ValueError(f"Scrypted executor cannot run adapter {request.adapter!r}")

        start = time.monotonic()
        opts = dict(request.options)
        operation = str(opts["operation"])
        try:
            socket = await self._bridge.ensure(
                opts,
                wait_for_control=operation != "inventory",
            )
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            return _result(
                start,
                "failed" if operation == "inventory" else "unknown",
                f"Scrypted bridge unavailable: {exc}",
                metadata={
                    "failure_kind": "parent_unavailable"
                    if operation != "inventory"
                    else "monitor_dependency"
                },
            )

        camera_id = str(opts.get("camera_id", ""))
        path = (
            "/v1/state"
            if operation == "inventory"
            else f"/v1/cameras/{quote(camera_id, safe='')}/state"
            if operation == "camera_state"
            else f"/v1/cameras/{quote(camera_id, safe='')}/probe?mode={operation}"
        )
        method = "GET" if operation in {"inventory", "camera_state"} else "POST"
        connector = aiohttp.UnixConnector(path=socket)
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.request(method, f"http://localhost{path}") as response:
                    payload = await response.json(content_type=None)
                    if response.status != 200:
                        parent = isinstance(payload, dict) and payload.get("kind") == "scrypted_unavailable"
                        return _result(
                            start,
                            "unknown" if parent and operation != "inventory" else "failed",
                            ("Scrypted unavailable: " if parent else f"{operation} failed: ")
                            + str(
                                payload.get("error", f"HTTP {response.status}")
                                if isinstance(payload, dict)
                                else f"HTTP {response.status}"
                            )[:200],
                            metadata={
                                "failure_kind": "parent_unavailable"
                                if parent
                                else "camera_function"
                            },
                        )
        except (aiohttp.ClientError, OSError, ValueError) as exc:
            return _result(
                start,
                "failed" if operation == "inventory" else "unknown",
                f"Scrypted bridge unavailable: {exc}",
                metadata={
                    "failure_kind": "parent_unavailable"
                    if operation != "inventory"
                    else "monitor_dependency"
                },
            )

        cameras = payload.get("cameras", []) if isinstance(payload, dict) else []
        if operation == "inventory":
            expected = {str(item) for item in opts.get("expected_camera_ids", [])}
            present = {
                str(item.get("id"))
                for item in cameras
                if isinstance(item, Mapping)
            }
            missing = sorted(expected - present)
            offline_exempt = {
                str(item) for item in opts.get("offline_exempt_camera_ids", [])
            }
            offline = sorted(
                str(item.get("name") or item.get("id"))
                for item in cameras
                if isinstance(item, Mapping)
                and str(item.get("id")) in expected
                and item.get("online") is False
                and str(item.get("id")) not in offline_exempt
            )
            state = "degraded" if missing or offline else "healthy"
            summary = (
                f"Missing cameras: {', '.join(missing)}"
                if missing
                else f"Offline cameras: {', '.join(offline)}"
                if offline
                else f"Scrypted {payload.get('serverVersion')} operational; "
                f"{len(expected)}/{len(expected)} expected cameras present"
            )
            return _result(
                start,
                state,
                summary,
                {
                    "expected_cameras": float(len(expected)),
                    "present_cameras": float(len(expected) - len(missing)),
                    "online_cameras": float(
                        sum(
                            isinstance(item, Mapping)
                            and str(item.get("id")) in expected
                            and item.get("online") is True
                            for item in cameras
                        )
                    ),
                },
                {
                    "server_version": payload.get("serverVersion"),
                    "missing_camera_ids": missing,
                    "offline_cameras": offline,
                    "cameras": cameras,
                    "discovery_evidence": _camera_discovery_evidence(cameras),
                },
            )

        if operation == "camera_state":
            camera = payload if isinstance(payload, dict) else {}
            if not camera:
                return _result(
                    start,
                    "failed",
                    "Expected camera is missing from Scrypted",
                    metadata={"camera_id": camera_id},
                )
            online = camera.get("online")
            state = "failed" if online is False else "unknown" if online is None else "healthy"
            return _result(
                start,
                state,
                "Camera online"
                if online is True
                else "Camera offline"
                if online is False
                else "Camera online state unavailable",
                {"online": 1.0 if online is True else 0.0} if online is not None else {},
                {
                    "camera_id": camera_id,
                    "camera_status": "online"
                    if online is True
                    else "offline"
                    if online is False
                    else "unknown",
                    "native_id": camera.get("nativeId"),
                    "provider": camera.get("provider"),
                    "interfaces": camera.get("interfaces", []),
                    "profiles": camera.get("profiles", []),
                    "selected_profile_id": camera.get("selectedProfileId"),
                },
            )

        payload_state = payload.get("state") if isinstance(payload, dict) else None
        if payload_state == "offline":
            return _result(
                start,
                "failed",
                "Scrypted reports camera offline",
                metadata={
                    "camera_id": camera_id,
                    "camera_status": "offline",
                    "failure_kind": "authoritative_offline",
                },
            )
        state = "healthy" if payload_state == "healthy" else "failed"
        latency = float(
            payload.get("latencyMs", _elapsed(start))
            if isinstance(payload, dict)
            else _elapsed(start)
        )
        if operation == "snapshot":
            return _result(
                start,
                state,
                f"Snapshot retrieved in {latency:.0f} ms",
                {
                    "latency_ms": latency,
                    "bytes": float(
                        payload.get("bytes", 0) if isinstance(payload, dict) else 0
                    ),
                },
                {
                    "camera_id": camera_id,
                    "attempts": payload.get("attempts")
                    if isinstance(payload, dict)
                    else None,
                },
            )

        profile = payload.get("profile", {}) or {} if isinstance(payload, dict) else {}
        video = profile.get("video", {}) or {} if isinstance(profile, Mapping) else {}
        detail = ""
        if video.get("width") and video.get("height"):
            detail = f" ({video['width']}×{video['height']} {video.get('codec', '')})"
        return _result(
            start,
            state,
            f"Stream acquired in {latency:.0f} ms{detail}",
            {
                "latency_ms": latency,
                "width": float(video.get("width", 0) or 0),
                "height": float(video.get("height", 0) or 0),
                "bitrate": float(video.get("bitrate", 0) or 0),
            },
            {
                "camera_id": camera_id,
                "attempts": payload.get("attempts") if isinstance(payload, dict) else None,
                "profile": profile,
            },
        )
