#!/usr/bin/env python3
"""Build contextual-configuration UI v1.2.0 build 32 from signed dev build 31.

Build 31's transient construction scripts were intentionally pruned after publication.
The signed dev package is therefore the immutable parent authority for build 32. This
builder verifies those exact bytes, renames only the package namespace/generation,
and composes the reviewable #315 contextual-detail source delta.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

import build_first_party_ui as stable

UI_VERSION = "1.2.0"
UI_BUILD = 32
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_VERSION = "1.1.18"
PARENT_BUILD = 31
PARENT_GENERATION = f"{PARENT_VERSION}-{PARENT_BUILD}"
PARENT_PACKAGE = "com.sickicarus.monitorbox.ui-1.1.18-build31.zip"
PARENT_SHA256 = "029a1584e6748a1c93f9d2903a2e7f22943d6044375dd19ceb56d7127b4ecd56"
PARENT_IMPORT_PACKAGE = "monitorbox_ui_b31"
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b32"
RELEASE32 = stable.Release(
    build=UI_BUILD,
    certified_sha="p0-315-contextual-configuration",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "contextual-configuration.js": "54d45d743a5c53ac3faaa9b345286be1f8cef91d",
    "contextual-configuration.css": "e4d34cda75dee76ed5ff47aef6c408835f816c26",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-32 {seam} seam changed: {old[:180]!r}")
    return payload.replace(old, new, 1)


def _parent_files(root: Path) -> dict[str, bytes]:
    parent = root / "channels" / "dev" / "packages" / PARENT_PACKAGE
    payload = parent.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != PARENT_SHA256:
        raise SystemExit(
            "signed UI build-31 parent drift: "
            f"expected {PARENT_SHA256}, got {actual}"
        )
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(PARENT_IMPORT_PACKAGE + "/"):
                raise SystemExit(
                    f"unexpected UI build-31 package member {info.filename!r}"
                )
            relative = info.filename[len(PARENT_IMPORT_PACKAGE) + 1 :]
            files[relative] = archive.read(info)
    if "__init__.py" not in files or "assets/dashboard.js" not in files:
        raise SystemExit("signed UI build-31 package is missing standalone UI authority")
    return files


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.2.0-build32"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(
            "UI build-32 delta shape changed: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI build-32 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent,
        b"Standalone managed MonitorBox UI 1.1.18 build 31.",
        b"Standalone managed MonitorBox UI 1.2.0 build 32.",
        "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI build-32 parent application has no build-31 generation marker")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = _replace_once(
        payload,
        b"ASSETS = {\n",
        b"ASSETS = {\n"
        b'    "contextual-configuration.js": "text/javascript",\n'
        b'    "contextual-configuration.css": "text/css",\n',
        "asset registry",
    )

    middleware = r'''@web.middleware
async def contextual_configuration_presentation(request: web.Request, handler):
    response = await handler(request)
    if not (
        request.path == "/"
        and isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        return response
    markup = response.text
    style = '<link rel="stylesheet" href="/static/contextual-configuration.css">'
    script = '<script src="/static/contextual-configuration.js" defer></script>'
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
        "contextual presentation middleware",
    )
    payload = _replace_once(
        payload,
        b"def install(app: web.Application) -> None:\n",
        b"def install(app: web.Application) -> None:\n"
        b"    app.middlewares.append(contextual_configuration_presentation)\n",
        "middleware installation",
    )
    return payload


def _package_files(root: Path) -> dict[str, bytes]:
    parent = _parent_files(root)
    delta = _delta_files(root)
    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        if PARENT_GENERATION.encode() in payload:
            parent[path] = payload.replace(
                PARENT_GENERATION.encode(), UI_GENERATION.encode()
            )
    parent["assets/contextual-configuration.js"] = delta["contextual-configuration.js"]
    parent["assets/contextual-configuration.css"] = delta["contextual-configuration.css"]

    forbidden = (
        b"monitorbox.v2.modules.ui",
        b"portainer",
        b"scrypted",
        b"unifi",
        b"data-object-gear",
    )
    contextual = delta["contextual-configuration.js"].lower()
    offenders = [token.decode("utf-8") for token in forbidden[1:] if token in contextual]
    if offenders:
        raise SystemExit(
            "contextual UI build32 contains provider/row-control coupling: "
            + ", ".join(offenders)
        )
    if forbidden[0] in parent["__init__.py"]:
        raise SystemExit("standalone UI build32 references retired Core UI authority")

    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    payload = stable._zip_bytes(files)
    target = output_dir / RELEASE32.filename
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"parent_sha256={PARENT_SHA256} entrypoint={TARGET_IMPORT_PACKAGE}:install"
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
