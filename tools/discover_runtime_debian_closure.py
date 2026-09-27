"""Dev-only discovery of exact Debian .deb changes to the digest-pinned base.

Runs inside native Python 3.13 Bookworm images. Apt verifies signed index
metadata, then discovered package SHA256 and actual downloaded bytes are
compared. Discovery alone does NOT freeze the mutable apt package index.
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
PACKAGES = ("libstdc++6", "libgcc-s1", "libatomic1")
SHA = re.compile(r"^[a-f0-9]{64}$")
ROOT = Path("/out")


def run(*command: str, cwd: Path | None = None) -> str:
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, timeout=180)
    return result.stdout


def inventory() -> dict[tuple[str, str], str]:
    output: dict[tuple[str, str], str] = {}
    expression = "-f=$" + "{Package}\\t$" + "{Version}\\t$" + "{Architecture}\\n"
    for line in run("dpkg-query", "-W", expression).splitlines():
        name, version, arch = line.split("\t")
        if (name, arch) in output:
            raise RuntimeError("duplicate Debian installed package")
        output[(name, arch)] = version
    return output


def signed_index_record(name: str, version: str, arch: str) -> tuple[str, str]:
    matches: set[tuple[str, str]] = set()
    for paragraph in run("apt-cache", "show", f"{name}={version}").split("\n\n"):
        pairs = {}
        for line in paragraph.splitlines():
            if line[:1].isspace():
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                pairs[key] = value.strip()
        if (pairs.get("Package") == name and pairs.get("Version") == version
                and pairs.get("Architecture") in (arch, "all")):
            sha = pairs.get("SHA256", "")
            if not SHA.fullmatch(sha):
                raise RuntimeError("signed apt Packages entry has no SHA256: " + name)
            matches.add((sha, pairs.get("Filename", "")))
    if len(matches) != 1:
        raise RuntimeError(f"ambiguous or missing signed apt index entry: {name}={version}")
    return matches.pop()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    arch = ARCH.get(platform.machine())
    if arch is None or platform.system() != "Linux":
        raise RuntimeError("unsupported Debian package discovery platform")
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RuntimeError("output must be real mounted directory")
    before = inventory()
    base_versions = {}
    for name in PACKAGES:
        key = (name, arch)
        base_versions[name] = before.get(key)
    ca = Path("/etc/ssl/certs/ca-certificates.crt").resolve(strict=True)
    if not ca.is_file():
        raise RuntimeError("base image trusted CA missing")
    base_ca = digest(ca)
    run("apt-get", "update")
    run("apt-get", "install", "-y", "--no-install-recommends", *PACKAGES)
    after = inventory()
    changes = [(name, version, package_arch)
               for (name, package_arch), version in sorted(after.items())
               if before.get((name, package_arch)) != version]
    if not (1 <= len(changes) <= 20):
        raise RuntimeError("unexpected native Debian ABI change set")
    dest = ROOT / "debs"
    dest.mkdir(mode=0o700, exist_ok=False)
    records = []
    for name, version, package_arch in changes:
        if package_arch not in (arch, "all"):
            raise RuntimeError("unexpected foreign architecture")
        sha, source = signed_index_record(name, version, package_arch)
        if not source.startswith("pool/") or ".." in source.split("/"):
            raise RuntimeError("unsafe Debian source path")
        existing = set(dest.iterdir())
        run("apt-get", "download", f"{name}={version}", cwd=dest)
        new = set(dest.iterdir()) - existing
        if len(new) != 1:
            raise RuntimeError("ambiguous downloaded .deb file")
        deb = new.pop()
        if deb.suffix != ".deb" or digest(deb) != sha or deb.stat().st_size > 25_000_000:
            raise RuntimeError("Debian package failed signed SHA256/size verification")
        records.append({"package": name, "version": version, "arch": package_arch,
                        "filename": deb.name, "source_path": source,
                        "sha256": sha, "size": deb.stat().st_size})
    output = {
        "schema": 1, "release_eligible": False,
        "packaging_stage": "discovery-only-unfrozen-debian-apt",
        "arch": arch, "base_ca_sha256": base_ca,
        "installed_ca_sha256": digest(ca),
        "baseline_abi_versions": base_versions,
        "installed_abi_versions": {
            name: after.get((name, arch)) for name in PACKAGES
        },
        "base_image": "python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26",
        "requested": list(PACKAGES), "changed_packages": records,
    }
    destination = ROOT / f"discovered-{arch}.json"
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    os.chmod(destination, 0o600)
    print("BEGIN_DEBIAN_ABI_CLOSURE_" + arch)
    print(destination.read_text(), end="")
    print("END_DEBIAN_ABI_CLOSURE_" + arch)


if __name__ == "__main__":
    main()
