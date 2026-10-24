"""The catalog: every released version and which channels it has reached.

catalog.json:
  {"schema": 1,
   "app": [{"version","url","sha256","signature","published","channels":["dev",...]}],
   "modules": {"<id>": [ ...same entries... ]}}

A version enters as ["dev"] when published. Promotion adds "beta", then "stable".
A channel offers the versions whose entry lists that channel. Standard library only.

  python tools/catalog.py catalog.json channels/*.json   # validate, cross-check pointers
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pointer  # noqa: E402

ORDER = ("dev", "beta", "stable")  # a version must reach them in this order


def validate(catalog: object) -> list[str]:
    errs: list[str] = []
    if not isinstance(catalog, dict) or catalog.get("schema") != 1:
        return ["catalog: schema must be 1"]
    groups = [("app", catalog.get("app"))] + [
        (f"modules.{mid}", entries) for mid, entries in (catalog.get("modules") or {}).items()
    ]
    for mid in (catalog.get("modules") or {}):
        if not pointer._MODULE_ID.match(mid):
            errs.append(f"catalog: bad module id {mid!r}")
    for name, entries in groups:
        if not isinstance(entries, list):
            errs.append(f"{name}: must be a list")
            continue
        seen = set()
        for e in entries:
            v = e.get("version", "?") if isinstance(e, dict) else "?"
            if not isinstance(e, dict) or not pointer._SEMVER.match(str(v)):
                errs.append(f"{name} {v}: bad entry/version")
                continue
            if v in seen:
                errs.append(f"{name} {v}: listed twice")
            seen.add(v)
            if not pointer._SHA256.match(str(e.get("sha256", ""))):
                errs.append(f"{name} {v}: sha256 must be 64 lowercase hex")
            if not str(e.get("url", "")).startswith("https://"):
                errs.append(f"{name} {v}: url must be https")
            ch = e.get("channels")
            if not isinstance(ch, list) or list(ch) != list(ORDER[: len(ch)]) or not ch:
                errs.append(f"{name} {v}: channels must be a prefix of {list(ORDER)}")
    return errs


def cross_check(catalog: dict, pointers: dict[str, dict]) -> list[str]:
    """Every version a channel points at must exist and have reached that channel."""
    errs = []
    for channel, ptr in pointers.items():
        refs = []
        if ptr.get("app"):
            refs.append(("app", catalog["app"], ptr["app"]))
        for mid, m in (ptr.get("modules") or {}).items():
            refs.append((f"module {mid}", (catalog.get("modules") or {}).get(mid, []), m))
        for name, entries, ref in refs:
            hit = next((e for e in entries if e["version"] == ref["version"]), None)
            if not hit:
                errs.append(f"{channel}: {name} {ref['version']} is not in the catalog")
            elif channel not in hit["channels"]:
                errs.append(f"{channel}: {name} {ref['version']} has not reached {channel} in the catalog")
            elif hit["sha256"] != ref["sha256"]:
                errs.append(f"{channel}: {name} {ref['version']} sha256 differs from the catalog")
    return errs


def mark_reached(catalog: dict, ptr: dict, channel: str) -> dict:
    """Add `channel` to the entries a promoted pointer names. Refuses to skip a stage."""
    prev = ORDER[ORDER.index(channel) - 1]
    refs = []
    if ptr.get("app"):
        refs.append(("app", catalog["app"], ptr["app"]["version"]))
    for mid, m in (ptr.get("modules") or {}).items():
        refs.append((f"module {mid}", (catalog.get("modules") or {}).get(mid, []), m["version"]))
    for name, entries, v in refs:
        hit = next((e for e in entries if e["version"] == v), None)
        if not hit:
            raise ValueError(f"{name} {v} is not in the catalog")
        if channel not in hit["channels"]:
            if prev not in hit["channels"]:
                raise ValueError(f"{name} {v} has not reached {prev}")
            hit["channels"].append(channel)
    return catalog


def load(path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(catalog: object) -> str:
    return json.dumps(catalog, indent=2) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: catalog.py catalog.json [channels/*.json]", file=sys.stderr)
        return 2
    cat = load(argv[0])
    errs = validate(cat)
    if not errs:
        ptrs = {Path(p).stem: load(p) for p in argv[1:]}
        errs = cross_check(cat, ptrs)
    for e in errs:
        print("ERROR", e, file=sys.stderr)
    if not errs:
        print("catalog ok")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
