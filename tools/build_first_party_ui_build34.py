#!/usr/bin/env python3
"""Build #316 global Settings-shell UI v1.3.0 build 34.

Build 34 derives from the signed dev build33 authority, preserving #315 exactly
while replacing #289's hamburger/global-nav presentation with the accepted
global Settings cog and folding #305's responsive Debug polish into the same
shared-shell delta.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build33 as previous

UI_VERSION = "1.3.0"
UI_BUILD = 34
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b34"
RELEASE34 = stable.Release(
    build=UI_BUILD,
    certified_sha="p0-316-global-settings-shell",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "settings-shell.js": "a5f8526d46c9a4373f6b950bdda9db6631e86107",
    "settings-shell.css": "06beb6ba1f717667252747b52fa9fe387c78e350",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-34 {seam} seam changed: {old[:180]!r}")
    return payload.replace(old, new, 1)


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.3.0-build34"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(
            "UI build-34 delta shape changed: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI build-34 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent,
        b"Standalone managed MonitorBox UI 1.2.1 build 33.",
        b"Standalone managed MonitorBox UI 1.3.0 build 34.",
        "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI build-34 parent application has no build-33 generation marker")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    payload = _replace_once(
        payload,
        b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "settings-shell.js": "text/javascript",\n'
        b'    "settings-shell.css": "text/css",\n',
        "asset registry",
    )

    middleware = rf'''_GLOBAL_DEBUG_STYLE = '<link rel="stylesheet" href="/static/global-debug.css?v={UI_GENERATION}">'
_GLOBAL_DEBUG_SCRIPT = '<script src="/static/global-debug.js?v={UI_GENERATION}" defer></script>'


def _has_element_id(markup: str, element_id: str) -> bool:
    return ('id="' + element_id + '"') in markup or ("id='" + element_id + "'") in markup


def _canonical_global_debug_fragments() -> tuple[str, str]:
    """Reuse the signed Dashboard's canonical Debug markup on every HTML surface."""
    dashboard_markup = _resource("dashboard.html").read_text(encoding="utf-8")

    toggle_start = dashboard_markup.find('<button id="debug-toggle"')
    toggle_end = dashboard_markup.find("</button>", toggle_start)
    console_start = dashboard_markup.find('<aside id="debug-console"')
    console_end = dashboard_markup.find("</aside>", console_start)
    if min(toggle_start, toggle_end, console_start, console_end) < 0:
        raise RuntimeError("canonical Dashboard Debug markup is incomplete")

    toggle_end += len("</button>")
    console_end += len("</aside>")
    return (
        dashboard_markup[toggle_start:toggle_end],
        dashboard_markup[console_start:console_end],
    )


@web.middleware
async def global_debug_presentation(request: web.Request, handler):
    response = await handler(request)
    if not (
        isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        return response

    markup = response.text
    if _GLOBAL_DEBUG_STYLE not in markup and "</head>" in markup:
        markup = markup.replace("</head>", _GLOBAL_DEBUG_STYLE + "</head>", 1)

    toggle, console = _canonical_global_debug_fragments()
    additions = []
    if not _has_element_id(markup, "debug-toggle"):
        additions.append(toggle)
    if not _has_element_id(markup, "debug-console"):
        additions.append(console)
    if _GLOBAL_DEBUG_SCRIPT not in markup:
        additions.append(_GLOBAL_DEBUG_SCRIPT)
    if additions and "</body>" in markup:
        markup = markup.replace("</body>", "".join(additions) + "</body>", 1)

    response.text = markup
    return response


@web.middleware
async def settings_shell_presentation(request: web.Request, handler):
    response = await handler(request)
    if not (
        isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        return response
    markup = response.text
    style = '<link rel="stylesheet" href="/static/settings-shell.css?v={UI_GENERATION}">'
    script = '<script src="/static/settings-shell.js?v={UI_GENERATION}" defer></script>'
    additions = []
    if style not in markup:
        additions.append(style)
    if script not in markup:
        additions.append(script)
    if additions and "</body>" in markup:
        response.text = markup.replace("</body>", "".join(additions) + "</body>", 1)
    return response


'''.encode("utf-8")
    payload = _replace_once(
        payload,
        b"async def dashboard(_: web.Request) -> web.Response:\n",
        middleware + b"async def dashboard(_: web.Request) -> web.Response:\n",
        "settings shell and global Debug middleware",
    )
    payload = _replace_once(
        payload,
        b"def install(app: web.Application) -> None:\n"
        b"    app.middlewares.append(contextual_configuration_presentation)\n",
        b"def install(app: web.Application) -> None:\n"
        b"    app.middlewares.append(settings_shell_presentation)\n"
        b"    app.middlewares.append(global_debug_presentation)\n"
        b"    app.middlewares.append(contextual_configuration_presentation)\n",
        "middleware installation",
    )
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    signed_parent = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent: dict[str, bytes] = {}
    for path, payload in signed_parent.items():
        if not path.startswith(prefix):
            raise SystemExit(f"unexpected UI build-33 package member {path!r}")
        parent[path[len(prefix):]] = payload

    # Debug is already owned by the signed standalone package. Build34 composes that
    # canonical capability globally; it must never fork or replace its behavior.
    for name in ("global-debug.js", "global-debug.css", "dashboard.html"):
        key = f"assets/{name}"
        if key not in parent:
            raise SystemExit(f"signed UI build33 is missing canonical Debug authority {name}")

    delta = _delta_files(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        if PARENT_GENERATION.encode() in payload:
            payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        if PARENT_IMPORT_PACKAGE.encode() in payload:
            payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        parent[path] = payload

    parent["assets/settings-shell.js"] = delta["settings-shell.js"]
    parent["assets/settings-shell.css"] = delta["settings-shell.css"]

    shell = delta["settings-shell.js"].lower()
    for token in (b"portainer", b"scrypted", b"unifi", b"nut", b"data-object-gear"):
        if token in shell:
            raise SystemExit(
                "settings shell build34 contains provider/context-object coupling: "
                + token.decode("utf-8")
            )
    if b"monitorbox.v2.modules.ui" in parent["__init__.py"]:
        raise SystemExit("standalone UI build34 references retired Core UI authority")
    if any(PARENT_GENERATION.encode() in payload for payload in parent.values()):
        raise SystemExit("UI build34 package retained build33 generation identity")

    # #315 and the signed Debug implementation remain byte-identical except for
    # unavoidable package-generation references applied uniformly above.
    if parent["assets/contextual-configuration.js"] != signed_parent[
        f"{PARENT_IMPORT_PACKAGE}/assets/contextual-configuration.js"
    ]:
        raise SystemExit("UI build34 changed #315 contextual JavaScript")
    if parent["assets/contextual-configuration.css"] != signed_parent[
        f"{PARENT_IMPORT_PACKAGE}/assets/contextual-configuration.css"
    ]:
        raise SystemExit("UI build34 changed #315 contextual CSS")
    for name in ("global-debug.js", "global-debug.css", "dashboard.html"):
        parent_payload = signed_parent[f"{PARENT_IMPORT_PACKAGE}/assets/{name}"]
        candidate_payload = parent[f"assets/{name}"]
        expected = parent_payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        expected = expected.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        if candidate_payload != expected:
            raise SystemExit(f"UI build34 changed canonical Debug authority {name}")

    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = stable._zip_bytes(files)
    target = output_dir / RELEASE34.filename
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"parent_sha256={previous.SIGNED_RELEASE_SHA256} "
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
