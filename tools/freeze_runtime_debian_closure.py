"""Verify and install the exact reviewed Debian ABI change to pinned Python OCI.

Fetch mode is CI *only*: it checks Debian-signed apt index SHA256 against
source-committed architecture locks, downloads only the explicit .deb bytes
and refuses a moved/missing version. Install mode runs in the Docker builder
with NO apt update, apt install or package-network access. This is still
unreleaseable pending immutable Debian index/CA publication.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
PYTHON_IMAGE = "python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26"
REQUIRED = ("libstdc++6", "libgcc-s1", "libatomic1")
SHA = re.compile(r"[0-9a-f]{64}\Z")
VERSION = "12.2.0-14+deb12u1"
BASE_CA = "714d457d580922dbf1d0be8bd35ba236a842b50b0072ae791582a19adef772a5"


class FrozenDebianError(ValueError):
    pass


def run(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(args, check=True, text=True, capture_output=True,
                                timeout=180, cwd=cwd, env={
                                    **os.environ, "DEBIAN_FRONTEND": "noninteractive",
                                })
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise FrozenDebianError(f"pinned Debian operation failed: {args[0]}") from exc
    return result.stdout


def object_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FrozenDebianError("duplicate Debian lock JSON key")
        result[key] = value
    return result


def sha256(path: Path) -> str:
    handle = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            handle.update(chunk)
    return handle.hexdigest()


def inventory() -> dict[str, str]:
    expression = "-f=$" + "{Package}\\t$" + "{Version}\\t$" + "{Architecture}\\n"
    result: dict[str, str] = {}
    arch = host_arch()
    for line in run("dpkg-query", "-W", expression).splitlines():
        name, version, package_arch = line.split("\t")
        if package_arch == arch:
            if name in result:
                raise FrozenDebianError("duplicate native Debian installed package")
            result[name] = version
    return result


def host_arch() -> str:
    arch = ARCH.get(platform.machine())
    if arch is None or platform.system() != "Linux":
        raise FrozenDebianError("unsupported native Debian ABI platform")
    return arch


def lock_file(lock_dir: Path) -> Path:
    return lock_dir / f"lock-{host_arch()}.json"


def load_lock(lock_dir: Path) -> dict:
    source = lock_file(lock_dir)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 8192:
        raise FrozenDebianError("approved native ABI lock is absent or unsafe")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)
    except FrozenDebianError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise FrozenDebianError("malformed pinned Debian lock") from exc
    expected = {
        "schema", "release_eligible", "packaging_stage", "base_image",
        "requested", "arch", "base_ca_sha256", "installed_ca_sha256",
        "baseline_abi_versions", "installed_abi_versions", "changed_packages",
    }
    arch = host_arch()
    baseline = {"libatomic1": None, "libgcc-s1": VERSION, "libstdc++6": VERSION}
    installed = {key: VERSION for key in baseline}
    if (type(raw) is not dict or set(raw) != expected or
            type(raw["schema"]) is not int or raw["schema"] != 1 or
            raw["release_eligible"] is not False or
            raw["packaging_stage"] != "sha256-locked-oci-base-debian-abi-proof" or
            raw["base_image"] != PYTHON_IMAGE or raw["arch"] != arch or
            raw["requested"] != list(REQUIRED) or
            raw["base_ca_sha256"] != BASE_CA or
            raw["installed_ca_sha256"] != BASE_CA or
            raw["baseline_abi_versions"] != baseline or
            raw["installed_abi_versions"] != installed):
        raise FrozenDebianError("unapproved Debian ABI baseline or lock schema")
    records = raw["changed_packages"]
    if type(records) is not list or len(records) != 1 or type(records[0]) is not dict:
        raise FrozenDebianError("Debian ABI closure differs from reviewed package list")
    item = records[0]
    name = f"libatomic1_{VERSION}_{arch}.deb"
    approved = "fbd4e154a6b444229ea002cc209df099209c0adc09102e5fd21239a3d2b55e2d"
    size = 9376
    if arch == "arm64":
        approved = "1693aa13ce2b30d061a519fc28b77b9bab8c8e45804ced5969d99821e1bc2159"
        size = 9568
    if (set(item) != {"package", "version", "arch", "filename",
                       "source_path", "sha256", "size"} or
            item != {
                "package": "libatomic1", "version": VERSION, "arch": arch,
                "filename": name, "source_path": "pool/main/g/gcc-12/" + name,
                "sha256": approved, "size": size,
            }):
        raise FrozenDebianError("unreviewed Debian ABI .deb version/hash/size")
    return raw


def verify_base(lock: dict) -> None:
    current = inventory()
    for name, expected in lock["baseline_abi_versions"].items():
        if current.get(name) != expected:
            raise FrozenDebianError("pinned OCI base ABI distribution drift: " + name)
    ca = Path("/etc/ssl/certs/ca-certificates.crt").resolve(strict=True)
    if not ca.is_file() or sha256(ca) != lock["base_ca_sha256"]:
        raise FrozenDebianError("pinned OCI base CA certificate bytes differ")


def signed_index_record(name: str, version: str, arch: str) -> tuple[str, str]:
    matches = set()
    for paragraph in run("apt-cache", "show", f"{name}={version}").split("\n\n"):
        fields: dict[str, str] = {}
        for line in paragraph.splitlines():
            if line[:1].isspace():
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        if (fields.get("Package") == name and
                fields.get("Version") == version and
                fields.get("Architecture") == arch):
            matches.add((fields.get("SHA256", ""), fields.get("Filename", "")))
    if len(matches) != 1:
        raise FrozenDebianError("selected Debian version absent/ambiguous in signed index")
    return matches.pop()


def verify_archives(lock: dict, archives: Path) -> Path:
    if archives.is_symlink() or not archives.is_dir():
        raise FrozenDebianError("Debian archive directory missing or linked")
    record = lock["changed_packages"][0]
    entries = list(archives.iterdir())
    if (len(entries) != 1 or entries[0].is_symlink() or
            not entries[0].is_file() or entries[0].name != record["filename"]):
        raise FrozenDebianError("unexpected missing/extra/linked Debian .deb files")
    deb = entries[0]
    if deb.stat().st_size != record["size"] or sha256(deb) != record["sha256"]:
        raise FrozenDebianError("Debian .deb bytes differ from the signed index + source lock")
    # With multiple names, dpkg-deb -f emits labelled RFC822 fields;
    # ask each one independently to compare its raw exact value.
    fields = [
        run("dpkg-deb", "--field", str(deb), field).strip()
        for field in ("Package", "Version", "Architecture")
    ]
    if fields != [record["package"], record["version"], record["arch"]]:
        raise FrozenDebianError("embedded dpkg metadata disagrees with pinned ABI package")
    return deb


def fetch(lock: dict, archives: Path) -> None:
    verify_base(lock)
    if archives.exists() or archives.is_symlink():
        raise FrozenDebianError("refusing to contaminate an existing downloaded ABI directory")
    archives.mkdir(mode=0o700, parents=True)
    run("apt-get", "update")  # Debian-signed indexes, discovery/fetch CI ONLY
    record = lock["changed_packages"][0]
    sha, source = signed_index_record(record["package"], record["version"], record["arch"])
    if sha != record["sha256"] or source != record["source_path"]:
        raise FrozenDebianError("current Debian-signed index differs from immutable source lock")
    run("apt-get", "download", f'{record["package"]}={record["version"]}', cwd=archives)
    verify_archives(lock, archives)
    print("Verified exact Debian-signed SHA256 against source lock:", record["filename"])


def install(lock: dict, archives: Path) -> None:
    verify_base(lock)
    deb = verify_archives(lock, archives)
    before = inventory()
    # Direct dpkg installation uses only already-verified local bytes.
    # Never invoke apt or touch package indexes in the runtime Dockerfile.
    run("dpkg", "-i", str(deb))
    after = inventory()
    changed = {name: version for name, version in after.items()
               if before.get(name) != version}
    if changed != {"libatomic1": VERSION}:
        raise FrozenDebianError("offline ABI install altered unexpected packages")
    for name, version in lock["installed_abi_versions"].items():
        if after.get(name) != version:
            raise FrozenDebianError("installed ABI distribution differs from lock: " + name)
    ca = Path("/etc/ssl/certs/ca-certificates.crt").resolve(strict=True)
    if sha256(ca) != lock["installed_ca_sha256"]:
        raise FrozenDebianError("offline package installation changed pinned CA")
    # /build/debian/lock-*.json is copied into the builder, and
    # downstream runtime packager independently checks this evidence.
    print("Offline ABI closure pinned, CA unchanged, no apt/network in builder.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("fetch", "install", "verify"))
    parser.add_argument("--lock-dir", required=True, type=Path)
    parser.add_argument("--archives", required=True, type=Path)
    args = parser.parse_args()
    lock = load_lock(args.lock_dir)
    if args.operation == "fetch":
        fetch(lock, args.archives)
    elif args.operation == "install":
        install(lock, args.archives)
    else:
        verify_base(lock)
        verify_archives(lock, args.archives)
        print("Exact SHA256-locked Debian ABI package and pinned OCI baseline verified")


if __name__ == "__main__":
    main()
