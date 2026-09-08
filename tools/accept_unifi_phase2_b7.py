#!/usr/bin/env python3
"""Physical-repair acceptance for UniFi 1.0.6 build 7."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BUILD7 = ROOT / "sources" / "unifi" / "1.0.6-build7"


@dataclass(frozen=True)
class Evidence:
    source: str
    source_id: str
    kind: str
    label: str
    addresses: tuple[str, ...] = ()
    mac: str | None = None
    confidence: int = 50
    suggested_capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "kind": self.kind,
            "label": self.label,
            "addresses": list(self.addresses),
            "mac": self.mac,
            "confidence": self.confidence,
            "suggested_capabilities": list(self.suggested_capabilities),
            "metadata": dict(self.metadata or {}),
        }


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_stubs() -> None:
    for name in ("candidate", "candidate.integrations", "candidate.integrations.unifi"):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package

    discovery = types.ModuleType("candidate.discovery")
    discovery.DiscoveryEvidence = Evidence
    sys.modules[discovery.__name__] = discovery

    plugin_api = types.ModuleType("candidate.plugin_api")
    plugin_api.RuntimeExecutionContext = type("RuntimeExecutionContext", (), {})
    plugin_api.RuntimeExecutionRequest = type("RuntimeExecutionRequest", (), {})
    plugin_api.RuntimeExecutionResult = type("RuntimeExecutionResult", (), {})
    sys.modules[plugin_api.__name__] = plugin_api

    runtime = types.ModuleType("candidate.integrations.unifi.discovery_runtime")
    runtime.UniFiRuntimeExecutor = type("UniFiRuntimeExecutor", (), {})
    sys.modules[runtime.__name__] = runtime


def _one(items, source_id: str) -> Evidence:
    return next(item for item in items if item.source_id == source_id)


def main() -> None:
    _install_stubs()
    discovery = _load(
        "candidate.integrations.unifi.discovery",
        BUILD7 / "discovery.py",
    )
    policy = _load(
        "candidate.integrations.unifi.phase2_policy",
        BUILD7 / "phase2_policy.py",
    )

    # #169: WAN interface truth stays informational provider metadata and does
    # not become an addressless/actionable generic gateway candidate.
    health = [
        {"subsystem": "wan", "wan_ip": "108.85.13.175"},
        {"subsystem": "lan", "ip": "192.168.3.1"},
    ]
    devices = [
        {
            "id": "gateway",
            "name": "Broad Leaf",
            "ip": "108.85.13.175",
            "mac": "70:a7:41:fe:79:de",
            "snmp_applicability": True,
        },
        {
            "id": "switch",
            "name": "Aggregation",
            "ip": "192.168.3.2",
            "mac": "aa:aa:aa:aa:aa:aa",
        },
        {
            "id": "manual-public",
            "name": "Explicit public target",
            "ip": "203.0.113.40",
            "mac": "cc:cc:cc:cc:cc:cc",
        },
    ]
    evidence = discovery.unifi_evidence(devices, [], health)
    assert discovery.wan_interface_addresses(health) == frozenset({"108.85.13.175"})
    assert all(item.source_id != "gateway" for item in evidence)
    assert _one(evidence, "switch").addresses == ("192.168.3.2",)
    assert "reachability" in _one(evidence, "switch").suggested_capabilities
    assert _one(evidence, "manual-public").addresses == ("203.0.113.40",)
    assert "reachability" in _one(evidence, "manual-public").suggested_capabilities

    # #170: use the exact provider topology tuple already consumed by the base
    # runtime for durable link expectations. Both sides of an inter-switch link
    # become infrastructure; an adjacent ordinary port remains optional.
    raw_devices = [
        {
            "mac": "aa:aa:aa:aa:aa:aa",
            "name": "Aggregation",
            "port_table": [
                {"port_idx": 24, "name": "Port 24", "up": True},
                {"port_idx": 25, "name": "Port 25", "up": True},
            ],
        },
        {
            "mac": "bb:bb:bb:bb:bb:bb",
            "name": "Switch 2",
            "uplink": {
                "uplink_mac": "aa:aa:aa:aa:aa:aa",
                "port_idx": 9,
                "uplink_remote_port": 25,
            },
            "port_table": [
                {"port_idx": 9, "name": "Port 9", "up": True},
                {"port_idx": 8, "name": "Port 8", "up": True},
            ],
        },
    ]
    normalized = [
        {
            "id": "agg24",
            "device_mac": "aa:aa:aa:aa:aa:aa",
            "device_name": "Aggregation",
            "port_idx": 24,
            "name": "Port 24",
            "linked": True,
            "admin_enabled": True,
        },
        {
            "id": "agg25",
            "device_mac": "aa:aa:aa:aa:aa:aa",
            "device_name": "Aggregation",
            "port_idx": 25,
            "name": "Port 25",
            "linked": True,
            "admin_enabled": True,
        },
        {
            "id": "switch9",
            "device_mac": "bb:bb:bb:bb:bb:bb",
            "device_name": "Switch 2",
            "port_idx": 9,
            "name": "Port 9",
            "linked": True,
            "admin_enabled": True,
        },
        {
            "id": "switch8",
            "device_mac": "bb:bb:bb:bb:bb:bb",
            "device_name": "Switch 2",
            "port_idx": 8,
            "name": "Uplink-looking name only",
            "linked": True,
            "admin_enabled": True,
        },
    ]
    roles = policy._topology_port_roles(raw_devices)
    assert roles[("bb:bb:bb:bb:bb:bb", 9)] == "uplink"
    assert roles[("aa:aa:aa:aa:aa:aa", 25)] == "infrastructure"
    assert ("aa:aa:aa:aa:aa:aa", 24) not in roles

    enriched = policy._enrich_port_roles(normalized, raw_devices)
    by_id = {item["id"]: item for item in enriched}
    assert by_id["switch9"]["is_uplink"] is True
    assert by_id["switch9"]["infrastructure_role"] == "uplink"
    assert by_id["agg25"]["infrastructure_role"] == "infrastructure"
    assert "infrastructure_role" not in by_id["agg24"]
    assert "infrastructure_role" not in by_id["switch8"]

    port_evidence = discovery.unifi_evidence([], enriched, [])
    assert _one(port_evidence, "switch9").metadata["policy_hint"] == "required"
    assert _one(port_evidence, "agg25").metadata["policy_hint"] == "required"
    assert _one(port_evidence, "agg24").metadata["policy_hint"] == "optional"
    assert _one(port_evidence, "switch8").metadata["policy_hint"] == "optional"

    # Names and port numbers alone remain non-authoritative.
    assert policy._explicit_port_role(
        {"name": "UPLINK", "port_idx": 25}
    ) == (None, False, False)

    authoritative = policy._inventory_authority({"source_available": True})
    assert authoritative["provider"] == "unifi"
    assert authoritative["authoritative"] is True

    print(
        "UniFi Phase-2 build-7 acceptance: PASS "
        "(informational WAN omission + provider-explicit topology uplink policy)"
    )


if __name__ == "__main__":
    main()
