#!/usr/bin/env python3
"""Verify and optionally stage an immutable signed module-channel snapshot."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _public_key(path: Path) -> Ed25519PublicKey:
    raw = base64.b64decode(path.read_text(encoding="utf-8").strip(), validate=True)
    if len(raw) != 32:
        raise SystemExit("trusted Ed25519 public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _identity(manifest: dict[str, object]) -> tuple[str, str, int]:
    return (
        str(manifest["module_id"]),
        str(manifest["version"]),
        int(manifest["build"]),
    )


def verify(snapshot_root: Path, trust_root: Path, stage_root: Path | None = None) -> None:
    source_path = snapshot_root / "catalog.source.json"
    index_path = snapshot_root / "index.json"
    packages_root = snapshot_root / "packages"
    if not source_path.is_file() or not index_path.is_file() or not packages_root.is_dir():
        raise SystemExit("snapshot must contain catalog.source.json, index.json, and packages/")

    source = json.loads(source_path.read_text(encoding="utf-8"))
    envelope = json.loads(index_path.read_text(encoding="utf-8"))
    if source.get("schema") != 1 or source.get("repository_id") != "official":
        raise SystemExit("snapshot source is not canonical official schema-1 authority")
    if source.get("display_name") != "MonitorBox Official":
        raise SystemExit("snapshot source display name is not canonical")

    signature = envelope.get("signature")
    signed = envelope.get("signed")
    if (
        envelope.get("schema") != 1
        or not isinstance(signature, dict)
        or not isinstance(signed, dict)
        or signature.get("algorithm") != "ed25519"
        or signature.get("identity") != "official-ed25519-1"
        or signed.get("repository_id") != "official-dev"
    ):
        raise SystemExit("snapshot index is not signed official-dev authority")

    key = _public_key(trust_root)
    try:
        key.verify(base64.b64decode(str(signature["value"]), validate=True), canonical(signed))
    except Exception as exc:
        raise SystemExit("snapshot repository signature verification failed") from exc

    source_rows = source.get("modules")
    signed_rows = signed.get("modules")
    if not isinstance(source_rows, list) or not isinstance(signed_rows, list):
        raise SystemExit("snapshot module collections are malformed")

    source_map: dict[tuple[str, str, int], dict[str, object]] = {}
    signed_map: dict[tuple[str, str, int], dict[str, object]] = {}
    for row in source_rows:
        if not isinstance(row, dict) or not isinstance(row.get("manifest"), dict):
            raise SystemExit("snapshot source contains malformed module row")
        ident = _identity(row["manifest"])
        if ident in source_map:
            raise SystemExit(f"duplicate source identity: {ident!r}")
        source_map[ident] = row
    for row in signed_rows:
        if not isinstance(row, dict) or not isinstance(row.get("manifest"), dict):
            raise SystemExit("snapshot signed index contains malformed module row")
        ident = _identity(row["manifest"])
        if ident in signed_map:
            raise SystemExit(f"duplicate signed identity: {ident!r}")
        signed_map[ident] = row
    if source_map.keys() != signed_map.keys():
        raise SystemExit("snapshot source and signed index identities disagree")

    referenced: list[str] = []
    for ident in sorted(source_map):
        source_row = source_map[ident]
        signed_row = signed_map[ident]
        if source_row["manifest"] != signed_row["manifest"]:
            raise SystemExit(f"manifest mismatch for {ident!r}")
        filename = source_row.get("package")
        package = signed_row.get("package")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".zip"):
            raise SystemExit(f"unsafe source package filename for {ident!r}")
        if not isinstance(package, dict):
            raise SystemExit(f"missing signed package metadata for {ident!r}")
        if package.get("filename") != filename or package.get("url") != f"packages/{filename}":
            raise SystemExit(f"signed package path mismatch for {ident!r}")
        if package.get("signature_identity") != "official-ed25519-1":
            raise SystemExit(f"unexpected package signing identity for {ident!r}")

        path = packages_root / filename
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"snapshot package missing or unsafe: {filename}")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != package.get("sha256"):
            raise SystemExit(f"snapshot package digest mismatch: {filename}")
        try:
            key.verify(base64.b64decode(str(package["signature"]), validate=True), payload)
        except Exception as exc:
            raise SystemExit(f"snapshot package signature verification failed: {filename}") from exc
        referenced.append(filename)

    if stage_root is not None:
        if stage_root.exists():
            shutil.rmtree(stage_root)
        (stage_root / "packages").mkdir(parents=True)
        shutil.copy2(source_path, stage_root / "catalog.source.json")
        shutil.copy2(index_path, stage_root / "index.json")
        for filename in referenced:
            shutil.copy2(packages_root / filename, stage_root / "packages" / filename)

    print(f"signed dev snapshot verification: PASS ({len(referenced)} releases)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--trust-root", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path)
    args = parser.parse_args()
    verify(args.snapshot_root, args.trust_root, args.stage_root)


if __name__ == "__main__":
    main()
