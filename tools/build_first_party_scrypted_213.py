#!/usr/bin/env python3
"""Build Scrypted 2.1.3 build 4 startup-hydration correction."""
from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base
import build_first_party_scrypted_212 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.1.3"
MODULE_BUILD = 4
IMPORT_PACKAGE = "monitorbox_scrypted_v213_b4"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-2.1.2-build3.zip"
STARTUP_SOURCE = "sources/scrypted/2.1.3-build4/startup_schedule.py"
STARTUP_BLOB = "18323544078b4709c2796fe11ab44e44c04dabc1"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _configure() -> None:
    # Materialize every accepted predecessor rewrite first; build 4 is a narrow
    # delta over the physically accepted 2.1.2 build 3 provider.
    previous._configure()
    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base._MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
    base.PREVIOUS_FILENAMES = set(base.PREVIOUS_FILENAMES) | {PREVIOUS_FILENAME}

    original_source_files = base._python_source_files
    original_rewrite = base._rewrite_source

    def source_files_build4(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        source = root / STARTUP_SOURCE
        payload = source.read_bytes()
        actual = base._git_blob_sha(payload)
        if actual != STARTUP_BLOB:
            raise SystemExit(
                f"Scrypted 2.1.3 startup-schedule source drift: expected {STARTUP_BLOB}, got {actual}"
            )
        files["startup_schedule.py"] = payload
        return files

    def rewrite_build4(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "runtime.py":
            text = _replace_once(
                text,
                "from .state_socket import resolve_managed_socket\n",
                "from .state_socket import resolve_managed_socket\n"
                "from .startup_schedule import ScryptedStartupSchedule\n",
                "Scrypted startup-schedule import",
            )
            text = _replace_once(
                text,
                "    def __init__(self) -> None:\n"
                "        self._bridge = _BridgeWorker()\n",
                "    def __init__(self) -> None:\n"
                "        self._bridge = _BridgeWorker()\n"
                "        self._startup_schedule = ScryptedStartupSchedule()\n",
                "Scrypted startup-schedule state",
            )
            text = _replace_once(
                text,
                "    async def start(self, context: RuntimeExecutionContext) -> None:\n"
                "        await self._bridge.start(context.state_root)\n",
                "    async def start(self, context: RuntimeExecutionContext) -> None:\n"
                "        self._startup_schedule.reset()\n"
                "        await self._bridge.start(context.state_root)\n",
                "Scrypted startup-schedule reset",
            )
            text = _replace_once(
                text,
                "    async def execute(\n"
                "        self,\n"
                "        request: RuntimeExecutionRequest,\n"
                "        context: RuntimeExecutionContext,\n"
                "    ) -> RuntimeExecutionResult:\n"
                "        del context\n",
                "    async def execute(\n"
                "        self,\n"
                "        request: RuntimeExecutionRequest,\n"
                "        context: RuntimeExecutionContext,\n"
                "    ) -> RuntimeExecutionResult:\n"
                "        result = await self._execute_provider(request, context)\n"
                "        self._startup_schedule.observe(request, result)\n"
                "        return result\n"
                "\n"
                "    async def reduce_schedule_delay(\n"
                "        self,\n"
                "        request: RuntimeExecutionRequest,\n"
                "        context: RuntimeExecutionContext,\n"
                "        *,\n"
                "        phase: str,\n"
                "        delay_seconds: float,\n"
                "    ) -> float:\n"
                "        del context\n"
                "        return self._startup_schedule.reduce_delay(\n"
                "            request,\n"
                "            phase=phase,\n"
                "            delay_seconds=delay_seconds,\n"
                "        )\n"
                "\n"
                "    async def _execute_provider(\n"
                "        self,\n"
                "        request: RuntimeExecutionRequest,\n"
                "        context: RuntimeExecutionContext,\n"
                "    ) -> RuntimeExecutionResult:\n"
                "        del context\n",
                "Scrypted startup-schedule execution wrapper",
            )
        elif name == "adoption.py":
            text = _replace_once(
                text,
                "from aiohttp import web\n",
                "from aiohttp import web\n\n"
                "from .startup_schedule import STARTUP_JITTER_CAP_SECONDS\n",
                "Scrypted adoption startup-schedule import",
            )
            text = _replace_once(
                text,
                '                "camera_id": camera_id,\n',
                '                "camera_id": camera_id,\n'
                '                "scheduler_jitter_seconds": STARTUP_JITTER_CAP_SECONDS,\n',
                "Scrypted fresh-adoption startup jitter",
            )
        return text.encode("utf-8")

    base._python_source_files = source_files_build4
    base._rewrite_source = rewrite_build4


def build(root: Path, output_dir: Path) -> Path:
    previous_package = output_dir / PREVIOUS_FILENAME
    if not previous_package.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous_package}; build 4 must not recreate build 3"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.1.3 build-4 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
