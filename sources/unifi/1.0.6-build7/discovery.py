from __future__ import annotations

from ipaddress import ip_address
from typing import Any, Mapping

from ...discovery import DiscoveryEvidence


def _address(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(ip_address(text))
    except ValueError:
        return None


def wan_interface_addresses(raw_health: Any) -> frozenset[str]:
    """Extract only addresses semantically identified by UniFi as WAN state.

    This deliberately does not classify by public/private address range. A
    manually configured public target remains ordinary operator intent; only
    provider rows explicitly describing the WAN subsystem suppress discovery.
    """
    if not isinstance(raw_health, list):
        return frozenset()
    result: set[str] = set()
    for row in raw_health:
        if not isinstance(row, Mapping):
            continue
        subsystem = str(row.get("subsystem") or "").strip().casefold()
        explicit_wan = subsystem == "wan" or row.get("wan_ip") not in (None, "")
        if not explicit_wan:
            continue
        for key in ("wan_ip", "ip"):
            value = _address(row.get(key))
            if value:
                result.add(value)
    return frozenset(result)


def _port_expectation(port: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return (importance, generic policy hint, provider-known role)."""
    if port.get("admin_enabled") is False:
        return "ignored", "optional", "administratively_disabled"
    role = str(port.get("infrastructure_role") or "").strip().casefold()
    infrastructure = bool(
        port.get("is_uplink") is True
        or port.get("is_trunk") is True
        or port.get("is_lag_member") is True
        or role in {"uplink", "trunk", "lag", "wan", "infrastructure"}
    )
    if infrastructure:
        return "required", "required", role or "uplink"
    return "not_required", "optional", role or "access_or_unknown"


def unifi_evidence(
    raw_devices: Any,
    raw_ports: Any = (),
    raw_health: Any = (),
) -> tuple[DiscoveryEvidence, ...]:
    """Project authenticated UniFi inventory into actionable discovery truth.

    Provider-proven WAN-interface addresses remain available in the enclosing
    inventory metadata via ``wan_interface_addresses``. They are intentionally
    omitted from generic DiscoveryEvidence because that channel is actionable
    monitoring intent; emitting an addressless gateway row allows downstream
    generic discovery to reconstitute a meaningless Ping candidate.
    """

    result: list[DiscoveryEvidence] = []
    wan_addresses = wan_interface_addresses(raw_health)
    if isinstance(raw_devices, list):
        for device in raw_devices:
            if not isinstance(device, dict):
                continue
            source_id = device.get("id") or device.get("mac")
            if not isinstance(source_id, str) or not source_id.strip():
                continue
            name = str(device.get("name") or device.get("model") or source_id).strip()
            ip = _address(device.get("ip"))
            if ip and ip in wan_addresses:
                # Informational WAN context is preserved by the provider runtime,
                # but it is not an actionable generic network-device candidate.
                continue
            addresses = () if not ip else (ip,)
            capabilities = ["unifi_network"]
            if addresses:
                capabilities.insert(0, "reachability")
            if device.get("snmp_applicability"):
                capabilities.append("snmp")
            metadata = {
                "model": device.get("model"),
                "connected": device.get("connected"),
                "object_id": device.get("object_id"),
                "snmp_applicability": device.get("snmp_applicability"),
            }
            result.append(
                DiscoveryEvidence(
                    source="unifi",
                    source_id=source_id,
                    kind="network_device",
                    label=name,
                    addresses=addresses,
                    mac=device.get("mac") if isinstance(device.get("mac"), str) else None,
                    confidence=95,
                    suggested_capabilities=tuple(capabilities),
                    metadata=metadata,
                )
            )

    if isinstance(raw_ports, list):
        for port in raw_ports:
            if not isinstance(port, dict):
                continue
            source_id = port.get("id")
            device_mac = port.get("device_mac")
            port_idx = port.get("port_idx")
            if (
                not isinstance(source_id, str)
                or not source_id.strip()
                or not isinstance(device_mac, str)
                or isinstance(port_idx, bool)
                or not isinstance(port_idx, int)
            ):
                continue
            device_name = str(port.get("device_name") or device_mac).strip()
            port_name = str(port.get("name") or f"Port {port_idx}").strip()
            linked = port.get("linked") is True
            admin_enabled = port.get("admin_enabled") is not False
            initial_importance, policy_hint, role = _port_expectation(port)
            result.append(
                DiscoveryEvidence(
                    source="unifi",
                    source_id=source_id,
                    kind="network_port",
                    label=f"{device_name} · {port_name}",
                    confidence=98,
                    suggested_capabilities=("port_state",),
                    metadata={
                        "device_mac": device_mac,
                        "device_name": device_name,
                        "device_object_id": port.get("device_object_id"),
                        "port_idx": port_idx,
                        "port_name": port_name,
                        "linked": linked,
                        "admin_enabled": admin_enabled,
                        "speed_mbps": port.get("speed_mbps"),
                        "is_uplink": port.get("is_uplink") is True,
                        "is_trunk": port.get("is_trunk") is True,
                        "is_lag_member": port.get("is_lag_member") is True,
                        "infrastructure_role": role,
                        "initial_importance": initial_importance,
                        "policy_hint": policy_hint,
                        "always_up_expectation": policy_hint == "required",
                    },
                )
            )
    return tuple(result)


__all__ = ["unifi_evidence", "wan_interface_addresses"]
