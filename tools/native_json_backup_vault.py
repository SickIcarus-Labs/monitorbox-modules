"""Private, JSON-only saved-backup vault for native MonitorBox v3.

This module ships in the independently signed Backup/Restore ZIP, not in Core.
It persists exactly Core's verified portable JSON export, with private
permissions and a metadata-last, integrity-verified commit protocol.
There are no ZIP archives, historical data, new credentials or module binaries.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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


MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
_DAILY_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_DEFAULT_POLICY = {"enabled": False, "time": "02:00", "retention_count": 7}


def checked_json_policy(raw: Any) -> dict[str, Any]:
    """A bounded, portable module-owned operator setting; no sidecar policy."""
    if raw is None:
        return dict(_DEFAULT_POLICY)
    if not isinstance(raw, dict) or set(raw) != set(_DEFAULT_POLICY):
        raise JsonBackupError("saved JSON schedule policy is invalid")
    if type(raw["enabled"]) is not bool:
        raise JsonBackupError("schedule enabled must be a boolean")
    if not isinstance(raw["time"], str) or not _DAILY_TIME.fullmatch(raw["time"]):
        raise JsonBackupError("schedule time must be HH:MM in appliance local time")
    if type(raw["retention_count"]) is not int or not 1 <= raw["retention_count"] <= 100:
        raise JsonBackupError("schedule retention must be 1 to 100")
    return dict(raw)


def policy_from_portable(doc: dict[str, Any]) -> dict[str, Any]:
    modules = doc.get("modules")
    if not isinstance(modules, list):
        raise JsonBackupError("portable module inventory is invalid")
    matches = [row for row in modules if isinstance(row, dict) and row.get("id") == MODULE_ID]
    if len(matches) != 1 or not isinstance(matches[0].get("settings", {}), dict):
        raise JsonBackupError("Backup/Restore portable module setting is unavailable")
    return checked_json_policy(matches[0].get("settings", {}).get("jsonBackups"))


def appliance_now() -> datetime:
    name = os.environ.get("TZ")
    try:
        return datetime.now(ZoneInfo(name)) if name else datetime.now().astimezone()
    except (ZoneInfoNotFoundError, ValueError):
        raise JsonBackupError("configured appliance timezone is invalid") from None


class JsonBackupScheduler:
    """One daily JSON backup using Core's exact credential-verified exporter.

    Uses the same validated JSON snapshot as Download and Save on MonitorBox.
    The policy lives in the portable configuration and survives a JSON restore.
    A local calendar date may be backed up only once (even on a DST fold).
    On spring-forward gaps, the next due minute is used.
    """

    def __init__(self, platform: Any, vault: JsonBackupVault, *, poll_seconds: float = 60) -> None:
        self.platform = platform
        self.vault = vault
        self.poll_seconds = max(1.0, float(poll_seconds))
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.status: dict[str, Any] = {
            "last_success": None, "last_error": None, "last_id": None,
            "last_check": None,
        }

    def _export(self) -> tuple[dict[str, Any], bytes, str]:
        exporter = getattr(self.platform, "export_verified_portable_json", None)
        if not callable(exporter):
            raise JsonBackupError("Core's signed portable exporter is not available")
        response = exporter()
        content = response.body
        try:
            doc = json.loads(content)
        except (ValueError, UnicodeError):
            raise JsonBackupError("Core returned invalid portable JSON") from None
        if not isinstance(doc, dict):
            raise JsonBackupError("Core returned invalid portable JSON")
        disposition = response.headers.get("Content-Disposition", "")
        prefix = 'attachment; filename="'
        if not disposition.startswith(prefix) or not disposition.endswith('"'):
            raise JsonBackupError("Core portable filename unavailable")
        filename = disposition[len(prefix):-1]
        self.vault._checked_source(content, filename)
        return doc, content, filename

    def policy(self) -> dict[str, Any]:
        document, _, _ = self._export()
        return policy_from_portable(document)

    async def start(self, _app: Any) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="monitorbox-json-backup-scheduler")

    async def stop(self, _app: Any) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Never include credential-bearing exception strings in logs.
                self.status["last_error"] = type(exc).__name__ + ": scheduled JSON backup failed"
            await asyncio.sleep(self.poll_seconds)

    async def run_due(self, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            local = appliance_now()
            self.status["last_check"] = local.isoformat()
            try:
                policy = self.policy()
                if not force and not policy["enabled"]:
                    return {"created": False, "reason": "disabled"}
                if not force and local.strftime("%H:%M") < policy["time"]:
                    return {"created": False, "reason": "not_due"}
                today = local.strftime("%Y-%m-%d")
                if not force and any(
                    item["kind"] == "scheduled" and item.get("local_day") == today
                    for item in self.vault.list()
                ):
                    return {"created": False, "reason": "already_created_today"}
                _doc, content, filename = self._export()
                record = self.vault.create(content, filename, kind="scheduled", local_day=today)
                self.status["last_success"] = datetime.now(timezone.utc).isoformat()
                self.status["last_id"] = record["id"]
                self.status["last_error"] = None
                scheduled = [item for item in self.vault.list() if item["kind"] == "scheduled"]
                for item in scheduled[policy["retention_count"]:]:
                    self.vault.delete(item["id"])
                return {"created": True, "backup": record}
            except Exception as exc:
                self.status["last_error"] = type(exc).__name__ + ": JSON backup failed"
                raise
