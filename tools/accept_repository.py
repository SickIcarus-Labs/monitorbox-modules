#!/usr/bin/env python3
"""Offline acceptance for the public MonitorBox module repository publication contract."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_repository import build as build_repository, canonical

MODULE_ID = "com.sickicarus.monitorbox.ui"
EXPECTED_BUILDS = (2, 3)
SIGNATURE_IDENTITY = "acceptance-ephemeral-ed25519"


def _package_shape(root: Path, source: dict) -> None:
    modules = source.get("modules")
    if not isinstance(modules, list):
        raise AssertionError("catalog modules must be an array")
    builds = tuple(sorted(item["manifest"]["build"] for item in modules))
    if builds != EXPECTED_BUILDS:
        raise AssertionError(f"expected UI builds {EXPECTED_BUILDS}, got {builds}")

    for item in modules:
        manifest = item["manifest"]
        build = manifest["build"]
        if manifest["module_id"] != MODULE_ID:
            raise AssertionError(f"unexpected module id {manifest['module_id']!r}")
        expected_entrypoint = {"webui": f"monitorbox_ui_b{build}:install"}
        if manifest["entrypoints"] != expected_entrypoint:
            raise AssertionError(f"UI build {build} does not use its generation-specific entrypoint")
        package = root / "packages" / item["package"]
        if not package.is_file():
            raise AssertionError(f"generated package is missing: {package.name}")
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
            package_root = f"monitorbox_ui_b{build}/"
            if f"{package_root}__init__.py" not in names:
                raise AssertionError(f"UI build {build} has no importable package root")
            if any(name.startswith("monitorbox/") for name in names):
                raise AssertionError("managed package may not shadow frozen Core's monitorbox namespace")
            expected_delta = build == 3
            for asset in ("discovery-v22.js", "endpoint-prefill-v22.js"):
                present = f"{package_root}assets/{asset}" in names
                if present != expected_delta:
                    raise AssertionError(
                        f"UI build {build} certified delta shape is wrong for {asset}"
                    )


def _signed_repository(root: Path, source: dict) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    with tempfile.TemporaryDirectory(prefix="monitorbox-public-repository-") as directory:
        output = Path(directory) / "index.json"
        build_repository(
            root / "catalog.source.json",
            output,
            private_key,
            SIGNATURE_IDENTITY,
        )
        envelope = json.loads(output.read_text(encoding="utf-8"))

    if envelope.get("schema") != 1:
        raise AssertionError("repository envelope schema changed")
    signed = envelope.get("signed")
    signature = envelope.get("signature")
    if not isinstance(signed, dict) or not isinstance(signature, dict):
        raise AssertionError("repository envelope is missing signed/signature objects")
    if signed.get("repository_id") != "official" or signed.get("display_name") != "MonitorBox Official":
        raise AssertionError("signed repository identity changed")
    if signature.get("algorithm") != "ed25519" or signature.get("identity") != SIGNATURE_IDENTITY:
        raise AssertionError("repository signature metadata changed")
    public_key.verify(base64.b64decode(signature["value"], validate=True), canonical(signed))

    releases = signed.get("modules")
    if not isinstance(releases, list) or tuple(item["manifest"]["build"] for item in releases) != EXPECTED_BUILDS:
        raise AssertionError("signed repository does not contain the two certified UI generations")

    source_by_build = {item["manifest"]["build"]: item for item in source["modules"]}
    for release in releases:
        build = release["manifest"]["build"]
        package = release["package"]
        expected_name = source_by_build[build]["package"]
        if package["filename"] != expected_name or package["url"] != f"packages/{expected_name}":
            raise AssertionError(f"signed package location changed for UI build {build}")
        payload = (root / "packages" / expected_name).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if package["sha256"] != digest:
            raise AssertionError(f"signed package digest is wrong for UI build {build}")
        if package["signature_identity"] != SIGNATURE_IDENTITY:
            raise AssertionError(f"signed package identity is wrong for UI build {build}")
        public_key.verify(base64.b64decode(package["signature"], validate=True), payload)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    _package_shape(root, source)
    _signed_repository(root, source)
    print("public module repository acceptance: PASS (reproducible packages + signed builds 2/3)")


if __name__ == "__main__":
    main()
