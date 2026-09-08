from __future__ import annotations

from typing import Any, Mapping

from ...plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)
from .discovery import unifi_evidence, wan_interface_addresses
from .discovery_runtime import UniFiRuntimeExecutor as _BaseUniFiRuntimeExecutor


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


def _enrich_port_roles(
    normalized: Any,
    raw_devices: Any,
) -> list[dict[str, Any]]:
    ports = [dict(item) for item in normalized if isinstance(item, Mapping)] if isinstance(normalized, list) else []
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
            index = raw_port.get("port_idx")
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            raw_by_identity[(mac, index)] = raw_port

    for port in ports:
        mac = str(port.get("device_mac") or "").strip().casefold()
        index = port.get("port_idx")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        raw = raw_by_identity.get((mac, index))
        if raw is None:
            continue
        role, is_trunk, is_lag_member = _explicit_port_role(raw)
        if role:
            port["infrastructure_role"] = role
        port["is_trunk"] = is_trunk
        port["is_lag_member"] = is_lag_member
    return ports


def _inventory_authority(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Publish provider-neutral authority markers required by frozen Core.

    The UniFi module owns its inventory schema and discovery projection. Frozen
    Core's persistent discovery inbox deliberately understands only generic
    provider/authority metadata, so successful provider inventory must identify
    itself explicitly. A non-available source remains non-authoritative and can
    never erase the last authoritative discovery snapshot.
    """
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
                raw_devices = [dict(item) for item in rows if isinstance(item, Mapping)]
            except Exception:
                # Discovery evidence remains available from the already-completed
                # provider observation even if this cache-backed enrichment read
                # cannot be repeated.
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


__all__ = ["UniFiPhase2RuntimeExecutor"]
