"""Build an explicitly unreleasable, relocatable Linux runtime proof ZIP.

Runs inside a trusted, architecture-matching upstream Python+Node builder
image. It never fetches a package from the network or handles signing keys.
Both archives must pass scratch-image smoke on amd64 and arm64.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path


class RuntimePackagingError(ValueError):
    pass


ARCHES = {"x86_64": "amd64", "aarch64": "arm64"}
LOADER_NAMES = {"amd64": "ld-linux-x86-64.so.2", "arm64": "ld-linux-aarch64.so.1"}
# Native Python extension modules and Node native addons may depend on these
# audited compiler/glibc ABI compatibility DSOs without the interpreter executable requiring them.
# Collect them from the architecture-matching trusted builder filesystem, not
# from a host-mounted path or a runtime network resolver.
LIBRARY_TRIPLES = {"amd64": "x86_64-linux-gnu", "arm64": "aarch64-linux-gnu"}
ABI_SUPPORT_LIBRARIES = ("libgcc_s.so.1", "libstdc++.so.6", "libatomic.so.1", "libpthread.so.0")

LANGUAGES = {"python", "node"}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXCLUDED = {"__pycache__", ".pytest_cache", "test", "tests", "tkinter", "idlelib", "turtledemo"}
MAX_FILE_SIZE = 150 * 1024 * 1024


PINNED_IMAGE = re.compile(r"^(python:3[.]13-slim-bookworm|node:24-bookworm-slim)@sha256:[0-9a-f]{64}$")
EXPECTED_ARCHES = ["linux/amd64", "linux/arm64"]


def _strict_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise RuntimePackagingError("duplicate immutable upstream lock key")
        result[key] = value
    return result


def load_upstream_lock(lock_path: Path | None = None) -> dict[str, str]:
    """Require exact immutable Docker Official Images index digests."""
    if lock_path is None:
        lock_path = Path(os.environ.get(
            "MONITORBOX_RUNTIME_UPSTREAM_LOCK",
            str(Path(__file__).resolve().parents[1] / "platform/runtime/upstream-lock.json"),
        ))
    if lock_path.is_symlink() or not lock_path.is_file():
        raise RuntimePackagingError("immutable runtime upstream lock is missing or linked")
    try:
        manifest = json.loads(lock_path.read_text(encoding="utf-8"),
                              object_pairs_hook=_strict_json_pairs)
    except RuntimePackagingError:
        raise  # Preserve the specific duplicate-key rejection for auditing.
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimePackagingError("malformed immutable runtime upstream lock") from exc
    if type(manifest) is not dict or set(manifest) != {
        "schema", "format", "python_image", "node_image", "platforms"
    } or type(manifest["schema"]) is not int or manifest["schema"] != 1 or (
        manifest["format"] != "docker-official-images-multiarch-index"
    ) or manifest["platforms"] != EXPECTED_ARCHES:
        raise RuntimePackagingError("unreviewed upstream manifest schema/platforms")
    for name, repository in (("python_image", "python:3.13-slim-bookworm"),
                             ("node_image", "node:24-bookworm-slim")):
        value = manifest[name]
        if not isinstance(value, str) or not PINNED_IMAGE.fullmatch(value) or (
            not value.startswith(repository + "@sha256:")
        ):
            raise RuntimePackagingError("runtime upstream must use an exact approved digest")
    return {"python_image": manifest["python_image"],
            "node_image": manifest["node_image"]}


def verify_locked_dockerfile(dockerfile_path: Path, upstream: dict[str, str]) -> None:
    if dockerfile_path.is_symlink() or not dockerfile_path.is_file():
        raise RuntimePackagingError("pinned runtime Dockerfile is unavailable or linked")
    content = dockerfile_path.read_text(encoding="utf-8")
    from_lines = [
        line.split() for line in content.splitlines()
        if line.strip().upper().startswith("FROM ")
    ]
    if from_lines != [
        ["FROM", upstream["node_image"], "AS", "node-upstream"],
        ["FROM", upstream["python_image"], "AS", "packer"],
    ] or any(line.strip().startswith("ARG ") for line in content.splitlines()):
        raise RuntimePackagingError("runtime Dockerfile differs from immutable upstream lock")



def verified_debian_abi(upstream: dict[str, str]) -> dict:
    """Recheck the installed OCI-base and downloaded exact Debian .deb bytes.

    The package builder cannot trust a JSON assertion alone. The separate
    offline Docker installation already checked before/after dpkg state; this
    checks that the result and exact approved artifact survive into each
    packaged Python/Node ZIP, even if the Dockerfile is later modified.
    """
    from freeze_runtime_debian_closure import (
        host_arch as debian_arch, inventory, load_lock, sha256, verify_archives,
    )
    directory = Path(os.environ.get(
        "MONITORBOX_RUNTIME_DEBIAN_LOCK_DIR",
        str(Path(__file__).resolve().parents[1] / "platform/runtime/debian"),
    ))
    archives = Path(os.environ.get(
        "MONITORBOX_RUNTIME_DEBIAN_ARCHIVES",
        str(directory / "debs"),
    ))
    lock = load_lock(directory)
    if lock["arch"] != debian_arch() or lock["base_image"] != upstream["python_image"]:
        raise RuntimePackagingError("Debian lock not bound to exact OCI Python base")
    installed = inventory()
    for name, version in lock["installed_abi_versions"].items():
        if installed.get(name) != version:
            raise RuntimePackagingError("installed native ABI differs from source lock: " + name)
    ca = Path("/etc/ssl/certs/ca-certificates.crt").resolve(strict=True)
    if not ca.is_file() or sha256(ca) != lock["installed_ca_sha256"]:
        raise RuntimePackagingError("copied runtime CA differs from pinned OCI base")
    verify_archives(lock, archives)
    from discover_archived_debian import load_approved_snapshot
    approved_snapshot_file = directory / ("snapshot-" + lock["arch"] + ".json")
    approved_snapshot = load_approved_snapshot(approved_snapshot_file, lock["arch"])
    approved_records = {
        item["package"]: item for item in approved_snapshot["debs"]
    }
    if set(approved_records) != {item["package"] for item in lock["changed_packages"]}:
        raise RuntimePackagingError(
            "archived Debian signed index omits part of the installed runtime closure"
        )
    for record in lock["changed_packages"]:
        approved = approved_records[record["package"]]
        if (
            approved["version"] != record["version"]
            or approved["sha256"] != record["sha256"]
            or approved["size"] != record["size"]
            or approved["source_path"] != record["source_path"]
        ):
            raise RuntimePackagingError(
                "archived Debian signed index differs from installed exact runtime package"
            )
    first_record = lock["changed_packages"][0]
    return {
        "snapshot": {
            "source_lock_sha256": sha256(approved_snapshot_file),
            "checkpoint": approved_snapshot["checkpoint"],
            "debian_keyring_sha256": approved_snapshot["keyring_sha256"],
            "signed_inrelease_sha256": approved_snapshot["inrelease"]["sha256"],
            "signed_packages_sha256": approved_snapshot["packages"]["sha256"],
            "signed_packages_path": approved_snapshot["packages"]["path"],
            "package_sha256": first_record["sha256"],
            "provenance": "independently-verified-external-Debian-snapshot-prototype",
        },
        "arch": lock["arch"],
        "lock_sha256": sha256(directory / ("lock-" + lock["arch"] + ".json")),
        "base_ca_sha256": lock["base_ca_sha256"],
        "installed_ca_sha256": lock["installed_ca_sha256"],
        "abi_versions": lock["installed_abi_versions"],
        "changed_packages": [
            {"package": item["package"], "version": item["version"],
             "sha256": item["sha256"], "size": item["size"]}
            for item in lock["changed_packages"]
        ],
    }


def host_arch() -> str:
    arch = ARCHES.get(platform.machine())
    if arch is None:
        raise RuntimePackagingError("unsupported build architecture")
    return arch


def _elf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"\x7fELF"


def _ldd_dependencies(binary: Path) -> dict[str, Path]:
    """Preserve the NEEDED soname, not the canonical target filename.

    For example, libz.so.1 frequently resolves to libz.so.1.2.13: copying
    only the target basename would break the bundled ELF loader in scratch.
    """
    result = subprocess.run(["ldd", str(binary)], check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimePackagingError(f"ldd failed on {binary.name}: {result.stderr.strip()}")
    found: dict[str, Path] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("linux-vdso") or "statically linked" in line:
            continue
        if "not found" in line:
            raise RuntimePackagingError(f"missing shared library for {binary.name}: {line}")
        if "=>" in line:
            required, address = line.split("=>", 1)
            required = required.strip()
            address = address.strip().split(" ", 1)[0]
        else:
            address = line.split(" ", 1)[0]
            required = Path(address).name
        if not address.startswith("/"):
            continue
        if not re.fullmatch(r"[a-zA-Z0-9._+-]+", required):
            raise RuntimePackagingError("unsafe shared-library soname")
        source = Path(address).resolve(strict=True)
        if not source.is_file() or not _elf(source):
            raise RuntimePackagingError(f"invalid ELF dependency for {binary.name}")
        previous = found.get(required)
        if previous is not None and previous != source:
            raise RuntimePackagingError("ambiguous ELF dependency soname")
        found[required] = source
    return found


def _resolve_abi_library(arch: str, name: str) -> Path:
    if arch not in LIBRARY_TRIPLES or name not in ABI_SUPPORT_LIBRARIES:
        raise RuntimePackagingError("unapproved runtime compiler-ABI library")
    triple = LIBRARY_TRIPLES[arch]
    for root in (Path("/lib"), Path("/usr/lib")):
        candidate = root / triple / name
        if candidate.is_file():
            source = candidate.resolve(strict=True)
            if not _elf(source):
                raise RuntimePackagingError("compiler-ABI dependency is not ELF")
            return source
    raise RuntimePackagingError("required compiler-ABI library absent from trusted builder: " + name)


def parse_ldd_for_test(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("linux-vdso") or "statically linked" in line:
            continue
        if "not found" in line:
            raise RuntimePackagingError("missing shared library")
        if "=>" in line:
            needed, _ = line.split("=>", 1)
            names.add(needed.strip())
        else:
            item = line.split(" ", 1)[0]
            if item.startswith("/"):
                names.add(Path(item).name)
    return names


def _copy_regular(source: Path, target: Path) -> None:
    if not source.is_file() or source.is_symlink():
        source = source.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_FILE_SIZE:
        raise RuntimePackagingError(f"invalid runtime source: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target, follow_symlinks=True)
    target.chmod(0o755 if bool(source.stat().st_mode & stat.S_IXUSR) else 0o644)


def _copy_tree(source: Path, dest: Path) -> list[Path]:
    elfs: list[Path] = []
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if (EXCLUDED.intersection(relative.parts) or item.name.startswith("_tkinter.") or
            item.name.endswith((".pyc", ".pyo", ".o", ".a", ".h"))):
            continue
        if item.is_dir():
            continue
        if item.is_symlink():
            target = item.resolve(strict=True)
            if not target.is_relative_to(source.resolve()):
                raise RuntimePackagingError("runtime stdlib contains escaping symlink")
        else:
            target = item
        if not target.is_file():
            continue
        dst = dest / relative
        _copy_regular(target, dst)
        if _elf(target):
            elfs.append(target)
    return elfs


def _version(language: str, binary: Path) -> str:
    flag = "--version" if language == "node" else "-V"
    run = subprocess.run([str(binary), flag], check=True, capture_output=True, text=True)
    match = re.search(r"(?:Python\s+|v)(\d+\.\d+\.\d+)", run.stdout + run.stderr)
    if not match:
        raise RuntimePackagingError("could not read upstream runtime version")
    version = match.group(1)
    if language == "python" and not version.startswith("3.13."):
        raise RuntimePackagingError("expected Python 3.13.x")
    if language == "node" and not version.startswith("24."):
        raise RuntimePackagingError("expected Node 24.x")
    return version


def _write_deterministic_zip(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise RuntimePackagingError("refusing to overwrite runtime candidate")
    temporary = output.with_suffix(".partial")
    if temporary.exists():
        raise RuntimePackagingError("stale unfinished runtime candidate")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
            for f in sorted(root.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(root).as_posix()
                entry = zipfile.ZipInfo(rel, date_time=ZIP_TIME)
                entry.create_system = 3
                mode = 0o755 if f.stat().st_mode & stat.S_IXUSR else 0o644
                entry.external_attr = (stat.S_IFREG | mode) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, f.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=7)
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build_runtime(language: str, output: Path, *, extract_to: Path | None = None,
                  python_prefix: Path = Path("/usr/local"),
                  node_binary: Path = Path("/opt/upstream/node"),
                  ping_binary: Path = Path("/usr/bin/ping")) -> dict:
    if language not in LANGUAGES:
        raise RuntimePackagingError("unsupported runtime kind")
    if output.exists() or output.is_symlink():
        raise RuntimePackagingError("refusing to overwrite candidate")
    arch = host_arch()
    upstream = load_upstream_lock()
    dockerfile = Path(os.environ.get(
        "MONITORBOX_RUNTIME_DOCKERFILE",
        str(Path(__file__).resolve().parents[1] / "platform/runtime/Dockerfile"),
    ))
    verify_locked_dockerfile(dockerfile, upstream)
    debian_abi = verified_debian_abi(upstream)
    upstream_bin = python_prefix / "bin/python3.13" if language == "python" else node_binary
    if not upstream_bin.resolve().is_file():
        raise RuntimePackagingError("upstream runtime executable not present")
    version = _version(language, upstream_bin)
    with tempfile.TemporaryDirectory(prefix="mb-runtime-") as tmp:
        root = Path(tmp)
        runtime = root / "runtime"
        included: list[Path] = []
        tools: dict[str, str] = {}
        if language == "python":
            binary = runtime / "usr/local/bin/python3.13"
            _copy_regular(upstream_bin, binary)
            included.append(upstream_bin.resolve())
            libpython = python_prefix / "lib/libpython3.13.so.1.0"
            if not libpython.is_file():
                raise RuntimePackagingError("shared libpython3.13 is required")
            _copy_regular(libpython, runtime / "usr/local/lib/libpython3.13.so.1.0")
            included.append(libpython.resolve())
            stdlib = python_prefix / "lib/python3.13"
            if not stdlib.is_dir():
                raise RuntimePackagingError("Python 3.13 stdlib is missing")
            included += _copy_tree(stdlib, runtime / "usr/local/lib/python3.13")
            ping = ping_binary.resolve(strict=True)
            if not ping.is_file() or not os.access(ping, os.X_OK) or not _elf(ping):
                raise RuntimePackagingError("reviewed ICMP runtime executable is unavailable")
            _copy_regular(ping, runtime / "usr/bin/ping")
            included.append(ping)
            tools["ping"] = "runtime/usr/bin/ping"
            entry = "runtime/usr/local/bin/python3.13"
            smoke = {"PYTHONHOME": "/runtime/usr/local", "PYTHONDONTWRITEBYTECODE": "1",
                     "SSL_CERT_FILE": "/runtime/etc/ssl/certs/ca-certificates.crt"}
        else:
            binary = runtime / "usr/local/bin/node"
            _copy_regular(upstream_bin, binary)
            included.append(upstream_bin.resolve())
            entry = "runtime/usr/local/bin/node"
            smoke = {}

        libraries: dict[str, Path] = {}
        # The Python interpreter and stdlib's DT_NEEDED closure is not enough:
        # cryptography's Rust wheel needs libgcc_s.so.1 even though CPython
        # itself does not. Resolve a narrow, reviewed ABI base and recurse
        # through those ELFs' own loader dependencies.
        for name in ABI_SUPPORT_LIBRARIES:
            source = _resolve_abi_library(arch, name)
            libraries[name] = source
            included.append(source)
        loader: Path | None = None
        for source in included:
            if not _elf(source):
                continue
            for needed, dependency in _ldd_dependencies(source).items():
                if needed.startswith("ld-linux"):
                    if needed != LOADER_NAMES[arch]:
                        raise RuntimePackagingError("unexpected ELF interpreter architecture")
                    loader = dependency
                    continue
                prev = libraries.get(needed)
                if prev is not None and hashlib.sha256(prev.read_bytes()).digest() != hashlib.sha256(dependency.read_bytes()).digest():
                    raise RuntimePackagingError(f"ambiguous library name: {needed}")
                libraries[needed] = dependency
        if loader is None:
            raise RuntimePackagingError("runtime dynamic loader was not resolved")
        _copy_regular(loader, runtime / "loader" / loader.name)
        for name, source in sorted(libraries.items()):
            _copy_regular(source, runtime / "lib" / name)
        ca = Path("/etc/ssl/certs/ca-certificates.crt")
        if not ca.is_file():
            raise RuntimePackagingError("trusted CA bundle missing in official build image")
        _copy_regular(ca, runtime / "etc/ssl/certs/ca-certificates.crt")
        manifest = {
            "schema": 1, "kind": "runtime",
            "artifact_id": f"com.sickicarus.monitorbox.runtime.{language}",
            "version": version, "build": 1, "release_eligible": False,
            "packaging_stage": "digest-pinned-upstream-runtime-proof",
            "platform": {"os": "linux", "arch": arch, "abi": "glibc"},
            "entrypoint": entry, "dynamic_loader": f"runtime/loader/{loader.name}",
            "library_paths": ["runtime/lib", "runtime/usr/local/lib"],
            "tools": tools,
            "environment": smoke, "verified_elf_count": len(included),
            "library_count": len(libraries),
            "upstream": {
                **upstream,
                "os_packages": "snapshot-locked-oci-base-abi-prototype",
                "debian_abi": debian_abi,
            },
        }
        (root / "package.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        if extract_to is not None:
            if extract_to.exists():
                raise RuntimePackagingError("extract destination must not exist")
            shutil.copytree(root, extract_to)
        _write_deterministic_zip(root, output)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create non-release-ready Python/Node ABI proof ZIPs")
    parser.add_argument("--language", choices=sorted(LANGUAGES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument("--python-prefix", type=Path, default=Path("/usr/local"))
    parser.add_argument("--node-binary", type=Path, default=Path("/opt/upstream/node"))
    args = parser.parse_args()
    print(json.dumps(build_runtime(args.language, args.output, extract_to=args.extract_to,
                                   python_prefix=args.python_prefix, node_binary=args.node_binary), sort_keys=True))


if __name__ == "__main__":
    main()
