"""Move a channel: copy one pointer file onto another, or roll one back.

  python tools/promote.py --source dev --target beta
  python tools/promote.py --source stable --target stable --ref <commit>   # rollback

Nothing is rebuilt. Only the pointer file changes. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import pointer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _show(ref: str, channel: str) -> object:
    out = subprocess.run(
        ["git", "show", f"{ref}:channels/{channel}.json"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=pointer.CHANNELS)
    parser.add_argument("--target", required=True, choices=pointer.CHANNELS)
    parser.add_argument("--ref", default="", help="git ref to read the source from (required for rollback)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        if args.source == args.target:
            if not args.ref:
                raise ValueError("a rollback needs --ref: the commit whose pointer to restore")
            result = pointer.rollback(_show(args.ref, args.source), args.target, now, args.ref)
        else:
            source = _show(args.ref or "HEAD", args.source)
            result = pointer.promote(source, args.target, now, args.source)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1

    if args.source != args.target:  # forward promotion: record that these versions reached the target
        try:
            cat_path = ROOT / "catalog.json"
            cat = catalog.mark_reached(catalog.load(cat_path), result, args.target)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        cat_path.write_text(catalog.dump(cat), encoding="utf-8")
        print("updated catalog.json")

    target_path = ROOT / "channels" / f"{args.target}.json"
    target_path.write_text(pointer.dump(result), encoding="utf-8")
    print(f"wrote {target_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
