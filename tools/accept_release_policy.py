#!/usr/bin/env python3
"""Executable negative/positive acceptance matrix for VERSIONING.md policy."""
from __future__ import annotations

from release_policy import (
    DevSupersession,
    Release,
    ReleasePolicyError,
    SemVer,
    validate_history,
    validate_release,
)

MODULE = "com.sickicarus.monitorbox.example"
SOURCE = "sources/example/"
DEV_DIGEST = "a" * 64
DEV_COMMIT = "b" * 40


def release(version: str, build: int, *, module_id: str = MODULE) -> Release:
    return Release(module_id, SemVer.parse(version), build, f"{module_id}-{version}-build{build}.zip", "com.sickicarus")


def intent(
    version: str,
    build: int,
    change_class: str,
    *,
    module_id: str = MODULE,
    supersedes_dev: tuple[str, int] | None = None,
):
    row = {
        "schema": 1,
        "module_id": module_id,
        "version": version,
        "build": build,
        "change_class": change_class,
        "source_prefix": SOURCE,
        "issue": 167,
        "summary": "synthetic release-policy acceptance case",
    }
    if supersedes_dev is not None:
        row["supersedes_dev"] = {
            "version": supersedes_dev[0],
            "build": supersedes_dev[1],
            "sha256": DEV_DIGEST,
            "authority_commit": DEV_COMMIT,
        }
    return row


def dev_supersession(version: str, build: int) -> DevSupersession:
    return DevSupersession(release(version, build), DEV_DIGEST, DEV_COMMIT)


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

    new_id = "com.sickicarus.monitorbox.new"
    expect_reject(
        "new first-party module below 1.0.0",
        lambda: validate_release(
            [],
            [release("0.9.0", 1, module_id=new_id)],
            paths=[SOURCE + "provider.py"],
            intents={new_id: intent("0.9.0", 1, "compatible-feature", module_id=new_id)},
        ),
        "must start at 1.0.0",
    )

    historical = [
        release("0.9.0", 4),
        release("0.9.0", 5),
        release("1.0.0", 1),
        release("1.0.1", 2),
    ]
    validate_history(historical)
    validate_release(historical, list(historical), paths=[], intents={})

    expect_reject(
        "post-policy build reset",
        lambda: validate_release(
            historical,
            historical + [release("1.0.2", 3)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.2", 3, "patch-polish")},
        ),
        "must increase beyond preserved maximum 5",
    )
    validate_release(
        historical,
        historical + [release("1.0.2", 6)],
        paths=[SOURCE + "provider.py"],
        intents={MODULE: intent("1.0.2", 6, "patch-polish")},
    )

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
        "non-increasing new build",
        lambda: validate_release(
            [release("1.0.0", 5)],
            [release("1.0.0", 5), release("1.0.1", 5)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.1", 5, "patch-polish")},
        ),
        "must increase beyond preserved maximum 5",
    )

    # A physically rejected dev package is real immutable semantic history even
    # though it never enters trunk/beta/stable. The superseding candidate must
    # advance from that exact signed identity, not reuse its semantic version.
    base = [release("1.0.1", 2)]
    candidate = base + [release("1.0.3", 4)]
    superseding_intent = intent(
        "1.0.3",
        4,
        "patch-polish",
        supersedes_dev=("1.0.2", 3),
    )
    validate_release(
        base,
        candidate,
        paths=[SOURCE + "provider.py"],
        intents={MODULE: superseding_intent},
        dev_supersessions={MODULE: dev_supersession("1.0.2", 3)},
    )

    expect_reject(
        "declared dev supersession without trusted resolution",
        lambda: validate_release(
            base,
            candidate,
            paths=[SOURCE + "provider.py"],
            intents={MODULE: superseding_intent},
        ),
        "no trusted predecessor was resolved",
    )

    expect_reject(
        "superseding dev candidate reuses failed semantic version",
        lambda: validate_release(
            base,
            base + [release("1.0.2", 4)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.2", 4, "patch-polish", supersedes_dev=("1.0.2", 3))},
            dev_supersessions={MODULE: dev_supersession("1.0.2", 3)},
        ),
        "patch-polish release must advance 1.0.2 -> 1.0.3",
    )

    expect_reject(
        "superseding dev candidate does not advance build",
        lambda: validate_release(
            base,
            base + [release("1.0.3", 3)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: intent("1.0.3", 3, "patch-polish", supersedes_dev=("1.0.2", 3))},
            dev_supersessions={MODULE: dev_supersession("1.0.2", 3)},
        ),
        "must increase beyond preserved maximum 3",
    )

    expect_reject(
        "dev predecessor already in trunk history",
        lambda: validate_release(
            base + [release("1.0.2", 3)],
            base + [release("1.0.2", 3), release("1.0.3", 4)],
            paths=[SOURCE + "provider.py"],
            intents={MODULE: superseding_intent},
            dev_supersessions={MODULE: dev_supersession("1.0.2", 3)},
        ),
        "already trunk/stable history",
    )

    print("module release policy acceptance: PASS")


if __name__ == "__main__":
    main()
