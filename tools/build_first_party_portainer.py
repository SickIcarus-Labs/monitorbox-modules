#!/usr/bin/env python3
"""Build the current managed Portainer integration for frozen MonitorBox 2.3 Core.

Portainer build 2 remains immutable release history in ``sources/`` and
``packages/``. Build 3 is a verified optimization delta over build 2. Build 4 is
a minimal activation hotfix delta over that effective build-3 source. Build 5 is
the release-certified successor for #126: it preserves the effective build-4
runtime while advancing immutable module identity after lifecycle acceptance.
The builder verifies every generation before composing the complete
generation-safe managed package.
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
MODULE_BUILD = 5
IMPORT_PACKAGE = "monitorbox_portainer_b5"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(
    {
        f"{MODULE_ID}-{MODULE_VERSION}-build2.zip",
        f"{MODULE_ID}-{MODULE_VERSION}-build3.zip",
        f"{MODULE_ID}-{MODULE_VERSION}-build4.zip",
    }
)

BASE_SOURCE_BLOBS = {
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

BUILD3_OVERRIDE_BLOBS = {
    "__init__.py": "1e2914562205ff7302bb1785ab7111512ca211c1",
    "onboarding.py": "f1d4a9c356bb3b8a29be5a87995f6bcd972ccfa6",
    "runtime.py": "3d68cdb507b1f70248476f9fa4e3356ecf6781ef",
}

BUILD4_OVERRIDE_BLOBS = {
    "__init__.py": "ada109385129e975e2c55dc4f1b2c840236a13f3",
    "validation.py": "b6856089ce01cbe69818ff6a2abd6294a4305ee8",
}

BUILD5_OVERRIDE_BLOBS = {
    "__init__.py": "a4dca6fc485387c17bff564a689384b9b52295b2",
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
        "managed Portainer build 5 requires MonitorBox Core build 0545+ provider authority"
    ) from exc
else:
    del _managed_provider_authority

'''


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verified_directory(
    source_root: Path,
    expected_blobs: dict[str, str],
    *,
    label: str,
) -> dict[str, bytes]:
    actual_names = {
        path.name
        for path in source_root.iterdir()
        if path.is_file()
    }
    expected_names = set(expected_blobs)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(
            f"{label} source shape changed: missing={missing}, extra={extra}"
        )

    result: dict[str, bytes] = {}
    for name, expected_blob in expected_blobs.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"{label} source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _source_files(root: Path) -> dict[str, bytes]:
    portainer_root = root / "sources" / "portainer"
    base = _verified_directory(
        portainer_root / "1.0.0-build2",
        BASE_SOURCE_BLOBS,
        label="immutable Portainer build 2",
    )
    build3 = _verified_directory(
        portainer_root / "1.0.0-build3",
        BUILD3_OVERRIDE_BLOBS,
        label="immutable Portainer build 3 delta",
    )
    build4 = _verified_directory(
        portainer_root / "1.0.0-build4",
        BUILD4_OVERRIDE_BLOBS,
        label="immutable Portainer build 4 activation-hotfix delta",
    )
    build5 = _verified_directory(
        portainer_root / "1.0.0-build5",
        BUILD5_OVERRIDE_BLOBS,
        label="Portainer build 5 release-certification delta",
    )
    result = dict(base)
    result.update(build3)
    result.update(build4)
    result.update(build5)
    if set(result) != set(BASE_SOURCE_BLOBS):
        raise SystemExit("Portainer build 5 composed source set does not match build 2 shape")
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
        f"base_build=2 build3_overrides={len(BUILD3_OVERRIDE_BLOBS)} "
        f"build4_overrides={len(BUILD4_OVERRIDE_BLOBS)} "
        f"build5_overrides={len(BUILD5_OVERRIDE_BLOBS)} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
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
