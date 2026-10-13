"""Re-sign the exact current signed successor Dev closure as Beta.

Trusted main-only publisher. No module packages are built, selected from
source branches or modified. The original Dev and Stable signed inventories
stay unchanged. Only the Beta catalog's *channel authority* advances.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from build_platform_index import sign_candidate
from sign_successor_dev_stage import (
    CHANNELS, KEY_ID, _source_from_signed,
)
from verify_platform_index import _date, verify_index, verify_package


class BetaPromotionRefused(ValueError):
    pass


REQUIRED_ROLES = frozenset({
    "com.sickicarus.monitorbox.core",
    "com.sickicarus.monitorbox.agent",
    "com.sickicarus.monitorbox.scaffold-manager",
    "com.sickicarus.monitorbox.backup-restore",
    "com.sickicarus.monitorbox.configuration-bootstrap",
    "com.sickicarus.monitorbox.http",
    "com.sickicarus.monitorbox.nut",
    "com.sickicarus.monitorbox.portainer",
    "com.sickicarus.monitorbox.scrypted",
    "com.sickicarus.monitorbox.snmp",
    "com.sickicarus.monitorbox.ui",
    "com.sickicarus.monitorbox.unifi",
    "com.sickicarus.monitorbox.wol",
})


def validate_cohort(previous: dict) -> None:
    """Fail closed on an incomplete or non-monotonic Beta snapshot."""
    dev = previous["dev"]["artifacts"]
    beta = previous["beta"]["artifacts"]
    if len(dev) != 22 or len(beta) != 22:
        raise BetaPromotionRefused("current signed closure must contain 22 architecture records")
    roles = {item["artifact_id"] for item in dev}
    # Supervisor's actual signed artifact name is platform-specific; its
    # identity must be confirmed independently before publication.
    if roles != REQUIRED_ROLES:
        raise BetaPromotionRefused("expected exactly the 13 approved signed functional roles")
    def keyed(items):
        return {(a["artifact_id"], a["platform"]["os"], a["platform"]["arch"], a["platform"]["abi"]): a for a in items}
    d, b = keyed(dev), keyed(beta)
    if len(d) != 22 or len(b) != 22 or set(d) != set(b):
        raise BetaPromotionRefused("Dev/Beta architecture inventory mismatch")
    for identity, current in d.items():
        old = b[identity]
        curr_rank = tuple(int(n) for n in current["version"].split(".")) + (current["build"],)
        old_rank = tuple(int(n) for n in old["version"].split(".")) + (old["build"],)
        if curr_rank < old_rank:
            raise BetaPromotionRefused("Dev role version regresses an existing Beta role")


def stage_beta(*, prior_platform: Path, output: Path, trust_root: Path, signer_seed: str) -> dict:
    if output.exists() or output.is_symlink() or prior_platform.is_symlink() or not prior_platform.is_dir():
        raise BetaPromotionRefused("unsafe signed Beta staging paths")
    raw_seed = base64.b64decode(signer_seed, validate=True)
    if len(raw_seed) != 32:
        raise BetaPromotionRefused("invalid protected signing seed")
    key = Ed25519PrivateKey.from_private_bytes(raw_seed)
    identity = base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    if identity != trust_root.read_text().strip():
        raise BetaPromotionRefused("protected signer differs from installed trust root")
    keys = {KEY_ID: key.public_key()}
    previous = {}
    for channel in CHANNELS:
        index = prior_platform / "channels" / channel / "index.json"
        if index.is_symlink() or not index.is_file():
            raise BetaPromotionRefused("signed channel missing")
        raw = index.read_bytes()
        issued = _date(json.loads(raw)["signed"]["generated_at"])
        signed = verify_index(raw, keys=keys, channel=channel, now=issued)
        if len(signed["artifacts"]) != 22:
            raise BetaPromotionRefused("incomplete signed channel")
        for artifact in signed["artifacts"]:
            verify_package(artifact, prior_platform.parent, keys)
        previous[channel] = signed
    validate_cohort(previous)
    now = datetime.now(timezone.utc)
    packages = prior_platform / "packages"
    if packages.is_symlink() or not packages.is_dir():
        raise BetaPromotionRefused("signed packages unavailable")
    required = set()
    for catalog in previous.values():
        for artifact in catalog["artifacts"]:
            url = artifact["package"]["url"]
            if not url.startswith("platform/packages/"):
                raise BetaPromotionRefused("untrusted signed package location")
            name = url.removeprefix("platform/packages/")
            if not name or Path(name).name != name:
                raise BetaPromotionRefused("unsafe signed package name")
            required.add(name)
    if len(required) > 128:
        raise BetaPromotionRefused("unbounded package closure")
    present = list(packages.iterdir())
    if len(present) > 128 or any(p.is_symlink() or not p.is_file() or p.suffix != ".zip" for p in present):
        raise BetaPromotionRefused("untrusted signed package directory")
    if not required.issubset({p.name for p in present}):
        raise BetaPromotionRefused("signed package missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".beta-stage-", dir=output.parent) as tmp:
        full = Path(tmp) / "full"
        target = full / "platform" / "packages"
        target.mkdir(parents=True)
        for name in sorted(required):
            shutil.copyfile(packages / name, target / name)
        signed = {}
        for channel in CHANNELS:
            origin = previous["dev"] if channel == "beta" else previous[channel]
            sequence = (previous["beta"]["sequence"] + 1 if channel == "beta"
                        else previous[channel]["sequence"])
            raw = sign_candidate(
                _source_from_signed(origin), package_root=full,
                key=key, key_id=KEY_ID, channel=channel,
                sequence=sequence, generated_at=now, valid_hours=168,
            )
            path = full / "platform" / "channels" / channel / "index.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            signed[channel] = verify_index(raw, keys=keys, channel=channel, now=now)
            if signed[channel]["artifacts"] != origin["artifacts"]:
                raise BetaPromotionRefused("promotion changed immutable package inventory")
            for artifact in signed[channel]["artifacts"]:
                verify_package(artifact, full, keys)
        if signed["beta"]["artifacts"] != signed["dev"]["artifacts"]:
            raise BetaPromotionRefused("Beta does not contain exact current signed Dev closure")
        if signed["stable"]["artifacts"] != previous["stable"]["artifacts"]:
            raise BetaPromotionRefused("Stable artifact authority unexpectedly changed")
        receipt = {
            "schema": 1,
            "action": "promote-exact-signed-dev-to-beta",
            "package_rebuild": False,
            "role_count": len({x["artifact_id"] for x in signed["beta"]["artifacts"]}),
            "signed_artifact_count": len(signed["beta"]["artifacts"]),
            "previous_beta_sequence": previous["beta"]["sequence"],
            "new_beta_sequence": signed["beta"]["sequence"],
            "dev_sequence": signed["dev"]["sequence"],
            "stable_sequence": signed["stable"]["sequence"],
            "channels_to_publish": ["beta"],
        }
        (Path(tmp) / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        Path(tmp).rename(output)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-platform", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trust-root", type=Path, default=Path("trust/official-ed25519-1.pub"))
    args = parser.parse_args()
    receipt = stage_beta(
        prior_platform=args.prior_platform, output=args.output,
        trust_root=args.trust_root, signer_seed=os.environ["MONITORBOX_PLATFORM_SIGNING_KEY"],
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
