#!/usr/bin/env python3
"""Build isolated #220 UI 1.4.1 build40 directly from accepted 1.3.1 build35.

Builds 36/37/38 are divergent experimental artifacts. Never chain through
their destructive-module UI or false-green aggregate fallback.
This build ONLY replaces homepage card eligibility/rendering with the Core
site.cards projection. Dashboard layout customization (#219) is not included.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build35 as previous

UI_VERSION = "1.4.1"
UI_BUILD = 40
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b40"

RELEASE40 = stable.Release(
    build=UI_BUILD,
    certified_sha="p1-85-explicit-card-contract",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-projection.js": "0749aa067b8b069e47a9fed590ac6c689fcec7fd",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(payload)}\0".encode("ascii") + payload
    ).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build40 {label} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _source(root: Path) -> bytes:
    base = root / "sources" / "ui" / "1.4.1-build40"
    actual = {item.name for item in base.iterdir() if item.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(
            f"UI build40 source shape changed: missing={sorted(expected-actual)} "
            f"extra={sorted(actual-expected)}"
        )
    value = (base / "card-projection.js").read_bytes()
    digest = _git_blob_sha(value)
    if digest != SOURCE_BLOBS["card-projection.js"]:
        raise SystemExit(
            "UI build40 source drift: expected "
            + SOURCE_BLOBS["card-projection.js"] + ", got " + digest
        )
    return value


def _application(parent: bytes) -> bytes:
    payload = _replace_once(
        parent,
        b"Standalone managed MonitorBox UI 1.3.1 build 35.",
        b"Standalone managed MonitorBox UI 1.4.1 build 40.",
        "standalone identity",
    )
    if PARENT_GENERATION.encode() not in payload:
        raise SystemExit("UI build40 parent missing build35 identity")
    payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
    payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    payload = _replace_once(
        payload,
        b"ASSETS = {\n",
        b'ASSETS = {\n    "card-projection.js": "text/javascript",\n',
        "asset registry",
    )
    # Admission guard precedes any browser routes, handlers or middleware.
    # Old dev Core reported 2.6.0 but did not expose site.cards. Semantic
    # version alone must never admit a blank/false-green dashboard.
    seam = b"def install(app: web.Application) -> None:\n"
    guard = (\n        b"def _require_card_projection_contract() -> None:\n"\n        b"    import monitorbox.v2.presentation as core_presentation\n"\n        b"    actual = getattr(core_presentation, 'CARD_PROJECTION_CONTRACT_VERSION', None)\n"\n        b"    if actual != 1:\n"\n        b"        raise RuntimeError('UI build40 requires Core dashboard-card projection contract v1; update Core using the Recovery page before enabling this UI')\n"\n        b"\n\n"\n        b"def install(app: web.Application) -> None:\n"\n        b"    _require_card_projection_contract()\n"\n    )\n    payload = _replace_once(payload, seam, guard, "required Core card-contract admission")\n    return payload\n\n\ndef _package_files(root: Path) -> dict[str, bytes]:
    signed_parent = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent: dict[str, bytes] = {}
    for path, payload in signed_parent.items():
        if not path.startswith(prefix):
            raise SystemExit(f"unexpected build35 package member {path!r}")
        parent[path[len(prefix):]] = payload

    card_js = _source(root)
    lowered = card_js.lower()
    for forbidden in (b"unifi", b"scrypted", b"portainer", b"nut", b"docker"):
        if forbidden in lowered:
            raise SystemExit("UI build40 contains provider/product coupling: "
                             + forbidden.decode())
    for token in (
        b"site?.cards",
        b"dashboard_card",
        b"projectedCoreObjects",
        b"object.kind === 'host'",
    ):
        if token not in card_js:
            raise SystemExit(f"UI build40 missing card contract {token!r}")
    if b"card_layout" in card_js or b"dashboardConfiguration" in card_js:
        raise SystemExit("UI build40 illegally imports #219 layout semantics")

    parent["__init__.py"] = _application(parent["__init__.py"])
    for path, payload in list(parent.items()):
        payload = payload.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        payload = payload.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        parent[path] = payload

    parent["assets/card-projection.js"] = card_js
    script = (
        f'<script src="/static/card-projection.js?v={UI_GENERATION}" defer></script>'
    ).encode()
    parent["assets/dashboard.html"] = _replace_once(
        parent["assets/dashboard.html"],
        b"</body>",
        script + b"</body>",
        "dashboard script injection",
    )

    if b"aggregate-evidence.js" in parent["assets/dashboard.html"]:
        raise SystemExit("UI build40 must not import rejected build37 fallback")
    if parent["assets/dashboard.html"].count(script) != 1:
        raise SystemExit("UI build40 must load card projection exactly once")
    if any(PARENT_GENERATION.encode() in payload for payload in parent.values()):
        raise SystemExit("UI build40 retained stale build35 generation")

    return {
        f"{TARGET_IMPORT_PACKAGE}/{relative}": payload
        for relative, payload in parent.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE40.filename
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
