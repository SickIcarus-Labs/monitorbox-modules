from __future__ import annotations

from typing import Any


def annotate_inventory_provenance(
    metadata: dict[str, Any],
    source_check_id: str,
) -> dict[str, Any]:
    """Attach the runnable collection-check identity to projected UniFi children.

    Core intentionally projects one provider inventory observation into virtual
    source/device/VPN components. Those virtual component ids are presentation
    identities, not runnable check ids. Keep the real check provenance in
    provider-owned metadata so UI actions can request a fresh provider sample
    without parsing synthetic ids or teaching Core about UniFi topology.
    """

    check_id = str(source_check_id or "").strip()
    if not check_id:
        return metadata

    # Core copies top-level metadata onto the synthetic ``:source`` component.
    metadata["source_check_id"] = check_id

    # Core uses each normalized device row as that virtual device component's
    # metadata, so stamp the same execution provenance on every device child.
    devices = metadata.get("devices")
    if isinstance(devices, list):
        for device in devices:
            if isinstance(device, dict):
                device["source_check_id"] = check_id

    # Configured VPN expectations are projected from ``vpn_components`` and Core
    # preserves each row's nested metadata on the resulting virtual component.
    vpn_components = metadata.get("vpn_components")
    if isinstance(vpn_components, list):
        for component in vpn_components:
            if not isinstance(component, dict):
                continue
            child_metadata = component.get("metadata")
            if not isinstance(child_metadata, dict):
                child_metadata = {}
                component["metadata"] = child_metadata
            child_metadata["source_check_id"] = check_id

    return metadata


__all__ = ["annotate_inventory_provenance"]
