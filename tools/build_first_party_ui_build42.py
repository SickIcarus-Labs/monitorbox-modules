#!/usr/bin/env python3
"""UI 1.6.0 build42: #91 Dashboard Cards/Graphs, content, curated promotion.

Builds over immutable beta-accepted UI41 without rewriting its source or ZIP.
The public Core authority stays unchanged; UI-owned optional card presentation
is preserved as opaque canonical module_preferences in existing snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build41 as previous

UI_VERSION = "1.6.0"
UI_BUILD = 42
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b42"
RELEASE42 = stable.Release(
    build=UI_BUILD, certified_sha="p1-91-dashboard-card-editor", version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-layout-policy.js": "30789db3c044b099f32028cf6e73516ac303c4d5",
    "card-layout.js": "205dcb8a3ebb40ca9a605ff90b1d92ffbbb5d5b5",
    "card-layout-editor.html": "fcee73dbb60898dd5758d3e17b7319c0bc882083",
    "card-layout-editor.js": "94a3769b63b257bd6a33d410fab9f409e4624eb2",
    "card-layout.css": "5de979130259c9b8c781a81b4cedfc17a932ccdd",
    "dashboard-editor-tabs.js": "0a4c5929612077fb488ed6ed98de68feaf23fe51",
    "dashboard-editor-tabs.css": "b67a8b9af08c37c0825db9b110ee9fe1dd3d5a98",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI42 {label} seam changed: {old[:130]!r}")
    return payload.replace(old, new, 1)


def _sources(root: Path) -> dict[str, bytes]:
    base = root / "sources" / "ui" / "1.6.0-build42"
    actual = {item.name for item in base.iterdir() if item.is_file()}
    if actual != set(SOURCE_BLOBS):
        raise SystemExit(f"UI42 source drift: {actual ^ set(SOURCE_BLOBS)}")
    result = {}
    for name, expected in SOURCE_BLOBS.items():
        blob = (base / name).read_bytes()
        if _git_blob_sha(blob) != expected:
            raise SystemExit(f"UI42 {name} source blob changed")
        result[name] = blob
    for name in ("card-layout-policy.js", "card-layout.js", "card-layout-editor.js"):
        for forbidden in (b"unifi", b"scrypted", b"portainer", b"meraki", b"eero"):
            if forbidden in result[name].lower():
                raise SystemExit(f"UI42 provider coupling in {name}: {forbidden!r}")
    return result


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent, b"Standalone managed MonitorBox UI 1.5.0 build 41.",
        b"Standalone managed MonitorBox UI 1.6.0 build 42.", "version",
    )
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    payload = _replace_once(
        payload, b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "dashboard-editor-tabs.js": "text/javascript",\n'
        b'    "dashboard-editor-tabs.css": "text/css",\n',
        "static assets",
    )
    # UI41 historic v1 remains byte-for-byte; UI42 initializes new automatic
    # snapshots as v2 and keeps existing v1/v2 auto layouts reconcilable.
    payload = _replace_once(
        payload, b'if current.get("schema_version") != 1:',
        b'if current.get("schema_version") not in (1, 2):',
        "initialization accepts v1 and v2",
    )
    payload = _replace_once(
        payload, b'return {"schema_version": 1, "data": {"sites": output}}',
        b'return {"schema_version": current["schema_version"] if current is not None else 2, "data": {"sites": output}}',
        "new automatic snapshots are v2",
    )

    middleware = rf'''_DASHBOARD_EDITOR_TABS = (
    '<link rel="stylesheet" href="/static/dashboard-editor-tabs.css?v={UI_GENERATION}">'
    '<script src="/static/dashboard-editor-tabs.js?v={UI_GENERATION}" defer></script>'
)


@web.middleware
async def dashboard_editor_tabs_middleware(request: web.Request, handler):
    response = await handler(request)
    if (
        request.path != "/settings/dashboard"
        or not isinstance(response, web.Response)
        or response.content_type != "text/html"
        or not response.body
    ):
        return response
    markup = response.text
    if _DASHBOARD_EDITOR_TABS not in markup and "</body>" in markup:
        response.text = markup.replace("</body>", _DASHBOARD_EDITOR_TABS + "</body>", 1)
    return response


'''.encode("utf-8")
    payload = _replace_once(
        payload, b"async def dashboard(_: web.Request) -> web.Response:\n",
        middleware + b"async def dashboard(_: web.Request) -> web.Response:\n",
        "Dashboard editor navigation middleware",
    )
    route = b'    app.router.add_get("/settings/cards", dashboard_cards_page)\n'
    payload = _replace_once(
        payload, route, route + b"    app.middlewares.append(dashboard_editor_tabs_middleware)\n",
        "Dashboard editor middleware registration",
    )
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    inherited = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent = {}
    for name, blob in inherited.items():
        if not name.startswith(prefix):
            raise SystemExit(f"UI42 foreign UI41 member: {name}")
        parent[name[len(prefix):]] = blob
    delta = _sources(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for name, blob in list(parent.items()):
        parent[name] = blob.replace(
            PARENT_GENERATION.encode(), UI_GENERATION.encode()
        ).replace(
            PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode()
        )
    for name, blob in delta.items():
        parent["assets/" + name] = blob

    # Cards is a peer of Graphs in Configuration. The existing b35 peer-nav
    # gets only the generic route classification; signed b41 source stays intact.
    nav = parent["assets/configuration-peer-navigation.js"]
    parent["assets/configuration-peer-navigation.js"] = _replace_once(
        nav,
        b"if (pathname.startsWith('/settings/dashboard')) return 'dashboard';",
        b"if (pathname.startsWith('/settings/dashboard') || "
        b"pathname.startsWith('/settings/cards')) return 'dashboard';",
        "Dashboard peer classification",
    )
    html = parent["assets/dashboard.html"]
    html = _replace_once(html, b"Dashboard / Graphs", b"Dashboard", "settings link")
    html = _replace_once(
        html, b"</head>",
        b"<style>.parity-card.mb-card-compact .parity-card-copy,"
        b".parity-card.mb-card-compact .parity-mini-directory,"
        b".parity-card.mb-card-compact .parity-camera-directory,"
        b".parity-card.mb-card-compact .parity-power-list{display:none}</style></head>",
        "compact homepage presentation",
    )
    parent["assets/dashboard.html"] = html
    if html.count(b"card-layout-policy.js") != 1 or html.count(b"card-layout.js") != 1:
        raise SystemExit("UI42 lost inherited composition scripts")
    if b"card-layout-edit" in delta["card-layout.js"]:
        raise SystemExit("UI42 still inserts the homepage card editor button")
    if inherited[prefix + "assets/card-projection.js"] != parent["assets/card-projection.js"]:
        raise SystemExit("UI42 modified accepted UI40 projector")
    if any(PARENT_GENERATION.encode() in blob for blob in parent.values()):
        raise SystemExit("UI42 contains stale generation identity")
    return {f"{TARGET_IMPORT_PACKAGE}/{name}": blob for name, blob in parent.items()}


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    blob = stable._zip_bytes(_package_files(root))
    path = output_dir / RELEASE42.filename
    path.write_bytes(blob)
    print(f"UI42 candidate {path}: sha256={hashlib.sha256(blob).hexdigest()}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent.parent/"packages")
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent, args.output_dir)


if __name__ == "__main__":
    main()
