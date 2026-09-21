#!/usr/bin/env python3
"""Build UniFi Network v1.1.1 build 12 for #358/#359.

Build 12 keeps exact build-11 runtime behavior, adds provider-owned POSSIBLE
discovery when TCP/443 is open but public status endpoints are inconclusive,
and declares the UniFi check as a Network-card contributor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_first_party_unifi as base
import build_first_party_unifi_b11 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.1.1"
MODULE_BUILD = 12
IMPORT_PACKAGE = "monitorbox_unifi_v111_b12"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
SOURCE_DELTA = "1.1.1-build12"
CONTRACT_BLOB = "75b3d650ab97e220259603bd23c665681535de50"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _contract(root: Path) -> dict:
    path = root / "sources" / "unifi" / SOURCE_DELTA / "discovery_contract.json"
    payload = path.read_bytes()
    actual = base._git_blob_sha(payload)
    if actual != CONTRACT_BLOB:
        raise SystemExit(
            f"UniFi 1.1.1 build12 contract drift: expected {CONTRACT_BLOB}, got {actual}"
        )
    data = json.loads(payload)
    if (
        data.get("schema") != 1
        or data.get("module_id") != MODULE_ID
        or data.get("version") != MODULE_VERSION
        or int(data.get("build") or 0) != MODULE_BUILD
    ):
        raise SystemExit("UniFi build12 discovery contract is malformed")
    return data


def _package_files(root: Path) -> dict[str, bytes]:
    _contract(root)
    prior = previous._package_files(root)
    old_prefix = previous.IMPORT_PACKAGE + "/"
    result: dict[str, bytes] = {}

    for path, payload in prior.items():
        if not path.startswith(old_prefix):
            raise SystemExit(f"unexpected UniFi build11 package member: {path}")
        name = path[len(old_prefix):]
        text = payload.decode("utf-8")

        if name in {"__init__.py", "runtime.py"}:
            text = _replace_once(
                text,
                f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}',
                f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
                f"UniFi build12 {name} entrypoint",
            )

        if name == "runtime.py":
            text = _replace_once(
                text,
                f'MODULE_VERSION = "{previous.MODULE_VERSION}"',
                f'MODULE_VERSION = "{MODULE_VERSION}"',
                "UniFi build12 version",
            )
            text = _replace_once(
                text,
                f"MODULE_BUILD = {previous.MODULE_BUILD}",
                f"MODULE_BUILD = {MODULE_BUILD}",
                "UniFi build12 build",
            )

        if name == "onboarding.py":
            text = _replace_once(
                text,
                '        "verify_tls": bool(values["verify_tls"]),\n',
                '        "verify_tls": bool(values["verify_tls"]),\n'
                '        "presentation_object": "network",\n',
                "UniFi build12 Network contribution",
            )
            old = '''        return ()

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
'''
            new = '''        return (
            DiscoveryEvidence(
                plugin_id="unifi",
                system_id=request.system_id,
                kind="unifi",
                label="UniFi Network",
                confidence=DiscoveryConfidence.POSSIBLE,
                endpoint=f"https://{host}",
                evidence="TCP/443 is open; UniFi identity requires credential validation",
                default_selected=False,
                values={
                    "base_url": f"https://{host}",
                    "network_site": "default",
                    "verify_tls": False,
                },
            ),
        )

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
'''
            text = _replace_once(
                text,
                old,
                new,
                "UniFi build12 bounded possible discovery",
            )

        if previous.IMPORT_PACKAGE in text:
            raise SystemExit(f"UniFi build12 retained build11 package identity in {name}")
        result[f"{IMPORT_PACKAGE}/{name}"] = text.encode("utf-8")

    return result


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = base._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
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
