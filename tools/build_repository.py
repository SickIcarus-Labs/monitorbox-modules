#!/usr/bin/env python3
"""Build MonitorBox's canonical signed repository index."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def load_private_key(value: str) -> Ed25519PrivateKey:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except ValueError as exc:
        raise SystemExit("signing key must be valid base64") from exc
    if len(raw) != 32:
        raise SystemExit("signing key must decode to exactly 32 raw Ed25519 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def build(source_path: Path, output_path: Path, key: Ed25519PrivateKey, identity: str) -> None:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    modules = []
    seen = set()
    root = source_path.parent.resolve()
    for item in source.get("modules", []):
        manifest = item["manifest"]
        package_name = item["package"]
        package = (root / "packages" / package_name).resolve()
        package.relative_to(root / "packages")
        if package.name != package_name or package.suffix != ".zip":
            raise SystemExit(f"invalid package filename: {package_name}")
        identity_tuple = (manifest["module_id"], manifest["version"], manifest["build"])
        if identity_tuple in seen:
            raise SystemExit(f"duplicate module release: {identity_tuple}")
        seen.add(identity_tuple)
        payload = package.read_bytes()
        modules.append(
            {
                "manifest": manifest,
                "package": {
                    "url": f"packages/{package.name}",
                    "filename": package.name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "signature_identity": identity,
                    "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
                },
            }
        )
    modules.sort(key=lambda value: (
        value["manifest"]["module_id"],
        value["manifest"]["version"],
        value["manifest"]["build"],
    ))
    signed = {
        "repository_id": source["repository_id"],
        "display_name": source["display_name"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "modules": modules,
    }
    envelope = {
        "schema": 1,
        "signed": signed,
        "signature": {
            "algorithm": "ed25519",
            "identity": identity,
            "value": base64.b64encode(key.sign(canonical(signed))).decode("ascii"),
        },
    }
    output_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("catalog.source.json"))
    parser.add_argument("--output", type=Path, default=Path("index.json"))
    parser.add_argument("--identity", default="official-ed25519-1")
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()
    build(args.source, args.output, load_private_key(args.private_key), args.identity)


if __name__ == "__main__":
    main()

