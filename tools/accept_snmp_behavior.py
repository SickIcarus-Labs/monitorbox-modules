#!/usr/bin/env python3
"""Behavioral acceptance for managed SNMP v1.0.0 build 1.

The immutable source blob is byte-identical to accepted MonitorBox Core 0547 and
0556. This harness supplies only provider-blind Core interfaces and synthetic
SNMP evidence so the public module repository can verify credential/reference,
validation, runtime-intent, provider-loss, and bounded-discovery behavior
without private Core source or live SNMP infrastructure.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

SNMP_PACKAGE = "com.sickicarus.monitorbox.snmp-1.0.0-build1.zip"
COMMUNITY = "snmp-community-secret-must-not-leak"
USERNAME = "snmpv3-user-secret-must-not-leak"
AUTH_PASSWORD = "snmpv3-auth-secret-must-not-leak"
PRIVACY_PASSWORD = "snmpv3-privacy-secret-must-not-leak"


@dataclass(frozen=True)
class AddCapabilityIntent:
    site_id: str
    object_id: str
    capability_data: Mapping[str, Any]


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


class SequencedRunner:
    def __init__(self, observations: list[Observation]) -> None:
        self.observations = list(observations)
        self.started = False
        self.closed = False
        self.checks: list[Any] = []
        self.env_snapshots: list[dict[str, str | None]] = []

    async def start(self) -> None:
        self.started = True

    async def run(self, check):
        if not self.started:
            raise AssertionError("SNMP validation runner was not started")
        self.checks.append(check)
        snapshot: dict[str, str | None] = {}
        for key, value in check.options.items():
            if key.endswith("_env") and isinstance(value, str):
                snapshot[key] = os.environ.get(value)
        self.env_snapshots.append(snapshot)
        if not self.observations:
            raise AssertionError("SNMP validation ran more checks than expected")
        return self.observations.pop(0)

    async def close(self) -> None:
        self.closed = True


class Probe:
    def __init__(self, capable: bool | None) -> None:
        self.capable = capable
        self.calls: list[tuple[str, str, int]] = []

    async def snmp_v3_capable(self, host: str, port: int) -> bool | None:
        self.calls.append(("snmp_v3_capable", host, port))
        return self.capable


def _candidate(plugin_api, *, mode: str, system_id: str = "goliath"):
    return plugin_api.DiscoveryEvidence(
        plugin_id="snmp",
        system_id=system_id,
        kind="snmp",
        label="SNMP",
        endpoint="udp://10.0.0.10:161",
        confidence=plugin_api.DiscoveryConfidence.POSSIBLE,
        evidence="synthetic SNMP fixture",
        default_selected=False,
        values={"host": "10.0.0.10", "port": 161, "snmp_mode": mode},
    )


def _community_request(plugin_api, *, validated_version: str = "2c"):
    return plugin_api.ConnectionRequest(
        candidate=_candidate(plugin_api, mode="community"),
        values={"community": COMMUNITY, "validated_version": validated_version},
    )


def _v3_request(plugin_api, **overrides):
    values = {
        "username": USERNAME,
        "auth_password": AUTH_PASSWORD,
        "auth_protocol": "SHA",
        "privacy_password": PRIVACY_PASSWORD,
        "privacy_protocol": "AES",
    }
    values.update(overrides)
    return plugin_api.ConnectionRequest(
        candidate=_candidate(plugin_api, mode="v3"),
        values=values,
    )


def _assert_no_secret(value: Any, where: str) -> None:
    rendered = json.dumps(value, sort_keys=True, default=str)
    for secret in (COMMUNITY, USERNAME, AUTH_PASSWORD, PRIVACY_PASSWORD):
        if secret in rendered:
            raise AssertionError(f"{where} leaked protected SNMP material")


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / SNMP_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed SNMP package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    plugin_api.AddCapabilityIntent = AddCapabilityIntent
    model = sys.modules["monitorbox.v2.model"]
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_snmp_b1")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.snmp":
        raise AssertionError("managed SNMP module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed SNMP release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.entrypoints != {"integration": "monitorbox_snmp_b1:PLUGIN"}:
        raise AssertionError("managed SNMP manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed SNMP Core compatibility changed")

    with zipfile.ZipFile(package) as archive:
        source = archive.read("monitorbox_snmp_b1/__init__.py")
    required_source = (
        b"await probe.snmp_v3_capable(host, 161)",
        b'versions = ("2c", "1")',
        b'"sys_uptime": ".1.3.6.1.2.1.1.3.0"',
        b'"adapter": "snmp"',
        b'"timeout_seconds": 10',
    )
    missing = [marker for marker in required_source if marker not in source]
    if missing:
        raise AssertionError(f"SNMP bounded/provider-local contract markers missing: {missing!r}")
    for forbidden in (b"qnap", b"QNAP", b"zpool", b"subprocess", b"snmpwalk"):
        if forbidden in source:
            raise AssertionError(f"SNMP package gained out-of-bound provider/shell behavior: {forbidden!r}")

    context = plugin_api.FacetContext(
        site_id="lab",
        current_config={"runtime": {"local_agent": {"agent_id": "monitor"}}},
        current_revision=19,
        current_hash="snmp-behavior-hash",
    )
    integration = managed.SnmpIntegration()

    v3_probe = Probe(True)
    discovered = await integration.detect(
        plugin_api.DiscoveryRequest(
            system_id="goliath",
            label="Goliath",
            address="10.0.0.10",
        ),
        context,
        v3_probe,
    )
    if len(discovered) != 1:
        raise AssertionError(f"expected one SNMPv3 discovery candidate, got {len(discovered)}")
    v3_evidence = discovered[0]
    if (
        v3_evidence.confidence != plugin_api.DiscoveryConfidence.DETECTED
        or not v3_evidence.default_selected
        or v3_evidence.values.get("snmp_mode") != "v3"
    ):
        raise AssertionError("positive SNMPv3 discovery semantics changed")
    if v3_probe.calls != [("snmp_v3_capable", "10.0.0.10", 161)]:
        raise AssertionError(f"SNMPv3 discovery stopped being one bounded probe: {v3_probe.calls!r}")

    community_probe = Probe(False)
    discovered = await integration.detect(
        plugin_api.DiscoveryRequest(
            system_id="goliath",
            label="Goliath",
            address="10.0.0.10",
        ),
        context,
        community_probe,
    )
    fallback = discovered[0]
    if (
        fallback.confidence != plugin_api.DiscoveryConfidence.POSSIBLE
        or fallback.default_selected
        or fallback.values.get("snmp_mode") != "community"
    ):
        raise AssertionError("SNMP community fallback discovery semantics changed")
    if community_probe.calls != [("snmp_v3_capable", "10.0.0.10", 161)]:
        raise AssertionError("SNMP community fallback performed unexpected discovery work")

    community_request = _community_request(plugin_api)
    plan = integration.plan(community_request, context)
    if plan.expected_revision != 19 or plan.expected_config_hash != "snmp-behavior-hash":
        raise AssertionError("SNMP plan lost optimistic transaction guards")
    if len(plan.operations) != 1 or not isinstance(plan.operations[0], AddCapabilityIntent):
        raise AssertionError("SNMP plan stopped attaching one capability to the declared System")
    if len(plan.secret_writes) != 1 or plan.secret_writes[0].value != COMMUNITY:
        raise AssertionError("SNMP community plan stopped emitting one credential-broker write")
    _assert_no_secret(plan.public(), "SNMP community public plan")

    capability = plan.operations[0].capability_data
    provider = capability["providers"][0]
    expected_config = {
        "host": "10.0.0.10",
        "port": 161,
        "oids": {"sys_uptime": ".1.3.6.1.2.1.1.3.0"},
        "version": "2c",
        "community_env": "MONITORBOX_GOLIATH_SNMP_COMMUNITY",
    }
    if provider["adapter"] != "snmp" or provider["config"] != expected_config:
        raise AssertionError(f"SNMP community provider config changed: {provider!r}")
    if provider["interval_seconds"] != 30 or provider["timeout_seconds"] != 10:
        raise AssertionError("SNMP polling cadence/bound changed")
    _assert_no_secret(capability, "SNMP canonical capability")

    runtime = integration.build_runtime_intent(community_request, context)
    if runtime.plugin_id != "snmp" or len(runtime.checks) != 1:
        raise AssertionError("SNMP runtime intent shape changed")
    runtime_check = runtime.checks[0]
    if runtime_check["adapter"] != "snmp" or runtime_check["agent_id"] != "monitor":
        raise AssertionError("SNMP runtime intent lost shared adapter/local-agent ownership")
    if runtime_check["config"] != expected_config:
        raise AssertionError("SNMP runtime intent diverged from canonical credential references")
    _assert_no_secret(runtime_check, "SNMP runtime intent")

    identities = integration.identities(community_request.candidate, context)
    if len(identities) != 1 or identities[0].namespace != "snmp-endpoint":
        raise AssertionError("SNMP identity namespace changed")
    if identities[0].value != "10.0.0.10:161":
        raise AssertionError("SNMP endpoint identity changed")

    fallback_runner = SequencedRunner(
        [
            Observation(
                model.State.UNKNOWN,
                f"v2c rejected community {COMMUNITY}",
                {"failure_kind": "monitor_dependency", "detail": COMMUNITY},
            ),
            Observation(model.State.HEALTHY, "SNMPv1 healthy", {"transport": "snmp"}),
        ]
    )
    validating = managed.SnmpIntegration(runner_factory=lambda: fallback_runner)
    result = await validating.validate(community_request, context)
    if not result.accepted or result.state != "healthy":
        raise AssertionError("SNMPv1 fallback stopped accepting a healthy observation")
    if result.metadata.get("attempted_versions") != ["2c", "1"]:
        raise AssertionError(f"SNMP community version order changed: {result.metadata!r}")
    if result.observation.get("metadata", {}).get("snmp_validated_version") != "1":
        raise AssertionError("SNMPv1 fallback stopped recording the validated version")
    if result.values.get("validated_version") != "1":
        raise AssertionError("SNMPv1 validated version stopped flowing into planned values")
    if not str(result.summary).startswith("SNMPv1 validated after SNMPv2c failed:"):
        raise AssertionError("SNMPv1 fallback summary lost explicit provenance")
    _assert_no_secret(result.__dict__, "SNMP validation result")
    if [check.options.get("version") for check in fallback_runner.checks] != ["2c", "1"]:
        raise AssertionError("SNMP community validation no longer isolates v2c and v1 attempts")
    if any(check.adapter != "snmp" or check.timeout_seconds != 10 for check in fallback_runner.checks):
        raise AssertionError("SNMP validation stopped using the bounded shared SNMP adapter")
    if [snap.get("community_env") for snap in fallback_runner.env_snapshots] != [COMMUNITY, COMMUNITY]:
        raise AssertionError("SNMP community validation did not bind the temporary secret for each attempt")
    if not fallback_runner.closed:
        raise AssertionError("SNMP community validation runner was not closed")
    for check in fallback_runner.checks:
        env_name = check.options["community_env"]
        if env_name in os.environ:
            raise AssertionError("temporary SNMP onboarding credential survived validation")

    loss_runner = SequencedRunner(
        [
            Observation(
                model.State.UNKNOWN,
                "SNMP monitoring unavailable",
                {"failure_kind": "monitor_dependency"},
            ),
            Observation(
                model.State.UNKNOWN,
                "SNMP monitoring unavailable",
                {"failure_kind": "monitor_dependency"},
            ),
        ]
    )
    unavailable = managed.SnmpIntegration(runner_factory=lambda: loss_runner)
    lost = await unavailable.validate(community_request, context)
    if lost.accepted or lost.state != "unknown":
        raise AssertionError("SNMP provider loss stopped preserving UNKNOWN truth")
    if lost.observation.get("metadata", {}).get("failure_kind") != "monitor_dependency":
        raise AssertionError("SNMP provider-loss diagnostics were discarded")
    if lost.metadata.get("attempted_versions") != ["2c", "1"]:
        raise AssertionError("SNMP provider loss stopped reporting attempted community versions")

    v3_request = _v3_request(plugin_api)
    v3_plan = integration.plan(v3_request, context)
    if len(v3_plan.secret_writes) != 3:
        raise AssertionError("SNMPv3 authPriv plan must emit username/auth/privacy secret writes")
    v3_config = v3_plan.operations[0].capability_data["providers"][0]["config"]
    expected_v3 = {
        "host": "10.0.0.10",
        "port": 161,
        "oids": {"sys_uptime": ".1.3.6.1.2.1.1.3.0"},
        "version": "3",
        "username_env": "MONITORBOX_GOLIATH_SNMP_USERNAME",
        "auth_password_env": "MONITORBOX_GOLIATH_SNMP_AUTH_PASSWORD",
        "auth_protocol": "SHA",
        "privacy_password_env": "MONITORBOX_GOLIATH_SNMP_PRIVACY_PASSWORD",
        "privacy_protocol": "AES",
    }
    if v3_config != expected_v3:
        raise AssertionError(f"SNMPv3 credential/reference config changed: {v3_config!r}")
    _assert_no_secret(v3_plan.public(), "SNMPv3 public plan")
    _assert_no_secret(v3_plan.operations[0].capability_data, "SNMPv3 canonical capability")

    v3_runner = SequencedRunner(
        [Observation(model.State.HEALTHY, "SNMPv3 healthy", {"transport": "snmp"})]
    )
    validating_v3 = managed.SnmpIntegration(runner_factory=lambda: v3_runner)
    v3_result = await validating_v3.validate(v3_request, context)
    if not v3_result.accepted or v3_result.state != "healthy":
        raise AssertionError("healthy SNMPv3 validation stopped being accepted")
    if v3_result.metadata.get("attempted_versions") != [] or len(v3_runner.checks) != 1:
        raise AssertionError("SNMPv3 validation unexpectedly entered community fallback")
    if v3_runner.env_snapshots != [
        {
            "username_env": USERNAME,
            "auth_password_env": AUTH_PASSWORD,
            "privacy_password_env": PRIVACY_PASSWORD,
        }
    ]:
        raise AssertionError(f"SNMPv3 temporary credential bindings changed: {v3_runner.env_snapshots!r}")
    _assert_no_secret(v3_result.__dict__, "SNMPv3 validation result")
    for env_name in (
        v3_runner.checks[0].options["username_env"],
        v3_runner.checks[0].options["auth_password_env"],
        v3_runner.checks[0].options["privacy_password_env"],
    ):
        if env_name in os.environ:
            raise AssertionError("temporary SNMPv3 onboarding credential survived validation")

    bad_v3 = _v3_request(plugin_api, auth_password="", privacy_password=PRIVACY_PASSWORD)
    try:
        integration.plan(bad_v3, context)
    except ValueError as exc:
        if "privacy requires an authentication password" not in str(exc):
            raise AssertionError(f"unexpected SNMPv3 privacy validation error: {exc}") from exc
    else:
        raise AssertionError("SNMPv3 privacy without authentication was accepted")

    presentation = integration.describe(context)
    fields = {item.key: item for item in presentation.fields}
    for key in ("community", "username", "auth_password", "privacy_password"):
        if not fields[key].secret:
            raise AssertionError(f"SNMP credential field {key!r} is no longer marked secret")
    if presentation.provenance_keys != (
        "transport",
        "snmp_attempted_versions",
        "snmp_validated_version",
    ):
        raise AssertionError("SNMP presentation provenance contract changed")


def main() -> None:
    asyncio.run(accept())
    print("managed SNMP behavioral acceptance: PASS")


if __name__ == "__main__":
    main()
