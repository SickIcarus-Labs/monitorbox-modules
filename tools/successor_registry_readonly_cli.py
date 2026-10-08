"""Manual, read-only qualification of a digest-pinned successor release candidate.

Example (private GHCR package):
  GHCR_USERNAME=<user> GHCR_READ_TOKEN=<read:packages token> \
    python tools/successor_registry_readonly_cli.py \
      --candidate /tmp/reviewed-candidate.json \
      --trust-root trust/official-ed25519-1.pub

This does NOT promote, sign, publish, or approve release.
Only --check-current-stable reads existing mutable tags, and never writes them.
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
from successor_github_readonly import source_api_from_environment
from successor_github_source_evidence import qualify_source_commits
from successor_registry_extract import admit_digest_pinned_registry_release
from successor_release_pairing import ReleaseRefusal, compare_verified_pair_freshness
from successor_stable_witness import observe_current_stable_pair


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GHCR immutable signed-release verification")
    parser.add_argument("--candidate", required=True, type=Path,
                        help="reviewed immutable candidate manifest JSON")
    parser.add_argument("--trust-root", required=True, type=Path,
                        help="approved Ed25519 public key, base64 raw 32-byte format")
    parser.add_argument("--require-source-ci", action="store_true",
                        help="also require live exact-source GitHub ancestry and CI/job qualification")
    parser.add_argument("--check-current-stable", action="store_true",
                        help="also read both current stable tags twice and refuse downgrade/mixed pairs")
    args = parser.parse_args()
    try:
        raw = args.candidate.read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            raise ReleaseRefusal("candidate manifest oversized")
        key_raw = base64.b64decode(args.trust_root.read_text("utf-8").strip(), validate=True)
        if len(key_raw) != 32:
            raise ReleaseRefusal("trust root must be a 32-byte Ed25519 key")
        key = Ed25519PublicKey.from_public_bytes(key_raw)
        proofs = (qualify_source_commits(raw, source_api_from_environment())
                  if args.require_source_ci else ())
        registry = read_only_ghcr_client_from_environment()
        now = datetime.now(timezone.utc)
        result = admit_digest_pinned_registry_release(
            raw, registry, keys={"official-ed25519-1": key}, now=now,
        )
        stable = (observe_current_stable_pair(
            registry, keys={"official-ed25519-1": key}, now=now)
            if args.check_current_stable else None)
        stable_decision = (compare_verified_pair_freshness(result.pair, stable.pair)
                           if stable is not None else None)
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
        "stable_pair_checked": stable is not None,
        "stable_pair_sequence_internal": stable.pair.sequence if stable is not None else None,
        "monotonic_preflight": stable_decision,
        "source_ci_verified": bool(proofs),
        "source_ci_roles": sorted(proof.role for proof in proofs),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
