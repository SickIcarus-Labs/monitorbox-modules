#!/usr/bin/env python3
"""Behavioral acceptance for managed NUT v1.0.1 build 2."""

from __future__ import annotations

import asyncio
import importlib
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

NUT_PACKAGE = "com.sickicarus.monitorbox.nut-1.0.1-build2.zip"


def _install_runtime_contracts(plugin_api) -> None:
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

    old = plugin_api.IntegrationDefinition

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: Any
        connection_kinds: tuple[str, ...] = ()
        discovery: Any = None
        connection: Any = None
        validation: Any = None
        identity: Any = None
        inventory: Any = None
        presentation: Any = None
        runtime: Any = None
        runtime_executor: Any = None
        runtime_adapter_kinds: tuple[str, ...] = ()
        adoption: Any = None
        candidate_adoption: Any = None
        candidate_review: Any = None

    del old
    plugin_api.RuntimeExecutionContext = RuntimeExecutionContext
    plugin_api.RuntimeExecutionRequest = RuntimeExecutionRequest
    plugin_api.RuntimeExecutionResult = RuntimeExecutionResult
    plugin_api.IntegrationDefinition = IntegrationDefinition


class Probe:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def tcp_open(self, host: str, port: int) -> bool:
        self.calls.append(("tcp_open", host, port))
        return host == "nut-a.example.test" and port == 3493

    async def tcp_exchange(self, host: str, port: int, payload: bytes, *, limit: int):
        self.calls.append(("tcp_exchange", host, port, payload, limit))
        return b"upsd 2.8.2\n"

    async def tcp_exchange_until(self, host: str, port: int, payload: bytes, terminator: bytes, *, limit: int):
        self.calls.append(("tcp_exchange_until", host, port, payload, terminator, limit))
        return (
            b'BEGIN LIST UPS\n'
            b'UPS network_ups "Network UPS"\n'
            b'UPS server_ups "Server UPS"\n'
            b'END LIST UPS\n'
        )


def _request(plugin_api, *, system_id: str, host: str, ups: str, label: str):
    candidate = plugin_api.DiscoveryEvidence(
        plugin_id="nut",
        system_id=system_id,
        kind="nut",
        label="UPS via NUT",
        endpoint=f"{host}:3493",
        confidence=plugin_api.DiscoveryConfidence.DETECTED,
        evidence="synthetic NUT fixture",
        default_selected=True,
        values={"host": host, "port": 3493, "ups": ups},
    )
    return plugin_api.ConnectionRequest(candidate=candidate, values={"label": label, "ups": ups})


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / NUT_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed NUT package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_nut_b2")
    runtime_module = importlib.import_module("monitorbox_nut_b2.runtime")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.nut":
        raise AssertionError("managed NUT module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.1", 2):
        raise AssertionError("managed NUT runtime-fix release identity changed")
    if managed.MODULE_MANIFEST.entrypoints != {"integration": "monitorbox_nut_b2:PLUGIN"}:
        raise AssertionError("managed NUT build 2 entrypoint is not generation-safe")
    if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
        raise AssertionError("NUT runtime-fix Core floor changed")
    if managed.PLUGIN.runtime_executor is None or managed.PLUGIN.runtime_adapter_kinds != ("nut",):
        raise AssertionError("NUT build 2 does not own its runtime adapter")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        if "monitorbox_nut_b2/runtime.py" not in names:
            raise AssertionError("NUT runtime executor is not packaged")
        root_source = archive.read("monitorbox_nut_b2/__init__.py")
        runtime_source = archive.read("monitorbox_nut_b2/runtime.py")
    for forbidden in (b"run_nut", b"self._runner_factory", b"monitorbox.v2.integrations.nut"):
        if forbidden in root_source + runtime_source:
            raise AssertionError(f"NUT build 2 retained a Core-provider fallback marker: {forbidden!r}")

    context = plugin_api.FacetContext(
        site_id="lab",
        current_config={"runtime": {"local_agent": {"agent_id": "monitor"}}},
        current_revision=11,
        current_hash="nut-behavior-hash",
    )
    probe = Probe()
    integration = managed.NutIntegration()
    discovered = await integration.detect(
        plugin_api.DiscoveryRequest(system_id="power_host", label="Power host", address="nut-a.example.test"),
        context,
        probe,
    )
    if len(discovered) != 1 or discovered[0].values.get("ups_options") != [
        {"id": "network_ups", "description": "Network UPS"},
        {"id": "server_ups", "description": "Server UPS"},
    ]:
        raise AssertionError(f"NUT UPS enumeration changed: {discovered!r}")

    request_a = _request(plugin_api, system_id="power_host", host="nut-a.example.test", ups="network_ups", label="Network UPS")
    request_b = _request(plugin_api, system_id="server_host", host="nut-b.example.test", ups="server_ups", label="Server UPS")
    plan_a = integration.plan(request_a, context)
    plan_b = integration.plan(request_b, context)
    if plan_a.object_ids == plan_b.object_ids:
        raise AssertionError("distinct NUT UPS Connections collapsed to one object id")

    executor = managed.PLUGIN.runtime_executor
    execution_context = plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root="/tmp/nut-package",
        state_root="/tmp/nut-state",
    )
    await executor.start(execution_context)
    try:
        async def healthy_vars(host: str, port: int, ups: str):
            if (host, port, ups) != ("nut-a.example.test", 3493, "network_ups"):
                raise AssertionError("NUT executor changed runtime request projection")
            return {
                "ups.status": "OL",
                "battery.charge": "100",
                "ups.load": "19.5",
                "ups.model": "Synthetic UPS",
            }

        runtime_module._nut_vars = healthy_vars
        runtime_request = plugin_api.RuntimeExecutionRequest(
            check_id="network_ups",
            object_id="network_ups",
            adapter="nut",
            timeout_seconds=5,
            options={"host": "nut-a.example.test", "port": 3493, "ups": "network_ups"},
        )
        healthy = await executor.execute(runtime_request, execution_context)
        if healthy.state != "healthy" or healthy.summary != "Utility power":
            raise AssertionError(f"NUT module-owned runtime failed healthy fixture: {healthy!r}")
        if healthy.metrics.get("battery.charge") != 100.0 or healthy.metadata.get("power_source") != "utility":
            raise AssertionError(f"NUT runtime lost metrics/metadata: {healthy!r}")

        async def unavailable(*args):
            del args
            raise OSError("connection refused")

        runtime_module._nut_vars = unavailable
        lost = await executor.execute(runtime_request, execution_context)
        if lost.state != "unknown" or lost.metadata.get("failure_kind") != "monitor_dependency":
            raise AssertionError(f"NUT provider loss stopped preserving UNKNOWN truth: {lost!r}")

        # Validation must use the same module-owned executor rather than the retired
        # Core AdapterRunner.run_nut fallback.
        integration = managed.NutIntegration(executor_factory=lambda: executor)
        runtime_module._nut_vars = healthy_vars
        validated = await integration.validate(request_a, context)
        if not validated.accepted or validated.state != "healthy":
            raise AssertionError(f"NUT module-owned validation failed: {validated!r}")
        if validated.metadata.get("runtime_executor") != "module_owned":
            raise AssertionError("NUT validation lost module-owned runtime provenance")
    finally:
        await executor.close(execution_context)


def main() -> None:
    asyncio.run(accept())
    print("managed NUT behavioral acceptance: PASS")


if __name__ == "__main__":
    main()
