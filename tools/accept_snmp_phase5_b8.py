#!/usr/bin/env python3
"""Phase-5 acceptance for SNMP 1.0.6 build 8 (#71 + #74)."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from accept_http_behavior import install_core_contract_stubs
from accept_snmp_runtime import _install_runtime_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.snmp-1.0.6-build8.zip"
IMPORT_PACKAGE = "monitorbox_snmp_v106_b8"
QNAP_POOL_STATUS_OID = ".1.3.6.1.4.1.55062.2.10.7.1.5.2"
QNAP_FIRMWARE_VERSION_OID = ".1.3.6.1.4.1.55062.2.12.6.0"
COMMUNITY_ENV = "PHASE5_SNMP_COMMUNITY"
COMMUNITY_A = "phase5-community-a-must-not-persist"
COMMUNITY_B = "phase5-community-b-must-not-persist"


class _ProbeEngine:
    def close_dispatcher(self) -> None:
        return None


class _ProbeHlapi:
    @staticmethod
    def SnmpEngine() -> _ProbeEngine:
        return _ProbeEngine()


def _request(plugin_api, *, extra_fault: bool = False):
    oids = {"pool2_status": QNAP_POOL_STATUS_OID}
    expected: dict[str, Any] = {"pool2_status": 0}
    if extra_fault:
        oids["other_health"] = ".1.3.6.1.2.1.2.2.1.8.4"
        expected["other_health"] = "Good"
    return plugin_api.RuntimeExecutionRequest(
        check_id="goliath_storage_pools",
        object_id="goliath",
        adapter="snmp",
        timeout_seconds=2.0,
        options={
            "host": "192.0.2.44",
            "port": 161,
            "version": "2c",
            "retries": 0,
            "community_env": COMMUNITY_ENV,
            "oids": oids,
            "expected": expected,
        },
    )


def _assert_scrub(result, *, source: str) -> None:
    if result.state != "healthy" or "scrubbing" not in result.summary.casefold():
        raise AssertionError(f"QuTS hero status 4 was not health-neutral: {result!r}")
    if result.metrics.get("pool2_status") != 4.0:
        raise AssertionError(f"raw QNAP status 4 was not retained: {result!r}")
    if result.metadata.get("qnap_storage_profile") != "quts_hero":
        raise AssertionError(f"scrub lost positive QuTS hero provenance: {result!r}")
    if result.metadata.get("qnap_storage_profile_source") != source:
        raise AssertionError(f"unexpected QNAP profile source: {result!r}")
    if result.metadata.get("maintenance_health_neutral") is not True:
        raise AssertionError(f"scrub lost health-neutral maintenance evidence: {result!r}")


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"SNMP Phase-5 package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)
    runtime = importlib.import_module(f"{IMPORT_PACKAGE}.runtime")
    cache_module = importlib.import_module(f"{IMPORT_PACKAGE}.qnap_profile_cache")

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.6", 8):
        raise AssertionError("SNMP Phase-5 release identity changed")
    if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("SNMP Phase-5 entrypoint is not generation-safe")
    if managed.PLUGIN.runtime_adapter_kinds != ("snmp",):
        raise AssertionError("SNMP Phase-5 changed adapter ownership")

    runtime._pysnmp_api = lambda: _ProbeHlapi
    os.environ[COMMUNITY_ENV] = COMMUNITY_A

    with tempfile.TemporaryDirectory(prefix="monitorbox-snmp-phase5-") as raw:
        state_root = Path(raw) / "module-state"
        context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root=str(Path(raw) / "package"),
            state_root=str(state_root),
        )

        control: dict[str, Any] = {
            "main": ["4"],
            "firmware": "h6.0.1.3564",
            "provider_loss": False,
        }
        firmware_queries = 0

        async def fake_query(
            engine,
            *,
            host,
            port,
            timeout,
            retries,
            options,
            oids,
        ):
            nonlocal firmware_queries
            del engine, host, port, timeout, retries, options
            protected = (os.environ.get(COMMUNITY_ENV, ""),)
            if tuple(oids) == (QNAP_FIRMWARE_VERSION_OID,):
                firmware_queries += 1
                mode = control["firmware"]
                if mode == "raise":
                    raise RuntimeError("transient helper failure")
                if mode == "empty":
                    return [], None, False, protected
                return [str(mode)], None, False, protected
            if control["provider_loss"]:
                return None, "Timeout: No Response", True, protected
            return list(control["main"]), None, False, protected

        runtime._query = fake_query
        executor = managed.PLUGIN.runtime_executor.__class__()
        await executor.start(context)
        try:
            # Fresh authoritative QuTS hero evidence establishes durable identity.
            first = await executor.execute(_request(plugin_api), context)
            _assert_scrub(first, source="fresh")

            # A helper failure on the next poll must not oscillate the unchanged
            # active scrub back to UNKNOWN.
            control["firmware"] = "raise"
            transient = await executor.execute(_request(plugin_api), context)
            _assert_scrub(transient, source="cached")

            # Persistent state must not contain the resolved credential material.
            for path in state_root.rglob("*"):
                if path.is_file():
                    payload = path.read_bytes()
                    if COMMUNITY_A.encode() in payload or COMMUNITY_B.encode() in payload:
                        raise AssertionError(f"QNAP profile cache persisted SNMP credential material: {path}")
        finally:
            await executor.close(context)

        # A new executor instance represents agent/module restart. With the same
        # Core-owned state_root and security identity, an empty helper read can
        # reuse the still-valid positive profile.
        executor = managed.PLUGIN.runtime_executor.__class__()
        await executor.start(context)
        try:
            control["firmware"] = "empty"
            restarted = await executor.execute(_request(plugin_api), context)
            _assert_scrub(restarted, source="cached")

            # Changing resolved credentials produces a different cache identity;
            # it must not inherit the prior endpoint classification.
            os.environ[COMMUNITY_ENV] = COMMUNITY_B
            changed_credentials = await executor.execute(_request(plugin_api), context)
            if changed_credentials.state != "unknown":
                raise AssertionError(
                    f"credential change inherited stale QNAP profile: {changed_credentials!r}"
                )
            if changed_credentials.metadata.get("failure_kind") != "provider_semantics_unknown":
                raise AssertionError("credential-change reidentification lost semantic-unknown provenance")

            # Restore the original identity and prove fresh contradictory QTS
            # evidence immediately replaces the cached QuTS hero classification.
            os.environ[COMMUNITY_ENV] = COMMUNITY_A
            control["firmware"] = "5.2.9.3499"
            qts = await executor.execute(_request(plugin_api), context)
            if qts.state != "unknown" or qts.metadata.get("qnap_storage_profile") != "qts":
                raise AssertionError(f"fresh QTS evidence did not replace cached QuTS hero: {qts!r}")
            if qts.metadata.get("qnap_storage_profile_source") != "fresh":
                raise AssertionError(f"fresh QTS evidence lost source provenance: {qts!r}")

            control["firmware"] = "empty"
            qts_cached = await executor.execute(_request(plugin_api), context)
            if qts_cached.state != "unknown" or qts_cached.metadata.get("qnap_storage_profile") != "qts":
                raise AssertionError(f"cached QTS evidence was misread as Scrubbing: {qts_cached!r}")
            if qts_cached.metadata.get("qnap_storage_profile_source") != "cached":
                raise AssertionError(f"cached QTS provenance changed: {qts_cached!r}")

            # Re-establish hero evidence, then a nonempty unrecognized firmware
            # string must invalidate it instead of falling back to stale cache.
            control["firmware"] = "h6.0.1.3564"
            _assert_scrub(await executor.execute(_request(plugin_api), context), source="fresh")
            control["firmware"] = "future-qnap-profile"
            unrecognized = await executor.execute(_request(plugin_api), context)
            if unrecognized.state != "unknown":
                raise AssertionError(f"unrecognized fresh firmware reused stale profile: {unrecognized!r}")
            control["firmware"] = "empty"
            after_invalidation = await executor.execute(_request(plugin_api), context)
            if after_invalidation.state != "unknown":
                raise AssertionError(f"invalidated profile survived into fallback: {after_invalidation!r}")
            if after_invalidation.metadata.get("qnap_storage_profile_source") == "cached":
                raise AssertionError("fresh unrecognized evidence failed to invalidate cached identity")

            # Provider loss remains #71's observer/dependency UNKNOWN semantics.
            # Rebuild positive cache first to prove cache cannot fabricate target
            # health when the actual monitored status query is unavailable.
            control["firmware"] = "h6.0.1.3564"
            _assert_scrub(await executor.execute(_request(plugin_api), context), source="fresh")
            control["provider_loss"] = True
            provider_loss = await executor.execute(_request(plugin_api), context)
            if provider_loss.state != "unknown" or provider_loss.metadata.get("failure_kind") != "monitor_dependency":
                raise AssertionError(f"#71 provider-loss truth regressed: {provider_loss!r}")
            rendered = repr((provider_loss.summary, dict(provider_loss.metadata)))
            if COMMUNITY_A in rendered:
                raise AssertionError("SNMP provider-loss result leaked credential material")
            control["provider_loss"] = False

            # Independent failure still wins before any maintenance profile probe.
            before = firmware_queries
            control["main"] = ["4", "Bad"]
            independent_fault = await executor.execute(
                _request(plugin_api, extra_fault=True),
                context,
            )
            if independent_fault.state != "failed" or "other_health=Bad" not in independent_fault.summary:
                raise AssertionError(f"independent fault was masked by maintenance: {independent_fault!r}")
            if firmware_queries != before:
                raise AssertionError("maintenance profile was queried before independent fault precedence")
        finally:
            await executor.close(context)

        # The durable identity is explicitly bounded. Expired evidence must not be
        # returned even when the endpoint/security identity still matches.
        os.environ[COMMUNITY_ENV] = COMMUNITY_A
        short_cache = cache_module.QnapPlatformProfileCache(str(state_root), ttl_seconds=10)
        key = short_cache.identity_key(
            host="192.0.2.44",
            port=161,
            options={"version": "2c", "community_env": COMMUNITY_ENV},
        )
        if not short_cache.remember(
            key,
            profile="quts_hero",
            firmware_version="h6.0.1.3564",
            now=100.0,
        ):
            raise AssertionError("could not persist bounded QNAP profile fixture")
        if short_cache.recall(key, now=111.0) is not None:
            raise AssertionError("expired QNAP platform evidence remained authoritative")

    print(
        "SNMP Phase-5 build-8 acceptance: PASS "
        "(fresh→cached scrub continuity, restart persistence, credential rekey, "
        "contradiction/invalidation, bounded TTL, #71 provider-loss truth, fault precedence)"
    )


if __name__ == "__main__":
    asyncio.run(accept())
