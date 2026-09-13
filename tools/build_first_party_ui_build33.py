#!/usr/bin/env python3
"""Reproduce signed contextual-configuration UI v1.2.1 build 33.

Build 33 is already materialized in the signed dev repository. The signed
artifact is therefore the immutable package authority; this retained builder
verifies the package digest, validates the reviewable #315 source delta against
the signed assets, and reproduces the exact ZIP bytes deterministically.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

import build_first_party_ui as stable

UI_VERSION = "1.2.1"
UI_BUILD = 33
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b33"
SIGNED_RELEASE_SHA256 = "f8ccf19a279ce6cc29d8bb9c3773e1ac4427b2b6ce45dacf9052b16071290412"
RELEASE33 = stable.Release(build=UI_BUILD, certified_sha="p0-315-contextual-configuration-fix", version=UI_VERSION)
SOURCE_BLOBS = {
    "contextual-configuration.js": "3a1267e88ad060f358b358c94ff83804351ee536",
    "contextual-configuration.css": "e4d34cda75dee76ed5ff47aef6c408835f816c26",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.2.1-build33"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(f"UI build-33 delta shape changed: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(f"UI build-33 source drift for {name}: expected Git blob {expected_blob}, got {actual_blob}")
        result[name] = payload
    return result


def _package_files(root: Path) -> dict[str, bytes]:
    package = root / "channels" / "dev" / "packages" / RELEASE33.filename
    payload = package.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != SIGNED_RELEASE_SHA256:
        raise SystemExit(f"signed UI build-33 drift: expected {SIGNED_RELEASE_SHA256}, got {actual}")

    files: dict[str, bytes] = {}
    prefix = TARGET_IMPORT_PACKAGE + "/"
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(prefix):
                raise SystemExit(f"unexpected signed UI build-33 package member {info.filename!r}")
            files[info.filename] = archive.read(info)

    init_key = f"{TARGET_IMPORT_PACKAGE}/__init__.py"
    dashboard_key = f"{TARGET_IMPORT_PACKAGE}/assets/dashboard.js"
    if init_key not in files or dashboard_key not in files:
        raise SystemExit("signed UI build-33 package is missing standalone UI authority")
    init = files[init_key]
    if UI_GENERATION.encode() not in init:
        raise SystemExit("signed UI build-33 package identity drift")

    delta = _delta_files(root)
    for name, source_payload in delta.items():
        package_key = f"{TARGET_IMPORT_PACKAGE}/assets/{name}"
        if files.get(package_key) != source_payload:
            raise SystemExit(f"signed UI build-33 asset {name} does not match retained source")

    contextual = delta["contextual-configuration.js"].lower()
    for token in (b"portainer", b"scrypted", b"unifi", b"data-object-gear"):
        if token in contextual:
            raise SystemExit("contextual UI build33 contains provider/row-control coupling: " + token.decode("utf-8"))
    if b"monitorbox.v2.modules.ui" in init:
        raise SystemExit("standalone UI build33 references retired Core UI authority")
    return files


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = stable._zip_bytes(files)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != SIGNED_RELEASE_SHA256:
        raise SystemExit(f"UI build-33 signed reproducibility drift: expected {SIGNED_RELEASE_SHA256}, got {digest}")
    target = output_dir / RELEASE33.filename
    target.write_bytes(payload)
    print(f"built {target}: sha256={digest} entrypoint={TARGET_IMPORT_PACKAGE}:install")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
