#!/usr/bin/env python3
"""Stage #59 bootstrap-discovery successor releases for all first-run providers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PORTAINER = "com.sickicarus.monitorbox.portainer"
NUT = "com.sickicarus.monitorbox.nut"
SCRYPTED = "com.sickicarus.monitorbox.scrypted"
SNMP = "com.sickicarus.monitorbox.snmp"
UNIFI = "com.sickicarus.monitorbox.unifi"
HTTP = "com.sickicarus.monitorbox.http"

PORTAINER_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [9000, 9443]},
    "matches": [
        {"id": "legacy-http-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "9000"}]},
        {"id": "https-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "9443"}]},
    ],
}
NUT_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [3493]},
    "matches": [
        {"id": "nut-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "3493"}]},
    ],
}
SCRYPTED_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [10443, 11080]},
    "matches": [
        {"id": "workload-image", "confidence": "detected", "all": [{"fact": "workload.image", "op": "contains", "value": "/scrypted"}]},
        {"id": "compose-service", "confidence": "detected", "all": [{"fact": "workload.compose_service", "op": "equals", "value": "scrypted"}]},
        {"id": "management-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "10443"}]},
        {"id": "http-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "11080"}]},
    ],
}
SNMP_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 2, "probes": [{"kind": "snmp_v3", "port": 161}]},
    "matches": [
        {
            "id": "snmp-v3-responsive",
            "confidence": "detected",
            "all": [
                {"fact": "probe.kind", "op": "equals", "value": "snmp_v3"},
                {"fact": "probe.result", "op": "equals", "value": "responsive"},
            ],
        },
    ],
}
UNIFI_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [443]},
    "matches": [
        {"id": "unifi-https-port", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": "443"}]},
    ],
}
HTTP_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [80, 443, 8443, 9090]},
    "matches": [
        {"id": f"http-port-{port}", "confidence": "possible", "all": [{"fact": "network.port", "op": "equals", "value": str(port)}]}
        for port in (80, 443, 8443, 9090)
    ],
}

RELEASES = (
    (
        (PORTAINER, "1.2.0", 8),
        (PORTAINER, "1.3.0", 9),
        {
            "manifest": {
                "module_id": PORTAINER,
                "display_name": "Portainer Integration",
                "description": "Monitors Docker environments and workload health through Portainer inventory.",
                "version": "1.3.0",
                "build": 9,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_portainer_b9:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": PORTAINER_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.portainer-1.3.0-build9.zip",
        },
    ),
    (
        (NUT, "1.0.1", 2),
        (NUT, "1.1.0", 3),
        {
            "manifest": {
                "module_id": NUT,
                "display_name": "NUT UPS Integration",
                "description": "Monitors UPS health and status through Network UPS Tools (NUT).",
                "version": "1.1.0",
                "build": 3,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_nut_b3:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": NUT_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.nut-1.1.0-build3.zip",
        },
    ),
    (
        (SCRYPTED, "2.2.0", 5),
        (SCRYPTED, "2.3.0", 6),
        {
            "manifest": {
                "module_id": SCRYPTED,
                "display_name": "Scrypted Integration",
                "description": "Monitors Scrypted service health and camera availability, snapshots, and streams.",
                "version": "2.3.0",
                "build": 6,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_scrypted_v230_b6:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": SCRYPTED_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.scrypted-2.3.0-build6.zip",
        },
    ),
    (
        (SNMP, "1.0.6", 8),
        (SNMP, "1.1.0", 9),
        {
            "manifest": {
                "module_id": SNMP,
                "display_name": "SNMP Integration",
                "description": "Monitors systems and appliances through SNMP.",
                "version": "1.1.0",
                "build": 9,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_snmp_v110_b9:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": SNMP_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.snmp-1.1.0-build9.zip",
        },
    ),
    (
        (UNIFI, "1.0.9", 10),
        (UNIFI, "1.1.0", 11),
        {
            "manifest": {
                "module_id": UNIFI,
                "display_name": "UniFi Network Integration",
                "description": "Monitors UniFi Network controller, device, and WAN health.",
                "version": "1.1.0",
                "build": 11,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_unifi_v110_b11:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": UNIFI_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.unifi-1.1.0-build11.zip",
        },
    ),
    (
        (HTTP, "1.0.1", 2),
        (HTTP, "1.1.0", 3),
        {
            "manifest": {
                "module_id": HTTP,
                "display_name": "HTTP(S) Integration",
                "description": "Monitors HTTP(S) endpoints and response health.",
                "version": "1.1.0",
                "build": 3,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_http_v110_b3:PLUGIN"},
                "requires_core": ">=2.4.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
                "capability_detection": HTTP_DETECTION,
            },
            "package": "com.sickicarus.monitorbox.http-1.1.0-build3.zip",
        },
    ),
)


def identity(item: dict[str, Any]) -> tuple[str, str, int]:
    manifest = item.get("manifest", {})
    return str(manifest.get("module_id") or ""), str(manifest.get("version") or ""), int(manifest.get("build") or 0)


def stage(path: Path) -> bool:
    source = json.loads(path.read_text(encoding="utf-8"))
    modules = source.get("modules")
    if not isinstance(modules, list):
        raise SystemExit("catalog.source.json has no modules list")
    changed = False
    for predecessor, release, entry in RELEASES:
        existing = [item for item in modules if identity(item) == release]
        if existing:
            if len(existing) != 1 or existing[0] != entry:
                raise SystemExit(f"catalog release conflicts with #59 contract: {release}")
            continue
        indexes = [index for index, item in enumerate(modules) if identity(item) == predecessor]
        if len(indexes) != 1:
            raise SystemExit(f"expected exactly one immutable predecessor {predecessor}, found {len(indexes)}")
        modules.insert(indexes[0] + 1, entry)
        changed = True
        print(f"staged {release[0]} {release[1]} build {release[2]}")
    if changed:
        path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
