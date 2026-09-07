#!/usr/bin/env python3
"""Canonical semantic-version/build guardrail for signed MonitorBox modules."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
CHANGE_CLASSES = {"breaking-feature", "compatible-feature", "patch-polish", "packaging-only"}
INTENT_DIR = Path("release-intents")


class ReleasePolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> "SemVer":
        text = str(value)
        match = SEMVER_RE.fullmatch(text)
        if not match:
            raise ReleasePolicyError(f"invalid semantic version {text!r}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class Release:
    module_id: str
    version: SemVer
    build: int
    package: str
    publisher_id: str

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.module_id, str(self.version), self.build


def load_catalog(path: Path) -> list[Release]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleasePolicyError(f"cannot read catalog {path}: {exc}") from exc
    if data.get("schema") != 1 or not isinstance(data.get("modules"), list):
        raise ReleasePolicyError(f"{path} is not a schema-1 module catalog")
    releases: list[Release] = []
    for row in data["modules"]:
        if not isinstance(row, dict) or not isinstance(row.get("manifest"), dict):
            raise ReleasePolicyError("catalog module row is malformed")
        manifest = row["manifest"]
        module_id = manifest.get("module_id")
        build = manifest.get("build")
        package = row.get("package")
        publisher = manifest.get("publisher_id", "")
        if not isinstance(module_id, str) or not module_id:
            raise ReleasePolicyError("module_id must be non-empty")
        if not isinstance(build, int) or build <= 0:
            raise ReleasePolicyError(f"{module_id} has invalid build {build!r}")
        if not isinstance(package, str) or not package:
            raise ReleasePolicyError(f"{module_id} build {build} has no package")
        releases.append(Release(module_id, SemVer.parse(manifest.get("version")), build, package, str(publisher)))
    return releases


def validate_history(releases: Iterable[Release]) -> None:
    by_module: dict[str, list[Release]] = {}
    identities: set[tuple[str, str, int]] = set()
    for release in releases:
        if release.identity in identities:
            raise ReleasePolicyError(f"duplicate release identity {release.identity}")
        identities.add(release.identity)
        by_module.setdefault(release.module_id, []).append(release)

    for module_id, history in by_module.items():
        history.sort(key=lambda item: item.build)
        builds = [item.build for item in history]
        if builds != sorted(set(builds)):
            raise ReleasePolicyError(f"{module_id} builds are not strictly increasing")
        if history[0].publisher_id == "com.sickicarus" and history[0].version != SemVer(1, 0, 0):
            raise ReleasePolicyError(f"first first-party release of {module_id} must be 1.0.0")
        previous = history[0].version
        for release in history[1:]:
            if release.version < previous:
                raise ReleasePolicyError(
                    f"{module_id} semantic version regressed at build {release.build}: {release.version} < {previous}"
                )
            previous = release.version


def load_intents(root: Path = INTENT_DIR) -> dict[str, dict[str, Any]]:
    intents: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return intents
    for path in sorted(root.glob("*.json")):
        try:
            intent = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleasePolicyError(f"cannot read {path}: {exc}") from exc
        if intent.get("schema") != 1:
            raise ReleasePolicyError(f"{path} must use intent schema 1")
        module_id = intent.get("module_id")
        if not isinstance(module_id, str) or not module_id:
            raise ReleasePolicyError(f"{path} has invalid module_id")
        if module_id in intents:
            raise ReleasePolicyError(f"duplicate release intent for {module_id}")
        if intent.get("change_class") not in CHANGE_CLASSES:
            raise ReleasePolicyError(f"{path} has invalid change_class {intent.get('change_class')!r}")
        SemVer.parse(intent.get("version"))
        if not isinstance(intent.get("build"), int) or intent["build"] <= 0:
            raise ReleasePolicyError(f"{path} has invalid build")
        source_prefix = intent.get("source_prefix")
        if not isinstance(source_prefix, str) or not source_prefix.startswith("sources/") or not source_prefix.endswith("/"):
            raise ReleasePolicyError(f"{path} source_prefix must be a sources/.../ prefix")
        if not isinstance(intent.get("issue"), int) or intent["issue"] <= 0:
            raise ReleasePolicyError(f"{path} must identify a positive issue number")
        if not isinstance(intent.get("summary"), str) or not intent["summary"].strip():
            raise ReleasePolicyError(f"{path} must contain a reviewable summary")
        intents[module_id] = intent
    return intents


def changed_paths(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _previous_for(module_id: str, releases: list[Release]) -> Release | None:
    matches = [release for release in releases if release.module_id == module_id]
    return max(matches, key=lambda item: item.build) if matches else None


def _check_bump(previous: Release | None, candidate: Release, intent: dict[str, Any], source_changed: bool) -> None:
    change_class = intent["change_class"]
    expected_version = SemVer.parse(intent["version"])
    if candidate.version != expected_version or candidate.build != intent["build"]:
        raise ReleasePolicyError(
            f"{candidate.module_id} candidate {candidate.version}+{candidate.build} does not match release intent "
            f"{expected_version}+{intent['build']}"
        )
    if previous is None:
        if candidate.publisher_id == "com.sickicarus" and candidate.version != SemVer(1, 0, 0):
            raise ReleasePolicyError(f"new first-party module {candidate.module_id} must start at 1.0.0")
        return
    if candidate.build <= previous.build:
        raise ReleasePolicyError(f"{candidate.module_id} build must increase beyond {previous.build}")

    if change_class == "packaging-only":
        if candidate.version != previous.version:
            raise ReleasePolicyError("packaging-only release must retain semantic version")
        if source_changed:
            raise ReleasePolicyError(
                f"{candidate.module_id} changes module source; same-semver packaging-only publication is forbidden"
            )
    elif change_class == "patch-polish":
        expected = SemVer(previous.version.major, previous.version.minor, previous.version.patch + 1)
        if candidate.version != expected:
            raise ReleasePolicyError(f"patch-polish release must advance {previous.version} -> {expected}")
    elif change_class == "compatible-feature":
        expected = SemVer(previous.version.major, previous.version.minor + 1, 0)
        if candidate.version != expected:
            raise ReleasePolicyError(f"compatible feature must advance {previous.version} -> {expected}")
    elif change_class == "breaking-feature":
        expected = SemVer(previous.version.major + 1, 0, 0)
        if candidate.version != expected:
            raise ReleasePolicyError(f"breaking feature must advance {previous.version} -> {expected}")


def validate_release(
    baseline: list[Release],
    candidate: list[Release],
    *,
    paths: Iterable[str],
    intents: dict[str, dict[str, Any]],
    require_packages: bool = False,
    root: Path = Path("."),
) -> list[Release]:
    validate_history(baseline)
    validate_history(candidate)
    base_ids = {item.identity for item in baseline}
    candidate_ids = {item.identity for item in candidate}
    removed = base_ids - candidate_ids
    if removed:
        raise ReleasePolicyError(f"historical signed release identities were removed: {sorted(removed)}")
    new = [item for item in candidate if item.identity not in base_ids]

    new_by_module: dict[str, list[Release]] = {}
    for release in new:
        new_by_module.setdefault(release.module_id, []).append(release)
    duplicate_candidates = {module: rows for module, rows in new_by_module.items() if len(rows) > 1}
    if duplicate_candidates:
        raise ReleasePolicyError(f"one publication may add only one release per module: {sorted(duplicate_candidates)}")

    path_list = list(paths)
    for release in new:
        intent = intents.get(release.module_id)
        if intent is None:
            raise ReleasePolicyError(f"new release {release.identity} has no release-intents metadata")
        source_changed = any(path.startswith(intent["source_prefix"]) for path in path_list)
        previous = _previous_for(release.module_id, baseline)
        _check_bump(previous, release, intent, source_changed)
        if require_packages and not (root / "packages" / release.package).is_file():
            raise ReleasePolicyError(f"candidate package packages/{release.package} was not built")
        print(
            f"module:{release.module_id} candidate v{release.version} build {release.build} "
            f"class={intent['change_class']} package={release.package}"
        )

    for path in path_list:
        if not path.startswith("sources/"):
            continue
        matching = [module_id for module_id, intent in intents.items() if path.startswith(intent["source_prefix"])]
        if not matching:
            raise ReleasePolicyError(f"module source change {path} has no release intent")
        if not any(module_id in new_by_module for module_id in matching):
            raise ReleasePolicyError(f"module source change {path} has no corresponding semantic release candidate")

    return new


def _tool_path(intent: dict[str, Any], key: str) -> str | None:
    value = intent.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("tools/") or ".." in Path(value).parts or not value.endswith(".py"):
        raise ReleasePolicyError(f"intent {key} must be a repository-local tools/*.py path")
    if not Path(value).is_file():
        raise ReleasePolicyError(f"intent {key} does not exist: {value}")
    return value


def run_changed_intents(base_ref: str, intents: dict[str, dict[str, Any]]) -> None:
    changed = set(changed_paths(base_ref))
    intent_files = {str(path) for path in INTENT_DIR.glob("*.json") if str(path) in changed}
    for path in sorted(intent_files):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        module_id = raw["module_id"]
        intent = intents[module_id]
        print(
            f"Preparing module:{module_id} v{intent['version']} build {intent['build']} "
            f"class={intent['change_class']}"
        )
        for key in ("stager", "builder"):
            tool = _tool_path(intent, key)
            if tool:
                subprocess.run([sys.executable, tool], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--base-catalog", type=Path, required=True)
    validate.add_argument("--candidate-catalog", type=Path, default=Path("catalog.source.json"))
    validate.add_argument("--base-ref", required=True)
    validate.add_argument("--require-packages", action="store_true")
    run = sub.add_parser("run-intents")
    run.add_argument("--base-ref", required=True)
    args = parser.parse_args(argv)

    try:
        intents = load_intents()
        if args.command == "run-intents":
            run_changed_intents(args.base_ref, intents)
        else:
            new = validate_release(
                load_catalog(args.base_catalog),
                load_catalog(args.candidate_catalog),
                paths=changed_paths(args.base_ref),
                intents=intents,
                require_packages=args.require_packages,
            )
            print(f"release policy accepted {len(new)} new module candidate(s)")
    except (OSError, subprocess.CalledProcessError, ReleasePolicyError, json.JSONDecodeError) as exc:
        print(f"release policy rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
