from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mac(value: Any) -> str:
    return _text(value).casefold()


def _port_index(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip(), 10)
    return None


def annotate_port_recommendation_relationships(
    ports: list[dict[str, Any]],
    raw_devices: list[dict[str, Any]],
    raw_topology: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach bounded authoritative peer context to topology-derived port recommendations.

    The relation comes only from authenticated UniFi wired-topology edges.  Nothing is
    inferred from port names, speeds, connector types, or numbering.
    """
    if not isinstance(raw_topology, Mapping):
        return ports

    device_names: dict[str, str] = {}
    for row in raw_devices:
        if not isinstance(row, Mapping):
            continue
        mac = _mac(row.get("mac") or row.get("id"))
        if not mac:
            continue
        device_names[mac] = _text(row.get("name") or row.get("model") or row.get("mac") or row.get("id"))

    port_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    for port in ports:
        if not isinstance(port, dict):
            continue
        mac = _mac(port.get("device_mac"))
        index = _port_index(port.get("port_idx"))
        if mac and index is not None:
            port_by_identity[(mac, index)] = port
            if mac not in device_names:
                name = _text(port.get("device_name"))
                if name:
                    device_names[mac] = name

    edges = raw_topology.get("edges")
    if not isinstance(edges, list):
        return ports

    def describe_peer(mac: str, index: int) -> tuple[str, str]:
        peer = port_by_identity.get((mac, index), {})
        device = device_names.get(mac) or mac
        port_name = _text(peer.get("name") or peer.get("port_name")) or f"Port {index}"
        return device, port_name

    def annotate(
        local_mac: str,
        local_index: int,
        *,
        kind: str,
        peer_mac: str,
        peer_index: int,
    ) -> None:
        local = port_by_identity.get((local_mac, local_index))
        if local is None:
            return
        role = _text(local.get("infrastructure_role")).casefold()
        if role not in {"uplink", "infrastructure"}:
            return
        peer_device, peer_port = describe_peer(peer_mac, peer_index)
        if not peer_device:
            return
        if kind == "uplink":
            reason = f"Uplink to {peer_device} · {peer_port}"
        else:
            reason = f"Inter-switch link → {peer_device} · {peer_port}"
        local["recommendation_reason"] = reason[:240]
        local["recommendation_relationship"] = {
            "kind": kind,
            "peer_device": peer_device[:120],
            "peer_port": peer_port[:120],
        }

    for edge in edges:
        if not isinstance(edge, Mapping) or _text(edge.get("type")).casefold() != "wired":
            continue
        child_mac = _mac(edge.get("downlinkMac"))
        parent_mac = _mac(edge.get("uplinkMac"))
        child_port = _port_index(edge.get("downlinkPortNumber"))
        parent_port = _port_index(edge.get("uplinkPortNumber"))
        if not child_mac or not parent_mac or child_port is None or parent_port is None:
            continue
        annotate(
            child_mac,
            child_port,
            kind="uplink",
            peer_mac=parent_mac,
            peer_index=parent_port,
        )
        annotate(
            parent_mac,
            parent_port,
            kind="inter_switch_link",
            peer_mac=child_mac,
            peer_index=child_port,
        )
    return ports


__all__ = ["annotate_port_recommendation_relationships"]
