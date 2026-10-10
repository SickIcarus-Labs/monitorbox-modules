"""Unpublished Backup/Restore P0 native ZIP request-intent ledger.

The Backup/Restore module owns its request nonce outside archived authority.
The real route must independently authenticate current administrator+CSRF
BEFORE prepare or acknowledge. The ID is not a bearer credential.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_ID = re.compile(r"[0-9a-f]{32}\Z")
_PHASES = frozenset({"submitting", "working", "ready", "failed", "claimed"})
_TERMINAL = frozenset({"failed", "claimed"})
_NAME = "native-full-archive-intent.json"
_LOCK = ".native-full-archive-intent.lock"
_MAX_BYTES = 4096


class ArchiveIntentUnavailable(RuntimeError):
    """Fail-closed storage error without echoing private journal bytes."""


@dataclass(frozen=True, slots=True)
class ArchiveIntent:
    request_id: str
    created_ns: int
    phase: str


class NativeArchiveIntentLedger:
    """Crash-durable single outstanding native export request, module-owned.

    The caller provides an existing private 0700 real directory UNDER the
    excluded backups root, not the portable/full snapshot contents.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self._validate_root()

    def _validate_root(self) -> None:
        raw = str(self.root)
        if (not self.root.is_absolute() or os.path.normpath(raw) != raw
                or os.path.realpath(raw) != raw):
            raise ArchiveIntentUnavailable("native archive intent storage unsafe")
        try:
            info = self.root.lstat()
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent storage unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.geteuid()):
            raise ArchiveIntentUnavailable("native archive intent storage unsafe")

    @staticmethod
    def _verified_file(fd: int) -> None:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()):
            raise ArchiveIntentUnavailable("native archive intent file unsafe")

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self._validate_root()
        fd = None
        try:
            fd = os.open(self.root / _LOCK, os.O_RDWR | os.O_CREAT
                         | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            self._verified_file(fd)
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._validate_root()
            yield
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent lock unavailable") from exc
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _decode(raw: bytes) -> ArchiveIntent:
        def reject_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        try:
            obj = json.loads(raw, object_pairs_hook=reject_duplicates)
            if (type(obj) is not dict
                    or set(obj) != {"schema", "request_id", "created_ns", "phase"}
                    or type(obj["schema"]) is not int or obj["schema"] != 1
                    or type(obj["request_id"]) is not str
                    or not _ID.fullmatch(obj["request_id"])
                    or type(obj["created_ns"]) is not int or obj["created_ns"] <= 0
                    or type(obj["phase"]) is not str or obj["phase"] not in _PHASES):
                raise ValueError("invalid intent")
            return ArchiveIntent(obj["request_id"], obj["created_ns"], obj["phase"])
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ArchiveIntentUnavailable("native archive intent invalid") from exc

    def _read_locked(self) -> ArchiveIntent | None:
        try:
            fd = os.open(self.root / _NAME,
                         os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent unreadable") from exc
        try:
            self._verified_file(fd)
            raw = os.read(fd, _MAX_BYTES + 1)
            if not raw or len(raw) > _MAX_BYTES:
                raise ArchiveIntentUnavailable("native archive intent invalid")
            return self._decode(raw)
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent unreadable") from exc
        finally:
            os.close(fd)

    def _sync_root(self) -> None:
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY
                         | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent durability unavailable") from exc

    def _write_locked(self, intent: ArchiveIntent) -> None:
        raw = json.dumps(
            {"schema": 1, "request_id": intent.request_id,
             "created_ns": intent.created_ns, "phase": intent.phase},
            sort_keys=True, separators=(",", ":"),
        ).encode()
        name = self.root / (".native-full-archive-intent-"
                            + secrets.token_hex(12) + ".tmp")
        created = False
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            created = True
            try:
                self._verified_file(fd)
                with os.fdopen(fd, "wb", closefd=False) as out:
                    out.write(raw)
                    out.flush()
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(name, self.root / _NAME)
            created = False
            self._sync_root()
        except OSError as exc:
            raise ArchiveIntentUnavailable("native archive intent commit failed") from exc
        finally:
            if created:
                name.unlink(missing_ok=True)

    def read(self) -> ArchiveIntent | None:
        with self._locked():
            return self._read_locked()

    def prepare(self) -> ArchiveIntent:
        """Persist nonce BEFORE returning it to the authenticated RPC caller.

        Reuse uncertain/lost ACK nonce after Core restart. Only an explicitly
        acknowledged terminal result permits a new unrelated backup.
        """
        with self._locked():
            prior = self._read_locked()
            if prior is not None:
                return prior
            intent = ArchiveIntent(secrets.token_hex(16), time.time_ns(), "submitting")
            self._write_locked(intent)
            return intent

    def observe(self, request_id: str, phase: str) -> ArchiveIntent:
        """Record independently verified Supervisor status for the same ID."""
        if phase not in _PHASES or phase == "submitting":
            raise ArchiveIntentUnavailable("native archive status invalid")
        with self._locked():
            prior = self._read_locked()
            if prior is None or prior.request_id != request_id:
                raise ArchiveIntentUnavailable("native archive identity changed")
            if prior.phase in _TERMINAL and prior.phase != phase:
                raise ArchiveIntentUnavailable("terminal native archive status changed")
            if prior.phase == "ready" and phase == "working":
                raise ArchiveIntentUnavailable("native archive status regressed")
            if prior.phase == phase:
                return prior
            updated = ArchiveIntent(prior.request_id, prior.created_ns, phase)
            self._write_locked(updated)
            return updated

    def acknowledge_terminal(self, request_id: str) -> None:
        """Requires external current-admin+CSRF authorization, never implicit."""
        with self._locked():
            prior = self._read_locked()
            if (prior is None or prior.request_id != request_id
                    or prior.phase not in _TERMINAL):
                raise ArchiveIntentUnavailable("native archive result not retired")
            try:
                os.unlink(self.root / _NAME)
                self._sync_root()
            except OSError as exc:
                raise ArchiveIntentUnavailable("native archive result not retired") from exc
