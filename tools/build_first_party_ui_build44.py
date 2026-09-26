#!/usr/bin/env python3
"""UI44 #94: inline live dashboard readings layered over immutable signed UI43."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build43 as previous

UI_VERSION = "1.8.0"
UI_BUILD = 44
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b44"
RELEASE44 = stable.Release(
    build=UI_BUILD, certified_sha="feature-94-live-inline-composer", version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-composer-renderer.js": "38a2c3941aaa4cd2e293b2302cdd71a14504c7f6",
    "card-composer.css": "ca5a855d82c10c1a467ad39a2d45cfc0adcaa876",
    "card-item-registry.js": "a07b74337de9f1303b80ef93bd578d27b9445711",
    "card-layout-editor.html": "ee26461ec68fcb51c63f193fe98940272d4dfae7",
    "card-layout-editor.js": "9e2079cbcaf1508aeaf6ee645feca24d8e5f21b7",
    "card-layout-policy.js": "0694c1068603af7fe083f90b08287333c4ff73e7",
    "card-layout.css": "e570812fb429399e57fc61deecb3c5a8a2092617",
    "card-layout.js": "b2cd72396bd8eb3478a41dbb3951efe0ac73f6ca",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def _sources(root: Path) -> dict[str, bytes]:
    folder = root / "sources" / "ui" / "1.8.0-build44"
    if {p.name for p in folder.iterdir() if p.is_file()} != set(SOURCE_BLOBS):
        raise SystemExit("UI44 source inventory drift")
    source = {}
    for name, expected in SOURCE_BLOBS.items():
        payload = (folder / name).read_bytes()
        if _git_blob_sha(payload) != expected:
            raise SystemExit(f"UI44 unreviewed source fingerprint: {name}")
        source[name] = payload
    for name in ("card-item-registry.js", "card-layout-policy.js",
                 "card-layout.js", "card-layout-editor.js"):
        for provider in (b"unifi", b"scrypted", b"portainer", b"meraki", b"eero"):
            if provider in source[name].lower():
                raise SystemExit(f"UI44 shared composer contains provider-specific logic: {name}")
    return source


def _package_files(root: Path) -> dict[str, bytes]:
    inherited = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent: dict[str, bytes] = {}
    for path, content in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit(f"Foreign inherited UI43 package member: {path}")
        parent[path[len(prefix):]] = content
    # Preserve all accepted Core-facing routes and the schema-v3 snapshot owner;
    # only immutable package identity and static presentation assets advance.
    parent["__init__.py"] = previous._replace_once(
        parent["__init__.py"],
        b"Standalone managed MonitorBox UI 1.7.0 build 43.",
        b"Standalone managed MonitorBox UI 1.8.0 build 44.",
        "module description",
    )
    for name, content in list(parent.items()):
        parent[name] = content.replace(
            PARENT_GENERATION.encode(), UI_GENERATION.encode()
        ).replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    for name, content in _sources(root).items():
        parent["assets/" + name] = content

    html = parent["assets/dashboard.html"]
    required = [
        b"/static/card-item-registry.js?v=" + UI_GENERATION.encode(),
        b"/static/card-layout-policy.js?v=" + UI_GENERATION.encode(),
        b"/static/card-layout.js?v=" + UI_GENERATION.encode(),
        b"/static/card-composer-renderer.js?v=" + UI_GENERATION.encode(),
        b"/static/card-composer.css?v=" + UI_GENERATION.encode(),
    ]
    if any(html.count(path) != 1 for path in required):
        raise SystemExit("UI44 homepage is missing or duplicating an asset")
    if not (html.index(required[0]) < html.index(required[1])
            < html.index(required[2]) < html.index(required[3])):
        raise SystemExit("UI44 deferred script dependency order changed")
    if parent["assets/card-layout-editor.html"].count(b'itemPicker') != 1:
        raise SystemExit("UI44 shared item picker disappeared")
    if inherited[prefix + "assets/card-projection.js"] != parent["assets/card-projection.js"]:
        raise SystemExit("UI44 changed accepted canonical Core card projection")
    if PARENT_GENERATION.encode() in html:
        raise SystemExit("UI44 homepage contains stale UI43 script identities")
    return {TARGET_IMPORT_PACKAGE + "/" + name: blob
            for name, blob in parent.items()}


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE44.filename
    target.write_bytes(data)
    print(f"UI44 dev candidate {target}: sha256={hashlib.sha256(data).hexdigest()}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "packages")
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent, args.output_dir)


if __name__ == "__main__":
    main()
