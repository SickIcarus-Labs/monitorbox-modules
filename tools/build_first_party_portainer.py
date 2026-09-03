#!/usr/bin/env python3
"""Build the certified managed Portainer integration for MonitorBox Core 0545+.

The source snapshot is vendored byte-for-byte from the certified MonitorBox
provider line. Packaging verifies every Git blob before applying only the
mechanical transforms required to move the provider out of Core's bundled
namespace and into a generation-safe managed-module namespace.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 2
CERTIFIED_SOURCE_SHA = "a707ace84a9112dca519fdcf0196fdc3bb990fa4"
IMPORT_PACKAGE = "monitorbox_portainer_b2"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"

SOURCE_BLOBS = {
    "__init__.py": "7757ab39a71d9a851dc942538b1961e9e7ee516f",
    "adoption.py": "5a6e8bd9b679665ec03e80bfb4a1a157396643ad",
    "deployment_transition.py": "ef291fcedb0f8faabda077cd6e5fe6fbe5480bd3",
    "endpoint_provenance.py": "ff66786fdaafcae5d4bb9d348da572fc178afb53",
    "expected_state_diagnostics.py": "68821de7451938fcdb74063fd4fa6dc52b0396d0",
    "lifecycle_diagnostics.py": "bfbec886d679170293eaed94c287d30f1eb584f1",
    "lifecycle_truth.py": "0ad1cbdcba9728433454150d5b89ff2c47ac7a90",
    "onboarding.py": "5347eeb9a9d91e9b93d6c11aed9e6a92868a5e77",
    "reconciliation.py": "17666cf02995d593ad8bb8aa8b11d46bef2a0154",
    "review.py": "e6e8a2653ac584cd96afdd6ba88f4378c773f304",
    "runtime.py": "49e85c2dc853f41fb49c55312956ae25fa832e76",
    "suggestions.py": "38d445510118af7be8219612003febe2cc2ce414",
    "validation.py": "78f3011d8cf417ef55b225439a635df39bd634c6",
}

_CORE_IMPORT_REWRITES = (
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
    ("from ...canonical_config", "from monitorbox.v2.canonical_config"),
    ("from ...operator_ontology", "from monitorbox.v2.operator_ontology"),
)

_COMPATIBILITY_GUARD = '''# Managed Portainer execution requires the generic provider-authority seam
# introduced by the certified MonitorBox 2.3 build 0545 Core. 2.3 build 0544
# shares the same SemVer/runtime-API identity, so package import is the final
# fail-closed capability boundary for that superseded Core checkpoint.
try:
    from monitorbox.v2.plugin_api.provider_authority import (
        load_provider_registry as _managed_provider_authority,
    )
except ImportError as exc:  # pragma: no cover - exercised against superseded Core
    raise ImportError(
        "managed Portainer build 2 requires MonitorBox Core build 0545 provider authority"
    ) from exc
else:
    del _managed_provider_authority

'''


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "portainer" / "1.0.0-build2"
    actual_names = {
        path.name
        for path in source_root.iterdir()
        if path.is_file()
    }
    expected_names = set(SOURCE_BLOBS)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(
            f"certified Portainer source shape changed: missing={missing}, extra={extra}"
        )

    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"certified Portainer source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
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
    payload = _zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"certified_source={CERTIFIED_SOURCE_SHA} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name != FILENAME
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
