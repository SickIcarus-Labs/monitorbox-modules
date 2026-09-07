#!/usr/bin/env python3
"""Build the independently managed NUT integration for MonitorBox 2.3 Core."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.nut"
MODULE_VERSION = "1.0.1"
MODULE_BUILD = 2
IMPORT_PACKAGE = "monitorbox_nut_b2"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset({f"{MODULE_ID}-1.0.0-build1.zip"})

BASE_SOURCE_BLOBS = {"__init__.py": "33c01d663f08cffb701bbe819bcf465accd8d4f1"}
BUILD2_SOURCE_BLOBS = {"runtime.py": "7434f22537ddce0b1171739bc757a678afb456b4"}

_CORE_IMPORT_REWRITES = (
    ("from ...adapters", "from monitorbox.v2.adapters"),
    ("from ...config", "from monitorbox.v2.config"),
    ("from ...model", "from monitorbox.v2.model"),
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verified_directory(source_root: Path, expected: dict[str, str], label: str) -> dict[str, bytes]:
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != set(expected):
        raise SystemExit(f"{label} source shape changed: expected={sorted(expected)}, actual={sorted(actual)}")
    result: dict[str, bytes] = {}
    for name, blob in expected.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != blob:
            raise SystemExit(f"{label} source drift for {name}: expected {blob}, got {actual_blob}")
        result[name] = payload
    return result


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _root_source(root: Path) -> bytes:
    return _verified_directory(
        root / "sources" / "nut" / "1.0.0-build1",
        BASE_SOURCE_BLOBS,
        "immutable NUT 1.0.0 build 1",
    )["__init__.py"]


def _runtime_source(root: Path) -> bytes:
    return _verified_directory(
        root / "sources" / "nut" / "1.0.1-build2",
        BUILD2_SOURCE_BLOBS,
        "NUT 1.0.1 build 2 runtime",
    )["runtime.py"]


def _rewrite_root(payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    text = _replace_once(text, 'MODULE_VERSION = "1.0.0"', f'MODULE_VERSION = "{MODULE_VERSION}"', "NUT version")
    text = _replace_once(text, "MODULE_BUILD = 1", f"MODULE_BUILD = {MODULE_BUILD}", "NUT build")
    text = _replace_once(
        text,
        "from monitorbox.v2.plugin_api import (\n",
        "from monitorbox.v2.plugin_api import (\n    RuntimeExecutionContext,\n    RuntimeExecutionRequest,\n",
        "NUT runtime contract imports",
    )
    text = _replace_once(
        text,
        "    RuntimeIntent,\n    ValidationResult,\n)\n",
        "    RuntimeIntent,\n    ValidationResult,\n)\n\nfrom .runtime import NutRuntimeExecutor\n",
        "NUT runtime executor import",
    )
    text = _replace_once(
        text,
        "_ACCEPTED_STATES = frozenset({State.HEALTHY, State.DEGRADED})",
        '_ACCEPTED_STATES = frozenset({"healthy", "degraded"})',
        "NUT validation accepted states",
    )
    text = _replace_once(
        text,
        "    def __init__(self, *, runner_factory: Callable[[], AdapterRunner] = AdapterRunner) -> None:\n        self._runner_factory = runner_factory\n",
        "    def __init__(self, *, executor_factory=NutRuntimeExecutor) -> None:\n        self._executor_factory = executor_factory\n",
        "NUT executor construction",
    )

    old_validation = '''        check = CheckConfig(\n            id="nut_validation",\n            object_id=request.candidate.system_id,\n            label="UPS status",\n            adapter="nut",\n            interval_seconds=15,\n            timeout_seconds=5,\n            enabled=True,\n            options={"host": host, "port": port, "ups": ups},\n            agent_id=agent_id,\n            capability_id=None,\n            capability_kind=None,\n        )\n        runner = self._runner_factory()\n        try:\n            await runner.start()\n            observation = await runner.run(check)\n        finally:\n            await runner.close()\n        public = copy.deepcopy(observation.as_dict())\n        return ValidationResult(\n            accepted=observation.state in _ACCEPTED_STATES,\n            state=observation.state.value,\n            summary=str(public.get("summary") or "NUT validation completed")[:400],\n            observation=public,\n            metadata={"transport": "nut"},\n            values={"host": host, "port": port, "ups": ups},\n        )'''
    new_validation = '''        executor = self._executor_factory()\n        execution_context = RuntimeExecutionContext(\n            module_id=MODULE_ID,\n            package_root="",\n            state_root="",\n        )\n        try:\n            await executor.start(execution_context)\n            result = await executor.execute(\n                RuntimeExecutionRequest(\n                    check_id="nut_validation",\n                    object_id=request.candidate.system_id,\n                    adapter="nut",\n                    timeout_seconds=5,\n                    options={"host": host, "port": port, "ups": ups},\n                    agent_id=agent_id,\n                ),\n                execution_context,\n            )\n        finally:\n            await executor.close(execution_context)\n        public = result.public()\n        return ValidationResult(\n            accepted=result.state in _ACCEPTED_STATES,\n            state=result.state,\n            summary=str(public.get("summary") or "NUT validation completed")[:400],\n            observation=public,\n            metadata={"transport": "nut", "runtime_executor": "module_owned"},\n            values={"host": host, "port": port, "ups": ups},\n        )'''
    text = _replace_once(text, old_validation, new_validation, "NUT validation execution boundary")

    text = _replace_once(
        text,
        "_NUT = NutIntegration()\nPLUGIN = IntegrationDefinition(\n",
        "_NUT = NutIntegration()\n_NUT_RUNTIME = NutRuntimeExecutor()\nPLUGIN = IntegrationDefinition(\n",
        "NUT runtime singleton",
    )
    text = _replace_once(
        text,
        "    runtime=_NUT,\n)",
        "    runtime=_NUT,\n    runtime_executor=_NUT_RUNTIME,\n    runtime_adapter_kinds=(\"nut\",),\n)",
        "NUT runtime ownership",
    )
    text = _replace_once(
        text,
        'entrypoints={"integration": "monitorbox.v2.integrations.nut:PLUGIN"}',
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        "NUT managed entrypoint",
    )
    text = _replace_once(
        text,
        'requires_core=">=2.2.2 <3.0.0"',
        'requires_core=">=2.3.1 <3.0.0"',
        "NUT Core requirement",
    )
    text = _replace_once(
        text,
        '    "NutIntegration",\n    "PLUGIN",\n',
        '    "NutIntegration",\n    "NutRuntimeExecutor",\n    "PLUGIN",\n',
        "NUT runtime public export",
    )

    forbidden = (
        "self._runner_factory",
        "monitorbox.v2.integrations.nut:PLUGIN",
        'requires_core=">=2.2.2 <3.0.0"',
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"NUT managed boundary rewrite incomplete: {remaining}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/__init__.py": _rewrite_root(_root_source(root)),
        f"{IMPORT_PACKAGE}/runtime.py": _runtime_source(root),
    }


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"runtime_blob={BUILD2_SOURCE_BLOBS['runtime.py']} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
    unexpected = sorted(
        path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed NUT packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
