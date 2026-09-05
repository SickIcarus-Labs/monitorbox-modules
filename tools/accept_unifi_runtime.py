#!/usr/bin/env python3
"""Behavioral/runtime acceptance for managed UniFi Network v1.0.0 build 1."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.0-build1.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b1"


def _install_unifi_contracts(plugin_api) -> None:
    model = sys.modules["monitorbox.v2.model"]

    class State(str, Enum):
        HEALTHY = "healthy"
        DEGRADED = "degraded"
        UNKNOWN = "unknown"
        UNAVAILABLE = "unavailable"
        FAILED = "failed"
        OFFLINE = "offline"

    model.State = State

    @dataclass(frozen=True)
    class RuntimeExecutionContext:
        module_id: str
        package_root: str
        state_root: str

    @dataclass(frozen=True)
    class RuntimeExecutionRequest:
        check_id: str
        object_id: str
        adapter: str
        timeout_seconds: float
        options: Mapping[str, Any] = field(default_factory=dict)
        agent_id: str | None = None
        capability_id: str | None = None
        capability_kind: str | None = None

    @dataclass(frozen=True)
    class RuntimeExecutionResult:
        state: str
        summary: str
        duration_ms: float
        metrics: Mapping[str, float] = field(default_factory=dict)
        metadata: Mapping[str, Any] = field(default_factory=dict)

        def public(self) -> dict[str, Any]:
            return {
                "state": self.state,
                "summary": self.summary,
                "duration_ms": self.duration_ms,
                "metrics": dict(self.metrics),
                "metadata": dict(self.metadata),
            }

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: Any
        connection_kinds: tuple[str, ...] = ()
        runtime_adapter_kinds: tuple[str, ...] = ()
        discovery: Any = None
        connection: Any = None
        validation: Any = None
        identity: Any = None
        inventory: Any = None
        presentation: Any = None
        runtime: Any = None
        runtime_executor: Any = None
        adoption: Any = None
        candidate_adoption: Any = None
        candidate_review: Any = None

    for value in (
        RuntimeExecutionContext,
        RuntimeExecutionRequest,
        RuntimeExecutionResult,
        IntegrationDefinition,
    ):
        setattr(plugin_api, value.__name__, value)

    discovery = ModuleType("monitorbox.v2.discovery")

    @dataclass(frozen=True)
    class DiscoveryEvidence:
        source: str
        source_id: str
        kind: str
        label: str
        addresses: tuple[str, ...] = ()
        mac: str | None = None
        confidence: int = 0
        suggested_capabilities: tuple[str, ...] = ()
        metadata: Mapping[str, Any] = field(default_factory=dict)

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
                "metadata": dict(self.metadata),
            }

    @dataclass(frozen=True)
    class DiscoveryCandidate:
        kind: str
        evidence: tuple[DiscoveryEvidence, ...]

    discovery.DiscoveryEvidence = DiscoveryEvidence
    discovery.DiscoveryCandidate = DiscoveryCandidate
    sys.modules["monitorbox.v2.discovery"] = discovery


def _runtime_request(plugin_api, *, operation: str = "port_state"):
    return plugin_api.RuntimeExecutionRequest(
        check_id="unifi_port_state",
        object_id="switch_port",
        adapter="unifi",
        timeout_seconds=1.0,
        options={
            "base_url": "https://unifi.example.test",
            "site": "default",
            "username_env": "UNIFI_USER",
            "password_env": "UNIFI_PASSWORD",
            "verify_tls": False,
            "operation": operation,
            "device_mac": "aa:bb:cc:dd:ee:02",
            "port_idx": 7,
        },
    )


def _link_inventory(*, capacities: bool) -> list[dict[str, Any]]:
    child_uplink: dict[str, Any] = {
        "uplink_mac": "aa:bb:cc:dd:ee:01",
        "port_idx": 1,
        "uplink_remote_port": 7,
    }
    if capacities:
        child_uplink["max_speed"] = 10000
    parent_port: dict[str, Any] = {"port_idx": 7}
    if capacities:
        parent_port["media"] = "10GE"
    return [
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "name": "Core Switch",
            "port_table": [parent_port],
        },
        {
            "mac": "aa:bb:cc:dd:ee:02",
            "name": "Access Switch",
            "uplink": child_uplink,
            "port_table": [{"port_idx": 1}],
        },
    ]


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed UniFi package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_unifi_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)
    vertical = importlib.import_module(f"{IMPORT_PACKAGE}.vertical_runtime")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.unifi":
        raise AssertionError("managed UniFi durable module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed UniFi release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.display_name != "UniFi Network Integration":
        raise AssertionError("managed UniFi product identity changed")
    if manifest.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("managed UniFi manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed UniFi Core compatibility changed")
    if manifest.state_schema != 1:
        raise AssertionError("managed UniFi state schema changed")
    if managed.PLUGIN.metadata.plugin_id != "unifi":
        raise AssertionError("managed UniFi provider identity changed")
    if managed.PLUGIN.metadata.display_name != "UniFi Network":
        raise AssertionError("managed UniFi display name changed")
    if managed.PLUGIN.runtime_adapter_kinds != ("unifi",):
        raise AssertionError("managed UniFi stopped claiming only the unifi runtime adapter")
    if managed.PLUGIN.candidate_adoption is None:
        raise AssertionError("managed UniFi lost provider-owned candidate adoption")

    context = plugin_api.FacetContext(
        site_id="lab",
        current_config={
            "sites": [{"id": "lab", "objects": []}],
            "runtime": {"local_agent": {"agent_id": "monitor"}},
        },
        current_revision=23,
        current_hash="unifi-acceptance-hash",
    )
    candidate = plugin_api.DiscoveryEvidence(
        plugin_id="unifi",
        system_id="unifi_controller",
        kind="unifi",
        label="UniFi Network",
        endpoint="https://unifi.example.test",
        confidence=plugin_api.DiscoveryConfidence.DETECTED,
        evidence="synthetic UniFi fixture",
        default_selected=True,
        values={
            "base_url": "https://unifi.example.test",
            "network_site": "default",
            "verify_tls": False,
        },
    )
    request = plugin_api.ConnectionRequest(
        candidate=candidate,
        values={
            "label": "UniFi Network",
            "username": "monitorbox",
            "password": "acceptance-secret",
            "network_site": "default",
            "verify_tls": False,
        },
    )
    plan = managed.UniFiIntegration().plan(request, context)
    if plan.expected_revision != 23 or plan.expected_config_hash != "unifi-acceptance-hash":
        raise AssertionError("UniFi connection plan lost optimistic transaction guards")
    if len(plan.operations) != 1 or len(plan.secret_writes) != 2:
        raise AssertionError("UniFi connection plan stopped brokering both credentials")
    provider = plan.operations[0].object_data["capabilities"][0]["providers"][0]
    if provider["adapter"] != "unifi" or provider["id"] != "unifi":
        raise AssertionError("UniFi canonical provider identity changed")
    if provider["config"]["site"] != "default":
        raise AssertionError("UniFi canonical Network site binding changed")
    if "acceptance-secret" in json.dumps(plan.public(), sort_keys=True):
        raise AssertionError("UniFi public connection plan leaked protected credentials")

    ports = vertical.normalize_unifi_ports(
        [
            {
                "mac": "AA:BB:CC:DD:EE:02",
                "name": "Access Switch",
                "port_table": [
                    {"port_idx": 7, "name": "Server", "up": True, "speed": 2500},
                    {"port_idx": 8, "name": "Spare", "up": False, "speed": 0},
                ],
            }
        ]
    )
    if len(ports) != 2 or ports[0]["id"] != "unifi_port_aabbccddee02_7":
        raise AssertionError(f"UniFi stable port normalization changed: {ports!r}")
    if not ports[0]["linked"] or ports[0]["speed_mbps"] != 2500.0:
        raise AssertionError("UniFi linked-port truth changed")
    if ports[1]["linked"]:
        raise AssertionError("UniFi unlinked-port truth changed")

    with tempfile.TemporaryDirectory(prefix="monitorbox-unifi-state-") as temp:
        state_root = Path(temp) / "state"
        runtime_context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root="/tmp/unifi-package",
            state_root=str(state_root),
        )
        first = managed.UniFiRuntimeExecutor()
        learned = first._derive_expectations(_link_inventory(capacities=True), {}, runtime_context)
        if learned.get("aa:bb:cc:dd:ee:02") != 10000:
            raise AssertionError(f"UniFi failed to learn 10Gb uplink expectation: {learned!r}")
        state_file = state_root / "link-expectations.json"
        if not state_file.is_file():
            raise AssertionError("UniFi restore-required link expectation state was not persisted")

        second = managed.UniFiRuntimeExecutor()
        recovered = second._derive_expectations(_link_inventory(capacities=False), {}, runtime_context)
        if recovered.get("aa:bb:cc:dd:ee:02") != 10000:
            raise AssertionError(
                f"UniFi state did not survive executor restart/recreate: {recovered!r}"
            )

        wrong_id_context = plugin_api.RuntimeExecutionContext(
            module_id="com.sickicarus.monitorbox.unifi-network",
            package_root="/tmp/unifi-package",
            state_root=str(Path(temp) / "different-module-id-state"),
        )
        isolated = managed.UniFiRuntimeExecutor()._derive_expectations(
            _link_inventory(capacities=False), {}, wrong_id_context
        )
        if isolated:
            raise AssertionError("UniFi state unexpectedly crossed module-id state roots")

    executor = managed.UniFiRuntimeExecutor()

    async def controller_unavailable(options, path):
        del options, path
        raise RuntimeError("controller unavailable")

    executor._get = controller_unavailable
    lost = await executor.execute(_runtime_request(plugin_api), plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root="/tmp/unifi-package",
        state_root="/tmp/unifi-state",
    ))
    if lost.state != "unknown":
        raise AssertionError(f"UniFi provider loss stopped being UNKNOWN: {lost!r}")
    if lost.metadata.get("failure_kind") != "monitor_dependency" or lost.metadata.get("authoritative") is not False:
        raise AssertionError(f"UniFi provider-loss truth changed: {lost.metadata!r}")

    async def unlinked_port(options, path):
        del options, path
        return {
            "data": [
                {
                    "mac": "aa:bb:cc:dd:ee:02",
                    "name": "Access Switch",
                    "port_table": [
                        {"port_idx": 7, "name": "Server", "up": False, "speed": 0}
                    ],
                }
            ]
        }

    executor._get = unlinked_port
    failed = await executor.execute(_runtime_request(plugin_api), plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root="/tmp/unifi-package",
        state_root="/tmp/unifi-state",
    ))
    if failed.state != "failed" or "no link" not in failed.summary.casefold():
        raise AssertionError(f"actionable UniFi switch-port failure was neutralized: {failed!r}")

    print(
        "Managed UniFi Network 1.0.0 build 1: identity + credential brokering + port truth + "
        "durable same-ID state + provider-loss UNKNOWN: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
