#!/usr/bin/env python3
"""Prepare a strictly UI-only successor feed delta from VERIFIED prior stable bytes.

No registry access, private keys, OCI tag mutation or network operations here.
The caller must verify the prior signed pair and supply its exact extracted ZIPs.
The trusted signer signs the resulting *complete* catalogs separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from build_successor_acceptance_feed_source import build_source
from build_successor_first_party_modules import build_all

UI = "com.sickicarus.monitorbox.ui"
EXPECTED_VERSION = "1.18.0"
EXPECTED_BUILD = 58
EXPECTED_PREVIOUS_VERSION = "1.17.1"
EXPECTED_PREVIOUS_BUILD = 57
SCHEMA_KEYS = {"schema", "signed", "signature"}


class DeltaRefused(ValueError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _records(document: dict) -> dict[tuple[str, str], dict]:
    if not isinstance(document, dict) or set(document) != SCHEMA_KEYS:
        raise DeltaRefused("signed feed has unexpected envelope")
    signed = document["signed"]
    if signed.get("repository_id") != "official-platform" or signed.get("channel") != "stable":
        raise DeltaRefused("not the official signed stable catalog")
    artifacts = signed.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 22:
        raise DeltaRefused("baseline must contain exactly 22 signed artifacts")
    found = {}
    for item in artifacts:
        key = (item["artifact_id"], item["platform"]["arch"])
        if key in found:
            raise DeltaRefused("duplicate artifact identity")
        found[key] = item
    if (UI, "any") not in found:
        raise DeltaRefused("baseline lacks UI module")
    return found


def assert_exact_delta(before: dict, after: dict, *, old_sequence: int) -> None:
    """Enforce exactly one package change; unchanged signed closure is immutable."""
    a = _records(before)
    b = _records(after)
    if set(a) != set(b):
        raise DeltaRefused("artifact inventory changed")
    if before["signed"]["sequence"] != old_sequence:
        raise DeltaRefused("baseline sequence drift")
    if after["signed"]["sequence"] != old_sequence + 1:
        raise DeltaRefused("release sequence must increment exactly once")
    old, new = a[(UI, "any")], b[(UI, "any")]
    if (old["version"], old["build"]) != (EXPECTED_PREVIOUS_VERSION, EXPECTED_PREVIOUS_BUILD):
        raise DeltaRefused("unexpected prior UI identity")
    if (new["version"], new["build"]) != (EXPECTED_VERSION, EXPECTED_BUILD):
        raise DeltaRefused("unexpected target UI identity")
    if old["package"]["sha256"] == new["package"]["sha256"]:
        raise DeltaRefused("new UI reused previous immutable package bytes")
    for key in a:
        if key == (UI, "any"):
            continue
        for field in ("artifact_id", "kind", "version", "build", "platform", "dependencies", "portable_config"):
            if a[key].get(field) != b[key].get(field):
                raise DeltaRefused(f"unrelated artifact metadata changed: {key} {field}")
        if a[key]["package"]["sha256"] != b[key]["package"]["sha256"]:
            raise DeltaRefused(f"unrelated artifact package changed: {key}")


def prepare(previous: Path, out: Path, *, baseline_index: Path,
            authority: Path, core_source_sha: str) -> dict:
    """Build UI58 only; retain the other 21 exact package bytes and their names.

    previous is a fresh, independently signed/verified copy of 22 stable ZIPs.
    """
    if out.exists() or out.is_symlink():
        raise DeltaRefused("output must not exist")
    raw = json.loads(baseline_index.read_text("utf-8"))
    existing = _records(raw)
    if raw["signed"]["sequence"] < 1:
        raise DeltaRefused("invalid baseline sequence")
    if (existing[(UI, "any")]["version"], existing[(UI, "any")]["build"]) != (
        EXPECTED_PREVIOUS_VERSION, EXPECTED_PREVIOUS_BUILD
    ):
        raise DeltaRefused("not the accepted UI57 predecessor")
    if previous.is_symlink() or not previous.is_dir():
        raise DeltaRefused("previous signed package directory is unavailable")
    files = {p.name: p for p in previous.iterdir() if p.is_file() and p.suffix == ".zip"}
    expected = {item["package"]["url"].removeprefix("platform/packages/"): item
                for item in existing.values()}
    if len(files) != 22 or set(files) != set(expected):
        raise DeltaRefused("previous stable ZIP inventory mismatches signed catalog")
    for name, source in files.items():
        if _digest(source) != expected[name]["package"]["sha256"]:
            raise DeltaRefused("previous stable ZIP digest mismatch: " + name)

    # Build the full first-party set as a deterministic QA fixture, but install
    # ONLY the changed UI ZIP into the resulting 22-package feed directory.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mb-ui58-") as scratch:
        all_built = build_all(Path(scratch), release_eligible=True)
        built = {p.name: p for p in all_built}
        ui = [p for p in all_built if p.name.startswith(UI + "-")]
        if len(all_built) != 10 or len(ui) != 1:
            raise DeltaRefused("UI candidate is not unique in reviewed build")
        target = ui[0]
        if target.name != f"{UI}-{EXPECTED_VERSION}-build{EXPECTED_BUILD}.zip":
            raise DeltaRefused("candidate identity drift")
        for name, path in built.items():
            if path == target:
                continue
            if name not in files or _digest(path) != _digest(files[name]):
                raise DeltaRefused("unchanged first-party module reproducibility failed: " + name)
        out.mkdir(parents=True)
        old_ui = existing[(UI, "any")]["package"]["url"].removeprefix("platform/packages/")
        for name, path in files.items():
            if name != old_ui:
                shutil.copyfile(path, out / name)
        shutil.copyfile(target, out / target.name)

    inventory = build_source(out, authority, core_source_sha=core_source_sha)
    after = {(item["artifact_id"], item["platform"]["arch"]): item
             for item in inventory["artifacts"]}
    if set(after) != set(existing) or len(inventory["artifacts"]) != 22:
        raise DeltaRefused("complete release source is not the same closure")
    for key, old in existing.items():
        if key != (UI, "any"):
            new = after[key]
            for field in ("artifact_id", "kind", "version", "build", "platform", "dependencies"):
                if old.get(field) != new.get(field):
                    raise DeltaRefused(f"unrelated source metadata differs: {key} {field}")
    return inventory


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--previous", type=Path, required=True)
    p.add_argument("--baseline-index", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--authority", type=Path, default=Path("platform/modules/first-party-successor-v1.json"))
    p.add_argument("--core-source-sha", required=True)
    args = p.parse_args()
    if args.source.exists() or args.source.is_symlink():
        raise SystemExit("source output already exists")
    inventory = prepare(args.previous, args.output,
                        baseline_index=args.baseline_index, authority=args.authority,
                        core_source_sha=args.core_source_sha)
    args.source.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Prepared unsigned 22-package successor delta: UI58 only; signer still required")


if __name__ == "__main__":
    main()
