"""Crash-recoverable saved appliance backup vault for Backup / Restore build 4."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from monitorbox.v2.appliance_backup import ApplianceBackupError, ApplianceBackupManager

_BACKUP_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_TRANSACTION_RE = re.compile(
    r"^(?P<backup_id>[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8})--[0-9a-f]{12}$"
)
_BACKUP_KINDS = frozenset({"manual", "scheduled", "copy"})
ARCHIVE_SUFFIX = ".zip"
METADATA_SUFFIX = ".json"
_READY_SCHEMA = 1
LOG = logging.getLogger(__name__)


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


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class BackupVault:
    """Module-owned vault with journaled two-file publication.

    A saved backup is prepared entirely under ``.transactions``.  The ready
    journal is fsynced only after both private archive and private metadata are
    durable and integrity-checked.  Final publication then renames the ZIP and
    metadata, in that order, while the ready journal remains available to finish
    an interrupted commit on the next vault construction/list operation.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "saved-backups"
        self.transactions = self.path / ".transactions"
        self.quarantine = self.path / ".quarantine"
        self.lock_path = self.path / ".vault.lock"
        self.manager = ApplianceBackupManager(self.root)
        self.ensure()
        self.reconcile()

    def ensure(self) -> None:
        for path in (self.path, self.transactions, self.quarantine):
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.ensure()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _checkpoint(self, _phase: str) -> None:
        """Internal deterministic crash-injection seam; production is a no-op."""

    @staticmethod
    def _new_id() -> str:
        return f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"

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
    def _transaction_backup_id(transaction: Path) -> str:
        match = _TRANSACTION_RE.fullmatch(transaction.name)
        if match is None:
            raise BackupVaultError("saved-backup transaction name is invalid")
        return match.group("backup_id")

    def _new_unused_id_locked(self) -> str:
        for _attempt in range(16):
            backup_id = self._new_id()
            if self._archive(backup_id).exists() or self._metadata(backup_id).exists():
                continue
            if any(self.transactions.glob(f"{backup_id}--*")):
                continue
            return backup_id
        raise BackupVaultError("unable to allocate a unique saved-backup id")

    def _begin_transaction_locked(self, backup_id: str) -> Path:
        backup_id = self._validate_id(backup_id)
        transaction = self.transactions / f"{backup_id}--{secrets.token_hex(6)}"
        transaction.mkdir(mode=0o700)
        _fsync_directory(self.transactions)
        self._checkpoint("transaction_created")
        return transaction

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

    @staticmethod
    def _write_json_atomic(destination: Path, payload: dict[str, Any], *, prefix: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=destination.parent)
        temp = Path(raw)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            os.replace(temp, destination)
            _fsync_directory(destination.parent)
        finally:
            temp.unlink(missing_ok=True)

    def _read_record_at(self, path: Path, *, expected_id: str) -> BackupRecord:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = BackupRecord(
                backup_id=self._validate_id(str(payload["backup_id"])),
                label=_normalize_label(payload.get("label"), fallback=expected_id),
                created_at=str(payload["created_at"]),
                kind=_validate_kind(str(payload.get("kind", "manual"))),
                bytes=int(payload["bytes"]),
                sha256=str(payload["sha256"]),
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise BackupVaultError(f"saved-backup metadata is invalid for {expected_id}") from exc
        if record.backup_id != expected_id:
            raise BackupVaultError(f"saved-backup metadata id mismatch for {expected_id}")
        if record.bytes < 0 or not re.fullmatch(r"[0-9a-f]{64}", record.sha256):
            raise BackupVaultError(
                f"saved-backup metadata integrity fields are invalid for {expected_id}"
            )
        return record

    def _read_metadata_locked(self, backup_id: str) -> BackupRecord:
        return self._read_record_at(self._metadata(backup_id), expected_id=backup_id)

    def _record_for_archive_locked(
        self,
        archive: Path,
        *,
        backup_id: str,
        label: str | None,
        kind: str,
    ) -> BackupRecord:
        try:
            self.manager.inspect(archive)
        except ApplianceBackupError as exc:
            raise BackupVaultError(str(exc)) from exc
        if archive.suffix != ARCHIVE_SUFFIX:
            raise BackupVaultError("saved backup archive must be a ZIP file")
        created_at = _utc_now().isoformat()
        return BackupRecord(
            backup_id=self._validate_id(backup_id),
            label=_normalize_label(label, fallback=f"Backup {created_at[:19].replace('T', ' ')} UTC"),
            created_at=created_at,
            kind=_validate_kind(kind),
            bytes=archive.stat().st_size,
            sha256=_sha256_file(archive),
        )

    def _prepare_transaction_locked(
        self,
        transaction: Path,
        *,
        label: str | None,
        kind: str,
    ) -> BackupRecord:
        backup_id = self._transaction_backup_id(transaction)
        archive = transaction / "archive.zip"
        if not archive.is_file() or archive.is_symlink():
            raise BackupVaultError("prepared saved-backup archive is missing")
        _fsync_file(archive)
        self._checkpoint("archive_fsynced")
        record = self._record_for_archive_locked(
            archive,
            backup_id=backup_id,
            label=label,
            kind=kind,
        )
        metadata = transaction / "metadata.json"
        self._write_json_atomic(metadata, record.public(), prefix=".metadata-")
        self._checkpoint("metadata_written")
        ready = {
            "schema": _READY_SCHEMA,
            "backup_id": backup_id,
            "record": record.public(),
            "metadata_sha256": _sha256_file(metadata),
        }
        self._write_json_atomic(transaction / "ready.json", ready, prefix=".ready-")
        _fsync_directory(transaction)
        self._checkpoint("ready_written")
        return record

    def _validate_prepared_locked(
        self,
        transaction: Path,
    ) -> tuple[BackupRecord, Path, Path]:
        backup_id = self._transaction_backup_id(transaction)
        ready_path = transaction / "ready.json"
        try:
            ready = json.loads(ready_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BackupVaultError("saved-backup transaction journal is unreadable") from exc
        if (
            not isinstance(ready, dict)
            or ready.get("schema") != _READY_SCHEMA
            or ready.get("backup_id") != backup_id
            or not isinstance(ready.get("record"), dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(ready.get("metadata_sha256", "")))
        ):
            raise BackupVaultError("saved-backup transaction journal is invalid")

        private_metadata = transaction / "metadata.json"
        final_metadata = self._metadata(backup_id)
        metadata_candidates = [path for path in (private_metadata, final_metadata) if path.exists()]
        if len(metadata_candidates) != 1:
            raise BackupVaultError("saved-backup transaction metadata state is ambiguous")
        metadata = metadata_candidates[0]
        if metadata.is_symlink() or not metadata.is_file():
            raise BackupVaultError("saved-backup transaction metadata is not a regular file")
        if _sha256_file(metadata) != ready["metadata_sha256"]:
            raise BackupVaultError("saved-backup transaction metadata failed integrity verification")
        record = self._read_record_at(metadata, expected_id=backup_id)
        if record.public() != ready["record"]:
            raise BackupVaultError("saved-backup transaction metadata does not match its journal")

        private_archive = transaction / "archive.zip"
        final_archive = self._archive(backup_id)
        archive_candidates = [path for path in (private_archive, final_archive) if path.exists()]
        if len(archive_candidates) != 1:
            raise BackupVaultError("saved-backup transaction archive state is ambiguous")
        archive = archive_candidates[0]
        if archive.is_symlink() or not archive.is_file():
            raise BackupVaultError("saved-backup transaction archive is not a regular file")
        if archive.stat().st_size != record.bytes or _sha256_file(archive) != record.sha256:
            raise BackupVaultError("saved-backup transaction archive failed integrity verification")
        try:
            self.manager.inspect(archive)
        except ApplianceBackupError as exc:
            raise BackupVaultError(str(exc)) from exc
        return record, archive, metadata

    def _cleanup_transaction_locked(self, transaction: Path) -> None:
        try:
            shutil.rmtree(transaction)
            _fsync_directory(self.transactions)
        except OSError as exc:
            LOG.warning(
                "saved-backup transaction cleanup deferred transaction=%s exception_type=%s",
                transaction.name,
                type(exc).__name__,
            )

    def _commit_transaction_locked(self, transaction: Path) -> BackupRecord:
        record, archive, metadata = self._validate_prepared_locked(transaction)
        final_archive = self._archive(record.backup_id)
        final_metadata = self._metadata(record.backup_id)
        try:
            if archive != final_archive:
                os.replace(archive, final_archive)
                _fsync_directory(self.path)
                self._checkpoint("archive_published")
            if metadata != final_metadata:
                os.replace(metadata, final_metadata)
                _fsync_directory(self.path)
                self._checkpoint("metadata_published")
        except OSError as exc:
            raise BackupVaultError(f"unable to commit saved backup {record.backup_id}: {exc}") from exc

        final_record = self._read_record_at(final_metadata, expected_id=record.backup_id)
        if final_record != record:
            raise BackupVaultError("committed saved-backup metadata changed during publication")
        if (
            final_archive.is_symlink()
            or not final_archive.is_file()
            or final_archive.stat().st_size != record.bytes
            or _sha256_file(final_archive) != record.sha256
        ):
            raise BackupVaultError("committed saved backup failed final integrity verification")
        self._cleanup_transaction_locked(transaction)
        self._checkpoint("transaction_cleaned")
        return record

    def _final_pair_valid_locked(self, backup_id: str) -> bool:
        try:
            record = self._read_metadata_locked(backup_id)
            archive = self._archive(backup_id)
            if archive.is_symlink() or not archive.is_file():
                return False
            if archive.stat().st_size != record.bytes or _sha256_file(archive) != record.sha256:
                return False
            self.manager.inspect(archive)
            return True
        except (BackupVaultError, ApplianceBackupError, OSError):
            return False

    def _quarantine_path_locked(self, path: Path, *, reason: str) -> None:
        if not path.exists() and not path.is_symlink():
            return
        token = secrets.token_hex(4)
        destination = self.quarantine / f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}-{token}-{path.name}"
        try:
            os.replace(path, destination)
            _fsync_directory(self.quarantine)
            _fsync_directory(path.parent)
        except OSError as exc:
            raise BackupVaultError(f"unable to quarantine incomplete saved backup: {exc}") from exc
        LOG.warning("quarantined saved-backup artifact artifact=%s reason=%s", destination.name, reason)

    def _quarantine_transaction_locked(self, transaction: Path, *, reason: str) -> None:
        try:
            backup_id = self._transaction_backup_id(transaction)
        except BackupVaultError:
            backup_id = None
        if backup_id is not None:
            self._quarantine_path_locked(self._archive(backup_id), reason=reason)
            self._quarantine_path_locked(self._metadata(backup_id), reason=reason)
        self._quarantine_path_locked(transaction, reason=reason)

    def _rollback_failed_transaction_locked(self, transaction: Path) -> None:
        try:
            backup_id = self._transaction_backup_id(transaction)
        except BackupVaultError:
            backup_id = None
        for path in (
            self._archive(backup_id) if backup_id else None,
            self._metadata(backup_id) if backup_id else None,
        ):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                try:
                    self._quarantine_path_locked(path, reason="failed publication rollback")
                except BackupVaultError:
                    pass
        try:
            shutil.rmtree(transaction, ignore_errors=True)
            _fsync_directory(self.path)
            _fsync_directory(self.transactions)
        except OSError:
            pass

    def _reconcile_transaction_locked(self, transaction: Path) -> None:
        if transaction.is_symlink() or not transaction.is_dir():
            self._quarantine_path_locked(transaction, reason="invalid transaction object")
            return
        try:
            backup_id = self._transaction_backup_id(transaction)
        except BackupVaultError:
            self._quarantine_path_locked(transaction, reason="invalid transaction name")
            return

        ready = transaction / "ready.json"
        if not ready.is_file() or ready.is_symlink():
            if self._final_pair_valid_locked(backup_id):
                self._cleanup_transaction_locked(transaction)
            else:
                shutil.rmtree(transaction, ignore_errors=True)
                _fsync_directory(self.transactions)
            return

        try:
            self._commit_transaction_locked(transaction)
        except BackupVaultError as exc:
            if self._final_pair_valid_locked(backup_id):
                self._cleanup_transaction_locked(transaction)
                return
            self._quarantine_transaction_locked(
                transaction,
                reason=f"unrecoverable prepared transaction: {type(exc).__name__}",
            )

    def _quarantine_orphans_locked(self) -> None:
        archive_ids = {
            path.name.removesuffix(ARCHIVE_SUFFIX)
            for path in self.path.glob(f"*{ARCHIVE_SUFFIX}")
            if _BACKUP_ID_RE.fullmatch(path.name.removesuffix(ARCHIVE_SUFFIX))
        }
        metadata_ids = {
            path.name.removesuffix(METADATA_SUFFIX)
            for path in self.path.glob(f"*{METADATA_SUFFIX}")
            if _BACKUP_ID_RE.fullmatch(path.name.removesuffix(METADATA_SUFFIX))
        }
        for backup_id in sorted(archive_ids | metadata_ids):
            archive = self._archive(backup_id)
            metadata = self._metadata(backup_id)
            if backup_id not in metadata_ids:
                self._quarantine_path_locked(archive, reason="orphan final archive without metadata")
                continue
            if backup_id not in archive_ids:
                self._quarantine_path_locked(metadata, reason="orphan final metadata without archive")
                continue
            if archive.is_symlink() or metadata.is_symlink() or not archive.is_file() or not metadata.is_file():
                self._quarantine_path_locked(archive, reason="unsafe committed backup object")
                self._quarantine_path_locked(metadata, reason="unsafe committed backup object")

    def _reconcile_locked(self) -> None:
        self.ensure()
        for transaction in sorted(self.transactions.iterdir(), key=lambda item: item.name):
            self._reconcile_transaction_locked(transaction)
        self._quarantine_orphans_locked()

    def reconcile(self) -> None:
        with self._locked():
            self._reconcile_locked()

    def create(self, *, label: str | None = None, kind: str = "manual") -> BackupRecord:
        _normalize_label(label, fallback="Backup")
        _validate_kind(kind)
        with self._locked():
            self._reconcile_locked()
            backup_id = self._new_unused_id_locked()
            transaction = self._begin_transaction_locked(backup_id)
            archive = transaction / "archive.zip"
            try:
                self.manager.create(archive)
                self._checkpoint("archive_written")
                self._prepare_transaction_locked(transaction, label=label, kind=kind)
                return self._commit_transaction_locked(transaction)
            except BackupVaultError:
                self._rollback_failed_transaction_locked(transaction)
                raise
            except (ApplianceBackupError, OSError) as exc:
                self._rollback_failed_transaction_locked(transaction)
                raise BackupVaultError(str(exc)) from exc

    def _list_locked(self) -> tuple[BackupRecord, ...]:
        records: list[BackupRecord] = []
        for metadata in sorted(self.path.glob(f"*{METADATA_SUFFIX}")):
            backup_id = metadata.name.removesuffix(METADATA_SUFFIX)
            if not _BACKUP_ID_RE.fullmatch(backup_id):
                continue
            archive = self._archive(backup_id)
            if not archive.is_file() or archive.is_symlink():
                continue
            records.append(self._read_metadata_locked(backup_id))
        return tuple(sorted(records, key=lambda item: (item.created_at, item.backup_id), reverse=True))

    def list(self) -> tuple[BackupRecord, ...]:
        with self._locked():
            self._reconcile_locked()
            return self._list_locked()

    def _get_locked(self, backup_id: str, *, verify: bool = False) -> BackupRecord:
        backup_id = self._validate_id(backup_id)
        record = self._read_metadata_locked(backup_id)
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

    def get(self, backup_id: str, *, verify: bool = False) -> BackupRecord:
        with self._locked():
            self._reconcile_locked()
            return self._get_locked(backup_id, verify=verify)

    def inspect(self, backup_id: str) -> dict[str, Any]:
        with self._locked():
            self._reconcile_locked()
            record = self._get_locked(backup_id, verify=True)
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
        with self._locked():
            self._reconcile_locked()
            self._get_locked(backup_id, verify=verify)
            return self._archive(backup_id)

    def rename(self, backup_id: str, *, label: str) -> BackupRecord:
        with self._locked():
            self._reconcile_locked()
            current = self._get_locked(backup_id)
            updated = BackupRecord(
                backup_id=current.backup_id,
                label=_normalize_label(label, fallback=current.label),
                created_at=current.created_at,
                kind=current.kind,
                bytes=current.bytes,
                sha256=current.sha256,
            )
            self._write_json_atomic(
                self._metadata(updated.backup_id),
                updated.public(),
                prefix=f".{updated.backup_id}.",
            )
            return updated

    def copy(self, backup_id: str, *, label: str | None = None) -> BackupRecord:
        with self._locked():
            self._reconcile_locked()
            current = self._get_locked(backup_id, verify=True)
            source = self._archive(current.backup_id)
            if label is not None:
                _normalize_label(label, fallback=f"Copy of {current.label}")
            new_id = self._new_unused_id_locked()
            transaction = self._begin_transaction_locked(new_id)
            archive = transaction / "archive.zip"
            try:
                self._copy_exclusive(source, archive)
                self._checkpoint("archive_written")
                self._prepare_transaction_locked(
                    transaction,
                    label=label or f"Copy of {current.label}",
                    kind="copy",
                )
                return self._commit_transaction_locked(transaction)
            except BackupVaultError:
                self._rollback_failed_transaction_locked(transaction)
                raise
            except (OSError, ApplianceBackupError) as exc:
                self._rollback_failed_transaction_locked(transaction)
                raise BackupVaultError(f"unable to copy saved backup: {exc}") from exc

    def prune_scheduled(self, *, retention_count: int, retention_bytes: int) -> tuple[str, ...]:
        if retention_count < 1 or retention_bytes < 1:
            raise BackupVaultError("scheduled retention limits must be positive")
        with self._locked():
            self._reconcile_locked()
            scheduled = [item for item in self._list_locked() if item.kind == "scheduled"]
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
                self._delete_locked(record.backup_id)
                deleted.append(record.backup_id)
            return tuple(deleted)

    def _delete_locked(self, backup_id: str) -> None:
        backup_id = self._validate_id(backup_id)
        self._get_locked(backup_id)
        archive = self._archive(backup_id)
        metadata = self._metadata(backup_id)
        try:
            archive.unlink()
            metadata.unlink(missing_ok=True)
            _fsync_directory(self.path)
        except OSError as exc:
            raise BackupVaultError(f"unable to delete saved backup {backup_id}: {exc}") from exc

    def delete(self, backup_id: str) -> None:
        with self._locked():
            self._reconcile_locked()
            self._delete_locked(backup_id)
