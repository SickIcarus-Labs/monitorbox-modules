"""Build a *candidate* successor signed platform catalog.

Never publishes a release or touches the existing 2.x catalog. Production signing
must invoke this only inside its isolated, approval-gated signing environment.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import io
import zipfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, FormatChecker

from verify_platform_index import SCHEMA, VerificationError, _parse, canonical, verify_index, verify_package
from portable_contracts import ContractError, MAX_CONTRACT_BYTES, verify_embedded_contract


class PublicationError(ValueError):
    """Candidate package publication fails closed before writing index bytes."""


def _safe_package_path(root: Path, filename: str) -> Path:
    # The v1 distribution contract deliberately uses simple filenames, never
    # source-supplied relative paths or URLs. No release can escape /packages.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", filename):
        raise PublicationError("package_file must be a simple, safe filename")
    directory = root / "platform" / "packages"
    for parent in (root, root / "platform", directory):
        if parent.is_symlink():
            raise PublicationError("package source directory may not be a symlink")
    source = directory / filename
    if source.is_symlink() or not source.is_file():
        raise PublicationError(f"missing or linked package: {filename}")
    return source


EXECUTABLE_MODULE_IDS = frozenset({
    "com.sickicarus.monitorbox.core", "com.sickicarus.monitorbox.agent",
})
WHEELHOUSE_ID = "com.sickicarus.monitorbox.core.wheels"

FIRST_PARTY_APPLICATION_MODULE_IDS = frozenset({
    "com.sickicarus.monitorbox.backup-restore",
    "com.sickicarus.monitorbox.configuration-bootstrap",
    "com.sickicarus.monitorbox.http",
    "com.sickicarus.monitorbox.nut",
    "com.sickicarus.monitorbox.portainer",
    "com.sickicarus.monitorbox.scrypted",
    "com.sickicarus.monitorbox.snmp",
    "com.sickicarus.monitorbox.ui",
    "com.sickicarus.monitorbox.unifi",
    "com.sickicarus.monitorbox.wol",
})



def _verify_core_or_agent_admission(item: dict[str, Any], payload: bytes) -> None:
    """Don't accidentally sign the explicitly unreleasable 2.x source proof.

    This is a publisher admission gate, not a claim that a signed package is
    executable: full dependency/runtime and process readiness are separate.
    """
    if item.get("artifact_id") not in EXECUTABLE_MODULE_IDS:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if "package.json" not in archive.namelist():
                raise PublicationError("Core/Agent package lacks package.json")
            if archive.getinfo("package.json").file_size > 64 * 1024:
                raise PublicationError("Core/Agent manifest exceeds size limit")
            manifest = _parse(archive.read("package.json"))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PublicationError("Core/Agent package is not a valid module ZIP") from exc
    except VerificationError as exc:
        raise PublicationError("invalid internal Core/Agent JSON manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("release_eligible") is not True:
        raise PublicationError("Core/Agent package is explicitly unreleasable or lacks approval")
    if any(manifest.get(key) != item.get(key) for key in ("artifact_id", "version", "build")):
        raise PublicationError("Core/Agent internal package identity disagrees with signed catalog candidate")



def _verify_first_party_application_module_admission(
    item: dict[str, Any], payload: bytes
) -> None:
    """Require a qualified Core3 runtime manifest for the ten first-party app modules."""
    artifact_id = item.get("artifact_id")
    if artifact_id not in FIRST_PARTY_APPLICATION_MODULE_IDS:
        return
    if item.get("kind") != "module":
        raise PublicationError("first-party application artifact must be kind=module")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if names.count("package.json") != 1:
                raise PublicationError(
                    "first-party application module requires exactly one package.json"
                )
            member = archive.getinfo("package.json")
            if member.file_size > 64 * 1024:
                raise PublicationError("first-party application module manifest is oversized")
            manifest = _parse(archive.read(member))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PublicationError(
            "first-party application module is not a valid successor ZIP"
        ) from exc
    except VerificationError as exc:
        raise PublicationError(
            "invalid first-party application module JSON manifest"
        ) from exc

    required = {
        "schema", "artifact_id", "kind", "version", "build",
        "release_eligible", "packaging_stage", "module_runtime", "provenance",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PublicationError("first-party application module manifest shape is invalid")
    if manifest.get("schema") != 1 or manifest.get("kind") != "module":
        raise PublicationError("unsupported first-party application module manifest")
    if manifest.get("release_eligible") is not True:
        raise PublicationError(
            "first-party application module is unreleasable or lacks qualification"
        )
    if manifest.get("packaging_stage") != "successor-module-requalification":
        raise PublicationError("unexpected first-party application packaging stage")
    if any(
        manifest.get(key) != item.get(key)
        for key in ("artifact_id", "version", "build")
    ):
        raise PublicationError(
            "first-party application module identity disagrees with signed catalog"
        )

    runtime = manifest.get("module_runtime")
    if not isinstance(runtime, dict):
        raise PublicationError("first-party module_runtime must be an object")
    if (
        runtime.get("module_id") != artifact_id
        or runtime.get("version") != item.get("version")
        or runtime.get("build") != item.get("build")
        or runtime.get("schema") != 1
        or runtime.get("requires_core") != ">=3.0.0 <4.0.0"
        or runtime.get("requires_runtime_api") != ">=1 <2"
    ):
        raise PublicationError("first-party module_runtime identity/API contract is invalid")
    entrypoints = runtime.get("entrypoints")
    if (
        not isinstance(entrypoints, dict)
        or not entrypoints
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(target, str)
            or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*",
                target,
            )
            for name, target in entrypoints.items()
        )
    ):
        raise PublicationError("first-party module_runtime entrypoints are invalid")

    provenance = manifest.get("provenance")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {
            "source", "predecessor_filename", "predecessor_sha256"
        }
        or provenance.get("source") != "immutable-signed-2.x-package"
        or not isinstance(provenance.get("predecessor_filename"), str)
        or Path(provenance["predecessor_filename"]).name
            != provenance["predecessor_filename"]
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(provenance.get("predecessor_sha256", ""))
        )
    ):
        raise PublicationError("first-party module provenance is invalid")


def _verify_module_portable_contract(
    item: dict[str, Any], payload: bytes
) -> dict[str, Any] | None:
    """Require package-owned first-party portable authority before signing."""
    if item.get("kind") != "module":
        return None
    if "portable_config" in item:
        raise PublicationError(
            "source inventory may not supply portable_config; capability is package-derived"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if names.count("portable-config.json") != 1:
                raise PublicationError(
                    "module package requires exactly one portable-config.json"
                )
            member = archive.getinfo("portable-config.json")
            if member.file_size > MAX_CONTRACT_BYTES:
                raise PublicationError("module portable-config.json exceeds size limit")
            raw = archive.read(member)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PublicationError("module package is not a valid portable-contract ZIP") from exc
    try:
        return verify_embedded_contract(
            raw,
            artifact_id=item.get("artifact_id"),
            version=item.get("version"),
            build=item.get("build"),
        )
    except ContractError as exc:
        raise PublicationError("module portable contract rejected: " + str(exc)) from exc


def _verify_wheelhouse_admission(item: dict[str, Any], payload: bytes) -> None:
    """Admit the sealed architecture-specific Core wheel closure.

    The wheelhouse is catalogued as kind=runtime so the resolver can enforce an
    exact mandatory dependency edge, but unlike Python/Node it intentionally has
    no package.json or executable ELF entrypoint. Its own signed inner authority
    is wheelhouse.json plus the complete hash-locked wheel set.
    """
    if item.get("artifact_id") != WHEELHOUSE_ID:
        return
    if (
        item.get("kind") != "runtime"
        or item.get("version") != "1.0.0"
        or item.get("build") != 1
        or item.get("platform", {}).get("os") != "linux"
        or item.get("platform", {}).get("abi") != "glibc"
        or item.get("platform", {}).get("arch") not in {"amd64", "arm64"}
    ):
        raise PublicationError("Core wheelhouse catalog identity/platform is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if names.count("wheelhouse.json") != 1 or names.count("requirements.lock") != 1:
                raise PublicationError("Core wheelhouse requires exact metadata and lock files")
            if len(names) < 3 or len(names) > 130 or len(names) != len(set(names)):
                raise PublicationError("Core wheelhouse member set is invalid")
            manifest_member = archive.getinfo("wheelhouse.json")
            if manifest_member.file_size > 64 * 1024:
                raise PublicationError("Core wheelhouse manifest is oversized")
            manifest = _parse(archive.read(manifest_member))
            if not isinstance(manifest, dict):
                raise PublicationError("Core wheelhouse manifest must be an object")
            required = {
                "schema", "artifact_id", "packaging_stage", "release_eligible",
                "platform", "direct_requirements", "wheels",
            }
            if set(manifest) != required:
                raise PublicationError("Core wheelhouse manifest shape is invalid")
            platform = manifest.get("platform")
            if (
                manifest.get("schema") != 1
                or manifest.get("artifact_id") != WHEELHOUSE_ID
                or manifest.get("packaging_stage") != "qualified-wheel-closure"
                or manifest.get("release_eligible") is not True
                or not isinstance(platform, dict)
                or platform != {
                    "os": "linux",
                    "arch": item["platform"]["arch"],
                    "python": "cp313",
                }
            ):
                raise PublicationError("Core wheelhouse inner authority is ineligible or mismatched")
            wheels = manifest.get("wheels")
            direct = manifest.get("direct_requirements")
            if (
                not isinstance(wheels, list) or not 1 <= len(wheels) <= 128
                or not isinstance(direct, list) or not direct
            ):
                raise PublicationError("Core wheelhouse dependency closure is empty or excessive")
            expected_names = {"wheelhouse.json", "requirements.lock"}
            seen_dist: set[str] = set()
            for record in wheels:
                if not isinstance(record, dict) or set(record) != {
                    "filename", "name", "version", "sha256", "size"
                }:
                    raise PublicationError("Core wheelhouse record shape is invalid")
                filename = record.get("filename")
                name = record.get("name")
                version = record.get("version")
                digest = record.get("sha256")
                size = record.get("size")
                if (
                    not isinstance(filename, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.+-]+[.]whl", filename)
                    or not isinstance(name, str) or not name
                    or not isinstance(version, str) or not version
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or type(size) is not int or size < 1 or size > 80 << 20
                ):
                    raise PublicationError("Core wheelhouse record is invalid")
                normalized = re.sub(r"[-_.]+", "-", name).lower()
                if normalized in seen_dist:
                    raise PublicationError("Core wheelhouse repeats a distribution")
                seen_dist.add(normalized)
                member_name = "wheels/" + filename
                expected_names.add(member_name)
                try:
                    member = archive.getinfo(member_name)
                except KeyError as exc:
                    raise PublicationError("Core wheelhouse is missing declared wheel bytes") from exc
                raw = archive.read(member)
                if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                    raise PublicationError("Core wheelhouse wheel bytes differ from manifest")
            if set(names) != expected_names:
                raise PublicationError("Core wheelhouse contains undeclared members")
            for requirement in direct:
                if (
                    not isinstance(requirement, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9_.+!]*", requirement)
                ):
                    raise PublicationError("Core wheelhouse direct requirements are not exact pins")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PublicationError("Core wheelhouse is not a valid sealed ZIP") from exc
    except VerificationError as exc:
        raise PublicationError("Core wheelhouse inner JSON is invalid") from exc


def _verify_runtime_or_manager_admission(item: dict[str, Any], payload: bytes) -> None:
    """Never sign an unapproved runtime or replacement manager executable.

    This validates archive admission and declared identity, not that a binary
    is self-contained or authorized for a particular production appliance.
    Those require signed full-generation runtime and physical acceptance.
    """
    if item.get("artifact_id") == WHEELHOUSE_ID:
        return
    if item.get("kind") not in {"runtime", "scaffold-manager"}:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.namelist()
            if entries.count("package.json") != 1:
                raise PublicationError("runtime/manager package needs one package.json")
            if archive.getinfo("package.json").file_size > 64 * 1024:
                raise PublicationError("runtime/manager package manifest is oversized")
            manifest = _parse(archive.read("package.json"))
            if item["kind"] == "runtime":
                entry = manifest.get("entrypoint") if isinstance(manifest, dict) else None
                loader = manifest.get("dynamic_loader") if isinstance(manifest, dict) else None
                for candidate in (entry, loader):
                    if (not isinstance(candidate, str) or
                        not candidate.startswith("runtime/") or
                        ".." in candidate.split("/") or
                        candidate not in entries):
                        raise PublicationError("runtime package missing safe entrypoint or ELF loader")
                    if archive.getinfo(candidate).file_size < 4 or archive.read(candidate)[:4] != b"\x7fELF":
                        raise PublicationError("runtime entrypoint/loader must contain ELF data")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PublicationError("runtime/manager is not a valid ZIP") from exc
    except VerificationError as exc:
        raise PublicationError("runtime/manager internal JSON is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("release_eligible") is not True:
        raise PublicationError("runtime/manager package is unreleasable or lacks approval")
    if manifest.get("kind") != item["kind"]:
        raise PublicationError("runtime/manager kind disagrees with catalog")
    if any(manifest.get(key) != item.get(key) for key in ("artifact_id", "version", "build")):
        raise PublicationError("runtime/manager identity disagrees with signed catalog")

def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise PublicationError("generated_at requires explicit timezone")
    return value.astimezone(timezone.utc)


def _label(raw: bytes) -> dict[str, Any]:
    try:
        data = _parse(raw)
    except VerificationError as exc:
        raise PublicationError(str(exc)) from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise PublicationError("source schema must be 1")
    if data.get("repository_id") != "official-platform":
        raise PublicationError("source repository identity must be official-platform")
    if set(data) != {"schema", "repository_id", "artifacts"}:
        raise PublicationError("source must contain only schema, repository_id and artifacts")
    if not isinstance(data["artifacts"], list) or not data["artifacts"]:
        raise PublicationError("source artifacts must be a nonempty array")
    return data


def sign_candidate(
    source_bytes: bytes,
    *,
    package_root: Path,
    key: Ed25519PrivateKey,
    key_id: str,
    channel: str,
    sequence: int,
    generated_at: datetime,
    valid_hours: int = 48,
) -> bytes:
    """Return signed v1 index bytes; never writes files or publishes artifacts."""
    if channel not in {"stable", "beta", "dev"}:
        raise PublicationError("unsupported signed channel")
    if type(sequence) is not int or sequence < 1:
        raise PublicationError("sequence must be a positive integer")
    if type(valid_hours) is not int or not 1 <= valid_hours <= 24 * 7:
        raise PublicationError("index expiry must be within 1 to 168 hours")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", key_id):
        raise PublicationError("invalid signing key identity")
    now = _timestamp(generated_at)
    source = _label(source_bytes)
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str, str, str]] = set()
    for item in source["artifacts"]:
        if not isinstance(item, dict) or "package_file" not in item:
            raise PublicationError("each source artifact requires package_file")
        filename = item["package_file"]
        if not isinstance(filename, str):
            raise PublicationError("package_file must be text")
        file_path = _safe_package_path(package_root, filename)
        payload = file_path.read_bytes()
        if not payload:
            raise PublicationError("empty packages cannot be published")
        portable_config = _verify_module_portable_contract(item, payload)
        _verify_first_party_application_module_admission(item, payload)
        _verify_core_or_agent_admission(item, payload)
        _verify_wheelhouse_admission(item, payload)
        _verify_runtime_or_manager_admission(item, payload)
        metadata = {k: v for k, v in item.items() if k != "package_file"}
        if portable_config is not None:
            metadata["portable_config"] = portable_config
        metadata["package"] = {
            "url": "platform/packages/" + filename,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "signature": {
                "algorithm": "ed25519", "identity": key_id,
                "value": base64.b64encode(key.sign(payload)).decode("ascii"),
            },
        }
        try:
            p = metadata["platform"]
            identity = (metadata["artifact_id"], metadata["version"], metadata["build"], p["os"], p["arch"], p["abi"])
        except (KeyError, TypeError) as exc:
            raise PublicationError("incomplete artifact identity or platform") from exc
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", str(metadata["artifact_id"])):
            raise PublicationError("invalid artifact identity in schema")
        if identity in seen:
            raise PublicationError("duplicate signed artifact identity")
        seen.add(identity)
        artifacts.append(metadata)
    artifacts.sort(key=lambda a: (a["artifact_id"], a["version"], a["build"], a["platform"]["arch"], a["platform"]["abi"]))
    signed = {
        "repository_id": "official-platform",
        "channel": channel,
        "sequence": sequence,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=valid_hours)).isoformat().replace("+00:00", "Z"),
        "artifacts": artifacts,
    }
    envelope = {
        "schema": 1,
        "signed": signed,
        "signature": {
            "algorithm": "ed25519", "identity": key_id,
            "value": base64.b64encode(key.sign(canonical(signed))).decode("ascii"),
        },
    }
    validator = Draft202012Validator(json.loads(SCHEMA.read_text("utf-8")), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(envelope), key=lambda error: error.json_path)
    if errors:
        raise PublicationError("invalid candidate schema: " + errors[0].message)
    public = key.public_key()
    try:
        # Always verify the bytes we are about to publish independently.
        raw = (json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        verify_index(raw, keys={key_id: public}, channel=channel, now=now)
        for a in artifacts:
            verify_package(a, package_root, {key_id: public})
    except VerificationError as exc:
        raise PublicationError("candidate self-verification failed: " + str(exc)) from exc
    return raw


def write_candidate(path: Path, candidate: bytes) -> None:
    """Write one candidate atomically, never auto-promote a channel index."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        raise PublicationError("refusing to overwrite an existing candidate or signed channel index")
    if path.parent.is_symlink():
        raise PublicationError("refusing symlink candidate output directory")
    fd, temporary = tempfile.mkstemp(prefix=".unsigned-publication-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(candidate)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        # O_EXCL above avoids overwriting files that exist at initial admission.
        if path.exists() or path.is_symlink():
            raise PublicationError("candidate destination appeared during staging")
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_key_from_env(name: str) -> Ed25519PrivateKey:
    # No private key CLI argument, log field, checked-in fixture or source file.
    value = os.environ.get(name, "")
    if not value:
        raise PublicationError(f"missing private signing key environment variable {name}")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise PublicationError("invalid base64 private signing key") from exc
    if len(raw) != 32:
        raise PublicationError("private Ed25519 seed must be exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a signed *candidate* successor platform catalog")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new candidate index path, never an existing index")
    parser.add_argument("--channel", choices=["stable", "beta", "dev"], required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--key-id", default="official-ed25519-1")
    parser.add_argument("--private-key-env", default="MONITORBOX_PLATFORM_SIGNING_KEY")
    parser.add_argument("--valid-hours", type=int, default=48)
    args = parser.parse_args()
    try:
        key = _load_key_from_env(args.private_key_env)
        raw = sign_candidate(args.source.read_bytes(), package_root=args.package_root, key=key,
                             key_id=args.key_id, channel=args.channel, sequence=args.sequence,
                             generated_at=datetime.now(timezone.utc), valid_hours=args.valid_hours)
        write_candidate(args.output, raw)
    except (PublicationError, OSError) as exc:
        print("platform candidate rejected: " + str(exc), file=sys.stderr)
        return 1
    print("candidate signed and independently verified (NOT published): " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
