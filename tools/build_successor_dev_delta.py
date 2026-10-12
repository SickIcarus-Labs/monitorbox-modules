"""Build the exact changed v3 Core/Manager packages without a signing key.

Caller checks out the explicitly approved Core commit. The unchanged Agent,
application modules and sealed Python/runtime dependencies are not rebuilt.
The output is an unsigned, 22-role Dev candidate, never an OCI publication.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from successor_dev_release import CORE, MANAGER, DevReleaseRefused, _records
from successor_dev_stage import stage_unsigned_dev_delta
from verify_platform_index import _date, verify_index, verify_package

SHA = re.compile(r"^[0-9a-f]{40}$")
ARCHES = ("amd64", "arm64")
KEY_ID = "official-ed25519-1"


def _call(argv: list[str], *, cwd: Path | None = None,
          env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, check=True, cwd=cwd, env=env)


def _json_from_package(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist().count("package.json") != 1:
                raise DevReleaseRefused("existing signed Core archive is ambiguous")
            value = json.loads(archive.read("package.json"))
        if not isinstance(value, dict):
            raise ValueError("package manifest is not object")
        return value
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise DevReleaseRefused("existing signed Core package has invalid manifest") from exc


def build_unsigned_dev(
    *, modules_root: Path, core_root: Path,
    previous_packages: Path, previous_dev_index: Path,
    output: Path, trust_root: Path, core_source_sha: str,
) -> dict:
    """Validate current Dev and build only four new ZIPs from the exact Core SHA."""
    if not isinstance(core_source_sha, str) or not SHA.fullmatch(core_source_sha):
        raise DevReleaseRefused("invalid exact Core source SHA")
    for path in (modules_root, core_root):
        if path.is_symlink() or not path.is_dir():
            raise DevReleaseRefused("reviewed source directory missing or linked")
    if output.exists() or output.is_symlink():
        raise DevReleaseRefused("refusing to overwrite candidate")
    source_sha = subprocess.check_output(
        ["git", "-C", str(core_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if source_sha != core_source_sha:
        raise DevReleaseRefused("Core checkout does not match approved commit")
    raw = previous_dev_index.read_bytes()
    try:
        index = json.loads(raw)
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trust_root.read_text().strip(), validate=True)
        )
        issued = _date(index["signed"]["generated_at"])
        signed = verify_index(raw, keys={KEY_ID: public}, channel="dev", now=issued)
        for item in signed["artifacts"]:
            verify_package(item, previous_packages.parent.parent, {KEY_ID: public})
        prior = _records(signed, channel="dev", full=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DevReleaseRefused("prior Dev catalog is not signed and complete") from exc

    with tempfile.TemporaryDirectory(prefix="monitorbox-unsigned-dev-") as td:
        work = Path(td)
        changes: dict[tuple[str, str], Path] = {}
        for arch in ARCHES:
            old_core = next(
                (item for key, item in prior.items()
                 if key[0] == CORE and key[2] == arch), None
            )
            old_manager = next(
                (item for key, item in prior.items()
                 if key[0] == MANAGER and key[2] == arch), None
            )
            if old_core is None or old_manager is None:
                raise DevReleaseRefused("prior signed Core/Manager architecture absent")
            version = old_core["version"]
            core_build = old_core["build"] + 1
            manager_version = old_manager["version"]
            manager_build = old_manager["build"] + 1
            existing_name = old_core["package"]["url"].removeprefix("platform/packages/")
            source_manifest = _json_from_package(previous_packages / existing_name)
            if source_manifest.get("artifact_id") != CORE:
                raise DevReleaseRefused("signed Core manifest artifact identity changed")
            runtime_ref = source_manifest.get("runtime")
            wheelhouse_ref = source_manifest.get("wheelhouse")
            if not isinstance(runtime_ref, dict) or not isinstance(wheelhouse_ref, dict):
                raise DevReleaseRefused("existing Core runtime/wheelhouse reference absent")
            out = work / arch
            out.mkdir()
            runtime_path = out / "runtime.json"
            wheel_path = out / "wheelhouse.json"
            runtime_path.write_text(json.dumps(runtime_ref, sort_keys=True))
            wheel_path.write_text(json.dumps(wheelhouse_ref, sort_keys=True))
            portable = out / "portable.json"
            _call([
                sys.executable, str(modules_root / "tools" / "portable_contracts.py"),
                "--artifact-id", CORE, "--version", version,
                "--build", str(core_build), "--output", str(portable),
            ])
            core_output = out / "new-core.zip"
            _call([
                sys.executable, str(core_root / "tools" / "build_successor_core3_package.py"),
                "--source-root", str(core_root),
                "--artifact-version", version, "--build", str(core_build),
                "--git-sha", core_source_sha,
                "--runtime-ref", str(runtime_path),
                "--wheelhouse-ref", str(wheel_path),
                "--portable-contract", str(portable),
                "--release-eligible", "--output", str(core_output),
            ])
            manager_binary = out / "monitorbox-scaffold"
            environment = dict(os.environ, CGO_ENABLED="0", GOOS="linux", GOARCH=arch)
            _call([
                "go", "build", "-trimpath", "-ldflags=-s -w",
                "-o", str(manager_binary), ".",
            ], cwd=core_root / "scaffold", env=environment)
            manager_output = out / "new-supervisor.zip"
            _call([
                sys.executable,
                str(core_root / "tools" / "build_successor_scaffold_manager_package.py"),
                "--binary", str(manager_binary), "--arch", arch,
                "--version", manager_version, "--build", str(manager_build),
                "--git-sha", core_source_sha,
                "--release-eligible", "--output", str(manager_output),
            ])
            changes[CORE, arch] = core_output
            changes[MANAGER, arch] = manager_output

        return stage_unsigned_dev_delta(
            previous_packages=previous_packages,
            previous_dev_index=previous_dev_index, replacements=changes,
            output=output, core_source_sha=core_source_sha,
            trust_root=trust_root,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules-root", type=Path, required=True)
    parser.add_argument("--core-root", type=Path, required=True)
    parser.add_argument("--previous-packages", type=Path, required=True)
    parser.add_argument("--previous-dev-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trust-root", type=Path, required=True)
    parser.add_argument("--core-source-sha", required=True)
    args = parser.parse_args()
    receipt = build_unsigned_dev(**vars(args))
    print("Unsigned Core/Supervisor Dev candidate staged (NOT SIGNED/PUBLISHED): " +
          json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
