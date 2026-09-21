#!/usr/bin/env python3
"""Acceptance for #359 provider child-adoption lifecycle authority."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"


def _run(tool: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / tool), "--output-dir", str(PACKAGES)],
        cwd=ROOT,
        check=True,
    )


def _inspect(filename: str, package_prefix: str) -> None:
    path = PACKAGES / filename
    if not path.is_file():
        raise SystemExit(f"candidate package is missing: {path}")
    with zipfile.ZipFile(path) as archive:
        adoption = archive.read(f"{package_prefix}/adoption.py").decode("utf-8")
        init = archive.read(f"{package_prefix}/__init__.py").decode("utf-8")
    compile(adoption, f"{filename}:adoption.py", "exec")
    if "def plan_candidate(" not in adoption:
        raise SystemExit(f"{filename}: candidate adoption does not emit a plan")
    if "def adopt_candidate(" in adoption:
        raise SystemExit(f"{filename}: legacy direct-mutation adoption contract remains")
    for needle in (
        'lifecycle_owner="connection"',
        'obj["depends_on"] = [connection_object_id]',
        "allowed_existing_object_ids=(connection_object_id,)",
        "expected_revision=context.current_revision",
        "expected_config_hash=context.current_hash",
    ):
        if needle not in adoption:
            raise SystemExit(f"{filename}: missing lifecycle transaction contract {needle!r}")
    if 'requires_core=">=2.6.0 <3.0.0"' not in init:
        raise SystemExit(f"{filename}: Core 2.6 adoption boundary is not declared")


def main() -> None:
    _run("build_first_party_scrypted_240.py")
    _run("build_first_party_portainer_b10.py")
    # UniFi build12 is still an unpublished candidate, so reconstruct it in-place
    # from its immutable build11 predecessor before inspecting the amended candidate.
    _run("build_first_party_unifi_b12.py")

    _inspect(
        "com.sickicarus.monitorbox.scrypted-2.4.0-build7.zip",
        "monitorbox_scrypted_v240_b7",
    )
    _inspect(
        "com.sickicarus.monitorbox.portainer-1.4.0-build10.zip",
        "monitorbox_portainer_b10",
    )
    _inspect(
        "com.sickicarus.monitorbox.unifi-1.1.1-build12.zip",
        "monitorbox_unifi_v111_b12",
    )
    print("candidate adoption lifecycle acceptance: PASS")


if __name__ == "__main__":
    main()
