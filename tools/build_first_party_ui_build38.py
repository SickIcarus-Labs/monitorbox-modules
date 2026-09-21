#!/usr/bin/env python3
"""Build #359/#220 MonitorBox UI v1.4.0 build 38.

Build 38 is the first dashboard generation that consumes controller-projected
card families rather than requiring same-id canonical aggregate Resources.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build37 as previous

UI_VERSION = "1.4.0"
UI_BUILD = 38
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b38"
RELEASE38 = stable.Release(
    build=UI_BUILD,
    certified_sha="p0-359-dashboard-card-projection",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-projection.js": "3b49e1b2225d294f26503b011588b82844d3aa30",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-38 {seam} seam changed: {old[:180]!r}")
    return payload.replace(old, new, 1)


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.4.0-build38"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(
            "UI build-38 delta shape changed: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI build-38 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent,
        b"Standalone managed MonitorBox UI 1.3.2 build 37.",
        b"Standalone managed MonitorBox UI 1.4.0 build 38.",
        "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI build-38 parent application has no build-37 generation marker")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    payload = _replace_once(
        payload,
        b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "card-projection.js": "text/javascript",\n',
        "asset registry",
    )
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    signed_parent = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent: dict[str, bytes] = {}
    for path, payload in signed_parent.items():
        if not path.startswith(prefix):
            raise SystemExit(f"unexpected UI build-37 package member {path!r}")
        parent[path[len(prefix):]] = payload

    delta = _delta_files(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        parent[path] = payload

    parent["assets/card-projection.js"] = delta["card-projection.js"]

    aggregate_script = (
        f'<script src="/static/aggregate-evidence.js?v={UI_GENERATION}" defer></script>'
    ).encode("utf-8")
    projection_script = (
        f'<script src="/static/card-projection.js?v={UI_GENERATION}" defer></script>'
    ).encode("utf-8")
    parent["assets/dashboard.html"] = _replace_once(
        parent["assets/dashboard.html"],
        aggregate_script,
        projection_script,
        "dashboard projection script",
    )

    projection = delta["card-projection.js"].lower()
    for forbidden in (b"unifi", b"scrypted", b"portainer", b"nut", b"docker"):
        if forbidden in projection:
            raise SystemExit(
                "UI build38 card projection contains provider/product coupling: "
                + forbidden.decode("utf-8")
            )
    for required in (
        b"site?.cards",
        b"dashboard_card",
        b"projectedcoreobjects",
        b"object.kind === 'host'",
    ):
        if required not in projection:
            raise SystemExit(f"UI build38 card projection missing contract: {required!r}")

    dashboard = parent["assets/dashboard.html"]
    if b"aggregate-evidence.js" in dashboard:
        raise SystemExit("UI build38 still loads build37 aggregate-evidence fallback")
    if projection_script not in dashboard:
        raise SystemExit("UI build38 dashboard does not load card projection")

    if any(PARENT_GENERATION.encode() in payload for payload in parent.values()):
        raise SystemExit("UI build38 package retained build37 generation identity")

    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = stable._zip_bytes(files)
    target = output_dir / RELEASE38.filename
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
