"""Private, JSON-only saved-backup vault for native MonitorBox v3.

This module ships in the independently signed Backup/Restore ZIP, not in Core.
It persists exactly Core's verified portable JSON export, with private
permissions and a metadata-last, integrity-verified commit protocol.
There are no ZIP archives, historical data, new credentials or module binaries.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}$")
_NAME = re.compile(r"^monitorbox-config_[A-Za-z0-9.+-]+_[0-9]{8}-[0-9]{6}\.json$")
_MAX_SIZE = 4 * 1024 * 1024 + 8192
_MAX_RECORDS = 2048


class JsonBackupError(ValueError):
    """Generic, secret-free backup-vault failure."""


class JsonBackupVault:
    def __init__(self, appliance_root: Path) -> None:
        self.root = Path(appliance_root)
        self.directory = self.root / "backups" / "portable-json"

    def _directory(self, *, create: bool) -> Path | None:
        parent = self.root / "backups"
        for folder in (self.root, parent, self.directory):
            if folder.is_symlink():
                raise JsonBackupError("backup vault path is not trustworthy")
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.chmod(0o700)
        elif not self.directory.exists():
            return None
        if not self.directory.is_dir():
            raise JsonBackupError("backup vault path is not a directory")
        if stat.S_IMODE(self.directory.stat().st_mode) & 0o077:
            raise JsonBackupError("backup vault has unsafe permissions")
        return self.directory

    @staticmethod
    def _valid_id(value: str) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise JsonBackupError("invalid saved backup ID")
        return value

    @staticmethod
    def _checked_source(content: bytes, filename: str) -> bytes:
        if not isinstance(content, bytes) or not 2 <= len(content) <= _MAX_SIZE:
            raise JsonBackupError("portable JSON size is invalid")
        if not isinstance(filename, str) or not _NAME.fullmatch(filename):
            raise JsonBackupError("portable JSON export filename is invalid")
        try:
            doc = json.loads(content)
        except (ValueError, UnicodeError):
            raise JsonBackupError("portable JSON export is invalid") from None
        if (
            not isinstance(doc, dict)
            or doc.get("schemaVersion") != "monitorbox.portable/v1"
            or not isinstance(doc.get("modules"), list)
            or "adminIdentity" in doc
        ):
            raise JsonBackupError("portable JSON schema or password exclusion is invalid")
        return content

    @staticmethod
    def _atomic(path: Path, content: bytes) -> None:
        temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _paths(self, backup_id: str) -> tuple[Path, Path]:
        backup_id = self._valid_id(backup_id)
        return (self.directory / (backup_id + ".json"),
                self.directory / (backup_id + ".meta.json"))

    @staticmethod
    def _file_bytes(path: Path) -> bytes:
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise JsonBackupError("saved backup is not a private regular file")
            if info.st_size < 2 or info.st_size > _MAX_SIZE:
                raise JsonBackupError("saved backup size is invalid")
            return path.read_bytes()
        except (OSError, ValueError):
            raise JsonBackupError("saved backup is unavailable") from None

    def create(self, content: bytes, filename: str, *, kind: str = "manual",
               local_day: str | None = None) -> dict[str, Any]:
        if kind not in {"manual", "scheduled"}:
            raise JsonBackupError("unsupported backup kind")
        self._checked_source(content, filename)
        self._directory(create=True)
        if len(list(self.directory.glob("*.meta.json"))) >= _MAX_RECORDS:
            raise JsonBackupError("saved backup vault is full")
        now = datetime.now(timezone.utc)
        backup_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(8)
        data, metadata = self._paths(backup_id)
        record = {
            "id": backup_id, "kind": kind, "filename": filename,
            "created_at_utc": now.isoformat(), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "local_day": local_day if kind == "scheduled" else None,
        }
        try:
            self._atomic(data, content)
            self._atomic(metadata, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
        except OSError:
            raise JsonBackupError("unable to commit saved backup") from None
        # The metadata is published last: an interrupted payload is never listed.
        return record

    def read(self, backup_id: str) -> tuple[dict[str, Any], bytes]:
        self._valid_id(backup_id)
        if self._directory(create=False) is None:
            raise JsonBackupError("saved backup not found")
        data, metadata = self._paths(backup_id)
        try:
            info = metadata.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 8192:
                raise JsonBackupError("saved backup metadata is invalid")
            record = json.loads(metadata.read_text("utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise JsonBackupError("saved backup metadata is unavailable") from None
        if (
            not isinstance(record, dict)
            or record.get("id") != backup_id
            or record.get("kind") not in {"manual", "scheduled"}
            or not isinstance(record.get("filename"), str)
            or not _NAME.fullmatch(record["filename"])
            or type(record.get("bytes")) is not int
            or not isinstance(record.get("sha256"), str)
        ):
            raise JsonBackupError("saved backup metadata is invalid")
        content = self._file_bytes(data)
        if record["bytes"] != len(content) or hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise JsonBackupError("saved backup integrity verification failed")
        self._checked_source(content, record["filename"])
        return record, content

    def list(self) -> list[dict[str, Any]]:
        if self._directory(create=False) is None:
            return []
        items = []
        for meta in sorted(self.directory.glob("*.meta.json"), reverse=True)[:_MAX_RECORDS]:
            backup_id = meta.name.removesuffix(".meta.json")
            if not _ID.fullmatch(backup_id):
                continue
            try:
                record, _ = self.read(backup_id)
                items.append(record)
            except JsonBackupError:
                # Never advertise uncommitted or corrupt private configuration.
                continue
        return items

    def delete(self, backup_id: str) -> None:
        self.read(backup_id)  # Provenance and digest check before deletion.
        data, metadata = self._paths(backup_id)
        try:
            metadata.unlink()  # Remove public vault authority first.
            data.unlink(missing_ok=True)
        except OSError:
            raise JsonBackupError("unable to delete saved backup") from None
