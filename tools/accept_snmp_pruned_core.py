#!/usr/bin/env python3
"""Acceptance for zipimport-safe self-contained managed SNMP 1.0.4 build 5."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.snmp-1.0.4-build5.zip"
IMPORT_PACKAGE = "monitorbox_snmp_b5"
COMMUNITY = "snmp-build5-community-secret"
USERNAME = "snmp-build5-v3-user"
AUTH_PASSWORD = "snmp-build5-auth-secret"
PRIVACY_PASSWORD = "snmp-build5-privacy-secret"
POOL_OID = ".1.3.6.1.4.1.55062.2.10.7.1.5.2"
FIRMWARE_OID = ".1.3.6.1.4.1.55062.2.12.6.0"


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


def _request(plugin_api, *, version: str = "2c", oids=None, expected=None, timeout: float = 1.0):
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
                "auth_protocol": "SHA256",
                "privacy_password_env": "TEST_SNMP_PRIVACY",
                "privacy_protocol": "AES256",
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


def _purge_ambient_vendor_modules() -> None:
    """Prevent CI/site-packages contamination from masking ZIP packaging defects."""
    for name in tuple(sys.modules):
        if name == "pysnmp" or name.startswith("pysnmp.") or name == "pyasn1" or name.startswith("pyasn1."):
            sys.modules.pop(name, None)


def _assert_loaded_from_artifact(module, package: Path, label: str) -> None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise AssertionError(f"{label} did not resolve to a concrete file inside the managed artifact")
    package_text = str(package.resolve())
    if package_text not in str(module_file):
        raise AssertionError(
            f"{label} leaked from ambient site-packages instead of managed artifact: {module_file}"
        )


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed SNMP build 5 package is missing: {package}")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required_vendor_import_roots = {
            "pysnmp/__init__.py",
            "pysnmp/hlapi/__init__.py",
            "pysnmp/hlapi/v3arch/__init__.py",
            "pysnmp/hlapi/v3arch/asyncio/__init__.py",
            "pyasn1/__init__.py",
        }
        missing = sorted(required_vendor_import_roots - names)
        if missing:
            raise AssertionError(f"SNMP build 5 is not zipimport-safe: missing {missing}")
        root_text = archive.read(f"{IMPORT_PACKAGE}/__init__.py").decode("utf-8")
        runtime_text = archive.read(f"{IMPORT_PACKAGE}/runtime.py").decode("utf-8")
    for forbidden in ("snmpget", "create_subprocess_exec", "monitorbox.v2.integrations.snmp"):
        if forbidden in root_text + runtime_text:
            raise AssertionError(f"SNMP build 5 retained hidden Core/OS transport dependency: {forbidden}")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    _purge_ambient_vendor_modules()
    sys.path.insert(0, str(package))
    try:
        managed = importlib.import_module(IMPORT_PACKAGE)
        runtime = importlib.import_module(f"{IMPORT_PACKAGE}.runtime")

        if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.4", 5):
            raise AssertionError("SNMP build 5 release identity changed")
        if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
            raise AssertionError("SNMP build 5 entrypoint is not generation-safe")
        if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
            raise AssertionError("SNMP build 5 Core floor changed")
        if managed.PLUGIN.runtime_executor is None or managed.PLUGIN.runtime_adapter_kinds != ("snmp",):
            raise AssertionError("SNMP build 5 does not own the snmp runtime adapter")

        # This is the physical failure boundary: resolve PySNMP directly from the
        # installed ZIP, with any ambient runner copy removed from sys.modules.
        hlapi = runtime._pysnmp_api()
        pysnmp = importlib.import_module("pysnmp")
        pyasn1 = importlib.import_module("pyasn1")
        _assert_loaded_from_artifact(pysnmp, package, "PySNMP")
        _assert_loaded_from_artifact(pyasn1, package, "PyASN1")

        os.environ["TEST_SNMP_COMMUNITY"] = COMMUNITY
        os.environ["TEST_SNMP_USERNAME"] = USERNAME
        os.environ["TEST_SNMP_AUTH"] = AUTH_PASSWORD
        os.environ["TEST_SNMP_PRIVACY"] = PRIVACY_PASSWORD
        credentials, protected = runtime._credential_data(
            hlapi,
            dict(_request(plugin_api, version="3").options),
        )
        if credentials is None or set(protected) != {USERNAME, AUTH_PASSWORD, PRIVACY_PASSWORD}:
            raise AssertionError("SNMPv3 build 5 credential projection changed")

        executor = managed.PLUGIN.runtime_executor
        context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root=str(package),
            state_root="/tmp/snmp-build5-state",
        )
        executor._engine = object()

        async def lost_query(*args, **kwargs):
            del args, kwargs
            return None, "request timed out", True, (COMMUNITY,)

        runtime._query = lost_query
        lost = await executor.execute(_request(plugin_api), context)
        if lost.state != "unknown" or lost.metadata.get("failure_kind") != "monitor_dependency":
            raise AssertionError(f"SNMP provider loss was not UNKNOWN/monitor_dependency: {lost!r}")
        _assert_no_secret(lost)

        async def healthy_query(*args, **kwargs):
            del args, kwargs
            return ["42"], None, False, (COMMUNITY,)

        runtime._query = healthy_query
        healthy = await executor.execute(_request(plugin_api, version="1"), context)
        if healthy.state != "healthy" or healthy.metrics.get("uptime") != 42.0:
            raise AssertionError(f"SNMP build 5 did not return healthy numeric metrics: {healthy!r}")
        if healthy.metadata.get("transport") != "pysnmp":
            raise AssertionError("SNMP build 5 lost explicit PySNMP transport provenance")

        async def mismatch_query(*args, **kwargs):
            del args, kwargs
            return ["Bad"], None, False, (COMMUNITY,)

        runtime._query = mismatch_query
        mismatch = await executor.execute(_request(plugin_api, expected={"uptime": "Good"}), context)
        if mismatch.state != "failed" or "assertion failed" not in mismatch.summary.casefold():
            raise AssertionError("SNMP assertion mismatch stopped being actionable FAILED")

        async def scrub_query(*args, **kwargs):
            del args
            oids = kwargs["oids"]
            if FIRMWARE_OID in oids:
                return ["h6.0.1.3564"], None, False, (COMMUNITY,)
            return ["4"], None, False, (COMMUNITY,)

        runtime._query = scrub_query
        scrub = await executor.execute(
            _request(plugin_api, oids={"pool2_status": POOL_OID}, expected={"pool2_status": 0}),
            context,
        )
        if scrub.state != "healthy" or scrub.metadata.get("maintenance_kind") != "scrub":
            raise AssertionError(f"QuTS hero scrub stopped being health-neutral: {scrub!r}")
        if scrub.metadata.get("qnap_storage_profile") != "quts_hero":
            raise AssertionError("QuTS hero scrub lost positive platform provenance")

        async def qts_four_query(*args, **kwargs):
            del args
            oids = kwargs["oids"]
            if FIRMWARE_OID in oids:
                return ["5.2.9.3499"], None, False, (COMMUNITY,)
            return ["4"], None, False, (COMMUNITY,)

        runtime._query = qts_four_query
        qts_four = await executor.execute(
            _request(plugin_api, oids={"pool2_status": POOL_OID}, expected={"pool2_status": 0}),
            context,
        )
        if qts_four.state != "unknown" or qts_four.metadata.get("failure_kind") != "provider_semantics_unknown":
            raise AssertionError("QTS status 4 was incorrectly treated as QuTS hero scrubbing")

        async def unmapped_query(*args, **kwargs):
            del args, kwargs
            return ["15"], None, False, (COMMUNITY,)

        runtime._query = unmapped_query
        unmapped = await executor.execute(
            _request(plugin_api, oids={"pool2_status": POOL_OID}, expected={"pool2_status": 0}),
            context,
        )
        if unmapped.state != "unknown" or unmapped.metadata.get("failure_kind") != "provider_semantics_unknown":
            raise AssertionError("unmapped QNAP pool state stopped failing safe as UNKNOWN")
    finally:
        if sys.path and sys.path[0] == str(package):
            sys.path.pop(0)
        for name in ("TEST_SNMP_COMMUNITY", "TEST_SNMP_USERNAME", "TEST_SNMP_AUTH", "TEST_SNMP_PRIVACY"):
            os.environ.pop(name, None)

    print("managed SNMP 1.0.4 build 5 zipimport/pruned-Core runtime acceptance: PASS", flush=True)


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
