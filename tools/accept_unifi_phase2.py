#!/usr/bin/env python3
"""Phase-2 acceptance for UniFi WAN and switch-port recommendation semantics."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DELTA = ROOT / "sources" / "unifi" / "1.0.4-build5"


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
        DELTA / "discovery.py",
    )
    policy = _load(
        "candidate.integrations.unifi.phase2_policy",
        DELTA / "phase2_policy.py",
    )

    health = [
        {"subsystem": "wan", "wan_ip": "108.85.13.175"},
        {"subsystem": "lan", "ip": "192.168.3.1"},
    ]
    devices = [
        {
            "id": "gateway",
            "name": "Gateway",
            "ip": "108.85.13.175",
            "mac": "00:11:22:33:44:55",
            "connected": True,
        },
        {
            "id": "switch",
            "name": "Switch",
            "ip": "192.168.3.2",
            "mac": "00:11:22:33:44:66",
            "connected": True,
        },
        {
            "id": "manual-public",
            "name": "Public device",
            "ip": "203.0.113.40",
            "mac": "00:11:22:33:44:77",
            "connected": True,
        },
    ]
    ports = [
        {
            "id": "unifi_port_switch_1",
            "device_mac": "00:11:22:33:44:66",
            "device_name": "Switch",
            "port_idx": 1,
            "name": "Port 1",
            "linked": True,
            "admin_enabled": True,
            "is_uplink": True,
        },
        {
            "id": "unifi_port_switch_2",
            "device_mac": "00:11:22:33:44:66",
            "device_name": "Switch",
            "port_idx": 2,
            "name": "Port 2",
            "linked": True,
            "admin_enabled": True,
            "is_uplink": False,
        },
        {
            "id": "unifi_port_switch_3",
            "device_mac": "00:11:22:33:44:66",
            "device_name": "Switch",
            "port_idx": 3,
            "name": "Port 3",
            "linked": False,
            "admin_enabled": False,
            "is_uplink": False,
        },
    ]
    evidence = discovery.unifi_evidence(devices, ports, health)

    wan = _one(evidence, "gateway")
    assert wan.addresses == ()
    assert "reachability" not in wan.suggested_capabilities
    assert wan.metadata["wan_interface_address"] == "108.85.13.175"
    assert wan.metadata["reachability_suppression_reason"] == "wan_interface_address"

    lan = _one(evidence, "switch")
    assert lan.addresses == ("192.168.3.2",)
    assert "reachability" in lan.suggested_capabilities

    # Public/private range is not the policy boundary. A public address not
    # semantically identified as WAN remains eligible for explicit discovery.
    public = _one(evidence, "manual-public")
    assert public.addresses == ("203.0.113.40",)
    assert "reachability" in public.suggested_capabilities

    uplink = _one(evidence, "unifi_port_switch_1")
    access = _one(evidence, "unifi_port_switch_2")
    disabled = _one(evidence, "unifi_port_switch_3")
    assert uplink.metadata["policy_hint"] == "required"
    assert uplink.metadata["initial_importance"] == "required"
    assert uplink.metadata["always_up_expectation"] is True
    assert access.metadata["policy_hint"] == "optional"
    assert access.metadata["initial_importance"] == "not_required"
    assert access.metadata["always_up_expectation"] is False
    assert disabled.metadata["policy_hint"] == "optional"
    assert disabled.metadata["initial_importance"] == "ignored"

    # Explicit role metadata can promote trunk/LAG semantics; names and port
    # numbers alone cannot.
    assert policy._explicit_port_role({"name": "TRUNK MAYBE", "port_idx": 48}) == (None, False, False)
    assert policy._explicit_port_role({"is_trunk": True}) == ("trunk", True, False)
    assert policy._explicit_port_role({"aggregate_num_ports": 2}) == ("lag", False, True)

    print(
        "UniFi Phase-2 acceptance: PASS "
        "(semantic WAN suppression + LAN/public preservation + expectation-aware port policy)"
    )


if __name__ == "__main__":
    main()
