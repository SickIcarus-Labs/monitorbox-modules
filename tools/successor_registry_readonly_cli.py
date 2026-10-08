"""Manual, read-only qualification of a digest-pinned successor release candidate.

Example (private GHCR package):
  GHCR_USERNAME=<user> GHCR_READ_TOKEN=<read:packages token> \
    python tools/successor_registry_readonly_cli.py \
      --candidate /tmp/reviewed-candidate.json \
      --trust-root trust/official-ed25519-1.pub

This does NOT promote, sign, publish, consult mutable tags or approve release.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from successor_ghcr_readonly import read_only_ghcr_client_from_environment
from successor_registry_extract import admit_digest_pinned_registry_release
from successor_release_pairing import ReleaseRefusal


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GHCR immutable signed-release verification")
    parser.add_argument("--candidate", required=True, type=Path,
                        help="reviewed immutable candidate manifest JSON")
    parser.add_argument("--trust-root", required=True, type=Path,
                        help="approved Ed25519 public key, base64 raw 32-byte format")
    args = parser.parse_args()
    try:
        raw = args.candidate.read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            raise ReleaseRefusal("candidate manifest oversized")
        key_raw = base64.b64decode(args.trust_root.read_text("utf-8").strip(), validate=True)
        if len(key_raw) != 32:
            raise ReleaseRefusal("trust root must be a 32-byte Ed25519 key")
        key = Ed25519PublicKey.from_public_bytes(key_raw)
        result = admit_digest_pinned_registry_release(
            raw, read_only_ghcr_client_from_environment(),
            keys={"official-ed25519-1": key},
            now=datetime.now(timezone.utc),
        )
    except (ReleaseRefusal, ValueError, OSError, TypeError) as exc:
        # Avoid echoing response bodies or tokens; only bounded internal errors.
        print("Release qualification refused: " + str(exc)[:240], file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "validated-read-only",
        "publication_authorized": False,
        "channel_changed": False,
        "sequence_internal": result.pair.sequence,
        "full": result.pair.full_digest,
        "supervisor": result.pair.supervisor_digest,
        "architectures": list(result.full_architectures),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
