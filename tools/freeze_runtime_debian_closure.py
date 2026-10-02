"""Verify and install the exact reviewed Debian runtime closure.

Fetch mode is CI-only and may consult Debian-signed package metadata, but every
selected package/version/path/hash/size is independently pinned below and in the
architecture lock. Install mode consumes only already-verified local .deb bytes;
the runtime Docker build performs no apt update/install or network access.

The closure now includes the Agent's external iputils ping executable required
by the accepted Broad Leaf ICMP checks, plus the exact additional packages that
changed relative to the immutable Python OCI base.
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
REQUIRED = ("libstdc++6", "libgcc-s1", "libatomic1", "iputils-ping")
GCC_VERSION = "12.2.0-14+deb12u1"
PING_VERSION = "3:20221126-1+deb12u1"
LIBCAP_BIN_VERSION = "1:2.66-4+deb12u3+b1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
BASE_CA = "714d457d580922dbf1d0be8bd35ba236a842b50b0072ae791582a19adef772a5"

APPROVED_CHANGED = {
    "amd64": (
        {
            "package": "iputils-ping",
            "version": PING_VERSION,
            "arch": "amd64",
            "filename": "iputils-ping_3%3a20221126-1+deb12u1_amd64.deb",
            "source_path": "pool/main/i/iputils/iputils-ping_20221126-1+deb12u1_amd64.deb",
            "sha256": "5a206d74e2147990e08b89d09a4655e59a17222e0513a309a48e16ed2281589b",
            "size": 47172,
        },
        {
            "package": "libatomic1",
            "version": GCC_VERSION,
            "arch": "amd64",
            "filename": "libatomic1_12.2.0-14+deb12u1_amd64.deb",
            "source_path": "pool/main/g/gcc-12/libatomic1_12.2.0-14+deb12u1_amd64.deb",
            "sha256": "fbd4e154a6b444229ea002cc209df099209c0adc09102e5fd21239a3d2b55e2d",
            "size": 9376,
        },
        {
            "package": "libcap2-bin",
            "version": LIBCAP_BIN_VERSION,
            "arch": "amd64",
            "filename": "libcap2-bin_1%3a2.66-4+deb12u3+b1_amd64.deb",
            "source_path": "pool/main/libc/libcap2/libcap2-bin_2.66-4+deb12u3+b1_amd64.deb",
            "sha256": "e7e14ebae53ef34c881a557e0a6d125b5e6721b692999045cf6af962daebe8d6",
            "size": 35220,
        },
    ),
    "arm64": (
        {
            "package": "iputils-ping",
            "version": PING_VERSION,
            "arch": "arm64",
            "filename": "iputils-ping_3%3a20221126-1+deb12u1_arm64.deb",
            "source_path": "pool/main/i/iputils/iputils-ping_20221126-1+deb12u1_arm64.deb",
            "sha256": "590a9f9226ed2c7fc71132d84d5eff8cf0e932f3744b42cbd02712ba7c9a2aca",
            "size": 46144,
        },
        {
            "package": "libatomic1",
            "version": GCC_VERSION,
            "arch": "arm64",
            "filename": "libatomic1_12.2.0-14+deb12u1_arm64.deb",
            "source_path": "pool/main/g/gcc-12/libatomic1_12.2.0-14+deb12u1_arm64.deb",
            "sha256": "1693aa13ce2b30d061a519fc28b77b9bab8c8e45804ced5969d99821e1bc2159",
            "size": 9568,
        },
        {
            "package": "libcap2-bin",
            "version": LIBCAP_BIN_VERSION,
            "arch": "arm64",
            "filename": "libcap2-bin_1%3a2.66-4+deb12u3+b1_arm64.deb",
            "source_path": "pool/main/libc/libcap2/libcap2-bin_2.66-4+deb12u3+b1_arm64.deb",
            "sha256": "139adf54b27522e838f3ce895c10d27a5fb406809b7b12d477dd5c13d2b2d286",
            "size": 34452,
        },
    ),
}


class FrozenDebianError(ValueError):
    pass


def run(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            args, check=True, text=True, capture_output=True, timeout=180, cwd=cwd,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
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
    expression = "-f=$" + "{Package}\t$" + "{Version}\t$" + "{Architecture}\n"
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


def _expected_baseline() -> dict[str, str | None]:
    return {
        "iputils-ping": None,
        "libatomic1": None,
        "libgcc-s1": GCC_VERSION,
        "libstdc++6": GCC_VERSION,
    }


def _expected_installed() -> dict[str, str]:
    return {
        "iputils-ping": PING_VERSION,
        "libatomic1": GCC_VERSION,
        "libgcc-s1": GCC_VERSION,
        "libstdc++6": GCC_VERSION,
    }


def load_lock(lock_dir: Path) -> dict:
    source = lock_file(lock_dir)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16384:
        raise FrozenDebianError("approved native ABI lock is absent or unsafe")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)
    except FrozenDebianError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise FrozenDebianError("malformed pinned Debian lock") from exc

    expected_keys = {
        "schema", "release_eligible", "packaging_stage", "base_image",
        "requested", "arch", "base_ca_sha256", "installed_ca_sha256",
        "baseline_abi_versions", "installed_abi_versions", "changed_packages",
    }
    arch = host_arch()
    if (
        type(raw) is not dict
        or set(raw) != expected_keys
        or type(raw["schema"]) is not int
        or raw["schema"] != 1
        or raw["release_eligible"] is not False
        or raw["packaging_stage"] != "sha256-locked-oci-base-debian-abi-proof"
        or raw["base_image"] != PYTHON_IMAGE
        or raw["arch"] != arch
        or raw["requested"] != list(REQUIRED)
        or raw["base_ca_sha256"] != BASE_CA
        or raw["installed_ca_sha256"] != BASE_CA
        or raw["baseline_abi_versions"] != _expected_baseline()
        or raw["installed_abi_versions"] != _expected_installed()
        or raw["changed_packages"] != list(APPROVED_CHANGED[arch])
    ):
        raise FrozenDebianError("unapproved Debian runtime closure or lock schema")
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
        if (
            fields.get("Package") == name
            and fields.get("Version") == version
            and fields.get("Architecture") == arch
        ):
            matches.add((fields.get("SHA256", ""), fields.get("Filename", "")))
    if len(matches) != 1:
        raise FrozenDebianError(
            f"selected Debian version absent/ambiguous in signed index: {name}"
        )
    return matches.pop()


def verify_archives(lock: dict, archives: Path) -> tuple[Path, ...]:
    if archives.is_symlink() or not archives.is_dir():
        raise FrozenDebianError("Debian archive directory missing or linked")
    entries = list(archives.iterdir())
    approved = {record["filename"]: record for record in lock["changed_packages"]}
    if (
        len(entries) != len(approved)
        or any(item.is_symlink() or not item.is_file() or item.name not in approved for item in entries)
        or set(item.name for item in entries) != set(approved)
    ):
        raise FrozenDebianError("unexpected missing/extra/linked Debian .deb files")

    verified: list[Path] = []
    for deb in sorted(entries, key=lambda item: item.name):
        record = approved[deb.name]
        if deb.stat().st_size != record["size"] or sha256(deb) != record["sha256"]:
            raise FrozenDebianError(
                "Debian .deb bytes differ from signed index + reviewed source lock"
            )
        fields = [
            run("dpkg-deb", "--field", str(deb), field).strip()
            for field in ("Package", "Version", "Architecture")
        ]
        if fields != [record["package"], record["version"], record["arch"]]:
            raise FrozenDebianError(
                "embedded dpkg metadata disagrees with pinned runtime package"
            )
        verified.append(deb)
    return tuple(verified)


def fetch(lock: dict, archives: Path) -> None:
    verify_base(lock)
    if archives.exists() or archives.is_symlink():
        raise FrozenDebianError("refusing to contaminate an existing downloaded ABI directory")
    archives.mkdir(mode=0o700, parents=True)
    run("apt-get", "update")
    for record in lock["changed_packages"]:
        sha, source = signed_index_record(record["package"], record["version"], record["arch"])
        if sha != record["sha256"] or source != record["source_path"]:
            raise FrozenDebianError(
                "current Debian-signed index differs from immutable source lock"
            )
        before = set(archives.iterdir())
        run("apt-get", "download", f'{record["package"]}={record["version"]}', cwd=archives)
        created = list(set(archives.iterdir()) - before)
        if len(created) != 1:
            raise FrozenDebianError("Debian package download produced ambiguous files")
        if created[0].name != record["filename"]:
            created[0].rename(archives / record["filename"])
    verify_archives(lock, archives)
    print("Verified exact Debian-signed runtime closure:", len(lock["changed_packages"]), "packages")


def install(lock: dict, archives: Path) -> None:
    verify_base(lock)
    debs = verify_archives(lock, archives)
    before = inventory()
    run("dpkg", "-i", *(str(path) for path in debs))
    after = inventory()

    changed = {
        name: version
        for name, version in after.items()
        if before.get(name) != version
    }
    expected_changed = {
        record["package"]: record["version"] for record in lock["changed_packages"]
    }
    if changed != expected_changed:
        raise FrozenDebianError(
            f"offline runtime install altered unexpected packages: {changed}"
        )
    for name, version in lock["installed_abi_versions"].items():
        if after.get(name) != version:
            raise FrozenDebianError("installed ABI distribution differs from lock: " + name)
    ca = Path("/etc/ssl/certs/ca-certificates.crt").resolve(strict=True)
    if sha256(ca) != lock["installed_ca_sha256"]:
        raise FrozenDebianError("offline package installation changed pinned CA")
    ping = Path("/usr/bin/ping")
    if not ping.is_file() or not os.access(ping, os.X_OK):
        raise FrozenDebianError("offline runtime closure did not install executable ping")
    print("Offline ICMP/ABI closure pinned, CA unchanged, no apt/network in builder.")


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
        print("Exact SHA256-locked Debian ICMP/ABI closure verified")


if __name__ == "__main__":
    main()
