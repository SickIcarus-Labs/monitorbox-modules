"""Development-only administrator API for v3 native Backup/Restore jobs.

This is deliberately NOT a versioned/signed module, and is NOT installed by
the released build 6. Once packaged, install only via the approved signed
first-party entrypoint. No operator-controlled Supervisor paths, generation
IDs or credentials cross this route.

The normal admin auth and CSRF checks precede *every* requested mutation.
An initial POST only admits a pending job and returns HTTP 202. The background
worker can resume an admitted job when Core starts following quiescence.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from backup_restore_native_jobs import NativeBackupJobError
from backup_restore_native_vault import BackupVaultError
from backup_restore_native_workflow import NativeBackupWorkflow, NativeBackupWorkflowError

LOG = logging.getLogger(__name__)
PREFIX = "/api/v2/config/backup-restore"
PROGRESS_INTERVAL_SECONDS = 5


class NativeBackupOperator:
    def __init__(self, platform: Any, *, workflow: NativeBackupWorkflow | None = None):
        self.platform = platform
        self.workflow = workflow if workflow is not None else NativeBackupWorkflow(platform)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def install(self, app: web.Application) -> None:
        app.router.add_post(PREFIX + "/native/backups", self.begin_manual)
        app.router.add_post(PREFIX + "/native/schedule/run", self.begin_scheduled)
        app.router.add_get(PREFIX + "/native/status", self.status)
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.stop)

    async def start(self, _app: web.Application) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._progress_loop(), name="native-backup-progress")

    async def stop(self, _app: web.Application) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _progress_loop(self) -> None:
        # This loop polls an independently durable job, never its own memory
        # of the initial HTTP request. It re-attaches after Core restarts.
        while True:
            try:
                async with self._lock:
                    current = await asyncio.to_thread(self.workflow.inspect)
                    if current is not None and current.phase in {
                        "requested", "accepted", "transfer_verified",
                    }:
                        await asyncio.to_thread(self.workflow.advance)
            except asyncio.CancelledError:
                raise
            except (NativeBackupJobError, BackupVaultError, NativeBackupWorkflowError) as exc:
                LOG.warning("native backup progress deferred exception_type=%s", type(exc).__name__)
            except Exception as exc:
                LOG.exception("native backup progress encountered error exception_type=%s", type(exc).__name__)
            await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)

    async def _request(self, request: web.Request, *, kind: str) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        try:
            # Explicitly empty body: the administrator cannot select an
            # archive output path, native job ID or signed generation.
            if request.content_length is not None and request.content_length > 2048:
                raise web.HTTPRequestEntityTooLarge(max_size=2048, actual_size=request.content_length)
            raw = await request.read()
            if raw not in (b"", b"{}"):
                raise web.HTTPBadRequest(text="native archive selection is not available in this operation")
            async with self._lock:
                accepted = await asyncio.to_thread(
                    self.workflow.request,
                    kind=kind, include_previous=True,
                )
            LOG.info("native %s backup admitted actor=%s request=%s",kind,session.actor,accepted.request_id)
            return web.json_response({
                "request_id": accepted.request_id,
                "phase": accepted.phase,
                "backup_id": None,
                "committed": False,
                "status_url": PREFIX + "/native/status",
            },status=202,headers={"Cache-Control":"no-store"})
        except (NativeBackupJobError, BackupVaultError) as exc:
            raise web.HTTPConflict(text="native backup request conflicts with pending job") from exc
        except NativeBackupWorkflowError as exc:
            # When request intent survived a Core restart/crash, a status GET
            # can show it. Do not report success from an ambiguous begin.
            raise web.HTTPServiceUnavailable(text="native backup accepted state requires recovery") from exc

    async def begin_manual(self, request: web.Request) -> web.Response:
        return await self._request(request,kind="manual")

    async def begin_scheduled(self, request: web.Request) -> web.Response:
        return await self._request(request,kind="scheduled")

    async def status(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        item = await asyncio.to_thread(self.workflow.inspect)
        status = {
            "active": item is not None and item.phase not in {"committed","failed"},
            "job": None,
        }
        if item is not None:
            # The private journal's whitelist has no provider material, paths,
            # signed tokens or passwords. Do not expose raw module objects.
            status["job"] = item.public()
        return web.json_response(status,headers={"Cache-Control":"no-store"})
