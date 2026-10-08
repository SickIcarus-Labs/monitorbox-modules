#!/usr/bin/env python3
"""Qualify reviewed successor runtime inputs into release-eligible package bytes.

This tool performs no signing and no publication. It converts only the already
reviewed, explicitly release-ineligible runtime proofs into the exact package
shapes consumed by the protected successor platform signer.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

APPROVED_CA = "714d457d580922dbf1d0be8bd35ba236a842b50b0072ae791582a19adef772a5"
MAX_RUNTIME_BYTES = 400 << 20
MAX_RUNTIME_FILES = 12000
MAX_MEMBER_BYTES = 160 << 20
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
RUNTIME_IDS = {
    "com.sickicarus.monitorbox.runtime.python",
    "com.sickicarus.monitorbox.runtime.node",
}
WHEELHOUSE_PROOF_ID = "com.sickicarus.monitorbox.core.wheelhouse-proof"
WHEELHOUSE_ID = "com.sickicarus.monitorbox.core.wheels"
DIGEST = re.compile(r"^[0-9a-f]{64}$")


class QualificationError(ValueError):
    pass


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _safe_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and "\x00" not in name
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def _encode_zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
        strict_timestamps=True,
    ) as archive:
        for name, payload in sorted(entries.items()):
            if not _safe_name(name):
                raise QualificationError("unsafe package member")
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o400) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6
            )
    return output.getvalue()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1 << 20:
        raise QualificationError(f"{label} is missing, linked or oversized")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} must be a JSON object")
    return value


def qualify_runtime(runtime_root: Path, snapshot_lock: Path) -> bytes:
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise QualificationError("runtime root is missing or linked")
    manifest_path = runtime_root / "package.json"
    manifest = _load_json(manifest_path, "runtime manifest")
    artifact_id = manifest.get("artifact_id")
    platform = manifest.get("platform")
    upstream = manifest.get("upstream")
    if (
        artifact_id not in RUNTIME_IDS
        or manifest.get("schema") != 1
        or manifest.get("kind") != "runtime"
        or manifest.get("release_eligible") is not False
        or manifest.get("packaging_stage") != "digest-pinned-upstream-runtime-proof"
        or not isinstance(platform, dict)
        or platform.get("os") != "linux"
        or platform.get("arch") not in {"amd64", "arm64"}
        or platform.get("abi") != "glibc"
        or not isinstance(upstream, dict)
        or upstream.get("os_packages") != "snapshot-locked-oci-base-abi-prototype"
    ):
        raise QualificationError("runtime proof is not the reviewed release-ineligible shape")

    snapshot = _load_json(snapshot_lock, "reviewed Debian snapshot lock")
    if (
        snapshot.get("schema") != 1
        or snapshot.get("release_eligible") is not False
        or snapshot.get("packaging_stage") != "snapshot-debian-signed-index-discovery-only"
        or snapshot.get("arch") != platform["arch"]
    ):
        raise QualificationError("Debian snapshot lock identity does not match runtime")

    debian = upstream.get("debian_abi")
    if not isinstance(debian, dict):
        raise QualificationError("runtime lacks reviewed Debian ABI authority")
    embedded = debian.get("snapshot")
    if (
        not isinstance(embedded, dict)
        or embedded.get("signed_inrelease_sha256") != snapshot.get("inrelease", {}).get("sha256")
        or embedded.get("signed_packages_sha256") != snapshot.get("packages", {}).get("sha256")
        or embedded.get("debian_keyring_sha256") != snapshot.get("keyring_sha256")
    ):
        raise QualificationError("runtime embedded Debian snapshot disagrees with reviewed lock")

    # The production Go manifest is intentionally strict and retains only the
    # reviewed compact ABI evidence after this qualification step.
    debian = dict(debian)
    debian.pop("snapshot", None)
    upstream = dict(upstream)
    upstream["debian_abi"] = debian
    upstream["os_packages"] = "qualified-archived-debian-abi"
    manifest = dict(manifest)
    manifest["upstream"] = upstream
    manifest["packaging_stage"] = "qualified-native-runtime"
    manifest["release_eligible"] = True

    entries: dict[str, bytes] = {"package.json": _json_bytes(manifest)}
    runtime_dir = runtime_root / "runtime"
    if runtime_dir.is_symlink() or not runtime_dir.is_dir():
        raise QualificationError("runtime proof lacks runtime/ tree")
    total = 0
    for item in sorted(runtime_dir.rglob("*")):
        if item.is_symlink():
            raise QualificationError("runtime proof contains linked content")
        if item.is_dir():
            continue
        if not item.is_file():
            raise QualificationError("runtime proof contains non-regular content")
        relative = item.relative_to(runtime_root).as_posix()
        if not relative.startswith("runtime/") or not _safe_name(relative):
            raise QualificationError("runtime proof member escaped runtime/")
        size = item.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise QualificationError("runtime proof member exceeds size bound")
        payload = item.read_bytes()
        total += len(payload)
        if total > MAX_RUNTIME_BYTES or len(entries) >= MAX_RUNTIME_FILES:
            raise QualificationError("runtime proof exceeds extraction budget")
        entries[relative] = payload

    ca = entries.get("runtime/etc/ssl/certs/ca-certificates.crt")
    if ca is None or _digest(ca) != APPROVED_CA:
        raise QualificationError("runtime CA bytes differ from reviewed authority")
    entrypoint = manifest.get("entrypoint")
    loader = manifest.get("dynamic_loader")
    if entrypoint not in entries or loader not in entries:
        raise QualificationError("runtime proof omits declared ELF entrypoint/loader")
    if not entries[entrypoint].startswith(b"\x7fELF") or not entries[loader].startswith(b"\x7fELF"):
        raise QualificationError("runtime declared entrypoint/loader are not ELF")
    return _encode_zip(entries)


def _read_wheelhouse(source: Path) -> dict[str, bytes]:
    if source.is_symlink() or not source.is_file():
        raise QualificationError("wheelhouse proof is missing or linked")
    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(source) as archive:
            if archive.testzip() is not None:
                raise QualificationError("wheelhouse proof CRC failure")
            for member in archive.infolist():
                name = member.filename
                if (
                    not _safe_name(name)
                    or member.is_dir()
                    or member.file_size > MAX_MEMBER_BYTES
                    or name in entries
                    or (
                        name not in {"wheelhouse.json", "requirements.lock"}
                        and not name.startswith("wheels/")
                    )
                ):
                    raise QualificationError("wheelhouse proof contains unsafe member")
                entries[name] = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise QualificationError("wheelhouse proof is not a ZIP") from exc
    return entries


def qualify_wheelhouse(source: Path) -> bytes:
    entries = _read_wheelhouse(source)
    try:
        manifest = json.loads(entries["wheelhouse.json"])
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("wheelhouse proof manifest is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("artifact_id") != WHEELHOUSE_PROOF_ID
        or manifest.get("release_eligible") is not False
        or manifest.get("packaging_stage") != "source-reviewed-hashlocked-offline-proof"
        or manifest.get("platform", {}).get("os") != "linux"
        or manifest.get("platform", {}).get("arch") not in {"amd64", "arm64"}
        or manifest.get("platform", {}).get("python") != "cp313"
    ):
        raise QualificationError("wheelhouse proof is not the reviewed release-ineligible shape")
    wheels = manifest.get("wheels")
    if not isinstance(wheels, list) or len(wheels) != 14:
        raise QualificationError("wheelhouse proof is not the exact fourteen-wheel closure")
    for record in wheels:
        if not isinstance(record, dict):
            raise QualificationError("wheelhouse wheel record is invalid")
        filename = record.get("filename")
        digest = record.get("sha256")
        size = record.get("size")
        payload = entries.get("wheels/" + str(filename))
        if (
            not isinstance(filename, str)
            or not isinstance(digest, str)
            or not DIGEST.fullmatch(digest)
            or type(size) is not int
            or size < 1
            or payload is None
            or len(payload) != size
            or _digest(payload) != digest
        ):
            raise QualificationError("wheelhouse wheel bytes changed from reviewed hashes")
    expected = {"wheelhouse.json", "requirements.lock"} | {
        "wheels/" + record["filename"] for record in wheels
    }
    if set(entries) != expected:
        raise QualificationError("wheelhouse proof contains unlisted wheel bytes")
    manifest = dict(manifest)
    manifest["artifact_id"] = WHEELHOUSE_ID
    manifest["packaging_stage"] = "qualified-wheel-closure"
    manifest["release_eligible"] = True
    entries["wheelhouse.json"] = _json_bytes(manifest)
    return _encode_zip(entries)


def write_output(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink() or path.parent.is_symlink():
        raise QualificationError("refusing existing or linked qualified output")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".qualified-runtime-", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _digest(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    runtime = sub.add_parser("runtime")
    runtime.add_argument("--runtime-root", type=Path, required=True)
    runtime.add_argument("--snapshot-lock", type=Path, required=True)
    runtime.add_argument("--output", type=Path, required=True)
    wheels = sub.add_parser("wheelhouse")
    wheels.add_argument("--source", type=Path, required=True)
    wheels.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "runtime":
            payload = qualify_runtime(args.runtime_root, args.snapshot_lock)
        else:
            payload = qualify_wheelhouse(args.source)
        digest = write_output(args.output, payload)
    except (OSError, QualificationError) as exc:
        print("successor runtime qualification rejected: " + str(exc), file=os.sys.stderr)
        return 1
    print(f"qualified successor runtime: {args.output} sha256:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
