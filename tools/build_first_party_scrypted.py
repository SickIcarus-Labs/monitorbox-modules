#!/usr/bin/env python3
"""Build the independently managed Scrypted integration for MonitorBox 2.3 Core."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.scrypted"
MODULE_VERSION = "2.0.0"
MODULE_BUILD = 1
IMPORT_PACKAGE = "monitorbox_scrypted_v2_b1"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-1.0.0-build1.zip"

PYTHON_SOURCE_NAMES = frozenset({
    "__init__.py",
    "adoption.py",
    "onboarding.py",
    "runtime.py",
})
BRIDGE_SOURCE_NAMES = frozenset({
    "package.json",
    "package-lock.json",
    "server.mjs",
})

_CORE_IMPORT_REWRITES = (
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)
_BUNDLED_ENTRYPOINT = 'entrypoints={"integration": "monitorbox.v2.integrations.scrypted:PLUGIN"}'
_MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'


def _source_root(root: Path) -> Path:
    return root / "sources" / "scrypted" / "2.0.0-build1"


def _python_source_files(root: Path) -> dict[str, bytes]:
    source_root = _source_root(root)
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != PYTHON_SOURCE_NAMES:
        missing = sorted(PYTHON_SOURCE_NAMES - actual_names)
        extra = sorted(actual_names - PYTHON_SOURCE_NAMES)
        raise SystemExit(
            f"Scrypted 2.0.0 build 1 Python source shape changed: "
            f"missing={missing}, extra={extra}"
        )
    return {name: (source_root / name).read_bytes() for name in sorted(PYTHON_SOURCE_NAMES)}


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    entrypoint_count = text.count(_BUNDLED_ENTRYPOINT)
    if name == "__init__.py":
        if entrypoint_count != 1:
            raise SystemExit(
                f"Scrypted bundled entrypoint contract changed in {name}: "
                f"found {entrypoint_count}"
            )
        text = text.replace(_BUNDLED_ENTRYPOINT, _MANAGED_ENTRYPOINT, 1)
    elif entrypoint_count:
        raise SystemExit(f"unexpected Scrypted manifest contract found in {name}")

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
        "/app/bridge/server.mjs",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"Scrypted managed boundary rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _bridge_files(root: Path) -> dict[str, bytes]:
    source_bridge = _source_root(root) / "bridge"
    actual_names = {path.name for path in source_bridge.iterdir() if path.is_file()}
    if actual_names != BRIDGE_SOURCE_NAMES:
        missing = sorted(BRIDGE_SOURCE_NAMES - actual_names)
        extra = sorted(actual_names - BRIDGE_SOURCE_NAMES)
        raise SystemExit(
            f"Scrypted 2.0.0 build 1 bridge source shape changed: "
            f"missing={missing}, extra={extra}"
        )

    with tempfile.TemporaryDirectory(prefix="monitorbox-scrypted-build-") as raw_temp:
        materialized = Path(raw_temp) / "bridge"
        materialized.mkdir()
        for name in sorted(BRIDGE_SOURCE_NAMES):
            shutil.copy2(source_bridge / name, materialized / name)

        environment = dict(os.environ)
        environment.update({
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "npm_config_ignore_scripts": "true",
        })
        try:
            subprocess.run(
                ["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
                cwd=materialized,
                env=environment,
                check=True,
            )
        except FileNotFoundError as exc:
            raise SystemExit("npm is required to build the Scrypted managed module") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"npm ci failed for Scrypted managed module: {exc.returncode}") from exc

        result: dict[str, bytes] = {}
        for path in sorted(materialized.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(materialized)
            if relative.as_posix() == "node_modules/.package-lock.json":
                continue
            result[f"{IMPORT_PACKAGE}/bridge/{relative.as_posix()}"] = path.read_bytes()
        if not any("node_modules/@scrypted/client/" in path for path in result):
            raise SystemExit("Scrypted bridge package is missing @scrypted/client runtime files")
        if not any("node_modules/ws/" in path for path in result):
            raise SystemExit("Scrypted bridge package is missing ws runtime files")
        return result


def _package_files(root: Path) -> dict[str, bytes]:
    files = {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _python_source_files(root).items()
    }
    files.update(_bridge_files(root))
    return files


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                files[path],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = _zip_bytes(files)
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"files={len(files)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    allowed = {PREVIOUS_FILENAME, FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in allowed
    )
    if unexpected:
        raise SystemExit(f"unexpected managed Scrypted packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
