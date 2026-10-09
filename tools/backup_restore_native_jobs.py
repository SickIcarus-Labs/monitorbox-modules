"""Development-only Backup/Restore v3 native Full ZIP job journal.

A native ZIP snapshot quiesces Core, so an in-process coroutine is not a
durable backup workflow. The independently signed Supervisor owns ZIP
creation and transfer; this module-only journal persists the accepted job,
source generation, transfer proof and ultimate vault publication outcome.

This module does NOT publish ZIPs, verify signed packages, create routes, or
replace the currently released build-6 module. A separate verified atomic
vault transaction must complete before calling commit().
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_KINDS = frozenset({"manual", "scheduled"})
_TERMINAL = frozenset({"committed", "failed"})
_FAILURES = frozenset({"archive_failed", "transfer_failed", "vault_failed", "expired"})
_JOURNAL_NAME = ".native-fullzip-job.json"
_LOCK_NAME = ".native-fullzip-job.lock"
_SCHEMA = 1
_MAX_JOURNAL_BYTES = 4096
_MAX_ARCHIVE_BYTES = (64 << 30) + (4 << 20)


class NativeBackupJobError(ValueError):
    """A bounded, credential-free native backup state error."""


@dataclass(frozen=True, slots=True)
class NativeBackupJob:
    schema: int
    request_id: str
    job_id: str
    generation: str
    kind: str
    include_previous: bool
    created_at: str
    phase: str
    bytes: int | None = None
    sha256: str | None = None
    backup_id: str | None = None
    failure_code: str | None = None

    def public(self) -> dict[str, object]:
        """User-visible fields. This never contains paths or credentials."""
        return asdict(self)


def _validate(record: NativeBackupJob) -> NativeBackupJob:
    if record.schema != _SCHEMA:
        raise NativeBackupJobError("unsupported native backup job schema")
    if not all(
        _HEX32.fullmatch(value or "")
        for value in (record.request_id, record.job_id, record.generation)
    ):
        raise NativeBackupJobError("invalid native backup job identity")
    if record.kind not in _KINDS or type(record.include_previous) is not bool:
        raise NativeBackupJobError("invalid native backup selection")
    try:
        date = datetime.fromisoformat(record.created_at)
    except (TypeError, ValueError) as exc:
        raise NativeBackupJobError("invalid native backup timestamp") from exc
    if date.tzinfo is None or date.utcoffset() is None:
        raise NativeBackupJobError("native backup timestamp must include UTC offset")
    if record.phase not in {"accepted", "transfer_verified", "committed", "failed"}:
        raise NativeBackupJobError("invalid native backup phase")
    if record.phase == "accepted":
        if any(x is not None for x in (
            record.bytes, record.sha256, record.backup_id, record.failure_code,
        )):
            raise NativeBackupJobError("pending backup improperly claims verified data")
    elif record.phase == "transfer_verified":
        if (type(record.bytes) is not int
            or not 0 < record.bytes <= _MAX_ARCHIVE_BYTES
            or not _SHA256.fullmatch(record.sha256 or "")
            or record.backup_id is not None or record.failure_code is not None):
            raise NativeBackupJobError("invalid verified native transfer evidence")
    elif record.phase == "committed":
        if (type(record.bytes) is not int
            or not 0 < record.bytes <= _MAX_ARCHIVE_BYTES
            or not _SHA256.fullmatch(record.sha256 or "")
            or not _BACKUP_ID.fullmatch(record.backup_id or "")
            or record.failure_code is not None):
            raise NativeBackupJobError("invalid committed native vault result")
    else:
        if record.backup_id is not None or record.failure_code not in _FAILURES:
            raise NativeBackupJobError("invalid native backup failure result")
        if record.bytes is not None or record.sha256 is not None:
            if (type(record.bytes) is not int
                or not 0 < record.bytes <= _MAX_ARCHIVE_BYTES
                or not _SHA256.fullmatch(record.sha256 or "")):
                raise NativeBackupJobError("invalid failed native transfer evidence")
    return record


def _private_directory(path: Path) -> None:
    if not path.is_absolute() or Path(os.path.normpath(path)) != path:
        raise NativeBackupJobError("native backup journal requires clean absolute path")
    if path.resolve(strict=True) != path:
        raise NativeBackupJobError("native backup journal rejects symlink ancestry")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise NativeBackupJobError("native backup journal directory is not private")


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class NativeBackupJobStore:
    """One recovery-safe native backup job per Backup/Restore vault.

    The existing Vault will continue to own ZIP/metadata publication once
    connected. The journal never marks an archive committed simply because
    Supervisor completed the ZIP or Core received all chunks.
    """

    def __init__(self, root: Path) -> None:
        root = Path(root)
        if not root.is_absolute() or root != Path(os.path.normpath(root)):
            raise NativeBackupJobError("native backup vault root must be absolute")
        if root.resolve(strict=True) != root:
            raise NativeBackupJobError("native backup vault root has symlink ancestry")
        self.directory = root / "saved-backups"
        if not self.directory.exists():
            self.directory.mkdir(mode=0o700)
            _sync_dir(root)
        _private_directory(self.directory)
        self.journal = self.directory / _JOURNAL_NAME
        self.lock = self.directory / _LOCK_NAME

    @contextmanager
    def _locked(self) -> Iterator[None]:
        _private_directory(self.directory)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock, flags, 0o600)
        try:
            mode = os.fstat(fd).st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                raise NativeBackupJobError("native backup lock file is unsafe")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read_locked(self) -> NativeBackupJob | None:
        try:
            fd = os.open(
                self.journal, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or not 0 < info.st_size <= _MAX_JOURNAL_BYTES
            ):
                raise NativeBackupJobError("native backup journal file is unsafe")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(_MAX_JOURNAL_BYTES + 1)
            if len(raw) > _MAX_JOURNAL_BYTES:
                raise NativeBackupJobError("native backup journal exceeds byte limit")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != set(NativeBackupJob.__dataclass_fields__):
                raise NativeBackupJobError("native backup journal shape is invalid")
            return _validate(NativeBackupJob(**payload))
        except (UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, NativeBackupJobError):
                raise
            raise NativeBackupJobError("native backup journal is malformed") from exc
        finally:
            os.close(fd)

    def _write_locked(self, job: NativeBackupJob) -> None:
        data = (json.dumps(
            _validate(job).public(), sort_keys=True, separators=(",", ":")
        ) + "\n").encode("utf-8")
        if len(data) > _MAX_JOURNAL_BYTES:
            raise NativeBackupJobError("native backup journal metadata exceeds limit")
        temp = self.directory / f".native-fullzip-{secrets.token_hex(12)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.journal)
            _sync_dir(self.directory)
        finally:
            temp.unlink(missing_ok=True)

    def inspect(self) -> NativeBackupJob | None:
        with self._locked():
            return self._read_locked()

    def accept(
        self, *, request_id: str, job_id: str, generation: str,
        kind: str, include_previous: bool,
    ) -> NativeBackupJob:
        record = _validate(NativeBackupJob(
            schema=_SCHEMA, request_id=request_id, job_id=job_id,
            generation=generation, kind=kind,
            include_previous=include_previous,
            created_at=datetime.now(timezone.utc).isoformat(),
            phase="accepted",
        ))
        with self._locked():
            old = self._read_locked()
            if old and old.phase not in _TERMINAL:
                if (
                    old.request_id == record.request_id
                    and old.job_id == record.job_id
                    and old.generation == record.generation
                    and old.kind == record.kind
                    and old.include_previous == record.include_previous
                ):
                    return old
                raise NativeBackupJobError("another native backup job is pending")
            if old and old.request_id == record.request_id:
                raise NativeBackupJobError("native backup request identity was already settled")
            self._write_locked(record)
            return record

    def _current_locked(self, request_id: str) -> NativeBackupJob:
        current = self._read_locked()
        if current is None or current.request_id != request_id:
            raise NativeBackupJobError("native backup request identity is not current")
        return current

    def mark_transfer_verified(
        self, *, request_id: str, bytes_count: int, sha256: str,
    ) -> NativeBackupJob:
        with self._locked():
            current = self._current_locked(request_id)
            if current.phase == "transfer_verified":
                if current.bytes == bytes_count and current.sha256 == sha256:
                    return current
                raise NativeBackupJobError("native backup transfer evidence changed")
            if current.phase != "accepted":
                raise NativeBackupJobError("native backup is not awaiting transfer")
            next_job = _validate(NativeBackupJob(
                **{**current.public(), "phase": "transfer_verified",
                   "bytes": bytes_count, "sha256": sha256}
            ))
            self._write_locked(next_job)
            return next_job

    def commit(self, *, request_id: str, backup_id: str) -> NativeBackupJob:
        with self._locked():
            current = self._current_locked(request_id)
            if current.phase == "committed" and current.backup_id == backup_id:
                return current
            if current.phase != "transfer_verified":
                raise NativeBackupJobError("native ZIP cannot be called saved before vault commit")
            result = _validate(NativeBackupJob(
                **{**current.public(), "phase": "committed", "backup_id": backup_id}
            ))
            self._write_locked(result)
            return result

    def fail(self, *, request_id: str, failure_code: str) -> NativeBackupJob:
        if failure_code not in _FAILURES:
            raise NativeBackupJobError("invalid native backup failure code")
        with self._locked():
            current = self._current_locked(request_id)
            if current.phase == "failed" and current.failure_code == failure_code:
                return current
            if current.phase not in {"accepted", "transfer_verified"}:
                raise NativeBackupJobError("native backup result is already terminal")
            result = _validate(NativeBackupJob(
                **{**current.public(), "phase": "failed", "failure_code": failure_code}
            ))
            self._write_locked(result)
            return result
