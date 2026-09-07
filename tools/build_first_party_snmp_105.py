#!/usr/bin/env python3
"""Build SNMP 1.0.5 build 7 with isolated PySNMP wire-query state.

Build 6 remains the immutable Python-3.13 ZIP/MIB packaging repair. Broad Leaf
physical acceptance then exposed a behavioral regression introduced when the old
per-process Net-SNMP transport was replaced by one long-lived PySNMP engine:
concurrent SNMPv3 endpoints/credentials share USM/LCD state. Build 7 preserves
all build-6 vendor patches, restores per-wire-query engine isolation, and treats
wrongDigest as authentication/observer loss rather than monitored-system failure.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_snmp as base
import build_first_party_snmp_mib_hotfix as build6

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.0.5"
MODULE_BUILD = 7
IMPORT_PACKAGE = "monitorbox_snmp_v105_b7"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-1.0.4-build6.zip"
ISOLATION_SOURCE = "sources/snmp/1.0.5-build7/v3_isolation.py"
ISOLATION_BLOB = "160121b3a957e615b4f4e6431f01d6859cefec5e"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _configure() -> None:
    # First install build 6's vendored PySNMP Python-3.13 ZIP/MIB adaptations.
    build6._configure_build6()

    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base.HISTORICAL_FILENAMES = frozenset(
        set(base.HISTORICAL_FILENAMES) | {PREVIOUS_FILENAME}
    )

    original_source_files = base._source_files
    original_rewrite = base._rewrite_source

    def source_files_build7(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        source = root / ISOLATION_SOURCE
        payload = source.read_bytes()
        actual = base._git_blob_sha(payload)
        if actual != ISOLATION_BLOB:
            raise SystemExit(
                f"SNMP 1.0.5 isolation source drift: expected {ISOLATION_BLOB}, got {actual}"
            )
        files["v3_isolation.py"] = payload
        return files

    def rewrite_build7(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name != "runtime.py":
            return text.encode("utf-8")

        text = _replace_once(
            text,
            ")\n\n_TRANSPORT_FAILURE_MARKERS = (",
            ")\n\nfrom .v3_isolation import is_auth_observer_loss, with_fresh_engine\n\n_TRANSPORT_FAILURE_MARKERS = (",
            "SNMP isolation helper import",
        )
        text = _replace_once(
            text,
            "async def _query(\n",
            "async def _query_with_engine(\n",
            "SNMP existing query implementation isolation",
        )
        text = _replace_once(
            text,
            '        if any(marker in lowered for marker in ("authorization", "authentication", "unknown user", "not in time window", "usm")):\n'
            "            transport_loss = True\n",
            "        if is_auth_observer_loss(detail):\n"
            "            transport_loss = True\n",
            "SNMP wrongDigest observer-loss classification",
        )

        wrapper_marker = "    return values, None, False, protected\n\n\nclass SnmpRuntimeExecutor:"
        wrapper = '''    return values, None, False, protected\n\n\nasync def _query(\n    engine: Any,\n    *,\n    host: str,\n    port: int,\n    timeout: float,\n    retries: int,\n    options: Mapping[str, Any],\n    oids: tuple[str, ...],\n) -> tuple[list[str] | None, str | None, bool, tuple[str, ...]]:\n    # The lifecycle marker proves PySNMP initialized successfully, but every wire\n    # query gets its own security-engine/LCD state just as the retired snmpget\n    # process transport did. This prevents concurrent SNMPv3 targets from sharing\n    # localized USM state.\n    del engine\n    hlapi = _pysnmp_api()\n\n    async def operation(query_engine: Any):\n        return await _query_with_engine(\n            query_engine,\n            host=host,\n            port=port,\n            timeout=timeout,\n            retries=retries,\n            options=options,\n            oids=oids,\n        )\n\n    return await with_fresh_engine(hlapi, operation)\n\n\nclass SnmpRuntimeExecutor:'''
        text = _replace_once(
            text,
            wrapper_marker,
            wrapper,
            "SNMP per-query engine wrapper",
        )

        old_lifecycle = '''    async def start(self, context: RuntimeExecutionContext) -> None:\n        del context\n        hlapi = _pysnmp_api()\n        self._engine = hlapi.SnmpEngine()\n\n    async def close(self, context: RuntimeExecutionContext) -> None:\n        del context\n        if self._engine is not None:\n            self._engine.close_dispatcher()\n            self._engine = None\n'''
        new_lifecycle = '''    async def start(self, context: RuntimeExecutionContext) -> None:\n        del context\n        hlapi = _pysnmp_api()\n        probe = hlapi.SnmpEngine()\n        probe.close_dispatcher()\n        self._engine = True\n\n    async def close(self, context: RuntimeExecutionContext) -> None:\n        del context\n        self._engine = None\n'''
        text = _replace_once(
            text,
            old_lifecycle,
            new_lifecycle,
            "SNMP lifecycle engine isolation",
        )
        return text.encode("utf-8")

    base._source_files = source_files_build7
    base._rewrite_source = rewrite_build7


def build(root: Path, output_dir: Path) -> Path:
    previous = output_dir / PREVIOUS_FILENAME
    if not previous.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous}; build 7 must not recreate build 6"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected SNMP 1.0.5 build-7 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
