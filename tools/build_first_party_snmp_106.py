#!/usr/bin/env python3
"""Build SNMP 1.0.6 build 8 with durable bounded QNAP platform identity.

Build 8 layers only the #74 QNAP profile-stability correction on top of the
accepted 1.0.5 build 7 package. Build 7's per-wire-query PySNMP isolation and
all build-6 ZIP/MIB compatibility fixes remain intact.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_snmp as base
import build_first_party_snmp_105 as build7

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.0.6"
MODULE_BUILD = 8
IMPORT_PACKAGE = "monitorbox_snmp_v106_b8"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-1.0.5-build7.zip"
PROFILE_CACHE_SOURCE = "sources/snmp/1.0.6-build8/qnap_profile_cache.py"
PROFILE_CACHE_BLOB = "056a03c80bf9ddd4aa9441bf8e7273441a62009c"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _configure() -> None:
    build7._configure()

    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base.HISTORICAL_FILENAMES = frozenset(
        set(base.HISTORICAL_FILENAMES) | {PREVIOUS_FILENAME}
    )

    original_source_files = base._source_files
    original_rewrite = base._rewrite_source

    def source_files_build8(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        source = root / PROFILE_CACHE_SOURCE
        payload = source.read_bytes()
        actual = base._git_blob_sha(payload)
        if actual != PROFILE_CACHE_BLOB:
            raise SystemExit(
                f"SNMP 1.0.6 QNAP profile-cache source drift: expected {PROFILE_CACHE_BLOB}, got {actual}"
            )
        files["qnap_profile_cache.py"] = payload
        return files

    def rewrite_build8(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name != "runtime.py":
            return text.encode("utf-8")

        text = _replace_once(
            text,
            "from .v3_isolation import is_auth_observer_loss, with_fresh_engine\n\n_TRANSPORT_FAILURE_MARKERS = (",
            "from .v3_isolation import is_auth_observer_loss, with_fresh_engine\n"
            "from .qnap_profile_cache import QnapPlatformProfileCache, classify_qnap_firmware\n\n"
            "_TRANSPORT_FAILURE_MARKERS = (",
            "SNMP QNAP profile-cache import",
        )

        text = _replace_once(
            text,
            "    def __init__(self) -> None:\n        self._engine = None\n",
            "    def __init__(self) -> None:\n"
            "        self._engine = None\n"
            "        self._qnap_profile_cache: QnapPlatformProfileCache | None = None\n",
            "SNMP QNAP profile-cache executor state",
        )

        old_lifecycle = '''    async def start(self, context: RuntimeExecutionContext) -> None:\n        del context\n        hlapi = _pysnmp_api()\n        probe = hlapi.SnmpEngine()\n        probe.close_dispatcher()\n        self._engine = True\n\n    async def close(self, context: RuntimeExecutionContext) -> None:\n        del context\n        self._engine = None\n'''
        new_lifecycle = '''    async def start(self, context: RuntimeExecutionContext) -> None:\n        hlapi = _pysnmp_api()\n        probe = hlapi.SnmpEngine()\n        probe.close_dispatcher()\n        self._engine = True\n        self._qnap_profile_cache = QnapPlatformProfileCache(context.state_root)\n\n    async def close(self, context: RuntimeExecutionContext) -> None:\n        del context\n        self._qnap_profile_cache = None\n        self._engine = None\n'''
        text = _replace_once(
            text,
            old_lifecycle,
            new_lifecycle,
            "SNMP QNAP profile-cache lifecycle",
        )

        old_status4 = '''        if status4_fields:\n            remaining = outer_timeout - (_elapsed_ms(started) / 1000.0)\n            firmware_version = ""\n            if remaining > 0.06:\n                try:\n                    firmware_values, _, _, _ = await _query(\n                        self._engine,\n                        host=host,\n                        port=port,\n                        timeout=min(1.0, max(0.05, remaining * 0.8)),\n                        retries=0,\n                        options=options,\n                        oids=(_QNAP_FIRMWARE_VERSION_OID,),\n                    )\n                    if firmware_values and len(firmware_values) == 1:\n                        firmware_version = firmware_values[0].strip().strip('"')\n                except Exception:\n                    firmware_version = ""\n            if firmware_version:\n                metadata["qnap_firmware_version"] = firmware_version[:200]\n            if firmware_version and _looks_like_quts_hero_firmware(firmware_version):\n                _record_scrub_metadata(metadata, status4_fields, firmware_version)\n                return RuntimeExecutionResult(\n                    state="healthy",\n                    summary="QNAP storage maintenance: Scrubbing",\n                    duration_ms=_elapsed_ms(started),\n                    metrics=metrics,\n                    metadata=metadata,\n                )\n            metadata["failure_kind"] = "provider_semantics_unknown"\n            metadata["qnap_pool_status_unresolved"] = [\n                f"{name}={_QNAP_QUTSHERO_SCRUBBING}" for name in status4_fields\n            ]\n            if firmware_version:\n                metadata["qnap_storage_profile"] = "non_quts_hero_or_unrecognized"\n            return RuntimeExecutionResult(\n                state="unknown",\n                summary="QNAP storage pool status 4 requires platform-specific interpretation",\n                duration_ms=_elapsed_ms(started),\n                metrics=metrics,\n                metadata=metadata,\n            )\n'''
        new_status4 = '''        if status4_fields:\n            remaining = outer_timeout - (_elapsed_ms(started) / 1000.0)\n            firmware_version = ""\n            profile = "unknown"\n            profile_source = "unresolved"\n            cache_key = None\n            cache = self._qnap_profile_cache\n            if cache is not None:\n                try:\n                    cache_key = cache.identity_key(host=host, port=port, options=options)\n                except Exception:\n                    cache_key = None\n\n            if remaining > 0.06:\n                try:\n                    firmware_values, _, _, _ = await _query(\n                        self._engine,\n                        host=host,\n                        port=port,\n                        timeout=min(1.0, max(0.05, remaining * 0.8)),\n                        retries=0,\n                        options=options,\n                        oids=(_QNAP_FIRMWARE_VERSION_OID,),\n                    )\n                    if firmware_values and len(firmware_values) == 1:\n                        firmware_version = firmware_values[0].strip().strip('"')\n                except Exception:\n                    firmware_version = ""\n\n            if firmware_version:\n                profile = classify_qnap_firmware(firmware_version)\n                profile_source = "fresh" if profile != "unknown" else "fresh_unrecognized"\n                if cache is not None and cache_key is not None:\n                    if profile in {"quts_hero", "qts"}:\n                        cache.remember(\n                            cache_key,\n                            profile=profile,\n                            firmware_version=firmware_version,\n                        )\n                    else:\n                        # Fresh contradictory/unrecognized evidence must not inherit\n                        # a prior positive platform classification.\n                        cache.forget(cache_key)\n            elif cache is not None and cache_key is not None:\n                cached = cache.recall(cache_key)\n                if cached is not None:\n                    profile = str(cached["profile"])\n                    firmware_version = str(cached["firmware_version"])\n                    profile_source = "cached"\n\n            if firmware_version:\n                metadata["qnap_firmware_version"] = firmware_version[:200]\n            if profile != "unknown":\n                metadata["qnap_storage_profile"] = profile\n                metadata["qnap_storage_profile_source"] = profile_source\n\n            if profile == "quts_hero":\n                _record_scrub_metadata(metadata, status4_fields, firmware_version)\n                metadata["qnap_storage_profile_source"] = profile_source\n                return RuntimeExecutionResult(\n                    state="healthy",\n                    summary="QNAP storage maintenance: Scrubbing",\n                    duration_ms=_elapsed_ms(started),\n                    metrics=metrics,\n                    metadata=metadata,\n                )\n\n            metadata["failure_kind"] = "provider_semantics_unknown"\n            metadata["qnap_pool_status_unresolved"] = [\n                f"{name}={_QNAP_QUTSHERO_SCRUBBING}" for name in status4_fields\n            ]\n            if firmware_version and profile == "unknown":\n                metadata["qnap_storage_profile"] = "non_quts_hero_or_unrecognized"\n                metadata["qnap_storage_profile_source"] = profile_source\n            return RuntimeExecutionResult(\n                state="unknown",\n                summary="QNAP storage pool status 4 requires platform-specific interpretation",\n                duration_ms=_elapsed_ms(started),\n                metrics=metrics,\n                metadata=metadata,\n            )\n'''
        text = _replace_once(
            text,
            old_status4,
            new_status4,
            "SNMP durable QNAP status-4 interpretation",
        )
        return text.encode("utf-8")

    base._source_files = source_files_build8
    base._rewrite_source = rewrite_build8


def build(root: Path, output_dir: Path) -> Path:
    previous = output_dir / PREVIOUS_FILENAME
    if not previous.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous}; build 8 must not recreate build 7"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected SNMP 1.0.6 build-8 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
