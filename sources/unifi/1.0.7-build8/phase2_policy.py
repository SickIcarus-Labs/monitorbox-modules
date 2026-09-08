from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from ...plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)
from .discovery import unifi_evidence, wan_interface_addresses
from .discovery_runtime import UniFiRuntimeExecutor as _BaseUniFiRuntimeExecutor


def _port_index(value: Any) -> int | None:
    """Normalize provider-supplied integral port identifiers without guessing.

    UniFi payloads are not lexically stable across controller/API paths: a port
    index may arrive as JSON integer, integral float, or decimal string. These
    forms all represent the same provider-native identifier. Names, fractions,
    negatives and booleans are intentionally rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not isfinite(value) or value < 0 or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or not text.isdecimal():
            return None
        return int(text, 10)
    return None


def _explicit_port_role(raw_port: Mapping[str, Any]) -> tuple[str | None, bool, bool]:
    """Return only provider-explicit infrastructure evidence.

    No switch names, port numbers, labels, or VLAN guesses are used here. If
    UniFi does not expose a sufficiently explicit role, the port remains
    access/unknown and therefore optional.
    """
    if raw_port.get("is_uplink") is True:
        return "uplink", False, False
    if raw_port.get("is_trunk") is True:
        return "trunk", True, False
    if raw_port.get("is_lag_member") is True or raw_port.get("lag_member") is True:
        return "lag", False, True
    aggregate_count = raw_port.get("aggregate_num_ports")
    if (
        isinstance(aggregate_count, int)
        and not isinstance(aggregate_count, bool)
        and aggregate_count > 1
    ):
        return "lag", False, True
    if raw_port.get("aggregated_by") not in (None, "", False):
        return "lag", False, True
    explicit = str(
        raw_port.get("port_role")
        or raw_port.get("role")
        or raw_port.get("forwarding_role")
        or ""
    ).strip().casefold()
    if explicit in {"uplink", "trunk", "lag", "wan", "infrastructure"}:
        return explicit, explicit == "trunk", explicit == "lag"
    return None, False, False


def _topology_port_roles(raw_devices: Any) -> dict[tuple[str, int], str]:
    """Project UniFi's explicit child->parent uplink topology onto both ports.

    The legacy authenticated device payload exposes ``uplink.port_idx``,
    ``uplink.uplink_mac`` and ``uplink.uplink_remote_port``. Provider versions
    may encode the two port identifiers as integers, integral floats or decimal
    strings, so they are normalized through ``_port_index`` before identity
    comparison. This remains provider topology evidence, not a switch-name or
    port-number heuristic.
    """
    if not isinstance(raw_devices, list):
        return {}
    known_macs = {
        str(device.get("mac") or "").strip().casefold()
        for device in raw_devices
        if isinstance(device, Mapping) and str(device.get("mac") or "").strip()
    }
    roles: dict[tuple[str, int], str] = {}
    for child in raw_devices:
        if not isinstance(child, Mapping):
            continue
        child_mac = str(child.get("mac") or "").strip().casefold()
        uplink = child.get("uplink")
        if not child_mac or not isinstance(uplink, Mapping):
            continue

        child_idx = _port_index(uplink.get("port_idx"))
        if child_idx is not None:
            roles[(child_mac, child_idx)] = "uplink"

        parent_mac = str(uplink.get("uplink_mac") or "").strip().casefold()
        parent_idx = _port_index(uplink.get("uplink_remote_port"))
        if parent_mac in known_macs and parent_idx is not None:
            roles[(parent_mac, parent_idx)] = "infrastructure"
    return roles


def _enrich_port_roles(
    normalized: Any,
    raw_devices: Any,
) -> list[dict[str, Any]]:
    ports = (
        [dict(item) for item in normalized if isinstance(item, Mapping)]
        if isinstance(normalized, list)
        else []
    )
    if not isinstance(raw_devices, list):
        return ports
    raw_by_identity: dict[tuple[str, int], Mapping[str, Any]] = {}
    for device in raw_devices:
        if not isinstance(device, Mapping):
            continue
        mac = str(device.get("mac") or "").strip().casefold()
        if not mac:
            continue
        for raw_port in device.get("port_table", []):
            if not isinstance(raw_port, Mapping):
                continue
            index = _port_index(raw_port.get("port_idx"))
            if index is None:
                continue
            raw_by_identity[(mac, index)] = raw_port

    topology_roles = _topology_port_roles(raw_devices)
    for port in ports:
        mac = str(port.get("device_mac") or "").strip().casefold()
        index = _port_index(port.get("port_idx"))
        if index is None:
            continue
        port["port_idx"] = index
        raw = raw_by_identity.get((mac, index))
        role: str | None = None
        is_trunk = False
        is_lag_member = False
        if raw is not None:
            role, is_trunk, is_lag_member = _explicit_port_role(raw)

        topology_role = topology_roles.get((mac, index))
        if role is None and topology_role:
            role = topology_role
        if topology_role == "uplink":
            port["is_uplink"] = True
        if role:
            port["infrastructure_role"] = role
        port["is_trunk"] = is_trunk
        port["is_lag_member"] = is_lag_member
    return ports


def _inventory_authority(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Publish provider-neutral authority markers required by frozen Core."""
    result = dict(metadata)
    available = result.get("source_available") is True
    result["provider"] = "unifi"
    result["provider_available"] = available
    result["authoritative"] = available
    return result


class UniFiPhase2RuntimeExecutor(_BaseUniFiRuntimeExecutor):
    """Reproject authenticated inventory through Phase-2 discovery semantics."""

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        runtime_operation = str(request.options.get("runtime_operation", "")).strip()
        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if runtime_operation or operation != "inventory":
            return result

        metadata = _inventory_authority(result.metadata)
        raw_devices: list[dict[str, Any]] = []
        if metadata.get("source_available") is True:
            site = str(request.options.get("site", "default"))
            try:
                payload = await self._get(
                    request.options,
                    f"/proxy/network/api/s/{site}/stat/device",
                )
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                raw_devices = [
                    dict(item) for item in rows if isinstance(item, Mapping)
                ]
            except Exception:
                raw_devices = []

        ports = _enrich_port_roles(metadata.get("ports", []), raw_devices)
        health = metadata.get("health", [])
        metadata["ports"] = ports
        metadata["wan_interface_addresses"] = sorted(wan_interface_addresses(health))
        evidence = unifi_evidence(metadata.get("devices", []), ports, health)
        metadata["discovery_evidence"] = [item.as_dict() for item in evidence]
        return RuntimeExecutionResult(
            state=result.state,
            summary=result.summary,
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )


__all__ = [
    "UniFiPhase2RuntimeExecutor",
    "_enrich_port_roles",
    "_explicit_port_role",
    "_inventory_authority",
    "_port_index",
    "_topology_port_roles",
]
