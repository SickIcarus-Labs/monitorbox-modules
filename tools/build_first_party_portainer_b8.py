#!/usr/bin/env python3
"""Build Portainer v1.2.0 build 8 generic capability-evidence release."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_portainer_b7 as previous

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.2.0"
MODULE_BUILD = 8
IMPORT_PACKAGE = "monitorbox_portainer_b8"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD8_OVERRIDE_BLOBS = {
    "__init__.py": "5b48e49dc8e08e67b2270ccffe9e9a1c3d3d8dde",
    "suggestions.py": "672cb090685420d54061101d108b80503b153788",
}

_CORE_IMPORT_REWRITES = previous._CORE_IMPORT_REWRITES
_COMPATIBILITY_GUARD = previous._COMPATIBILITY_GUARD.replace(
    "managed Portainer build 7 requires", "managed Portainer build 8 requires"
)


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    build8 = previous.previous._verified_directory(
        root / "sources" / "portainer" / "1.2.0-build8",
        BUILD8_OVERRIDE_BLOBS,
        label="Portainer v1.2.0 build 8 generic-capability delta",
    )
    result.update(build8)
    if set(result) != set(previous.previous.BASE_SOURCE_BLOBS):
        raise SystemExit("Portainer build 8 composed source shape changed")
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

        old_core_requirement = 'requires_core=">=2.2.2 <3.0.0"'
        new_core_requirement = 'requires_core=">=2.3.0 <3.0.0"'
        if text.count(old_core_requirement) != 1:
            raise SystemExit("Portainer package root Core requirement contract changed")
        text = text.replace(old_core_requirement, new_core_requirement, 1)

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
    payload = previous.previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build8_overrides={len(BUILD8_OVERRIDE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    historical = set(previous.previous.HISTORICAL_FILENAMES) | {
        previous.previous.FILENAME,
        previous.FILENAME,
    }
    expected = historical | {FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
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
