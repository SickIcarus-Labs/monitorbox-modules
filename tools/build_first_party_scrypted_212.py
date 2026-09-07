#!/usr/bin/env python3
"""Build Scrypted 2.1.2 build 3 managed-state socket correction.

Broad Leaf physical acceptance of pruned Core proved the managed executor starts,
but the Scrypted worker still inherited a historical deployment path under
/run/monitorbox-scrypted. Managed modules already receive a writable Core-owned
state_root; build 3 relocates only that historical/default IPC path while
preserving explicit absolute sockets used by validation and tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.1.2"
MODULE_BUILD = 3
IMPORT_PACKAGE = "monitorbox_scrypted_v212_b3"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-2.1.1-build2.zip"
STATE_SOCKET_SOURCE = "sources/scrypted/2.1.2-build3/state_socket.py"
STATE_SOCKET_BLOB = "ae3ea6d1435b77b5df22e855fc4f7924570c95c1"


def _git_blob_sha(payload: bytes) -> str:
    return base._git_blob_sha(payload)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _configure() -> None:
    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base._MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
    base.PREVIOUS_FILENAMES = set(base.PREVIOUS_FILENAMES) | {PREVIOUS_FILENAME}

    original_source_files = base._python_source_files
    original_rewrite = base._rewrite_source

    def source_files_build3(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        source = root / STATE_SOCKET_SOURCE
        payload = source.read_bytes()
        actual = _git_blob_sha(payload)
        if actual != STATE_SOCKET_BLOB:
            raise SystemExit(
                f"Scrypted 2.1.2 managed-socket source drift: expected {STATE_SOCKET_BLOB}, got {actual}"
            )
        files["state_socket.py"] = payload
        return files

    def rewrite_build3(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "runtime.py":
            text = _replace_once(
                text,
                "from dataclasses import dataclass\n",
                "from dataclasses import dataclass, replace\n",
                "Scrypted managed-socket dataclass import",
            )
            text = _replace_once(
                text,
                "from .legacy_control import resolve_legacy_worker_config\n",
                "from .legacy_control import resolve_legacy_worker_config\n"
                "from .state_socket import resolve_managed_socket\n",
                "Scrypted managed-socket import",
            )
            text = _replace_once(
                text,
                "        self._configured = asyncio.Event()\n",
                "        self._configured = asyncio.Event()\n"
                "        self._state_root: str | None = None\n",
                "Scrypted bridge state-root storage",
            )
            text = _replace_once(
                text,
                "    async def start(self) -> None:\n"
                "        if self._bridge_root is not None:\n"
                "            return\n",
                "    async def start(self, state_root: str | None = None) -> None:\n"
                "        if state_root is not None:\n"
                "            self._state_root = state_root\n"
                "        if self._bridge_root is not None:\n"
                "            return\n",
                "Scrypted bridge managed-state lifecycle",
            )
            text = _replace_once(
                text,
                "            if requested_socket not in (None, \"\") and str(requested_socket) != config.socket:\n"
                "                raise RuntimeError(\"Scrypted camera socket does not match active worker configuration\")\n",
                "            if (\n"
                "                requested_socket not in (None, \"\")\n"
                "                and resolve_managed_socket(requested_socket, self._state_root) != config.socket\n"
                "            ):\n"
                "                raise RuntimeError(\"Scrypted camera socket does not match active worker configuration\")\n",
                "Scrypted child-check legacy socket normalization",
            )
            text = _replace_once(
                text,
                "        async with self._lock:\n"
                "            await self._ensure_locked(config)\n"
                "            return config.socket\n",
                "        resolved_socket = resolve_managed_socket(config.socket, self._state_root)\n"
                "        if resolved_socket != config.socket:\n"
                "            config = replace(config, socket=resolved_socket)\n"
                "\n"
                "        async with self._lock:\n"
                "            await self._ensure_locked(config)\n"
                "            return config.socket\n",
                "Scrypted worker socket normalization",
            )
            text = _replace_once(
                text,
                "    async def start(self, context: RuntimeExecutionContext) -> None:\n"
                "        del context\n"
                "        await self._bridge.start()\n",
                "    async def start(self, context: RuntimeExecutionContext) -> None:\n"
                "        await self._bridge.start(context.state_root)\n",
                "Scrypted executor Core-owned state handoff",
            )
        elif name == "onboarding.py":
            legacy_line = '            "socket": "/run/monitorbox-scrypted/bridge.sock",\n'
            count = text.count(legacy_line)
            if count != 2:
                raise SystemExit(
                    f"Scrypted onboarding legacy socket shape changed: expected 2 persisted paths, got {count}"
                )
            text = text.replace(legacy_line, "")
        return text.encode("utf-8")

    base._python_source_files = source_files_build3
    base._rewrite_source = rewrite_build3


def build(root: Path, output_dir: Path) -> Path:
    previous = output_dir / PREVIOUS_FILENAME
    if not previous.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous}; build 3 must not recreate build 2"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.1.2 build-3 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
