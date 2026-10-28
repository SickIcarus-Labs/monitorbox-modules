"""Channel pointer helpers. Standard library only, so CI needs no installs.

A channel pointer is one JSON file (channels/dev.json, beta.json, stable.json)
that names the exact App and module versions an install on that channel gets.
Moving a channel means replacing one file in one commit.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CHANNELS = ("dev", "beta", "stable")
# Allowed promotions. Anything else is refused.
PROMOTIONS = {("dev", "beta"), ("beta", "stable")}

# Modules that exist only to try things out (the sample module). They are published to dev and never promoted: beta and stable never list them.
DEV_ONLY = ("hello",)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MODULE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


def _check_artifact(where: str, item: object, errors: list[str]) -> None:
    """An artifact is a downloadable archive: version, https url, sha256."""
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return
    allowed = {"version", "url", "sha256", "signature"}
    for key in item:
        if key not in allowed:
            errors.append(f"{where}: unknown key {key!r}")
    version = item.get("version")
    if not isinstance(version, str) or not _SEMVER.match(version):
        errors.append(f"{where}.version: must be a semantic version like 1.2.3")
    url = item.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{where}.url: must be an https URL")
    digest = item.get("sha256")
    if not isinstance(digest, str) or not _SHA256.match(digest):
        errors.append(f"{where}.sha256: must be 64 lowercase hex characters")
    # Reserved so signing can be added later without a format change.
    if item.get("signature") is not None and not isinstance(item.get("signature"), str):
        errors.append(f"{where}.signature: must be null or a string")


def validate(pointer: object, expected_channel: str | None = None) -> list[str]:
    """Return a list of problems; an empty list means the pointer is valid."""
    errors: list[str] = []
    if not isinstance(pointer, dict):
        return ["pointer must be a JSON object"]
    allowed = {"schema", "channel", "updated", "promotedFrom", "app", "modules", "launcher"}
    for key in pointer:
        if key not in allowed:
            errors.append(f"unknown top-level key {key!r}")
    if pointer.get("schema") != 1:
        errors.append("schema: must be 1")
    channel = pointer.get("channel")
    if channel not in CHANNELS:
        errors.append(f"channel: must be one of {', '.join(CHANNELS)}")
    elif expected_channel and channel != expected_channel:
        errors.append(f"channel: file is for {expected_channel!r} but says {channel!r}")
    if not isinstance(pointer.get("updated"), str):
        errors.append("updated: must be a timestamp string")
    # Optional: the container image (launcher) version this release was built for, so a box on an older image can say so.
    launcher = pointer.get("launcher")
    if launcher is not None:
        if not isinstance(launcher, dict) or set(launcher) != {"version"} or not isinstance(launcher["version"], str) or not _SEMVER.match(launcher["version"]):
            errors.append("launcher: must be {\"version\": \"1.2.3\"} or absent")
    # app is null until the first App release exists.
    if pointer.get("app") is not None:
        _check_artifact("app", pointer["app"], errors)
    modules = pointer.get("modules")
    if not isinstance(modules, dict):
        errors.append("modules: must be an object keyed by module id")
    else:
        for module_id, item in modules.items():
            if not _MODULE_ID.match(module_id):
                errors.append(f"modules: bad module id {module_id!r}")
            _check_artifact(f"modules.{module_id}", item, errors)
    return errors


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def promote(source: object, target_channel: str, now: str, source_channel: str) -> dict:
    """Build the target pointer from a validated source pointer."""
    if (source_channel, target_channel) not in PROMOTIONS:
        raise ValueError(
            f"promotion {source_channel} -> {target_channel} is not allowed; "
            f"allowed: {', '.join(f'{a} -> {b}' for a, b in sorted(PROMOTIONS))}"
        )
    problems = validate(source, source_channel)
    if problems:
        raise ValueError("source pointer is invalid: " + "; ".join(problems))
    if source.get("app") is None:  # type: ignore[union-attr]
        raise ValueError("source pointer has no App release yet; nothing to promote")
    result = dict(source)  # type: ignore[arg-type]
    result["modules"] = {k: v for k, v in source["modules"].items() if k not in DEV_ONLY}  # type: ignore[index]
    result["channel"] = target_channel
    result["updated"] = now
    result["promotedFrom"] = source_channel
    return result


def rollback(old: object, channel: str, now: str, ref: str) -> dict:
    """Re-publish an earlier pointer of the same channel (an undo)."""
    problems = validate(old, channel)
    if problems:
        raise ValueError("earlier pointer is invalid: " + "; ".join(problems))
    result = dict(old)  # type: ignore[arg-type]
    result["updated"] = now
    result["promotedFrom"] = f"rollback:{ref[:12]}"
    return result


def dump(pointer: object) -> str:
    return json.dumps(pointer, indent=2, sort_keys=False) + "\n"


def main(argv: list[str]) -> int:
    """Validate every channel file: python tools/pointer.py channels/*.json"""
    status = 0
    for name in argv:
        path = Path(name)
        problems = validate(load(path), path.stem)
        for problem in problems:
            print(f"{path}: {problem}")
            status = 1
        if not problems:
            print(f"{path}: ok")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
