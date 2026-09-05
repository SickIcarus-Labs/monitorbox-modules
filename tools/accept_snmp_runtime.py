#!/usr/bin/env python3
"""Runtime acceptance for managed SNMP v1.0.2 build 3."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.snmp-1.0.2-build3.zip"
COMMUNITY = "runtime-community-must-not-leak"
USERNAME = "runtime-v3-user-must-not-leak"
AUTH_PASSWORD = "runtime-auth-must-not-leak"
PRIVACY_PASSWORD = "runtime-privacy-must-not-leak"
QNAP_POOL2_STATUS_OID = ".1.3.6.1.4.1.55062.2.10.7.1.5.2"
QNAP_FIRMWARE_VERSION_OID = ".1.3.6.1.4.1.55062.2.12.6.0"


def _install_runtime_contracts(plugin_api) -> None:
    @dataclass(frozen=True)
    class AddCapabilityIntent:
        site_id: str
        object_id: str
        capability_data: Mapping[str, Any]

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

    for value in (
        AddCapabilityIntent,
        RuntimeExecutionContext,
        RuntimeExecutionRequest,
        RuntimeExecutionResult,
        IntegrationDefinition,
    ):
        setattr(plugin_api, value.__name__, value)


def _request(
    plugin_api,
    *,
    version: str,
    timeout: float = 1.0,
    expected=None,
    oids: Mapping[str, str] | None = None,
):
    options: dict[str, Any] = {
        "host": "192.0.2.10",
        "port": 161,
        "version": version,
        "retries": 1,
        "oids": dict(oids or {"uptime": ".1.3.6.1.2.1.1.3.0"}),
    }
    if version in {"1", "2", "2c"}:
        options["community_env"] = "TEST_SNMP_COMMUNITY"
    else:
        options.update(
            {
                "username_env": "TEST_SNMP_USERNAME",
                "auth_password_env": "TEST_SNMP_AUTH",
                "auth_protocol": "SHA",
                "privacy_password_env": "TEST_SNMP_PRIVACY",
                "privacy_protocol": "AES",
            }
        )
    if expected is not None:
        options["expected"] = expected
    return plugin_api.RuntimeExecutionRequest(
        check_id="snmp_runtime",
        object_id="host",
        adapter="snmp",
        timeout_seconds=timeout,
        options=options,
    )


def _assert_no_secret(result) -> None:
    rendered = repr((result.summary, dict(result.metadata), dict(result.metrics)))
    for secret in (COMMUNITY, USERNAME, AUTH_PASSWORD, PRIVACY_PASSWORD):
        if secret in rendered:
            raise AssertionError("SNMP runtime result leaked protected credential material")


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed SNMP runtime package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_snmp_b3")
    runtime_module = importlib.import_module("monitorbox_snmp_b3.runtime")

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.2", 3):
        raise AssertionError("managed SNMP runtime correction release identity changed")
    if managed.MODULE_MANIFEST.entrypoints != {"integration": "monitorbox_snmp_b3:PLUGIN"}:
        raise AssertionError("managed SNMP build 3 entrypoint is not generation-safe")
    if managed.PLUGIN.runtime_executor is None:
        raise AssertionError("SNMP build 3 did not claim module-owned runtime execution")
    if managed.PLUGIN.runtime_adapter_kinds != ("snmp",):
        raise AssertionError("SNMP build 3 did not claim only the snmp runtime adapter")

    executor = managed.PLUGIN.runtime_executor
    context = plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root="/tmp/snmp-package",
        state_root="/tmp/snmp-state",
    )
    await executor.start(context)
    try:
        os.environ["TEST_SNMP_COMMUNITY"] = COMMUNITY
        os.environ["TEST_SNMP_USERNAME"] = USERNAME
        os.environ["TEST_SNMP_AUTH"] = AUTH_PASSWORD
        os.environ["TEST_SNMP_PRIVACY"] = PRIVACY_PASSWORD

        calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

        async def no_response(*args: str, env=None):
            calls.append((tuple(args), env))
            return 1, "", "Timeout: No Response from 192.0.2.10"

        runtime_module._command = no_response
        lost = await executor.execute(_request(plugin_api, version="2c"), context)
        if lost.state != "unknown" or lost.metadata.get("failure_kind") != "monitor_dependency":
            raise AssertionError(f"SNMP provider loss was not UNKNOWN/monitor_dependency: {lost!r}")
        if "-v2c" not in calls[-1][0]:
            raise AssertionError("SNMPv2c runtime stopped using v2c community transport")
        _assert_no_secret(lost)

        async def blocked(*args: str, env=None):
            del args, env
            await asyncio.sleep(1)
            return 1, "", "unreachable"

        runtime_module._command = blocked
        started = asyncio.get_running_loop().time()
        bounded = await executor.execute(_request(plugin_api, version="2c", timeout=0.2), context)
        elapsed = asyncio.get_running_loop().time() - started
        if bounded.state != "unknown" or bounded.metadata.get("failure_kind") != "monitor_dependency":
            raise AssertionError(f"bounded SNMP timeout escaped provider-loss truth: {bounded!r}")
        if elapsed >= 0.2:
            raise AssertionError(f"SNMP provider timeout did not finish inside Core watchdog: {elapsed:.3f}s")

        async def v1_ok(*args: str, env=None):
            del env
            calls.append((tuple(args), None))
            return 0, "42\n", ""

        runtime_module._command = v1_ok
        v1 = await executor.execute(_request(plugin_api, version="1"), context)
        if v1.state != "healthy" or v1.metrics.get("uptime") != 42.0:
            raise AssertionError(f"SNMPv1 runtime did not return healthy metrics: {v1!r}")
        if "-v1" not in calls[-1][0] or "-v3" in calls[-1][0]:
            raise AssertionError(f"SNMPv1 runtime used the wrong transport: {calls[-1][0]!r}")

        captured_config: list[str] = []
        captured_path: list[str] = []

        async def v3_ok(*args: str, env=None):
            calls.append((tuple(args), env))
            if env is None or "SNMPCONFPATH" not in env:
                raise AssertionError("SNMPv3 runtime did not use an isolated Net-SNMP config path")
            path = Path(env["SNMPCONFPATH"])
            captured_path.append(str(path))
            captured_config.append((path / "snmp.conf").read_text())
            return 0, "7\n", ""

        runtime_module._command = v3_ok
        v3 = await executor.execute(_request(plugin_api, version="3"), context)
        if v3.state != "healthy" or v3.metrics.get("uptime") != 7.0:
            raise AssertionError(f"SNMPv3 authPriv runtime failed: {v3!r}")
        args = calls[-1][0]
        if "-v3" not in args or AUTH_PASSWORD in args or PRIVACY_PASSWORD in args:
            raise AssertionError("SNMPv3 runtime exposed passphrases on the process command line")
        config_text = captured_config[-1]
        if AUTH_PASSWORD not in config_text or PRIVACY_PASSWORD not in config_text:
            raise AssertionError("SNMPv3 runtime did not broker auth/privacy material through temporary config")
        if Path(captured_path[-1]).exists():
            raise AssertionError("SNMPv3 temporary credential directory survived runtime execution")
        _assert_no_secret(v3)

        async def assertion_value(*args: str, env=None):
            del args, env
            return 0, "Bad\n", ""

        runtime_module._command = assertion_value
        assertion = await executor.execute(
            _request(plugin_api, version="2c", expected={"uptime": "Good"}),
            context,
        )
        if assertion.state != "failed" or "assertion failed" not in assertion.summary.casefold():
            raise AssertionError("SNMP target assertion mismatch stopped being actionable FAILED")

        # QNAP's NAS.mib documents status 4 as SCRUBBING on QuTS hero but as
        # REMOVING_TIER on QTS. The runtime must positively identify firmware
        # from the same endpoint before neutralizing the maintenance state.
        async def qnap_scrubbing(*args: str, env=None):
            del env
            if QNAP_FIRMWARE_VERSION_OID in args:
                return 0, "h6.0.1.3564\n", ""
            return 0, "4\n", ""

        runtime_module._command = qnap_scrubbing
        scrub = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={"pool2_status": QNAP_POOL2_STATUS_OID},
                expected={"pool2_status": 0},
            ),
            context,
        )
        if scrub.state != "healthy" or "scrubbing" not in scrub.summary.casefold():
            raise AssertionError(f"positively identified QuTS hero scrub was not health-neutral: {scrub!r}")
        if scrub.metrics.get("pool2_status") != 4.0:
            raise AssertionError(f"QuTS hero scrub lost raw pool status evidence: {scrub!r}")
        if scrub.metadata.get("maintenance_health_neutral") is not True:
            raise AssertionError(f"QuTS hero scrub lacks explicit neutral-maintenance evidence: {scrub!r}")
        if scrub.metadata.get("maintenance_kind") != "scrub":
            raise AssertionError(f"QuTS hero scrub maintenance kind changed: {scrub!r}")
        if scrub.metadata.get("qnap_storage_profile") != "quts_hero":
            raise AssertionError(f"QuTS hero scrub was neutralized without positive platform provenance: {scrub!r}")

        # The same status value on non-hero QTS must not inherit the scrub rule.
        async def qts_status_four(*args: str, env=None):
            del env
            if QNAP_FIRMWARE_VERSION_OID in args:
                return 0, "5.2.9.3499\n", ""
            return 0, "4\n", ""

        runtime_module._command = qts_status_four
        qts_four = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={"pool2_status": QNAP_POOL2_STATUS_OID},
                expected={"pool2_status": 0},
            ),
            context,
        )
        if qts_four.state != "unknown" or qts_four.metadata.get("failure_kind") != "provider_semantics_unknown":
            raise AssertionError(f"QTS status 4 was incorrectly treated as a QuTS hero scrub: {qts_four!r}")

        # Numeric 4 is not globally healthy. The exemption is bound to QNAP's
        # pool status table plus a positively identified QuTS hero profile.
        async def arbitrary_four(*args: str, env=None):
            del args, env
            return 0, "4\n", ""

        runtime_module._command = arbitrary_four
        non_qnap_four = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={"status": ".1.3.6.1.2.1.2.2.1.8.4"},
                expected={"status": 0},
            ),
            context,
        )
        if non_qnap_four.state != "failed":
            raise AssertionError(f"numeric 4 was incorrectly whitelisted outside QNAP pool status: {non_qnap_four!r}")

        # Documented non-ready QuTS hero states remain actionable. Build 3 only
        # neutralizes positively identified SCRUBBING; it does not flatten
        # WARNING/recovery/error states.
        async def qnap_warning(*args: str, env=None):
            del args, env
            return 0, "-1\n", ""

        runtime_module._command = qnap_warning
        warning = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={"pool2_status": QNAP_POOL2_STATUS_OID},
                expected={"pool2_status": 0},
            ),
            context,
        )
        if warning.state != "failed":
            raise AssertionError(f"QuTS hero WARNING stopped being actionable: {warning!r}")

        # Broad Leaf previously observed pool status 15 during online expansion,
        # but the checked-in QNAP MIB does not define 15. Fail safe as UNKNOWN;
        # do not invent either a healthy expansion mapping or a hard failure.
        async def qnap_unmapped(*args: str, env=None):
            del args, env
            return 0, "15\n", ""

        runtime_module._command = qnap_unmapped
        unmapped = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={"pool2_status": QNAP_POOL2_STATUS_OID},
                expected={"pool2_status": 0},
            ),
            context,
        )
        if unmapped.state != "unknown":
            raise AssertionError(f"unmapped QuTS hero pool state was fabricated as known health: {unmapped!r}")
        if unmapped.metadata.get("failure_kind") != "provider_semantics_unknown":
            raise AssertionError(f"unmapped QuTS hero pool state lost semantic-unknown provenance: {unmapped!r}")
        if unmapped.metrics.get("pool2_status") != 15.0:
            raise AssertionError(f"unmapped QuTS hero pool state lost raw provider value: {unmapped!r}")

        # A real independent mismatch in the same query must override an active
        # maintenance value before any profile probe. Maintenance never masks a
        # separate fault.
        async def scrub_plus_fault(*args: str, env=None):
            del args, env
            return 0, "4\nBad\n", ""

        runtime_module._command = scrub_plus_fault
        overridden = await executor.execute(
            _request(
                plugin_api,
                version="2c",
                oids={
                    "pool2_status": QNAP_POOL2_STATUS_OID,
                    "other_health": ".1.3.6.1.2.1.1.5.0",
                },
                expected={"pool2_status": 0, "other_health": "Good"},
            ),
            context,
        )
        if overridden.state != "failed" or "other_health=Bad" not in overridden.summary:
            raise AssertionError(f"active scrub masked an independent assertion fault: {overridden!r}")

        async def rejected_query(*args: str, env=None):
            del args, env
            return 1, "", "Authentication failure"

        runtime_module._command = rejected_query
        rejected = await executor.execute(_request(plugin_api, version="2c"), context)
        if rejected.state != "failed":
            raise AssertionError("non-transport SNMP query rejection was incorrectly neutralized")
        _assert_no_secret(rejected)
    finally:
        await executor.close(context)
        for name in (
            "TEST_SNMP_COMMUNITY",
            "TEST_SNMP_USERNAME",
            "TEST_SNMP_AUTH",
            "TEST_SNMP_PRIVACY",
        ):
            os.environ.pop(name, None)

    print(
        "Managed SNMP 1.0.2 build 3 runtime: provider-loss UNKNOWN + bounded timeout + "
        "v1/v2c/v3 credential transport + actionable assertions + profiled QuTS hero scrub truth: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
