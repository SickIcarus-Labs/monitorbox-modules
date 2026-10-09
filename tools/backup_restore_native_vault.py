"""Unreleased native Full ZIP adapter for the build-4 crash-safe saved vault.

The historical BackupVault is format-hardwired to the v2 ApplianceBackupManager
for record creation, prepared-transaction validation, post-crash recovery and
saved-backup inspection. NEVER pass a v3 ZIP through its legacy inspector.

This adapter reuses its durable two-file ZIP+metadata transaction algorithm,
but replaces the inspector *before any reconciliation* with an explicitly
injected locally authenticated signed-closure validator. The structural
validator alone does not establish package authenticity. If the independent
Supervisor verification API does not exist, the production caller MUST fail
closed; this prototype is not wired to an operator route or release package.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Callable

from backup_restore_native_archive import (
    NativeArchiveInspection,
    NativeArchiveError,
    inspect_native_archive,
)
from monitorbox_backup_restore_b4_vault import (
    BackupVault, BackupRecord, BackupVaultError, _normalize_label,
    _validate_kind, _sha256_file,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SignedArchiveVerifier = Callable[[Path, NativeArchiveInspection], None]


class _NativeSignedInspector:
    """Mandatory offline authenticated native signed-package verifier seam."""

    def __init__(self, verify_signed_closure: SignedArchiveVerifier) -> None:
        if not callable(verify_signed_closure):
            raise BackupVaultError(
                "native Full ZIP publication requires independent signed closure authority"
            )
        self._verified = verify_signed_closure

    def inspect(self, path: Path) -> NativeArchiveInspection:
        try:
            inspection = inspect_native_archive(path)
        except NativeArchiveError as exc:
            # The historical vault's reconciliation machinery recognizes its
            # own BackupVaultError, not a new native format exception. Invalid
            # staged ZIPs must be quarantined, not strand startup.
            raise BackupVaultError("native ZIP failed structural verification") from exc
        try:
            # This callback must be provided by the already-authenticated
            # native Supervisor trust-root/package-closure verification API.
            # ZIP-supplied receipts/digests do NOT substitute for trust.
            result = self._verified(Path(path), inspection)
        except Exception as exc:
            raise BackupVaultError(
                "native ZIP signed package authority could not be verified"
            ) from exc
        if result is not None:
            raise BackupVaultError("native signed verifier must return no unauthenticated metadata")
        return inspection

    def create(self, path: Path) -> None:
        raise BackupVaultError("legacy archive writer forbidden for native BackupVault")


class NativeBackupVault(BackupVault):
    """Only expose verified native ZIPs through inherited atomic vault journal."""

    def __init__(
        self, root: Path, *,
        verify_signed_closure: SignedArchiveVerifier | None = None,
    ) -> None:
        self.root = Path(root)
        # The inherited ensure() mutates directory permissions. Refuse a
        # symlinked or nonprivate root BEFORE invoking it; in particular do
        # not chmod an attacker-selected directory through a symlink.
        if (
            not self.root.is_absolute()
            or Path(os.path.normpath(self.root)) != self.root
            or self.root.resolve(strict=True) != self.root
        ):
            raise BackupVaultError("native vault root must be a clean real absolute directory")
        root_mode = self.root.lstat().st_mode
        if not stat.S_ISDIR(root_mode) or root_mode & 0o077:
            raise BackupVaultError("native vault root must be private")
        # The existing implementation uses /saved-backups, .transactions and
        # .quarantine as stable state. Set the adapter inspector BEFORE calling
        # reconcile so existing native ZIPs are never misread/quarantined by
        # ApplianceBackupManager.
        self.path = self.root / "saved-backups"
        self.transactions = self.path / ".transactions"
        self.quarantine = self.path / ".quarantine"
        self.lock_path = self.path / ".vault.lock"
        self.manager = _NativeSignedInspector(verify_signed_closure)
        self.ensure()
        self.reconcile()

    def create(self, *, label: str | None = None, kind: str = "manual") -> BackupRecord:
        """Refuse silent fallback to v2 legacy ZIP writer."""
        raise BackupVaultError("native backup must be created by signed Supervisor")

    def create_from_verified_transfer(
        self,
        source: Path, *,
        transport_bytes: int, transport_sha256: str,
        label: str | None = None, kind: str = "manual",
    ) -> BackupRecord:
        """Copy a fully transferred signed ZIP into the existing vault journal.

        The source file is caller-owned private scratch; Supervisor has already
        verified the transfer hash. ZIP structure and *independent signed
        closure authority* are verified again on the immutable private
        transaction copy, before the ready journal or published ZIP appears.
        """
        _normalize_label(label, fallback="Backup")
        _validate_kind(kind)
        source = Path(source)
        if (
            not source.is_absolute() or source != Path(os.path.normpath(source))
            or source.resolve(strict=True) != source
        ):
            raise BackupVaultError("native ZIP source path is not private and canonical")
        info = source.lstat()
        parent = source.parent
        parent_info = parent.stat()
        if (
            not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
            or not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_mode & 0o077
            or parent.resolve(strict=True) != parent
        ):
            raise BackupVaultError("native ZIP transfer must be private regular file")
        if (
            type(transport_bytes) is not int or transport_bytes <= 0
            or transport_bytes > (64 << 30) + (4 << 20)
            or info.st_size != transport_bytes
            or not isinstance(transport_sha256, str)
            or not _SHA256.fullmatch(transport_sha256)
        ):
            raise BackupVaultError("native ZIP transport evidence is invalid")

        with self._locked():
            self._reconcile_locked()
            backup_id = self._new_unused_id_locked()
            transaction = self._begin_transaction_locked(backup_id)
            staged = transaction / "archive.zip"
            try:
                self._copy_exclusive(source, staged)
                if (
                    staged.stat().st_size != transport_bytes
                    or _sha256_file(staged) != transport_sha256
                ):
                    raise BackupVaultError("native ZIP changed during private vault copy")
                # Inherited _prepare_transaction_locked -> _record_for_archive_locked
                # -> self.manager.inspect performs structure+native signature
                # verification before durable metadata+ready publication.
                self._checkpoint("native_verified_copy")
                self._prepare_transaction_locked(
                    transaction, label=label, kind=kind,
                )
                record = self._commit_transaction_locked(transaction)
                if record.bytes != transport_bytes or record.sha256 != transport_sha256:
                    raise BackupVaultError("native vault committed unexpected transport bytes")
                return record
            except Exception:
                # Regular errors clean incomplete work; actual abrupt process
                # exits leave the crash journal for a later independent
                # verification/reconciliation pass.
                self._rollback_failed_transaction_locked(transaction)
                raise
