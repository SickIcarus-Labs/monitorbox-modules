#!/usr/bin/env python3
"""Build #353 MonitorBox UI v1.3.2 build 37.

Build 37 supersedes signed-dev build 36 before physical acceptance. Its only
functional delta is a non-mutating Core compatibility/removal review preflight;
all #220 provider-blind aggregate work from build 36 is retained byte-for-byte.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build36 as previous

UI_VERSION = "1.3.2"
UI_BUILD = 37
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b37"
RELEASE37 = stable.Release(
    build=UI_BUILD,
    certified_sha="p1-353-safe-removal-preflight",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "modules-removal.js": "54369247629af65f146bbcd50a8aaf1ce94718a2",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-37 {seam} seam changed: {old[:180]!r}")
    return payload.replace(old, new, 1)


def _replace_region(
    payload: bytes,
    start_marker: bytes,
    end_marker: bytes,
    replacement: bytes,
    seam: str,
) -> bytes:
    start = payload.find(start_marker)
    end = payload.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise SystemExit(f"UI build-37 {seam} region changed")
    return payload[:start] + replacement.rstrip() + b"\n\n" + payload[end:]


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.3.2-build37"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(
            "UI build-37 delta shape changed: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    result = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI build-37 source drift for {name}: expected {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent,
        b"Standalone managed MonitorBox UI 1.3.2 build 36.",
        b"Standalone managed MonitorBox UI 1.3.2 build 37.",
        "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI build-37 parent application has no build-36 generation marker")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    signed_parent = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent = {}
    for path, payload in signed_parent.items():
        if not path.startswith(prefix):
            raise SystemExit(f"unexpected UI build-36 package member {path!r}")
        parent[path[len(prefix):]] = payload

    delta = _delta_files(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        parent[path] = payload

    parent["assets/modules.js"] = _replace_region(
        parent["assets/modules.js"],
        b"  function moduleRemovalImpactLines(review) {\n",
        b"  async function updateAllModules() {",
        delta["modules-removal.js"],
        "Modules safe removal lifecycle",
    )

    modules_lower = delta["modules-removal.js"].lower()
    for token in (b"unifi", b"scrypted", b"portainer", b"nut"):
        if token in modules_lower:
            raise SystemExit(
                "UI build37 contains provider-specific module-removal coupling: "
                + token.decode("utf-8")
            )
    required = (
        b"/remove/review",
        b"safe_simple_remove",
        b"Update Core before removing modules",
        b"/remove/apply",
    )
    for token in required:
        if token not in delta["modules-removal.js"]:
            raise SystemExit(f"UI build37 missing safe removal token: {token!r}")

    if any(PARENT_GENERATION.encode() in payload for payload in parent.values()):
        raise SystemExit("UI build37 package retained build36 generation identity")

    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = stable._zip_bytes(files)
    target = output_dir / RELEASE37.filename
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={TARGET_IMPORT_PACKAGE}:install"
    )
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
