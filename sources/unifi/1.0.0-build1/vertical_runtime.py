from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ...model import State
from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult
from .runtime import UniFiRuntimeExecutor as _BaseUniFiRuntimeExecutor

_PERSISTENCE_VERSION = 2
_SUCCESS_TTL_SECONDS = 5.0
_FAILURE_TTL_SECONDS = 2.0
_MAX_CACHE_ENTRIES = 32


@dataclass(slots=True)
class _Snapshot:
    captured_at: float
    payload: Any = None
    error: str | None = None


def normalize_unifi_ports(
    raw_devices: Any,
    *,
    device_object_ids: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize stable physical switch-port identity from UniFi inventory."""
    if not isinstance(raw_devices, list):
        return []
    object_ids = {
        str(key).strip().casefold(): str(value)
        for key, value in dict(device_object_ids or {}).items()
        if str(key).strip() and str(value).strip()
    }
    result: list[dict[str, Any]] = []
    for device in raw_devices:
        if not isinstance(device, Mapping):
            continue
        mac = str(device.get("mac") or "").strip().casefold()
        if not mac:
            continue
        device_name = str(device.get("name") or device.get("model") or mac).strip()
        device_object_id = object_ids.get(mac) or object_ids.get(device_name.casefold())
        raw_ports = device.get("port_table", [])
        if not isinstance(raw_ports, list):
            continue
        for raw_port in raw_ports:
            if not isinstance(raw_port, Mapping):
                continue
            port_idx = raw_port.get("port_idx")
            if isinstance(port_idx, bool) or not isinstance(port_idx, int) or port_idx < 0:
                continue
            disabled = raw_port.get("is_disabled") is True or raw_port.get("disabled") is True
            admin_enabled = not disabled
            speed_raw = raw_port.get("speed")
            speed = (
                float(speed_raw)
                if isinstance(speed_raw, (int, float))
                and not isinstance(speed_raw, bool)
                and speed_raw >= 0
                else None
            )
            linked = raw_port.get("up") is True or bool(admin_enabled and speed and speed > 0)
            result.append(
                {
                    "id": f"unifi_port_{mac.replace(':', '')}_{port_idx}",
                    "device_mac": mac,
                    "device_name": device_name,
                    "device_object_id": device_object_id,
                    "port_idx": port_idx,
                    "name": str(raw_port.get("name") or f"Port {port_idx}").strip(),
                    "linked": linked,
                    "admin_enabled": admin_enabled,
                    "speed_mbps": speed,
                    "is_uplink": raw_port.get("is_uplink") is True,
                }
            )
    return result


def _positive_int(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return int(value)
    return None


def _port_by_index(device: Mapping[str, Any], index: Any) -> Mapping[str, Any] | None:
    if index is None:
        return None
    return next(
        (
            item
            for item in device.get("port_table", [])
            if isinstance(item, Mapping) and item.get("port_idx") == index
        ),
        None,
    )


def _configured_speed(
    device: Mapping[str, Any],
    port_index: Any,
    port: Mapping[str, Any] | None,
) -> int | None:
    if port and port.get("autoneg") is False:
        speed = _positive_int(port.get("speed"))
        if speed is not None:
            return speed
    override = next(
        (
            item
            for item in device.get("port_overrides", [])
            if isinstance(item, Mapping) and item.get("port_idx") == port_index
        ),
        None,
    )
    return _positive_int(override.get("speed")) if override else None


class UniFiRuntimeExecutor(_BaseUniFiRuntimeExecutor):
    """Complete provider-local executor including 0540 port/cache/link policy."""

    def __init__(self) -> None:
        super().__init__()
        self._device_snapshots: dict[tuple[str, str, str, str, bool], _Snapshot] = {}
        self._device_snapshot_locks: dict[
            tuple[str, str, str, str, bool], asyncio.Lock
        ] = {}

    async def close(self, context: RuntimeExecutionContext) -> None:
        self._device_snapshots.clear()
        self._device_snapshot_locks.clear()
        await super().close(context)

    @staticmethod
    def _snapshot_key(
        options: Mapping[str, Any], path: str
    ) -> tuple[str, str, str, str, bool]:
        return (
            str(options.get("base_url") or "").rstrip("/").casefold(),
            path,
            str(options.get("username_env") or ""),
            str(options.get("password_env") or ""),
            bool(options.get("verify_tls", False)),
        )

    @staticmethod
    def _is_device_inventory(path: str) -> bool:
        return path.rstrip("/").endswith("/stat/device")

    def _prune_snapshots(self, now: float) -> None:
        stale = [
            key
            for key, value in self._device_snapshots.items()
            if now - value.captured_at
            > max(_SUCCESS_TTL_SECONDS, _FAILURE_TTL_SECONDS) * 4
        ]
        for key in stale:
            self._device_snapshots.pop(key, None)
            self._device_snapshot_locks.pop(key, None)
        if len(self._device_snapshots) <= _MAX_CACHE_ENTRIES:
            return
        oldest = sorted(
            self._device_snapshots.items(), key=lambda item: item[1].captured_at
        )
        for key, _ in oldest[: len(self._device_snapshots) - _MAX_CACHE_ENTRIES]:
            self._device_snapshots.pop(key, None)
            self._device_snapshot_locks.pop(key, None)

    @staticmethod
    def _fresh_snapshot(snapshot: _Snapshot | None, now: float) -> tuple[bool, Any]:
        if snapshot is None:
            return False, None
        ttl = _FAILURE_TTL_SECONDS if snapshot.error is not None else _SUCCESS_TTL_SECONDS
        if now - snapshot.captured_at > ttl:
            return False, None
        if snapshot.error is not None:
            raise RuntimeError(snapshot.error)
        return True, snapshot.payload

    async def _get(self, options: Mapping[str, Any], path: str) -> Any:
        if not self._is_device_inventory(path):
            return await super()._get(options, path)
        key = self._snapshot_key(options, path)
        now = time.monotonic()
        fresh, payload = self._fresh_snapshot(self._device_snapshots.get(key), now)
        if fresh:
            return payload
        lock = self._device_snapshot_locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            fresh, payload = self._fresh_snapshot(self._device_snapshots.get(key), now)
            if fresh:
                return payload
            try:
                payload = await super()._get(options, path)
            except Exception as exc:
                message = (
                    f"UniFi device inventory unavailable: {type(exc).__name__}: {exc}"
                )[:400]
                self._device_snapshots[key] = _Snapshot(
                    captured_at=time.monotonic(), error=message
                )
                self._prune_snapshots(time.monotonic())
                raise
            self._device_snapshots[key] = _Snapshot(
                captured_at=time.monotonic(), payload=payload
            )
            self._prune_snapshots(time.monotonic())
            return payload

    @staticmethod
    def _state_path(context: RuntimeExecutionContext) -> Path:
        return Path(context.state_root) / "link-expectations.json"

    def _load_links(
        self, context: RuntimeExecutionContext
    ) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self._state_path(context).read_text())
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != _PERSISTENCE_VERSION:
            return {}
        links = payload.get("links")
        if not isinstance(links, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for link_id, record in links.items():
            if not isinstance(record, dict):
                continue
            speed = _positive_int(record.get("speed_mbps"))
            if speed is not None:
                result[str(link_id)] = {**record, "speed_mbps": speed}
        return result

    def _save_links(
        self,
        context: RuntimeExecutionContext,
        links: Mapping[str, Mapping[str, Any]],
    ) -> None:
        path = self._state_path(context)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(
                json.dumps(
                    {"version": _PERSISTENCE_VERSION, "links": dict(links)},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            temp.replace(path)
        except OSError:
            pass

    def _derive_expectations(
        self,
        raw_devices: list[dict[str, Any]],
        options: Mapping[str, Any],
        context: RuntimeExecutionContext,
    ) -> dict[str, int]:
        persisted = self._load_links(context)
        explicit = {
            str(key).lower(): int(value)
            for key, value in dict(options.get("expected_uplink_speeds", {})).items()
        }
        by_mac = {str(item.get("mac", "")).lower(): item for item in raw_devices}
        resolved: dict[str, int] = {}
        durable = dict(persisted)
        for child in raw_devices:
            child_mac = str(child.get("mac", "")).lower()
            if not child_mac:
                continue
            explicit_mac = _positive_int(explicit.get(child_mac))
            if explicit_mac is not None:
                resolved[child_mac] = explicit_mac
                continue
            uplink = child.get("uplink") or {}
            parent_mac = str(uplink.get("uplink_mac", "")).lower()
            child_port_idx = uplink.get("port_idx")
            parent_port_idx = uplink.get("uplink_remote_port")
            parent = by_mac.get(parent_mac)
            if (
                not parent_mac
                or parent is None
                or child_port_idx is None
                or parent_port_idx is None
            ):
                continue
            link_id = f"{child_mac}@{parent_mac}:{child_port_idx}-{parent_port_idx}"
            explicit_link = _positive_int(explicit.get(link_id.lower()))
            if explicit_link is not None:
                resolved[child_mac] = explicit_link
                continue
            child_port = _port_by_index(child, child_port_idx)
            parent_port = _port_by_index(parent, parent_port_idx)
            child_capacity = _positive_int(uplink.get("max_speed"))
            parent_capacity = self._port_capacity(parent_port or {})
            record: dict[str, Any] | None = None
            if child_capacity is not None and parent_capacity is not None:
                constraints = [child_capacity, parent_capacity]
                for device, port_index, port in (
                    (child, child_port_idx, child_port),
                    (parent, parent_port_idx, parent_port),
                ):
                    configured = _configured_speed(device, port_index, port)
                    if configured is not None:
                        constraints.append(configured)
                inferred = min(constraints)
                record = {
                    "speed_mbps": inferred,
                    "child_mac": child_mac,
                    "parent_mac": parent_mac,
                    "child_port": child_port_idx,
                    "parent_port": parent_port_idx,
                    "child_capacity_mbps": child_capacity,
                    "parent_capacity_mbps": parent_capacity,
                }
                previous = persisted.get(link_id)
                if previous and int(previous.get("speed_mbps", 0)) > inferred:
                    record = {**previous}
            else:
                previous = persisted.get(link_id)
                if previous:
                    record = {**previous}
            if record is None:
                continue
            speed = _positive_int(record.get("speed_mbps"))
            if speed is None:
                continue
            resolved[child_mac] = speed
            durable[link_id] = {**record, "speed_mbps": speed}
        self._save_links(context, durable)
        return resolved

    async def _port_state(
        self,
        request: RuntimeExecutionRequest,
    ) -> RuntimeExecutionResult:
        start = time.monotonic()
        options = request.options
        site = str(options.get("site", "default"))
        try:
            payload = await self._get(
                options, f"/proxy/network/api/s/{site}/stat/device"
            )
        except Exception as exc:
            return RuntimeExecutionResult(
                state=State.UNKNOWN.value,
                summary=(
                    f"UniFi port state unavailable: {type(exc).__name__}: {exc}"
                )[:400],
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": False,
                    "failure_kind": "monitor_dependency",
                },
            )
        raw_devices = payload.get("data", []) if isinstance(payload, dict) else []
        object_ids = {
            str(key).strip().casefold(): str(value)
            for key, value in dict(options.get("device_object_ids", {})).items()
        }
        ports = normalize_unifi_ports(raw_devices, device_object_ids=object_ids)
        wanted_mac = str(options.get("device_mac") or "").strip().casefold()
        wanted_idx = options.get("port_idx")
        port = next(
            (
                item
                for item in ports
                if item["device_mac"] == wanted_mac and item["port_idx"] == wanted_idx
            ),
            None,
        )
        if port is None:
            return RuntimeExecutionResult(
                state=State.FAILED.value,
                summary="Configured switch port is missing from UniFi inventory",
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": True,
                    "missing": True,
                    "device_mac": wanted_mac,
                    "port_idx": wanted_idx,
                },
            )
        linked = port.get("linked") is True
        admin_enabled = port.get("admin_enabled") is not False
        speed = port.get("speed_mbps")
        metrics = {
            "linked": 1.0 if linked else 0.0,
            "admin_enabled": 1.0 if admin_enabled else 0.0,
        }
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            metrics["speed_mbps"] = float(speed)
        metadata = {
            "provider": "unifi",
            "device_mac": port.get("device_mac"),
            "device_name": port.get("device_name"),
            "port_idx": port.get("port_idx"),
            "port_name": port.get("name"),
            "linked": linked,
            "admin_enabled": admin_enabled,
            "is_uplink": port.get("is_uplink") is True,
        }
        if not admin_enabled:
            state, summary = State.HEALTHY, "Switch port is administratively disabled"
        elif linked:
            detail = (
                f" at {float(speed):g} Mbps"
                if isinstance(speed, (int, float)) and speed
                else ""
            )
            state, summary = State.HEALTHY, f"Switch port link up{detail}"
        else:
            state, summary = State.FAILED, "Switch port is enabled but has no link"
        return RuntimeExecutionResult(
            state=state.value,
            summary=summary,
            duration_ms=(time.monotonic() - start) * 1000,
            metrics=metrics,
            metadata=metadata,
        )

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        runtime_operation = str(request.options.get("runtime_operation", "")).strip()
        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if not runtime_operation and operation == "port_state":
            return await self._port_state(request)
        result = await super().execute(request, context)
        if runtime_operation or operation != "inventory":
            return result
        site = str(request.options.get("site", "default"))
        try:
            payload = await self._get(
                request.options, f"/proxy/network/api/s/{site}/stat/device"
            )
            raw_devices = payload.get("data", []) if isinstance(payload, dict) else []
            object_ids = {
                str(key).strip().casefold(): str(value)
                for key, value in dict(
                    request.options.get("device_object_ids", {})
                ).items()
            }
            ports = normalize_unifi_ports(raw_devices, device_object_ids=object_ids)
            metadata = dict(result.metadata)
            metrics = dict(result.metrics)
            metadata["ports"] = ports
            metrics["port_count"] = float(len(ports))
        except Exception as exc:
            metadata = dict(result.metadata)
            metrics = dict(result.metrics)
            metadata["ports"] = []
            metadata["ports_error"] = f"{type(exc).__name__}: {exc}"[:300]
        return RuntimeExecutionResult(
            state=result.state,
            summary=result.summary,
            duration_ms=result.duration_ms,
            metrics=metrics,
            metadata=metadata,
        )


__all__ = ["UniFiRuntimeExecutor", "normalize_unifi_ports"]
