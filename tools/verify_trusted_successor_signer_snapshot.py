#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "platform" / "successor-signing" / "trusted-source-v1.json"


def git_blob_sha1(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    ).hexdigest()


def main() -> int:
    doc = json.loads(SNAPSHOT.read_text("utf-8"))
    if doc.get("schema") != 1:
        raise SystemExit("trusted signer snapshot schema must be 1")
    source = doc.get("source_commit")
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise SystemExit("trusted signer source commit must be an exact SHA")
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("trusted signer snapshot file set is empty")
    for name, expected in sorted(files.items()):
        if not isinstance(name, str) or name.startswith("/") or ".." in Path(name).parts:
            raise SystemExit("unsafe trusted signer path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise SystemExit(f"invalid expected blob SHA for {name}")
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"trusted signer file missing or linked: {name}")
        actual = git_blob_sha1(path)
        if actual != expected:
            raise SystemExit(
                f"trusted signer file drift: {name}: expected {expected}, got {actual}"
            )
    print(
        f"verified {len(files)} trusted successor signer files from source {source}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
