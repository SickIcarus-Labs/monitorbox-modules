#!/usr/bin/env python3
"""Build Portainer v1.3.0 build 9 bootstrap-discovery contract release."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_portainer_b8 as previous

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.3.0"
MODULE_BUILD = 9
IMPORT_PACKAGE = "monitorbox_portainer_b9"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD9_OVERRIDE_BLOBS = {
    "__init__.py": "a8dcb5db99920ea4ded794f1c48b54db62360842",
    "onboarding.py": "0c9f5e451799b70b963f74d44ff99b8b20ad0350",
}

_CORE_IMPORT_REWRITES = previous._CORE_IMPORT_REWRITES
_COMPATIBILITY_GUARD = previous._COMPATIBILITY_GUARD.replace(
    "managed Portainer build 8 requires", "managed Portainer build 9 requires"
)


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    build9 = previous.previous.previous._verified_directory(
        root / "sources" / "portainer" / "1.3.0-build9",
        BUILD9_OVERRIDE_BLOBS,
        label="Portainer v1.3.0 build 9 bootstrap-discovery delta",
    )
    result.update(build9)
    if set(result) != set(previous.previous.previous.BASE_SOURCE_BLOBS):
        raise SystemExit("Portainer build 9 composed source shape changed")
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    if name == "__init__.py":
        marker = "from __future__ import annotations\n\n"
        if text.count(marker) != 1:
            raise SystemExit("Portainer package root future-import marker changed")
        text = text.replace(marker, marker + _COMPATIBILITY_GUARD, 1)
        bundled_entrypoint = 'entrypoints={"integration": "monitorbox.v2.integrations.portainer:PLUGIN"}'
        managed_entrypoint = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        if text.count(bundled_entrypoint) != 1:
            raise SystemExit("Portainer package root bundled entrypoint contract changed")
        text = text.replace(bundled_entrypoint, managed_entrypoint, 1)
        if text.count('requires_core=">=2.4.0 <3.0.0"') != 1:
            raise SystemExit("Portainer bootstrap Core requirement contract changed")

    forbidden = (
        "from ...plugin_api",
        "from ...canonical_config",
        "from ...operator_ontology",
        "monitorbox.v2.integrations.portainer:PLUGIN",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"Portainer managed namespace rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous.previous.previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build9_overrides={len(BUILD9_OVERRIDE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    base = previous.previous.previous
    historical = set(base.HISTORICAL_FILENAMES) | {
        base.FILENAME,
        previous.previous.FILENAME,
        previous.FILENAME,
    }
    expected = historical | {FILENAME}
    unexpected = sorted(
        path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed Portainer packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
