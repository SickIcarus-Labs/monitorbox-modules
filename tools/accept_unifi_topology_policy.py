#!/usr/bin/env python3
"""Regression for #170: provider-authoritative UniFi infrastructure port policy."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from accept_http_behavior import install_core_contract_stubs
from accept_unifi_runtime import _install_unifi_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.9-build10.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b10"
CORE = "aa:bb:cc:dd:ee:01"
EDGE = "aa:bb:cc:dd:ee:02"
CLIENT = "aa:bb:cc:dd:ee:99"


def normalized_ports():
    def port(device_mac: str, device_name: str, idx: int):
        return {
            "id": f"port-{device_mac[-2:]}-{idx}",
            "device_mac": device_mac,
            "device_name": device_name,
            "port_idx": idx,
            "name": f"Port {idx}",
            "linked": True,
            "admin_enabled": True,
            "speed_mbps": 10000.0,
            "is_uplink": False,
        }

    return [
        port(CORE, "Core", 15),
        port(CORE, "Core", 16),
        port(EDGE, "Edge", 8),
        port(EDGE, "Edge", 9),
        port(EDGE, "Edge", 10),
    ]


def raw_devices():
    # Deliberately stale/conflicting stat/device uplink tuple. When an explicit
    # /topology device-to-device snapshot exists, that topology must win rather
    # than creating a second guessed infrastructure recommendation.
    return [
        {
            "mac": CORE,
            "name": "Core",
            "port_table": [{"port_idx": 15}, {"port_idx": 16}],
        },
        {
            "mac": EDGE,
            "name": "Edge",
            "uplink": {
                "port_idx": 8,
                "uplink_mac": CORE,
                "uplink_remote_port": 16,
            },
            "port_table": [
                {"port_idx": 8},
                {"port_idx": 9},
                {"port_idx": 10},
            ],
        },
    ]


def topology_fixture():
    # Shape copied from the sanitized Broad Leaf Network 10.6.101 census, with
    # synthetic identities. Only the relationship/field schema is retained.
    return {
        "edges": [
            {
                "downlinkMac": EDGE,
                "downlinkPortNumber": "9",
                "duplex": "FULL",
                "networkId": "synthetic",
                "rateMbps": 10000,
                "type": "WIRED",
                "uplinkMac": CORE,
                "uplinkPortNumber": 15.0,
            },
            {
                # Ordinary wired client edge: no device-side downlink port, so
                # the switch port must not become an infrastructure expectation.
                "downlinkMac": CLIENT,
                "networkId": "synthetic",
                "rateMbps": 1000,
                "type": "WIRED",
                "uplinkMac": CORE,
                "uplinkPortNumber": 16,
            },
        ]
    }


def by_identity(rows):
    return {(row["device_mac"], row["port_idx"]): row for row in rows}


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed UniFi #170 candidate is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_unifi_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)
    policy = importlib.import_module(f"{IMPORT_PACKAGE}.phase2_policy")
    discovery = importlib.import_module(f"{IMPORT_PACKAGE}.discovery")

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.9", 10):
        raise AssertionError("UniFi #170 candidate identity changed")

    devices = raw_devices()
    topology = topology_fixture()
    roles = policy._topology_port_roles(devices, topology)
    expected = {
        (EDGE, 9): "uplink",
        (CORE, 15): "infrastructure",
    }
    if roles != expected:
        raise AssertionError(f"authoritative /topology projection changed: {roles!r}")

    enriched = policy._enrich_port_roles(normalized_ports(), devices, topology)
    indexed = by_identity(enriched)
    edge9 = indexed[(EDGE, 9)]
    core15 = indexed[(CORE, 15)]
    edge8 = indexed[(EDGE, 8)]
    edge10 = indexed[(EDGE, 10)]
    core16 = indexed[(CORE, 16)]

    if edge9.get("infrastructure_role") != "uplink" or edge9.get("is_uplink") is not True:
        raise AssertionError(f"known child infrastructure port not classified: {edge9!r}")
    if core15.get("infrastructure_role") != "infrastructure":
        raise AssertionError(f"known parent infrastructure port not classified: {core15!r}")
    for ordinary in (edge8, edge10, core16):
        if ordinary.get("infrastructure_role"):
            raise AssertionError(f"ordinary/unknown port was promoted by heuristic: {ordinary!r}")

    evidence = discovery.unifi_evidence([], enriched, [])
    evidence_by_id = {item.source_id: item for item in evidence}
    if evidence_by_id[edge9["id"]].metadata.get("policy_hint") != "required":
        raise AssertionError("known infrastructure port is not Recommended/required")
    if evidence_by_id[core15["id"]].metadata.get("initial_importance") != "required":
        raise AssertionError("peer infrastructure port is not Recommended/required")
    for ordinary in (edge8, edge10, core16):
        metadata = evidence_by_id[ordinary["id"]].metadata
        if metadata.get("policy_hint") != "optional" or metadata.get("initial_importance") != "not_required":
            raise AssertionError(f"ordinary/unknown port stopped being Optional: {metadata!r}")

    # If /topology is unavailable, retain the previous provider-native
    # stat/device uplink tuple as a bounded fallback. This is still explicit
    # provider evidence, not a switch-name/port-number heuristic.
    fallback = policy._topology_port_roles(devices, None)
    if fallback != {(EDGE, 8): "uplink", (CORE, 16): "infrastructure"}:
        raise AssertionError(f"stat/device uplink fallback changed: {fallback!r}")

    print(
        "Managed UniFi Network 1.0.9 build 10: authoritative legacy topology + "
        "ordinary-port negative controls + stat/device fallback: PASS",
        flush=True,
    )


if __name__ == "__main__":
    main()
