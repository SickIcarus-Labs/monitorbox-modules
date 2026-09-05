from __future__ import annotations

from typing import Any

from ...discovery import DiscoveryEvidence


def unifi_evidence(
    raw_devices: Any,
    raw_ports: Any = (),
) -> tuple[DiscoveryEvidence, ...]:
    """Project authenticated UniFi inventory into normal discovery evidence.

    This is provider knowledge: device identity, switch-port identity and the
    initial port-importance hint all remain inside the UniFi vertical. The
    generic discovery engine only transports validated ``DiscoveryEvidence``.
    """

    result: list[DiscoveryEvidence] = []
    if isinstance(raw_devices, list):
        for device in raw_devices:
            if not isinstance(device, dict):
                continue
            source_id = device.get("id") or device.get("mac")
            if not isinstance(source_id, str) or not source_id.strip():
                continue
            name = str(device.get("name") or device.get("model") or source_id).strip()
            ip = device.get("ip")
            addresses = (ip,) if isinstance(ip, str) and ip.strip() else ()
            capabilities = ["reachability", "unifi_network"]
            if device.get("snmp_applicability"):
                capabilities.append("snmp")
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
                    metadata={
                        "model": device.get("model"),
                        "connected": device.get("connected"),
                        "object_id": device.get("object_id"),
                        "snmp_applicability": device.get("snmp_applicability"),
                    },
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
            initial_importance = (
                "required" if linked else "not_required" if admin_enabled else "ignored"
            )
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
                        "initial_importance": initial_importance,
                    },
                )
            )
    return tuple(result)


__all__ = ["unifi_evidence"]
