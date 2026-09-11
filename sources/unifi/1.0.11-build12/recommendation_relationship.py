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
    """Attach bounded peer context from the same authoritative relations used for roles."""
    device_names: dict[str, str] = {}
    raw_ports: dict[tuple[str, int], Mapping[str, Any]] = {}
    normalized: dict[tuple[str, int], dict[str, Any]] = {}

    for row in raw_devices:
        if not isinstance(row, Mapping):
            continue
        mac = _mac(row.get("mac") or row.get("id"))
        if not mac:
            continue
        device_names[mac] = _text(row.get("name") or row.get("model") or row.get("mac") or row.get("id"))
        for raw in row.get("port_table", []):
            if not isinstance(raw, Mapping):
                continue
            index = _port_index(raw.get("port_idx"))
            if index is not None:
                raw_ports[(mac, index)] = raw

    for port in ports:
        if not isinstance(port, dict):
            continue
        mac = _mac(port.get("device_mac"))
        index = _port_index(port.get("port_idx"))
        if mac and index is not None:
            normalized[(mac, index)] = port
            if mac not in device_names:
                name = _text(port.get("device_name"))
                if name:
                    device_names[mac] = name

    def describe(mac: str, index: int) -> tuple[str, str]:
        raw = raw_ports.get((mac, index), {})
        norm = normalized.get((mac, index), {})
        device = device_names.get(mac) or mac
        port_name = _text(
            raw.get("name")
            or raw.get("port_name")
            or norm.get("name")
            or norm.get("port_name")
        ) or f"Port {index}"
        return device, port_name

    def annotate(local_mac: str, local_index: int, kind: str, peer_mac: str, peer_index: int) -> None:
        local = normalized.get((local_mac, local_index))
        if local is None:
            return
        role = _text(local.get("infrastructure_role")).casefold()
        if role not in {"uplink", "infrastructure"}:
            return
        peer_device, peer_port = describe(peer_mac, peer_index)
        if not peer_device:
            return
        prefix = "Uplink to" if kind == "uplink" else "Inter-switch link →"
        local["recommendation_reason"] = f"{prefix} {peer_device} · {peer_port}"[:240]
        local["recommendation_relationship"] = {
            "kind": kind,
            "peer_device": peer_device[:120],
            "peer_port": peer_port[:120],
        }

    # Primary authority: authenticated wired topology edges.
    edges = raw_topology.get("edges") if isinstance(raw_topology, Mapping) else None
    topology_applied = False
    if isinstance(edges, list):
        known = set(device_names)
        for edge in edges:
            if not isinstance(edge, Mapping) or _text(edge.get("type")).casefold() != "wired":
                continue
            child_mac = _mac(edge.get("downlinkMac"))
            parent_mac = _mac(edge.get("uplinkMac"))
            child_port = _port_index(edge.get("downlinkPortNumber"))
            parent_port = _port_index(edge.get("uplinkPortNumber"))
            if child_mac not in known or parent_mac not in known or child_port is None or parent_port is None:
                continue
            annotate(child_mac, child_port, "uplink", parent_mac, parent_port)
            annotate(parent_mac, parent_port, "inter_switch_link", child_mac, child_port)
            topology_applied = True

    # Match phase2_policy authority exactly: only use stat/device uplink tuples
    # when topology supplied no eligible device-to-device edges.
    if not topology_applied:
        known = set(device_names)
        for child in raw_devices:
            if not isinstance(child, Mapping):
                continue
            child_mac = _mac(child.get("mac"))
            uplink = child.get("uplink")
            if not child_mac or not isinstance(uplink, Mapping):
                continue
            child_port = _port_index(uplink.get("port_idx"))
            parent_mac = _mac(uplink.get("uplink_mac"))
            parent_port = _port_index(uplink.get("uplink_remote_port"))
            if child_port is None or parent_mac not in known or parent_port is None:
                continue
            annotate(child_mac, child_port, "uplink", parent_mac, parent_port)
            annotate(parent_mac, parent_port, "inter_switch_link", child_mac, child_port)

    return ports


__all__ = ["annotate_port_recommendation_relationships"]
