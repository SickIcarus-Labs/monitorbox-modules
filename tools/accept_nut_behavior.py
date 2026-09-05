#!/usr/bin/env python3
"""Behavioral acceptance for managed NUT v1.0.0 build 1.

The immutable source blob is byte-identical to certified Core 0556. This harness
supplies only provider-blind Core interfaces and synthetic NUT evidence so the
public module repository can verify the managed artifact without private Core
source or live UPS infrastructure.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from accept_http_behavior import install_core_contract_stubs

NUT_PACKAGE = "com.sickicarus.monitorbox.nut-1.0.0-build1.zip"


@dataclass
class Observation:
    state: Any
    summary: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }


class Runner:
    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self.started = False
        self.closed = False
        self.check = None

    async def start(self) -> None:
        self.started = True

    async def run(self, check):
        if not self.started:
            raise AssertionError("NUT validation runner was not started")
        self.check = check
        return self.observation

    async def close(self) -> None:
        self.closed = True


class Probe:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def tcp_open(self, host: str, port: int) -> bool:
        self.calls.append(("tcp_open", host, port))
        return host == "nut-a.example.test" and port == 3493

    async def tcp_exchange(self, host: str, port: int, payload: bytes, *, limit: int):
        self.calls.append(("tcp_exchange", host, port, payload, limit))
        return b"upsd 2.8.2\n"

    async def tcp_exchange_until(
        self,
        host: str,
        port: int,
        payload: bytes,
        terminator: bytes,
        *,
        limit: int,
    ):
        self.calls.append(
            ("tcp_exchange_until", host, port, payload, terminator, limit)
        )
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
    return plugin_api.ConnectionRequest(
        candidate=candidate,
        values={"label": label, "ups": ups},
    )


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / NUT_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed NUT package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    model = sys.modules["monitorbox.v2.model"]
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_nut_b1")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.nut":
        raise AssertionError("managed NUT module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed NUT release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.entrypoints != {"integration": "monitorbox_nut_b1:PLUGIN"}:
        raise AssertionError("managed NUT manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed NUT Core compatibility changed")

    with zipfile.ZipFile(package) as archive:
        source = archive.read("monitorbox_nut_b1/__init__.py")
    for required in (b'b"VER\\n"', b'b"LIST UPS\\n"'):
        if required not in source:
            raise AssertionError(f"NUT read-only discovery marker missing: {required!r}")
    for forbidden in (b"SET VAR ", b"INSTCMD ", b"USERNAME ", b"PASSWORD "):
        if forbidden in source:
            raise AssertionError(f"NUT managed source gained a mutating/auth command: {forbidden!r}")

    context = plugin_api.FacetContext(
        site_id="lab",
        current_config={"runtime": {"local_agent": {"agent_id": "monitor"}}},
        current_revision=11,
        current_hash="nut-behavior-hash",
    )

    probe = Probe()
    integration = managed.NutIntegration()
    discovered = await integration.detect(
        plugin_api.DiscoveryRequest(
            system_id="power_host",
            label="Power host",
            address="nut-a.example.test",
        ),
        context,
        probe,
    )
    if len(discovered) != 1:
        raise AssertionError(f"expected one NUT discovery candidate, got {len(discovered)}")
    evidence = discovered[0]
    if evidence.confidence != plugin_api.DiscoveryConfidence.DETECTED:
        raise AssertionError("NUT discovery confidence changed")
    if evidence.values.get("ups_options") != [
        {"id": "network_ups", "description": "Network UPS"},
        {"id": "server_ups", "description": "Server UPS"},
    ]:
        raise AssertionError(f"NUT UPS enumeration changed: {evidence.values!r}")
    if "ups" in evidence.values:
        raise AssertionError("multi-UPS discovery must not silently select one UPS")

    expected_calls = [
        ("tcp_open", "nut-a.example.test", 3493),
        ("tcp_exchange", "nut-a.example.test", 3493, b"VER\n", 4096),
        (
            "tcp_exchange_until",
            "nut-a.example.test",
            3493,
            b"LIST UPS\n",
            b"END LIST UPS\n",
            65536,
        ),
    ]
    if probe.calls != expected_calls:
        raise AssertionError(f"NUT bounded discovery contract changed: {probe.calls!r}")

    request_a = _request(
        plugin_api,
        system_id="power_host",
        host="nut-a.example.test",
        ups="network_ups",
        label="Network UPS",
    )
    request_b = _request(
        plugin_api,
        system_id="server_host",
        host="nut-b.example.test",
        ups="server_ups",
        label="Server UPS",
    )

    plan_a = integration.plan(request_a, context)
    plan_b = integration.plan(request_b, context)
    if plan_a.expected_revision != 11 or plan_a.expected_config_hash != "nut-behavior-hash":
        raise AssertionError("NUT plan lost optimistic transaction guards")
    if plan_a.object_ids == plan_b.object_ids:
        raise AssertionError("distinct NUT UPS Connections collapsed to one object id")
    provider_a = plan_a.operations[0].object_data["capabilities"][0]["providers"][0]
    provider_b = plan_b.operations[0].object_data["capabilities"][0]["providers"][0]
    if provider_a["config"] != {
        "host": "nut-a.example.test",
        "port": 3493,
        "ups": "network_ups",
    }:
        raise AssertionError(f"first NUT provider config changed: {provider_a!r}")
    if provider_b["config"] != {
        "host": "nut-b.example.test",
        "port": 3493,
        "ups": "server_ups",
    }:
        raise AssertionError(f"second NUT provider config changed: {provider_b!r}")
    if provider_a["adapter"] != "nut" or provider_b["adapter"] != "nut":
        raise AssertionError("NUT plans stopped targeting the shared bounded NUT adapter")

    runtime_a = integration.build_runtime_intent(request_a, context)
    runtime_b = integration.build_runtime_intent(request_b, context)
    if runtime_a.checks[0]["config"] == runtime_b.checks[0]["config"]:
        raise AssertionError("distinct NUT runtime intents collapsed")
    if runtime_a.checks[0]["agent_id"] != "monitor":
        raise AssertionError("NUT runtime intent lost local-agent ownership")

    ids_a = integration.identities(request_a.candidate, context)
    ids_b = integration.identities(request_b.candidate, context)
    if ids_a[0].namespace != "nut-ups" or ids_b[0].namespace != "nut-ups":
        raise AssertionError("NUT UPS identity namespace changed")
    if ids_a[0].value == ids_b[0].value:
        raise AssertionError("distinct NUT endpoint/UPS identities collapsed")

    unknown_runner = Runner(
        Observation(
            model.State.UNKNOWN,
            "NUT monitoring unavailable: connection refused",
            {"failure_kind": "monitor_dependency", "nut_host": "nut-a.example.test"},
        )
    )
    unavailable = managed.NutIntegration(runner_factory=lambda: unknown_runner)
    result = await unavailable.validate(request_a, context)
    if result.accepted or result.state != "unknown":
        raise AssertionError("NUT provider loss stopped preserving UNKNOWN truth")
    if result.observation.get("metadata", {}).get("failure_kind") != "monitor_dependency":
        raise AssertionError("NUT provider-loss diagnostics were discarded")
    if not unknown_runner.closed:
        raise AssertionError("NUT validation runner was not closed")
    if unknown_runner.check.adapter != "nut":
        raise AssertionError("NUT validation stopped using the bounded NUT adapter")

    healthy_runner = Runner(
        Observation(
            model.State.HEALTHY,
            "Utility power",
            {"power_source": "utility", "nut_ups": "network_ups"},
        )
    )
    healthy = managed.NutIntegration(runner_factory=lambda: healthy_runner)
    result = await healthy.validate(request_a, context)
    if not result.accepted or result.state != "healthy":
        raise AssertionError("healthy NUT validation stopped being accepted")

    incomplete = managed._parse_complete_nut_ups(
        b'BEGIN LIST UPS\nUPS network_ups "Network UPS"\n'
    )
    if incomplete:
        raise AssertionError("incomplete NUT UPS inventory must not be treated as authoritative")


def main() -> None:
    asyncio.run(accept())
    print("managed NUT behavioral acceptance: PASS")


if __name__ == "__main__":
    main()
