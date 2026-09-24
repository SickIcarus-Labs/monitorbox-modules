#!/usr/bin/env python3
"""Isolated #219 UI 1.5.0 build41 over immutable corrected UI40.

UI40 retains its fail-closed site.cards admission guard. Build41 adds generic
opaque preference admission, a real managed editor route and two provider-blind
scripts; it does not repack an experimental 36-39 lineage or mutate signed b40.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build40 as previous

UI_VERSION = "1.5.0"
UI_BUILD = 41
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b41"
RELEASE41 = stable.Release(build=UI_BUILD, certified_sha="p3-219-opaque-card-layout", version=UI_VERSION)
SOURCE_BLOBS = {
    "card-layout-policy.js": "528139a08066be6e22defa6d9489786d380754bd",
    "card-layout.js": "24aa0d23d3981716f6741ad71b516a0d6d45d00d",
    "card-layout-editor.html": "152236ee3f44232a58f1562ddff249662c834d24",
    "card-layout-editor.js": "1c555ea5ff6eca165264184c277798743de6c924",
    "card-layout.css": "302a2764a12bb4de97ea2c20e45693a0d57febd1",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build41 {label} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _sources(root: Path) -> dict[str, bytes]:
    base = root / "sources" / "ui" / "1.5.0-build41"
    actual = {path.name for path in base.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(f"UI41 source drift: missing={expected-actual} extra={actual-expected}")
    output: dict[str, bytes] = {}
    for name, expected_sha in SOURCE_BLOBS.items():
        data = (base / name).read_bytes()
        digest = _git_blob_sha(data)
        if digest != expected_sha:
            raise SystemExit(f"UI41 source blob drift for {name}: {digest} != {expected_sha}")
        output[name] = data
    for name in ("card-layout-policy.js", "card-layout.js", "card-layout-editor.js"):
        script = output[name].lower()
        for forbidden in (b"unifi", b"scrypted", b"portainer", b"nut", b"meraki", b"eero"):
            if forbidden in script:
                raise SystemExit(f"UI41 provider coupling in {name}: {forbidden!r}")
    return output


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent, b"Standalone managed MonitorBox UI 1.4.1 build 40.",
        b"Standalone managed MonitorBox UI 1.5.0 build 41.", "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI41 missing explicit b40 parent identity")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    payload = _replace_once(
        payload, b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "card-layout-policy.js": "text/javascript",\n'
        b'    "card-layout.js": "text/javascript",\n'
        b'    "card-layout-editor.js": "text/javascript",\n'
        b'    "card-layout.css": "text/css",\n',
        "managed static assets",
    )
    page = b'''async def dashboard_cards_page(_: web.Request) -> web.Response:
    return web.Response(
        text=_resource("card-layout-editor.html").read_text(encoding="utf-8"),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


'''
    payload = _replace_once(
        payload,
        b"async def dashboard(_: web.Request) -> web.Response:\n",
        page + b"async def dashboard(_: web.Request) -> web.Response:\n",
        "card editor route handler",
    )
    guard = b'''def _require_opaque_preference_contract() -> None:
    try:
        from monitorbox.v2.module_preferences import (
            MODULE_PREFERENCES_CONTRACT_VERSION,
            MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION,
            register_preference_default,
        )
    except ImportError as exc:
        raise RuntimeError(
            "UI build41 requires Core opaque preference initialization v1; update Core via Recovery"
        ) from exc
    if (MODULE_PREFERENCES_CONTRACT_VERSION != 1 or
            MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION != 1):
        raise RuntimeError(
            "UI build41 requires Core opaque preference initialization v1; update Core via Recovery"
        )
    return register_preference_default


'''
    payload = _replace_once(
        payload,
        b"def install(app: web.Application) -> None:\n"
        b"    _require_card_projection_contract()\n",
        guard +
        b"def install(app: web.Application) -> None:\n"
        b"    _require_card_projection_contract()\n"
        b"    register_default = _require_opaque_preference_contract()\n"
        b'    register_default(app, "com.sickicarus.monitorbox.ui", {\n'
        b'        "schema_version": 1, "data": {"sites": {}},\n'
        b'    })\n'
        b'    app.router.add_get("/settings/cards", dashboard_cards_page)\n',
        "pre-route Core preference contract guard",
    )
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    inherited = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent: dict[str, bytes] = {}
    for path, payload in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit(f"UI41 foreign b40 package member {path}")
        parent[path[len(prefix):]] = payload

    delta = _sources(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        parent[path] = payload.replace(
            PARENT_GENERATION.encode(), UI_GENERATION.encode()
        ).replace(
            PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode()
        )
    for name, payload in delta.items():
        parent["assets/" + name] = payload

    script = (
        f'<script src="/static/card-layout-policy.js?v={UI_GENERATION}" defer></script>'
        f'<script src="/static/card-layout.js?v={UI_GENERATION}" defer></script>'
    ).encode()
    # The editor owns its full stylesheet. The homepage gets only its two
    # scoped controls; importing editor-wide body/top/button CSS would mutate
    # immutable UI40 dashboard styling as an accidental side effect.
    style = (
        b"<style>.card-layout-edit{display:inline-flex;align-items:center;"
        b"min-height:44px;margin:0 0 12px;padding:8px 12px;"
        b"border-radius:9px;border:1px solid currentColor;text-decoration:none}"
        b".card-layout-status{margin:0 0 12px;font-size:12px;color:#efbd66}"
        b".card-layout-status[hidden]{display:none}</style>"
    )
    parent["assets/dashboard.html"] = _replace_once(
        parent["assets/dashboard.html"], b"</head>", style + b"</head>",
        "dashboard style",
    )
    parent["assets/dashboard.html"] = _replace_once(
        parent["assets/dashboard.html"], b"</body>", script + b"</body>",
        "dashboard layout scripts",
    )
    html = parent["assets/dashboard.html"]
    if html.count(b"card-projection.js") != 1:
        raise SystemExit("UI41 lost or duplicated signed UI40 card projection")
    if html.count(b"card-layout-policy.js") != 1 or html.count(b"card-layout.js") != 1:
        raise SystemExit("UI41 failed to load shared dashboard policy")
    if any(PARENT_GENERATION.encode() in payload for payload in parent.values()):
        raise SystemExit("UI41 retained b40 generation metadata")
    if parent["assets/card-projection.js"] != inherited[prefix + "assets/card-projection.js"]:
        raise SystemExit("UI41 mutated immutable UI40 projector")
    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE41.filename
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
