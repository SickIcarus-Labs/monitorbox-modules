"""Successor signed-catalog verifier; only the fixed scaffold embeds trust roots.

This standalone Python tool is for publication/CI verification. The native
scaffold must implement the same contract without importing Python.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = Path(__file__).resolve().parents[1] / "platform/schema/index-v1.schema.json"


class VerificationError(ValueError):
    pass


def canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    if len(raw) > 4 * 1024 * 1024:
        raise VerificationError("catalog exceeds maximum size")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                VerificationError(f"non-JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid UTF-8 JSON catalog: {exc}") from exc


def _date(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise VerificationError(f"invalid catalog timestamp: {exc}") from exc


def _package_path(name: str) -> tuple[str, ...]:
    parts = name.split("/")
    if (
        len(parts) < 3
        or parts[:2] != ["platform", "packages"]
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in name
        or "%" in name
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", name)
    ):
        raise VerificationError("unsafe package path")
    return tuple(parts)


def verify_index(
    raw: bytes,
    *,
    keys: dict[str, Ed25519PublicKey],
    channel: str,
    now: datetime | None = None,
    min_sequence: int = 0,
) -> dict[str, Any]:
    document = _parse(raw)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda e: str(e.json_path),
    )
    if errors:
        raise VerificationError(f"invalid platform catalog: {errors[0].message}")
    signed = document["signed"]
    if signed["channel"] != channel:
        raise VerificationError("signed channel differs from requested channel")
    if signed["sequence"] < min_sequence:
        raise VerificationError("catalog sequence regressed")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if _date(signed["expires_at"]) <= current or _date(signed["generated_at"]) > current + timedelta(minutes=5):
        raise VerificationError("expired or future-dated catalog")
    if _date(signed["expires_at"]) <= _date(signed["generated_at"]):
        raise VerificationError("invalid catalog lifetime")
    signature = document["signature"]
    key = keys.get(signature["identity"])
    if key is None:
        raise VerificationError("unknown catalog signing key")
    try:
        key.verify(base64.b64decode(signature["value"], validate=True), canonical(signed))
    except (InvalidSignature, ValueError) as exc:
        raise VerificationError("invalid catalog signature") from exc
    seen: set[tuple[str, str, int, str, str, str]] = set()
    for artifact in signed["artifacts"]:
        _package_path(artifact["package"]["url"])
        platform = artifact["platform"]
        if platform["arch"] == "any" and platform["abi"] != "pure":
            raise VerificationError("architecture-neutral binary package is forbidden")
        api = artifact["requires_scaffold_api"]
        if api["minimum"] >= api["maximum_exclusive"]:
            raise VerificationError("invalid scaffold API interval")
        identity = (
            artifact["artifact_id"], artifact["version"], artifact["build"],
            platform["os"], platform["arch"], platform["abi"],
        )
        if identity in seen:
            raise VerificationError("duplicate artifact identity")
        seen.add(identity)
        if artifact["package"]["signature"]["identity"] not in keys:
            raise VerificationError("unknown package signing key")
    return signed


def verify_package(
    artifact: dict[str, Any], root: Path, keys: dict[str, Ed25519PublicKey]
) -> None:
    package = artifact["package"]
    parts = _package_path(package["url"])
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise VerificationError("package path traverses symlink")
    if not path.is_file():
        raise VerificationError("package missing")
    raw = path.read_bytes()
    if len(raw) != package["size"] or hashlib.sha256(raw).hexdigest() != package["sha256"]:
        raise VerificationError("package size or digest mismatch")
    signature = package["signature"]
    key = keys.get(signature["identity"])
    if key is None:
        raise VerificationError("unknown package signing key")
    try:
        key.verify(base64.b64decode(signature["value"], validate=True), raw)
    except (InvalidSignature, ValueError) as exc:
        raise VerificationError("invalid package signature") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify successor catalog and its artifacts")
    parser.add_argument("index", type=Path)
    parser.add_argument("--packages-root", type=Path, required=True)
    parser.add_argument("--trust-root", type=Path, required=True, help="base64 Ed25519 public key")
    parser.add_argument("--key-id", default="official-ed25519-1")
    parser.add_argument("--channel", choices=["stable", "beta", "dev"], required=True)
    parser.add_argument("--min-sequence", type=int, default=0)
    args = parser.parse_args()
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(args.trust_root.read_text().strip(), validate=True)
        )
        keys = {args.key_id: key}
        signed = verify_index(
            args.index.read_bytes(), keys=keys, channel=args.channel,
            min_sequence=args.min_sequence,
        )
        for artifact in signed["artifacts"]:
            verify_package(artifact, args.packages_root, keys)
    except (OSError, ValueError) as exc:
        print(f"platform catalog verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified {len(signed['artifacts'])} platform artifacts for {args.channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
