"""P0 #757 development-only Backup/Restore module native ZIP handoff.

This is not packaged or installed. The real module must supply its trusted,
signed-full-archive verifier and transactional durable vault publisher. Neither
a request nonce nor a caller-selected file path is an authorization credential.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Callable, Any

from native_archive_intent import NativeArchiveIntentLedger, ArchiveIntentUnavailable


class NativeArchiveHandoff:
    """User-driven sequence around the already authenticated Core IPC client.

    All operations require a live Core admin session; mutations require CSRF.
    Automatic backup scheduling will need a separate approved scoped product
    authority, not a reused browser session or Recovery bearer.
    """

    def __init__(
        self,
        ledger: NativeArchiveIntentLedger,
        ipc: Any,
        private_staging: Path,
        verify_signed_zip: Callable[[Path], None],
        publish_verified_zip: Callable[[Path, str], str],
    ) -> None:
        self.ledger = ledger
        self.ipc = ipc
        self.private_staging = Path(private_staging)
        self.verify_signed_zip = verify_signed_zip
        self.publish_verified_zip = publish_verified_zip
        self._validate_staging()

    def _validate_staging(self) -> None:
        root = self.private_staging
        raw = str(root)
        if (not root.is_absolute() or os.path.normpath(raw) != raw
                or os.path.realpath(raw) != raw):
            raise ArchiveIntentUnavailable("native ZIP vault staging unsafe")
        try:
            info = root.lstat()
        except OSError as exc:
            raise ArchiveIntentUnavailable("native ZIP vault staging unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.geteuid()):
            raise ArchiveIntentUnavailable("native ZIP vault staging unsafe")

    def begin_for_admin(self, auth: Any, request: Any) -> str:
        auth.require(request, csrf=True)
        # fsync the nonce BEFORE the native Begin RPC can quiesce this Core.
        intent = self.ledger.prepare()
        # A lost ACK or terminated Core leaves precisely the same pending ID
        # on disk. The caller must never generate another ID on uncertainty.
        self.ipc.begin_for_admin(auth, request, intent.request_id)
        return intent.request_id

    def status_for_admin(self, auth: Any, request: Any):
        auth.require(request)
        intent = self.ledger.read()
        if intent is None:
            raise ArchiveIntentUnavailable("no pending native ZIP request")
        status = self.ipc.status_for_admin(auth, request, intent.request_id)
        if status.request_id != intent.request_id:
            raise ArchiveIntentUnavailable("native ZIP status identity changed")
        self.ledger.observe(intent.request_id, status.phase)
        return status

    def receive_for_admin(self, auth: Any, request: Any) -> str:
        """Receive one-time claim into private 0600 scratch and atomically vault.

        No request is retired until verified bytes are durably published AND
        Supervisor independently reports CLAIMED. Any interruption deletes
        partial scratch and leaves the ID for explicit status/reconciliation.
        """
        auth.require(request, csrf=True)
        intent = self.ledger.read()
        if intent is None or intent.phase != "ready":
            raise ArchiveIntentUnavailable("native ZIP is not ready to claim")
        status = self.ipc.status_for_admin(auth, request, intent.request_id)
        if status.request_id != intent.request_id or status.phase != "ready":
            raise ArchiveIntentUnavailable("native ZIP is no longer ready")
        self._validate_staging()
        fd, name = tempfile.mkstemp(
            prefix=".native-zip-claim-", suffix=".partial",
            dir=self.private_staging,
        )
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as sink:
                streamed = self.ipc.claim_into_for_admin(
                    auth, request, intent.request_id, sink,
                )
                sink.flush()
                os.fsync(sink.fileno())
            size = path.stat().st_size
            if type(streamed) is not int or streamed <= 0 or size != streamed:
                raise ArchiveIntentUnavailable("native ZIP stream incomplete")
            # The verifier MUST validate exact signed 13-role receipt, authority
            # and ZIP contents; checking only the 'PK' magic is insufficient.
            self.verify_signed_zip(path)
            # Publisher MUST atomically durably register bytes in module vault
            # and return a nonempty archival record ID only after completion.
            record_id = self.publish_verified_zip(path, intent.request_id)
            if not isinstance(record_id, str) or not record_id:
                raise ArchiveIntentUnavailable("verified ZIP was not durably saved")
            claimed = self.ipc.status_for_admin(auth, request, intent.request_id)
            if claimed.request_id != intent.request_id or claimed.phase != "claimed":
                raise ArchiveIntentUnavailable("native ZIP claim status uncertain")
            self.ledger.observe(intent.request_id, "claimed")
            self.ledger.acknowledge_terminal(intent.request_id)
            return record_id
        finally:
            # A failed claim cannot be replayed, and failed bytes must never
            # be presented as a completed backup. Preserve the durable nonce.
            path.unlink(missing_ok=True)
