#!/usr/bin/env python3
"""Generic integrity/reproducibility helper for changed module release candidates.

This intentionally does not encode a fixed set of release identities. Historical
immutable packages are repository state; changed release intents identify the only
packages that need to be rebuilt for a PR. The helper can snapshot those candidate
bytes, safely prune untracked builder byproducts not referenced by the staged
catalog, export the candidate packages for physical acceptance, and validate the
resulting staged catalog/package shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.source.json"
PACKAGES = ROOT / "packages"
INTENTS = ROOT / "release-intents"


def _identity(manifest: dict) -> tuple[str, str, int]:
    return (
        str(manifest.get("module_id") or ""),
        str(manifest.get("version") or ""),
        int(manifest.get("build") or 0),
    )


def _catalog() -> dict:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(data.get("modules"), list):
        raise SystemExit("catalog.source.json has no modules list")
    return data


def _changed_intents(base_ref: str) -> list[dict]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD", "--", "release-intents"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    intents: list[dict] = []
    seen_modules: set[str] = set()
    for relative in sorted(line.strip() for line in result.stdout.splitlines() if line.strip()):
        path = ROOT / relative
        if not path.is_file():
            # Deleted predecessor intents are expected during atomic successor swaps.
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        module_id = str(payload.get("module_id") or "")
        if not module_id:
            raise SystemExit(f"changed release intent has no module_id: {relative}")
        if module_id in seen_modules:
            raise SystemExit(f"multiple changed release intents for module {module_id}")
        seen_modules.add(module_id)
        intents.append(payload)
    return intents


def _candidate_rows(base_ref: str) -> list[dict]:
    catalog = _catalog()
    releases = {
        _identity(item.get("manifest", {})): item
        for item in catalog["modules"]
    }
    rows: list[dict] = []
    for intent in _changed_intents(base_ref):
        identity = (
            str(intent.get("module_id") or ""),
            str(intent.get("version") or ""),
            int(intent.get("build") or 0),
        )
        release = releases.get(identity)
        if release is None:
            raise SystemExit(f"changed release intent is not staged in catalog: {identity}")
        package = str(release.get("package") or "")
        path = PACKAGES / package
        if not path.is_file():
            raise SystemExit(f"changed release candidate package is missing: {package}")
        rows.append(
            {
                "module_id": identity[0],
                "version": identity[1],
                "build": identity[2],
                "package": package,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return sorted(rows, key=lambda row: (row["module_id"], row["version"], row["build"]))


def _snapshot(base_ref: str, output: Path) -> list[dict]:
    rows = _candidate_rows(base_ref)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"candidate snapshot: {len(rows)} release(s) -> {output}")
    return rows


def _referenced_package_paths() -> set[str]:
    return {
        f"packages/{str(item.get('package') or '')}"
        for item in _catalog()["modules"]
        if str(item.get("package") or "")
    }


def _untracked_package_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "packages"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().endswith(".zip")
    )


def _prune_unreferenced_untracked() -> None:
    referenced = _referenced_package_paths()
    removed: list[str] = []
    for relative in _untracked_package_paths():
        if relative in referenced:
            continue
        path = ROOT / relative
        if path.is_file():
            path.unlink()
            removed.append(relative)
    print(f"pruned unreferenced untracked package byproducts: {len(removed)}")
    remaining = [path for path in _untracked_package_paths() if path not in referenced]
    if remaining:
        raise SystemExit(f"unreferenced untracked package byproducts remain: {remaining}")


def _export_candidates(base_ref: str, output_dir: Path) -> None:
    rows = _candidate_rows(base_ref)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    for row in rows:
        shutil.copy2(PACKAGES / row["package"], output_dir / row["package"])
    (output_dir / "candidate-manifest.json").write_text(
        json.dumps(rows, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(rows)} candidate package(s) to {output_dir}")


def _validate_catalog_packages() -> None:
    catalog = _catalog()
    identities: set[tuple[str, str, int]] = set()
    package_names: set[str] = set()
    for item in catalog["modules"]:
        manifest = item.get("manifest")
        if not isinstance(manifest, dict):
            raise SystemExit("catalog release has no manifest object")
        identity = _identity(manifest)
        if not all((identity[0], identity[1])) or identity[2] <= 0:
            raise SystemExit(f"invalid catalog release identity: {identity}")
        if identity in identities:
            raise SystemExit(f"duplicate catalog release identity: {identity}")
        identities.add(identity)

        package = str(item.get("package") or "")
        expected = f"{identity[0]}-{identity[1]}-build{identity[2]}.zip"
        if package != expected:
            raise SystemExit(f"package filename does not match release identity {identity}: {package!r}")
        if package in package_names:
            raise SystemExit(f"duplicate catalog package reference: {package}")
        package_names.add(package)

        package_path = PACKAGES / package
        if not package_path.is_file():
            raise SystemExit(f"catalog package is missing: {package}")
        try:
            with zipfile.ZipFile(package_path) as archive:
                names = archive.namelist()
                if not names:
                    raise SystemExit(f"catalog package is empty: {package}")
                if len(names) != len(set(names)):
                    raise SystemExit(f"catalog package contains duplicate members: {package}")
                bad = archive.testzip()
                if bad is not None:
                    raise SystemExit(f"catalog package CRC failure {package}: {bad}")
                for name in names:
                    member = PurePosixPath(name)
                    if member.is_absolute() or ".." in member.parts:
                        raise SystemExit(f"catalog package contains unsafe path {package}: {name}")
                entrypoints = manifest.get("entrypoints")
                if not isinstance(entrypoints, dict) or not entrypoints:
                    raise SystemExit(f"catalog release has no entrypoints: {identity}")
                for value in entrypoints.values():
                    module_name = str(value or "").split(":", 1)[0]
                    module_path = module_name.replace(".", "/")
                    if f"{module_path}.py" not in names and f"{module_path}/__init__.py" not in names:
                        raise SystemExit(
                            f"catalog entrypoint {value!r} is absent from package {package}"
                        )
        except zipfile.BadZipFile as exc:
            raise SystemExit(f"catalog package is not a ZIP archive: {package}: {exc}") from exc

    referenced = {f"packages/{name}" for name in package_names}
    unexpected_untracked = [path for path in _untracked_package_paths() if path not in referenced]
    if unexpected_untracked:
        raise SystemExit(f"unreferenced untracked packages remain: {unexpected_untracked}")
    print(f"candidate repository package/catalog integrity: PASS ({len(identities)} releases)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--prune-unreferenced-untracked", action="store_true")
    parser.add_argument("--export-candidates", type=Path)
    args = parser.parse_args()

    if args.snapshot or args.export_candidates:
        if not args.base_ref:
            raise SystemExit("--base-ref is required for candidate snapshot/export")
    if args.snapshot:
        _snapshot(args.base_ref, args.snapshot)
    if args.prune_unreferenced_untracked:
        _prune_unreferenced_untracked()
    if args.export_candidates:
        _export_candidates(args.base_ref, args.export_candidates)
    if not (args.snapshot or args.prune_unreferenced_untracked or args.export_candidates):
        _validate_catalog_packages()


if __name__ == "__main__":
    main()
