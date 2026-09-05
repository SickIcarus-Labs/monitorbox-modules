"""Bounded in-process scheduler for managed Backup / Restore."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from monitorbox_backup_restore_b3_destinations import (
    BackupDestinationError,
    FilesystemBackupDestination,
)
from monitorbox_backup_restore_b3_policy import BackupPolicy, BackupPolicyError, BackupPolicyStore
from monitorbox_backup_restore_b3_vault import ARCHIVE_SUFFIX, BackupVault, BackupVaultError

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class BackupSchedulerStatus:
    running: bool = False
    last_check: str | None = None
    last_success: str | None = None
    last_error: str | None = None
    last_backup_id: str | None = None
    last_destination: str | None = None
    pruned_backup_ids: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class BackupScheduler:
    def __init__(
        self,
        root: Path,
        *,
        vault: BackupVault | None = None,
        policy_store: BackupPolicyStore | None = None,
        poll_seconds: float = 60.0,
    ) -> None:
        self.root = Path(root)
        self.vault = vault or BackupVault(self.root)
        self.policy_store = policy_store or BackupPolicyStore(self.root)
        self.poll_seconds = max(float(poll_seconds), 1.0)
        self.status = BackupSchedulerStatus()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._run_lock = asyncio.Lock()

    def install(self, app: web.Application) -> None:
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.stop)

    async def start(self, _app: web.Application) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self.status.running = True
        self._task = asyncio.create_task(self._loop(), name="monitorbox-backup-scheduler")

    async def stop(self, _app: web.Application) -> None:
        self.status.running = False
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    await self.run_due()
                except Exception as exc:
                    self.status.last_error = f"{type(exc).__name__}: scheduled backup failed"
                    LOG.error(
                        "scheduled backup iteration failed exception_type=%s",
                        type(exc).__name__,
                    )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    def _is_due(self, policy: BackupPolicy, now: datetime) -> bool:
        scheduled = [item for item in self.vault.list() if item.kind == "scheduled"]
        if not scheduled:
            return True
        try:
            latest = _parse_timestamp(scheduled[0].created_at)
        except ValueError:
            return True
        return now >= latest + timedelta(hours=policy.interval_hours)

    @staticmethod
    def _destination(policy: BackupPolicy):
        if policy.destination_type is None:
            return None
        if policy.destination_type == "filesystem":
            return FilesystemBackupDestination(Path(str(policy.destination_path)))
        raise BackupPolicyError("unsupported backup destination type")

    async def run_due(self, *, force: bool = False) -> dict[str, Any]:
        async with self._run_lock:
            checked = _now()
            self.status.last_check = checked.isoformat()
            try:
                policy = await asyncio.to_thread(self.policy_store.load)
                if not force and not policy.enabled:
                    self.status.last_error = None
                    return {
                        "created": False,
                        "reason": "schedule_disabled",
                        "status": self.status.public(),
                    }
                if not force and not await asyncio.to_thread(self._is_due, policy, checked):
                    self.status.last_error = None
                    return {"created": False, "reason": "not_due", "status": self.status.public()}

                label = f"Scheduled {checked.strftime('%Y-%m-%d %H:%M UTC')}"
                record = await asyncio.to_thread(
                    self.vault.create,
                    label=label,
                    kind="scheduled",
                )
                destination_result = None
                destination_error = None
                destination = self._destination(policy)
                if destination is not None:
                    try:
                        source = await asyncio.to_thread(
                            self.vault.archive_path,
                            record.backup_id,
                        )
                        destination_result = await asyncio.to_thread(
                            destination.publish,
                            source,
                            filename=f"{record.backup_id}{ARCHIVE_SUFFIX}",
                        )
                    except BackupDestinationError as exc:
                        destination_error = f"{type(exc).__name__}: destination publication failed"
                        LOG.error(
                            "scheduled backup destination publication failed backup_id=%s exception_type=%s",
                            record.backup_id,
                            type(exc).__name__,
                        )
                pruned = await asyncio.to_thread(
                    self.vault.prune_scheduled,
                    retention_count=policy.retention_count,
                    retention_bytes=policy.retention_bytes,
                )
                self.status.last_success = _now().isoformat()
                self.status.last_error = destination_error
                self.status.last_backup_id = record.backup_id
                self.status.last_destination = (
                    destination_result.locator if destination_result is not None else None
                )
                self.status.pruned_backup_ids = pruned
                LOG.info(
                    "scheduled appliance backup complete backup_id=%s bytes=%d destination=%s pruned=%d",
                    record.backup_id,
                    record.bytes,
                    destination_result.destination_id if destination_result is not None else "vault",
                    len(pruned),
                )
                return {
                    "created": True,
                    "backup": record.public(),
                    "destination": destination_result.public() if destination_result is not None else None,
                    "destination_error": destination_error,
                    "pruned_backup_ids": list(pruned),
                    "status": self.status.public(),
                }
            except (BackupPolicyError, BackupVaultError, OSError) as exc:
                self.status.last_error = f"{type(exc).__name__}: scheduled backup failed"
                LOG.error(
                    "scheduled appliance backup failed exception_type=%s",
                    type(exc).__name__,
                )
                raise
