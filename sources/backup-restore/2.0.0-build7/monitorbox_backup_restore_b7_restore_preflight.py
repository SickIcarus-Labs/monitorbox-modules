"""Read-only, independently signed native Full ZIP restore preflight.

THIS IS NOT A RESTORE HANDOFF. No native activation, archive extraction,
administrator identity import, Core restart, or restore token is exposed.
Both saved vault archives and direct uploads must pass the independently
authenticated Supervisor signature verifier behind the scoped Core host
capability. Successful preview never authorizes subsequent restore without
fresh verification and a separate request-bound atomic transaction.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from monitorbox_backup_restore_b7_native_archive import (
    NativeArchiveInspection, MAX_BYTES,
)
from monitorbox_backup_restore_b7_native_vault import BackupVaultError

PREFIX = "/api/v2/config/backup-restore"
MAX_UPLOAD_BYTES = MAX_BYTES + (4 << 20)
CHUNK_BYTES = 1 << 20
UPLOAD_TIMEOUT_SECONDS = 45 * 60
# More than double the maximum live upload window. A previous Core may
# briefly overlap with a restarted Core and still be writing its preview.
ABANDONED_UPLOAD_SECONDS = 2 * 60 * 60
_OWNED_STAGE = re.compile(r"\.inspect-[A-Za-z0-9_-]{8,32}\Z")


def _private_directory(path: Path) -> None:
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or path.resolve(strict=True) != path
    ):
        raise BackupVaultError("native restore preflight scratch is not canonical")
    mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise BackupVaultError("native restore preflight scratch must be private")


def _summary(inspection: NativeArchiveInspection, *, source: str) -> dict[str, Any]:
    # A whitelist: NEVER serialize receipts, config, provider credentials,
    # SQLite rows, paths, admin identities, secrets or a restore commit token.
    if not isinstance(inspection, NativeArchiveInspection):
        raise BackupVaultError("native signed restore inspection unavailable")
    return {
        "verified": True,
        "restorable": False,  # Explicitly NOT an in-place restore admission.
        "source": source,
        "format": inspection.format,
        "schema": inspection.schema,
        "sha256": inspection.sha256,
        "zip_bytes": inspection.zip_bytes,
        "file_count": inspection.file_count,
        "payload_bytes": inspection.payload_bytes,
        "package_count": inspection.packages,
        "includes_previous": inspection.includes_previous,
        "active_generation_id": inspection.active_id,
        "note": "Signed ZIP inspection only; native restore remains unavailable.",
    }


class NativeRestorePreflight:
    def __init__(self, platform: Any, workflow: Any):
        self.platform = platform
        self.workflow = workflow
        self._upload_lock = asyncio.Lock()

    def install(self, app: web.Application) -> None:
        app.on_startup.append(self.recover_abandoned)
        app.router.add_post(
            PREFIX + "/native/restore/preflight/{backup_id}", self.saved
        )
        app.router.add_post(
            PREFIX + "/native/restore/preflight-file", self.upload
        )
        # Deliberately DO NOT add /native/restore/commit.

    async def recover_abandoned(self, _app: web.Application) -> None:
        """Reclaim abandoned protected ZIP uploads without following links.

        Never remove the private staging root itself, a non-owned entry, a
        symlink, or a directory recent enough to belong to overlapping Core.
        A malformed owned entry fails closed rather than traversing it.
        """
        await asyncio.to_thread(self._reap_abandoned)

    def _reap_abandoned(self) -> None:
        vault = self.workflow.vault.path
        _private_directory(vault)
        scratch = vault / ".native-restore-preflight"
        if not scratch.exists() and not scratch.is_symlink():
            return
        _private_directory(scratch)
        cutoff = time.time() - ABANDONED_UPLOAD_SECONDS
        for stage in scratch.iterdir():
            if not _OWNED_STAGE.fullmatch(stage.name):
                continue
            _private_directory(stage)
            if stage.lstat().st_mtime <= cutoff:
                # stage has been verified to be a genuine private directory
                # under a non-symlinked module-owned parent. Python rmtree
                # refuses recursive traversal of directory symlink children.
                shutil.rmtree(stage)

    async def saved(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        if request.content_length not in (None, 0):
            raise web.HTTPBadRequest(text="native restore preflight accepts no body")
        if await request.content.read(1):
            raise web.HTTPBadRequest(text="native restore preflight accepts no body")
        try:
            # Independent real signature verification is mandatory. The vault
            # refuses either missing or tampered saved ZIPs; never trust
            # a browser-supplied path or signature flag.
            inspected_path = await asyncio.to_thread(
                self.workflow.vault.archive_path,
                request.match_info["backup_id"], verify=True,
            )
            inspection = await asyncio.to_thread(
                self.workflow.vault.manager.inspect, inspected_path
            )
        except (BackupVaultError, OSError, ValueError) as exc:
            raise web.HTTPUnprocessableEntity(
                text="saved native ZIP failed independent signed verification"
            ) from exc
        return web.json_response(
            _summary(inspection, source="saved-vault"),
            headers={"Cache-Control": "no-store"},
        )

    async def upload(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        if request.content_type not in ("application/zip", "application/octet-stream"):
            raise web.HTTPUnsupportedMediaType(
                text="upload raw native ZIP bytes as application/zip"
            )
        if request.content_length is not None and request.content_length > MAX_UPLOAD_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_UPLOAD_BYTES, actual_size=request.content_length
            )
        if self._upload_lock.locked():
            raise web.HTTPConflict(text="native restore inspection already in progress")
        async with self._upload_lock:
            # The native vault has already verified its trusted root and
            # created saved-backups as a private directory at construction.
            root = self.workflow.vault.path
            try:
                _private_directory(root)
                scratch = root / ".native-restore-preflight"
                if scratch.exists() or scratch.is_symlink():
                    _private_directory(scratch)
                else:
                    scratch.mkdir(mode=0o700)
                    _private_directory(scratch)
                stage = Path(tempfile.mkdtemp(prefix=".inspect-", dir=scratch))
                _private_directory(stage)
            except (OSError, BackupVaultError) as exc:
                raise web.HTTPServiceUnavailable(
                    text="private native restore inspection staging unavailable"
                ) from exc
            try:
                path = stage / "uploaded.zip"
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                count = 0
                try:
                    with os.fdopen(fd, "wb") as stream:
                        async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                            async for chunk in request.content.iter_chunked(CHUNK_BYTES):
                                count += len(chunk)
                                if count > MAX_UPLOAD_BYTES:
                                    raise web.HTTPRequestEntityTooLarge(
                                        max_size=MAX_UPLOAD_BYTES, actual_size=count
                                    )
                                stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception:
                    raise
                if count == 0:
                    raise web.HTTPBadRequest(text="native ZIP upload is empty")
                try:
                    # This invokes both strict ZIP/member structure and the
                    # independently signed Supervisor offline verifier.
                    inspection = await asyncio.to_thread(
                        self.workflow.vault.manager.inspect, path
                    )
                except (BackupVaultError, OSError, ValueError) as exc:
                    raise web.HTTPUnprocessableEntity(
                        text="uploaded native ZIP failed independent signed verification"
                    ) from exc
                return web.json_response(
                    _summary(inspection, source="uploaded-file"),
                    headers={"Cache-Control": "no-store"},
                )
            finally:
                # A preflight never publishes a file into the saved vault and
                # never retains uploaded protected credentials after response.
                shutil.rmtree(stage, ignore_errors=True)
