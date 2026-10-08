"""Verify *existing* GHCR stable pair only; no candidate, signer or publication.

Designed for a privileged-enough READ-ONLY Actions token or manual invocation.
Uses accepted main's trust root and never writes GHCR tags or package metadata.
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
from successor_stable_witness import observe_current_stable_pair
from successor_release_pairing import ReleaseRefusal


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only historical signed GHCR stable-pair acceptance")
    parser.add_argument("--trust-root", type=Path, required=True,
                        help="approved Ed25519 public key, base64 raw 32 bytes")
    args = parser.parse_args()
    try:
        key_raw = base64.b64decode(args.trust_root.read_text("utf-8").strip(), validate=True)
        if len(key_raw) != 32:
            raise ReleaseRefusal("invalid official Ed25519 trust root")
        key = Ed25519PublicKey.from_public_bytes(key_raw)
        witness = observe_current_stable_pair(
            read_only_ghcr_client_from_environment(),
            keys={"official-ed25519-1": key},
            now=datetime.now(timezone.utc),
        )
    except (ReleaseRefusal, ValueError, OSError, TypeError) as exc:
        # Exception strings are internal refusal reasons, not HTTP responses.
        print("Existing stable pair read-only verification refused: " +
              str(exc)[:240], file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "historical-stable-validated-read-only",
        "publication_authorized": False,
        "channel_changed": False,
        "catalog_sequence_internal": witness.pair.sequence,
        "full_digest": witness.pair.full_digest,
        "supervisor_digest": witness.pair.supervisor_digest,
        "architecture_coverage": ["amd64", "arm64"],
        "source_ci_verified": False,
        "candidate_release_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
