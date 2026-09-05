"""Module-owned saved appliance backup vault for managed Backup / Restore."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monitorbox.v2.appliance_backup import ApplianceBackupError, ApplianceBackupManager

_BACKUP_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_BACKUP_KINDS = frozenset({"manual", "scheduled", "imported", "copy"})
ARCHIVE_SUFFIX = ".zip"
METADATA_SUFFIX = ".json"


class BackupVaultError(ValueError):
    """Raised for module-owned saved-backup policy/storage failures."""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    backup_id: str
    label: str
    created_at: str
    kind: str
    bytes: int
    sha256: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_label(value: str | None, *, fallback: str) -> str:
    label = " ".join(str(value or "").split())
    if not label:
        label = fallback
    if len(label) > 120:
        raise BackupVaultError("backup label must be 120 characters or fewer")
    if any(ord(ch) < 32 for ch in label):
        raise BackupVaultError("backup label contains unsupported control characters")
    return label


def _validate_kind(value: str) -> str:
    kind = str(value).strip().lower()
    if kind not in _BACKUP_KINDS:
        raise BackupVaultError("invalid saved-backup kind")
    return kind


class BackupVault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "saved-backups"
        self.manager = ApplianceBackupManager(self.root)

    def ensure(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path, 0o700)
        except OSError:
            pass

    @staticmethod
    def _new_id() -> str:
        return f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"

    def _new_unused_id(self) -> str:
        self.ensure()
        for _attempt in range(16):
            backup_id = self._new_id()
            if not self._archive(backup_id).exists() and not self._metadata(backup_id).exists():
                return backup_id
        raise BackupVaultError("unable to allocate a unique saved-backup id")

    @staticmethod
    def _validate_id(backup_id: str) -> str:
        value = str(backup_id).strip()
        if not _BACKUP_ID_RE.fullmatch(value):
            raise BackupVaultError("invalid saved-backup id")
        return value

    def _archive(self, backup_id: str) -> Path:
        return self.path / f"{self._validate_id(backup_id)}{ARCHIVE_SUFFIX}"

    def _metadata(self, backup_id: str) -> Path:
        return self.path / f"{self._validate_id(backup_id)}{METADATA_SUFFIX}"

    @staticmethod
    def _copy_exclusive(source: Path, destination: Path) -> None:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                fd = -1
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        except Exception:
            if fd >= 0:
                os.close(fd)
            destination.unlink(missing_ok=True)
            raise

    def _write_metadata(self, record: BackupRecord) -> None:
        self.ensure()
        destination = self._metadata(record.backup_id)
        fd, raw = tempfile.mkstemp(prefix=f".{record.backup_id}.", suffix=".tmp", dir=self.path)
        temp = Path(raw)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.public(), handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    def _read_metadata(self, backup_id: str) -> BackupRecord:
        path = self._metadata(backup_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = BackupRecord(
                backup_id=self._validate_id(str(payload["backup_id"])),
                label=_normalize_label(payload.get("label"), fallback=backup_id),
                created_at=str(payload["created_at"]),
                kind=_validate_kind(str(payload.get("kind", "manual"))),
                bytes=int(payload["bytes"]),
                sha256=str(payload["sha256"]),
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise BackupVaultError(f"saved-backup metadata is invalid for {backup_id}") from exc
        if record.backup_id != backup_id:
            raise BackupVaultError(f"saved-backup metadata id mismatch for {backup_id}")
        if record.bytes < 0 or not re.fullmatch(r"[0-9a-f]{64}", record.sha256):
            raise BackupVaultError(f"saved-backup metadata integrity fields are invalid for {backup_id}")
        return record

    def _record_archive(self, archive: Path, *, label: str | None, kind: str) -> BackupRecord:
        self.manager.inspect(archive)
        if archive.suffix != ARCHIVE_SUFFIX:
            raise BackupVaultError("saved backup archive must be a ZIP file")
        backup_id = archive.name.removesuffix(ARCHIVE_SUFFIX)
        created_at = _utc_now().isoformat()
        record = BackupRecord(
            backup_id=backup_id,
            label=_normalize_label(label, fallback=f"Backup {created_at[:19].replace('T', ' ')} UTC"),
            created_at=created_at,
            kind=_validate_kind(kind),
            bytes=archive.stat().st_size,
            sha256=_sha256_file(archive),
        )
        self._write_metadata(record)
        return record

    def create(self, *, label: str | None = None, kind: str = "manual") -> BackupRecord:
        self.ensure()
        _normalize_label(label, fallback="Backup")
        _validate_kind(kind)
        backup_id = self._new_unused_id()
        archive = self._archive(backup_id)
        try:
            self.manager.create(archive)
            return self._record_archive(archive, label=label, kind=kind)
        except BackupVaultError:
            archive.unlink(missing_ok=True)
            self._metadata(backup_id).unlink(missing_ok=True)
            raise
        except (ApplianceBackupError, OSError) as exc:
            archive.unlink(missing_ok=True)
            self._metadata(backup_id).unlink(missing_ok=True)
            raise BackupVaultError(str(exc)) from exc

    def list(self) -> tuple[BackupRecord, ...]:
        self.ensure()
        records: list[BackupRecord] = []
        for metadata in sorted(self.path.glob(f"*{METADATA_SUFFIX}")):
            backup_id = metadata.name.removesuffix(METADATA_SUFFIX)
            if not _BACKUP_ID_RE.fullmatch(backup_id):
                continue
            archive = self._archive(backup_id)
            if not archive.is_file() or archive.is_symlink():
                continue
            records.append(self._read_metadata(backup_id))
        return tuple(sorted(records, key=lambda item: (item.created_at, item.backup_id), reverse=True))

    def get(self, backup_id: str, *, verify: bool = False) -> BackupRecord:
        backup_id = self._validate_id(backup_id)
        record = self._read_metadata(backup_id)
        archive = self._archive(backup_id)
        if not archive.is_file() or archive.is_symlink():
            raise BackupVaultError(f"saved backup {backup_id} is missing")
        if verify:
            if archive.stat().st_size != record.bytes or _sha256_file(archive) != record.sha256:
                raise BackupVaultError(f"saved backup {backup_id} failed vault integrity verification")
            try:
                self.manager.inspect(archive)
            except ApplianceBackupError as exc:
                raise BackupVaultError(str(exc)) from exc
        return record

    def inspect(self, backup_id: str) -> dict[str, Any]:
        record = self.get(backup_id, verify=True)
        inspection = self.manager.inspect(self._archive(backup_id))
        manifest = inspection.manifest
        core = manifest.get("core") if isinstance(manifest.get("core"), dict) else {}
        return {
            **record.public(),
            "format": manifest.get("format"),
            "format_version": manifest.get("version"),
            "core_version": core.get("version"),
            "core_build": core.get("build"),
            "installation_id": manifest.get("installation_id"),
            "canonical_revision": manifest.get("canonical_revision"),
            "installation_fingerprint": manifest.get("installation_fingerprint"),
            "file_count": inspection.file_count,
            "payload_bytes": inspection.total_bytes,
        }

    def archive_path(self, backup_id: str, *, verify: bool = True) -> Path:
        self.get(backup_id, verify=verify)
        return self._archive(backup_id)

    def rename(self, backup_id: str, *, label: str) -> BackupRecord:
        current = self.get(backup_id)
        updated = BackupRecord(
            backup_id=current.backup_id,
            label=_normalize_label(label, fallback=current.label),
            created_at=current.created_at,
            kind=current.kind,
            bytes=current.bytes,
            sha256=current.sha256,
        )
        self._write_metadata(updated)
        return updated

    def copy(self, backup_id: str, *, label: str | None = None) -> BackupRecord:
        source = self.archive_path(backup_id, verify=True)
        current = self.get(backup_id)
        if label is not None:
            _normalize_label(label, fallback=f"Copy of {current.label}")
        new_id = self._new_unused_id()
        destination = self._archive(new_id)
        try:
            self._copy_exclusive(source, destination)
            return self._record_archive(
                destination,
                label=label or f"Copy of {current.label}",
                kind="copy",
            )
        except BackupVaultError:
            destination.unlink(missing_ok=True)
            self._metadata(new_id).unlink(missing_ok=True)
            raise
        except (OSError, ApplianceBackupError) as exc:
            destination.unlink(missing_ok=True)
            self._metadata(new_id).unlink(missing_ok=True)
            raise BackupVaultError(f"unable to copy saved backup: {exc}") from exc

    def import_file(self, source: Path, *, label: str | None = None) -> BackupRecord:
        self.ensure()
        source = Path(source)
        _normalize_label(label, fallback="Imported backup")
        if source.suffix.lower() != ARCHIVE_SUFFIX:
            raise BackupVaultError("import rejected: appliance backup must be a .zip file")
        try:
            self.manager.inspect(source)
        except (ApplianceBackupError, OSError) as exc:
            raise BackupVaultError(f"import rejected: {exc}") from exc
        backup_id = self._new_unused_id()
        destination = self._archive(backup_id)
        try:
            self._copy_exclusive(source, destination)
            record = self._record_archive(destination, label=label, kind="imported")
            source.unlink()
            return record
        except BackupVaultError:
            destination.unlink(missing_ok=True)
            self._metadata(backup_id).unlink(missing_ok=True)
            raise
        except (OSError, ApplianceBackupError) as exc:
            destination.unlink(missing_ok=True)
            self._metadata(backup_id).unlink(missing_ok=True)
            raise BackupVaultError(f"unable to import saved backup: {exc}") from exc

    def prune_scheduled(self, *, retention_count: int, retention_bytes: int) -> tuple[str, ...]:
        if retention_count < 1 or retention_bytes < 1:
            raise BackupVaultError("scheduled retention limits must be positive")
        scheduled = [item for item in self.list() if item.kind == "scheduled"]
        deleted: list[str] = []
        retained = 0
        retained_bytes = 0
        for index, record in enumerate(scheduled):
            keep = index == 0 or (
                retained < retention_count
                and retained_bytes + record.bytes <= retention_bytes
            )
            if keep:
                retained += 1
                retained_bytes += record.bytes
                continue
            self.delete(record.backup_id)
            deleted.append(record.backup_id)
        return tuple(deleted)

    def delete(self, backup_id: str) -> None:
        backup_id = self._validate_id(backup_id)
        self.get(backup_id)
        archive = self._archive(backup_id)
        metadata = self._metadata(backup_id)
        try:
            archive.unlink()
            metadata.unlink(missing_ok=True)
        except OSError as exc:
            raise BackupVaultError(f"unable to delete saved backup {backup_id}: {exc}") from exc
