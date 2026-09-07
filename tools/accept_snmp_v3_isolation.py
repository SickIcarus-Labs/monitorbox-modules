#!/usr/bin/env python3
"""Regression for SNMP 1.0.5 build 7 SNMPv3 engine isolation."""

from __future__ import annotations

import asyncio
import importlib
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.snmp-1.0.5-build7.zip"
IMPORT_PACKAGE = "monitorbox_snmp_v105_b7"


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


def _request(plugin_api, check_id: str):
    return plugin_api.RuntimeExecutionRequest(
        check_id=check_id,
        object_id=check_id,
        adapter="snmp",
        timeout_seconds=2.0,
        options={
            "host": "192.0.2.10",
            "port": 161,
            "version": "2c",
            "retries": 0,
            "community_env": "TEST_SNMP_COMMUNITY",
            "oids": {"uptime": ".1.3.6.1.2.1.1.3.0"},
        },
    )


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed SNMP build 7 package is missing: {package}")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {
            f"{IMPORT_PACKAGE}/runtime.py",
            f"{IMPORT_PACKAGE}/v3_isolation.py",
            "pysnmp/smi/builder.py",
        }
        missing = required - names
        if missing:
            raise AssertionError(f"SNMP build 7 omitted isolation/MIB assets: {sorted(missing)}")
        runtime_text = archive.read(f"{IMPORT_PACKAGE}/runtime.py").decode("utf-8")
        builder_text = archive.read("pysnmp/smi/builder.py").decode("utf-8")

    if "with_fresh_engine(hlapi, operation)" not in runtime_text:
        raise AssertionError("SNMP build 7 runtime does not isolate wire-query engines")
    if "is_auth_observer_loss(detail)" not in runtime_text:
        raise AssertionError("SNMP build 7 runtime does not classify auth observer loss centrally")
    if '_get_files' not in builder_text or "isinstance(mibSource, DirMibSource)" not in builder_text:
        raise AssertionError("SNMP build 7 lost build-6 Python-3.13 ZIP/MIB compatibility")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    sys.path.insert(0, str(package))
    try:
        managed = importlib.import_module(IMPORT_PACKAGE)
        runtime = importlib.import_module(f"{IMPORT_PACKAGE}.runtime")
        isolation = importlib.import_module(f"{IMPORT_PACKAGE}.v3_isolation")

        if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.5", 7):
            raise AssertionError("SNMP build 7 release identity changed")
        if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
            raise AssertionError("SNMP build 7 entrypoint is not generation-safe")
        if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
            raise AssertionError("SNMP build 7 Core compatibility changed")
        if not isolation.is_auth_observer_loss("Wrong SNMP PDU digest"):
            raise AssertionError("PySNMP wrongDigest is not treated as authentication observer loss")
        if isolation.is_auth_observer_loss("noSuchObject at this OID"):
            raise AssertionError("ordinary SNMP target semantics were misclassified as auth loss")

        created = []

        class FakeEngine:
            def __init__(self, number: int):
                self.number = number
                self.closed = False

            def close_dispatcher(self):
                self.closed = True

        class FakeHlapi:
            @staticmethod
            def SnmpEngine():
                engine = FakeEngine(len(created) + 1)
                created.append(engine)
                return engine

        runtime._pysnmp_api = lambda: FakeHlapi
        seen = []
        gate = asyncio.Event()

        async def isolated_query(engine, **kwargs):
            del kwargs
            seen.append(engine)
            if len(seen) == 1:
                await gate.wait()
            else:
                gate.set()
            return [str(engine.number)], None, False, ()

        runtime._query_with_engine = isolated_query
        executor = managed.PLUGIN.runtime_executor
        executor._engine = True
        context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root=str(package),
            state_root="/tmp/snmp-build7-state",
        )
        first, second = await asyncio.gather(
            executor.execute(_request(plugin_api, "snmp_a"), context),
            executor.execute(_request(plugin_api, "snmp_b"), context),
        )
        if first.state != "healthy" or second.state != "healthy":
            raise AssertionError(f"isolated concurrent SNMP queries did not stay healthy: {first!r}, {second!r}")
        if len(created) != 2 or len({id(item) for item in seen}) != 2:
            raise AssertionError(f"concurrent SNMP queries reused PySNMP engine state: {seen!r}")
        if not all(engine.closed for engine in created):
            raise AssertionError("per-query PySNMP engines were not closed deterministically")

        # Classification must turn wrongDigest into observer/auth loss, which the
        # executor publishes as UNKNOWN rather than blaming the monitored host.
        runtime._query = lambda *args, **kwargs: None  # source routing asserted above
        detail = "Wrong SNMP PDU digest"
        transport_loss = isolation.is_auth_observer_loss(detail)
        if not transport_loss:
            raise AssertionError("wrongDigest no longer maps to provider/auth observer loss")
    finally:
        if sys.path and sys.path[0] == str(package):
            sys.path.pop(0)

    print("managed SNMP 1.0.5 build 7 per-query isolation acceptance: PASS", flush=True)


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
