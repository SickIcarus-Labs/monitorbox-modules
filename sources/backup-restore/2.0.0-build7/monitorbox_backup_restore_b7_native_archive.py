"""Strict, streaming *structural* validator for v3 native Full ZIP archives.

This module has no authority to establish package authenticity. A caller MUST
also obtain independent local-trust-root signature/receipt verification from
Supervisor before admitting a ZIP to the durable BackupVault. The manifest is
untrusted input, including its digest and its package list.

Unsigned pre-release candidate successor Backup/Restore prototype; not a published module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT = "monitorbox-successor-full-v1"
MAX_FILES = 200_000
MAX_BYTES = 64 << 30
MAX_MANIFEST = 32 << 20
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")


class NativeArchiveError(ValueError):
    """Untrusted ZIP/manifest structure is invalid."""


@dataclass(frozen=True, slots=True)
class NativeArchiveInspection:
    format: str
    schema: int
    file_count: int
    payload_bytes: int
    packages: int
    includes_previous: bool
    sha256: str
    zip_bytes: int
    active_id: str

    # Legacy BackupVault.inspect expects attributes in its inspection object.
    @property
    def manifest(self) -> dict[str, Any]:
        return {"format": self.format, "version": self.schema}

    @property
    def total_bytes(self) -> int:
        return self.payload_bytes


def _name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise NativeArchiveError("unsafe native archive member name")
    if (
        value[0] == "/" or "\\" in value or "\x00" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise NativeArchiveError("unsafe native archive member path")
    return value


def _member_meta(value: object) -> tuple[int, str, int]:
    if not isinstance(value, dict) or set(value) != {"size", "sha256", "mode"}:
        raise NativeArchiveError("invalid native archive member metadata")
    size, digest, mode = value["size"], value["sha256"], value["mode"]
    if (
        type(size) is not int or size < 0 or size > MAX_BYTES
        or not isinstance(digest, str) or not _SHA256.fullmatch(digest)
        or type(mode) is not int or not 0 <= mode <= 0o777
    ):
        raise NativeArchiveError("invalid native archive member metadata")
    return size, digest, mode


def inspect_native_archive(path: Path) -> NativeArchiveInspection:
    """Check ZIP inventory and every declared member byte/hash, with budgets.

    Do NOT use this alone as an authorizer; signed executable closure checks
    must be performed by the native Supervisor trust-root verifier.
    """
    path = Path(path)
    try:
        file_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
            raise NativeArchiveError("native backup ZIP must be private regular file")
        if file_stat.st_size <= 0 or file_stat.st_size > MAX_BYTES + (4 << 20):
            raise NativeArchiveError("native backup ZIP outside transport budget")
        with zipfile.ZipFile(path, "r") as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_FILES + 1:
                raise NativeArchiveError("native ZIP exceeds member count")
            by_name: dict[str, zipfile.ZipInfo] = {}
            total = 0
            for entry in entries:
                name = _name(entry.filename)
                if name in by_name or entry.is_dir():
                    raise NativeArchiveError("duplicate/invalid native ZIP member")
                if entry.flag_bits & 0x1:
                    raise NativeArchiveError("encrypted native ZIP member")
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise NativeArchiveError("unsupported native ZIP compression")
                unix_mode = entry.external_attr >> 16
                mode_type = stat.S_IFMT(unix_mode)
                if mode_type not in (0, stat.S_IFREG) or (
                    unix_mode & 0o7000
                ):
                    raise NativeArchiveError("unsafe native ZIP member mode")
                total += entry.file_size
                if total > MAX_BYTES + MAX_MANIFEST:
                    raise NativeArchiveError("native ZIP uncompressed byte budget exceeded")
                by_name[name] = entry
            top = by_name.get("manifest.json")
            if top is None or top.file_size > MAX_MANIFEST:
                raise NativeArchiveError("native ZIP manifest missing or oversized")
            with archive.open(top) as stream:
                raw = stream.read(MAX_MANIFEST + 1)
            if len(raw) != top.file_size or len(raw) > MAX_MANIFEST:
                raise NativeArchiveError("native ZIP manifest size mismatch")
            try:
                manifest = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise NativeArchiveError("native ZIP manifest JSON invalid") from exc
            if not isinstance(manifest, dict) or (
                manifest.get("format") != FORMAT or manifest.get("schema") != 1
            ):
                raise NativeArchiveError("not a supported native Full ZIP")
            described = manifest.get("files")
            if not isinstance(described, dict) or len(described) > MAX_FILES:
                raise NativeArchiveError("native ZIP manifest file inventory invalid")
            if set(described) != set(by_name) - {"manifest.json"}:
                raise NativeArchiveError("native ZIP member inventory disagrees with manifest")
            active = manifest.get("active")
            if not isinstance(active, dict) or not isinstance(active.get("ref"), dict):
                raise NativeArchiveError("native ZIP missing signed Active selection")
            active_id = active["ref"].get("id")
            if not isinstance(active_id, str) or not _HEX32.fullmatch(active_id):
                raise NativeArchiveError("native ZIP Active identity invalid")
            for selection in (active, manifest.get("previous")):
                if selection is None:
                    continue
                if not isinstance(selection, dict) or not isinstance(selection.get("ref"), dict):
                    raise NativeArchiveError("native ZIP previous selection invalid")
                if not all(
                    isinstance(selection.get(key), str)
                    and selection[key] in described
                    for key in ("receipt", "config")
                ):
                    raise NativeArchiveError("native ZIP signed selection payload is missing")
                agent = selection.get("agent_receipt")
                if agent is not None and (
                    not isinstance(agent, str) or agent not in described
                ):
                    raise NativeArchiveError("native ZIP Agent selection is missing")
            packages = manifest.get("packages")
            if not isinstance(packages, list) or not packages:
                raise NativeArchiveError("native ZIP signed package inventory missing")
            seen_packages: set[str] = set()
            for item in packages:
                if not isinstance(item, dict):
                    raise NativeArchiveError("native ZIP package inventory invalid")
                rel = _name(item.get("path"))
                name = "packages/" + rel
                if name in seen_packages or name not in described:
                    raise NativeArchiveError("native ZIP signed package absent or duplicated")
                seen_packages.add(name)
                declared = described[name]
                size, digest, _ = _member_meta(declared)
                if item.get("sha256") != digest or item.get("size") != size:
                    raise NativeArchiveError("native ZIP package contradicts member integrity")
            # A perfectly hashed ZIP is still untrusted input. Only the
            # selected signed authority files, selected state trees and
            # explicitly listed package closure may be present. In particular
            # an archive cannot smuggle loose auth/session objects or caches
            # into the vault merely by listing their hashes in manifest.json.
            allowed_authority: set[str] = set()
            allowed_state_prefixes: list[str] = []
            for role, selection in (
                ("active", active), ("previous", manifest.get("previous"))
            ):
                if selection is None:
                    continue
                prefix = f"authority/{role}"
                if (
                    selection.get("receipt") != prefix + "/receipt.json"
                    or selection.get("config") != prefix + "/config.json"
                    or selection.get("state_root") != prefix + "/state"
                    or selection.get("agent_receipt", "") not in (
                        "", prefix + "/agent-receipt.json"
                    )
                ):
                    raise NativeArchiveError("native ZIP selected authority paths are invalid")
                allowed_authority.update((
                    prefix + "/receipt.json", prefix + "/config.json"
                ))
                if selection.get("agent_receipt"):
                    allowed_authority.add(prefix + "/agent-receipt.json")
                allowed_state_prefixes.append(prefix + "/state/")
            for name in described:
                if (
                    name not in allowed_authority
                    and name not in seen_packages
                    and not any(name.startswith(prefix) for prefix in allowed_state_prefixes)
                ):
                    raise NativeArchiveError("native ZIP contains unreferenced archive member")
            payload_bytes = 0
            for name, meta in described.items():
                _name(name)
                size, digest, mode = _member_meta(meta)
                entry = by_name[name]
                if entry.file_size != size:
                    raise NativeArchiveError("native ZIP member size mismatch")
                unix_mode = entry.external_attr >> 16
                if unix_mode & 0o777 != mode:
                    raise NativeArchiveError("native ZIP member permission mismatch")
                h = hashlib.sha256()
                consumed = 0
                with archive.open(entry) as stream:
                    while True:
                        chunk = stream.read(1 << 20)
                        if not chunk:
                            break
                        consumed += len(chunk)
                        if consumed > size:
                            raise NativeArchiveError("native ZIP expanded member exceeded declared size")
                        h.update(chunk)
                if consumed != size or h.hexdigest() != digest:
                    raise NativeArchiveError("native ZIP member digest mismatch")
                payload_bytes += size
            file_digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    file_digest.update(chunk)
            if path.stat().st_size != file_stat.st_size:
                raise NativeArchiveError("native ZIP changed during verification")
            return NativeArchiveInspection(
                format=FORMAT, schema=1, file_count=len(described),
                payload_bytes=payload_bytes, packages=len(packages),
                includes_previous=manifest.get("previous") is not None,
                sha256=file_digest.hexdigest(), zip_bytes=file_stat.st_size,
                active_id=active_id,
            )
    except (OSError, zipfile.BadZipFile, EOFError) as exc:
        raise NativeArchiveError("native ZIP structure unreadable") from exc
