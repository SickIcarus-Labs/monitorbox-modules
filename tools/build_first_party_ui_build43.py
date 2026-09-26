#!/usr/bin/env python3
"""UI43 #94: grouped-source dashboard composer over immutable accepted UI42."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build42 as previous

UI_VERSION = "1.7.0"
UI_BUILD = 43
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b43"
RELEASE43 = stable.Release(
    build=UI_BUILD, certified_sha="feature-94-grouped-card-composer", version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-composer-renderer.js": "65e8e8ebed7bf822d901e713ba17d3559a44a3b3",
    "card-composer.css": "3b725b3fd86a72eaefd6b7929a5a6cd8652a6cb5",
    "card-item-registry.js": "4533bfec7ea2db50fce042d853b9a3572b82cf3e",
    "card-layout-editor.html": "e8f922ebee91be7dd203d52bae56a3b6a5337253",
    "card-layout-editor.js": "396d6e6ebbd76346fac042d5b5caa54b1c8ddb45",
    "card-layout-policy.js": "34ece158d4c0bc4bc7f95b055ac19a5418dd1449",
    "card-layout.css": "e570812fb429399e57fc61deecb3c5a8a2092617",
    "card-layout.js": "b2cd72396bd8eb3478a41dbb3951efe0ac73f6ca",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI43 {label} seam changed: {old[:130]!r}")
    return payload.replace(old, new, 1)


def _sources(root: Path) -> dict[str, bytes]:
    base = root / "sources" / "ui" / "1.7.0-build43"
    actual = {p.name for p in base.iterdir() if p.is_file()}
    if actual != set(SOURCE_BLOBS):
        raise SystemExit(f"UI43 source inventory drift: {actual ^ set(SOURCE_BLOBS)}")
    result = {}
    for name, expected in SOURCE_BLOBS.items():
        blob = (base / name).read_bytes()
        if _git_blob_sha(blob) != expected:
            raise SystemExit(f"UI43 {name} source changed without reviewed fingerprint")
        result[name] = blob
    for name in ("card-item-registry.js", "card-layout-policy.js",
                 "card-layout.js", "card-layout-editor.js"):
        for forbidden in (b"unifi", b"scrypted", b"portainer", b"meraki", b"eero"):
            if forbidden in result[name].lower():
                raise SystemExit(f"UI43 provider-specific editor logic in {name}")
    return result


def _application(parent: bytes) -> bytes:
    data = _replace_once(
        parent, b"Standalone managed MonitorBox UI 1.6.0 build 42.",
        b"Standalone managed MonitorBox UI 1.7.0 build 43.", "module description",
    )
    data = data.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    data = data.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    data = _replace_once(
        data, b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "card-item-registry.js": "text/javascript",\n'
        b'    "card-composer-renderer.js": "text/javascript",\n'
        b'    "card-composer.css": "text/css",\n',
        "new static assets",
    )
    # No silent rewrite of historical schema-v1/v2 automatic snapshots. Newly
    # initialized layouts are v3; restored automatic v1/v2/v3 keep their schema.
    data = _replace_once(
        data, b'if current.get("schema_version") not in (1, 2):',
        b'if current.get("schema_version") not in (1, 2, 3):',
        "snapshot layout versions",
    )
    data = _replace_once(
        data,
        b'return {"schema_version": current["schema_version"] if current is not None else 2, "data": {"sites": output}}',
        b'return {"schema_version": current["schema_version"] if current is not None else 3, "data": {"sites": output}}',
        "default automatic snapshot version",
    )
    return data


def _package_files(root: Path) -> dict[str, bytes]:
    inherited = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent = {}
    for path, blob in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit(f"UI43 foreign inherited package member: {path}")
        parent[path[len(prefix):]] = blob
    delta = _sources(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for name, blob in list(parent.items()):
        parent[name] = blob.replace(
            PARENT_GENERATION.encode(), UI_GENERATION.encode()
        ).replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    for name, blob in delta.items():
        parent["assets/" + name] = blob

    html = parent["assets/dashboard.html"]
    html = _replace_once(
        html,
        b'<script src="/static/card-layout-policy.js?v=' + UI_GENERATION.encode(),
        b'<script src="/static/card-item-registry.js?v=' + UI_GENERATION.encode()
        + b'" defer></script>'
        + b'<script src="/static/card-layout-policy.js?v=' + UI_GENERATION.encode(),
        "registry before policy",
    )
    html = _replace_once(
        html,
        b'<script src="/static/card-layout.js?v=' + UI_GENERATION.encode() + b'" defer></script>',
        b'<script src="/static/card-layout.js?v=' + UI_GENERATION.encode() + b'" defer></script>'
        + b'<script src="/static/card-composer-renderer.js?v='
        + UI_GENERATION.encode() + b'" defer></script>',
        "renderer after inherited card wrapper",
    )
    html = _replace_once(
        html, b"</head>",
        b'<link rel="stylesheet" href="/static/card-composer.css?v='
        + UI_GENERATION.encode() + b'"></head>',
        "homepage-only composer styles",
    )
    parent["assets/dashboard.html"] = html
    if inherited[prefix + "assets/card-projection.js"] != parent["assets/card-projection.js"]:
        raise SystemExit("UI43 modified accepted UI40 canonical projector")
    if parent["assets/card-layout-editor.html"].count(b'itemPicker') != 1:
        raise SystemExit("UI43 grouped item picker was not included")
    if any(PARENT_GENERATION.encode() in blob for blob in parent.values()):
        raise SystemExit("UI43 package contains stale generation identity")
    return {f"{TARGET_IMPORT_PACKAGE}/{name}": blob for name, blob in parent.items()}


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE43.filename
    target.write_bytes(payload)
    print(f"UI43 dev candidate {target}: sha256={hashlib.sha256(payload).hexdigest()}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent.parent / "packages")
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent, args.output_dir)


if __name__ == "__main__":
    main()
