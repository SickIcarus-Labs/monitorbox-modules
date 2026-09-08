#!/usr/bin/env python3
"""Build Portainer v1.1.1 build 7 over immutable build-6 source history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_portainer as previous

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.1.1"
MODULE_BUILD = 7
IMPORT_PACKAGE = "monitorbox_portainer_b7"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD7_OVERRIDE_BLOBS = {
    "__init__.py": "7721fdb3163e6f4da1fb9795ee481ecd2bf7595d",
    "endpoint_provenance.py": "21d1f0a7759fed8829a87b0032a827d443049bef",
    "suggestions.py": "4ee9b544f9f2d1ca8c1c4a6bee889b4994fc284a",
}

_CORE_IMPORT_REWRITES = previous._CORE_IMPORT_REWRITES
_COMPATIBILITY_GUARD = previous._COMPATIBILITY_GUARD.replace(
    "managed Portainer build 6 requires", "managed Portainer build 7 requires"
)


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    build7 = previous._verified_directory(
        root / "sources" / "portainer" / "1.1.1-build7",
        BUILD7_OVERRIDE_BLOBS,
        label="Portainer v1.1.1 build 7 Phase-2 delta",
    )
    result.update(build7)
    if set(result) != set(previous.BASE_SOURCE_BLOBS):
        raise SystemExit("Portainer build 7 composed source shape changed")
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
    payload = previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build7_overrides={len(BUILD7_OVERRIDE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    historical = set(previous.HISTORICAL_FILENAMES) | {previous.FILENAME}
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
