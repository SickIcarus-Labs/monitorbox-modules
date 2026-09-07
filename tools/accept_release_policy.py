#!/usr/bin/env python3
"""Executable negative/positive acceptance matrix for VERSIONING.md policy."""
from __future__ import annotations

from pathlib import Path

from release_policy import Release, ReleasePolicyError, SemVer, validate_history, validate_release

MODULE = "com.sickicarus.monitorbox.example"
SOURCE = "sources/example/"


def release(version: str, build: int, *, module_id: str = MODULE) -> Release:
    return Release(module_id, SemVer.parse(version), build, f"{module_id}-{version}-build{build}.zip", "com.sickicarus")


def intent(version: str, build: int, change_class: str, *, module_id: str = MODULE):
    return {
        "schema": 1,
        "module_id": module_id,
        "version": version,
        "build": build,
        "change_class": change_class,
        "source_prefix": SOURCE,
        "issue": 167,
        "summary": "synthetic release-policy acceptance case",
    }


def expect_reject(label: str, fn, contains: str) -> None:
    try:
        fn()
    except ReleasePolicyError as exc:
        if contains not in str(exc):
            raise AssertionError(f"{label}: wrong rejection: {exc}") from exc
    else:
        raise AssertionError(f"{label}: expected rejection")


def check(candidate_version: str, build: int, change_class: str, *, source_changed: bool = True):
    base = [release("1.0.0", 5)]
    candidate = base + [release(candidate_version, build)]
    return validate_release(
        base,
        candidate,
        paths=[SOURCE + "provider.py"] if source_changed else ["tools/repack.py"],
        intents={MODULE: intent(candidate_version, build, change_class)},
    )


def main() -> None:
    expect_reject(
        "behavior change at same semver",
        lambda: check("1.0.0", 6, "packaging-only", source_changed=True),
        "same-semver packaging-only publication is forbidden",
    )
    check("1.0.1", 6, "patch-polish")
    check("1.1.0", 6, "compatible-feature")
    check("2.0.0", 6, "breaking-feature")
    check("1.0.0", 6, "packaging-only", source_changed=False)

    expect_reject(
        "new first-party module below 1.0.0",
        lambda: validate_history([release("0.9.0", 1, module_id="com.sickicarus.monitorbox.new")]),
        "must be 1.0.0",
    )

    historical = [release("1.0.0", 1), release("1.0.0", 2), release("1.0.1", 3)]
    validate_history(historical)
    validate_release(historical, list(historical), paths=[], intents={})

    expect_reject(
        "source change without release candidate",
        lambda: validate_release(
            [release("1.0.0", 5)],
            [release("1.0.0", 5)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.1", 6, "patch-polish")},
        ),
        "no corresponding semantic release candidate",
    )

    expect_reject(
        "non-increasing build",
        lambda: validate_release(
            [release("1.0.0", 5)],
            [release("1.0.0", 5), release("1.0.1", 5)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.1", 5, "patch-polish")},
        ),
        "builds are not strictly increasing",
    )

    print("module release policy acceptance: PASS")


if __name__ == "__main__":
    main()
