from __future__ import annotations

import time
from typing import Any, Mapping
from urllib.parse import quote

import aiohttp

from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult

MODULE_ID = "com.sickicarus.monitorbox.scrypted"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1


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


class ScryptedRuntimeExecutor:
    """Provider-owned Scrypted bridge client.

    The bridge process itself remains a MonitorBox-managed sidecar/worker. This
    executor owns the Scrypted wire protocol and converts inventory into generic
    discovery evidence before returning across the runtime boundary.
    """

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context

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
        camera_id = str(opts.get("camera_id", ""))
        path = (
            "/v1/state"
            if operation == "inventory"
            else f"/v1/cameras/{quote(camera_id, safe='')}/state"
            if operation == "camera_state"
            else f"/v1/cameras/{quote(camera_id, safe='')}/probe?mode={operation}"
        )
        method = "GET" if operation in {"inventory", "camera_state"} else "POST"
        connector = aiohttp.UnixConnector(path=str(opts["socket"]))
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

        profile = (
            payload.get("profile", {}) or {}
            if isinstance(payload, dict)
            else {}
        )
        video = profile.get("video", {}) or {} if isinstance(profile, Mapping) else {}
        detail = ""
        if video.get("width") and video.get("height"):
            detail = (
                f" ({video['width']}×{video['height']} {video.get('codec', '')})"
            )
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
                "attempts": payload.get("attempts")
                if isinstance(payload, dict)
                else None,
                "profile": profile,
            },
        )
