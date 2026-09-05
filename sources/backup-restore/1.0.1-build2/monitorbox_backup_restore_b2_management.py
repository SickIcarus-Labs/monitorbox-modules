"""Authenticated policy/scheduler/destination handlers for managed Backup / Restore."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from monitorbox_backup_restore_b2_destinations import (
    BackupDestinationError,
    FilesystemBackupDestination,
)
from monitorbox_backup_restore_b2_policy import BackupPolicy, BackupPolicyError, BackupPolicyStore
from monitorbox_backup_restore_b2_scheduler import BackupScheduler
from monitorbox_backup_restore_b2_vault import ARCHIVE_SUFFIX, BackupVault, BackupVaultError


class BackupRestoreManagement:
    def __init__(self, platform) -> None:
        self.platform = platform
        self.vault = BackupVault(platform.root)
        self.policy_store = BackupPolicyStore(platform.root)
        self.scheduler = BackupScheduler(
            platform.root,
            vault=self.vault,
            policy_store=self.policy_store,
        )

    async def get_policy(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        try:
            policy = await asyncio.to_thread(self.policy_store.load)
        except BackupPolicyError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        return web.json_response(
            {
                "policy": policy.public(),
                "supported_destinations": ["filesystem"],
                "cloud_support": False,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def put_policy(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        payload = await self._json(request)
        raw_policy = payload.get("policy", payload)
        if not isinstance(raw_policy, dict):
            raise web.HTTPBadRequest(text="backup policy must be a JSON object")
        try:
            policy = BackupPolicy.from_mapping(raw_policy)
            await asyncio.to_thread(self.policy_store.save, policy)
        except BackupPolicyError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response(
            {"policy": policy.public()},
            headers={"Cache-Control": "no-store"},
        )

    async def get_schedule(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        return web.json_response(
            {"status": self.scheduler.status.public()},
            headers={"Cache-Control": "no-store"},
        )

    async def run_schedule(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        try:
            result = await self.scheduler.run_due(force=True)
        except (BackupPolicyError, BackupVaultError, BackupDestinationError) as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def publish_destination(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        backup_id = request.match_info["backup_id"]
        try:
            policy = await asyncio.to_thread(self.policy_store.load)
            if policy.destination_type != "filesystem" or not policy.destination_path:
                raise BackupPolicyError("no filesystem backup destination is configured")
            source = await asyncio.to_thread(self.vault.archive_path, backup_id)
            result = await asyncio.to_thread(
                FilesystemBackupDestination(Path(policy.destination_path)).publish,
                source,
                filename=f"{backup_id}{ARCHIVE_SUFFIX}",
            )
        except (BackupPolicyError, BackupVaultError, BackupDestinationError) as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        return web.json_response(result.public(), status=201, headers={"Cache-Control": "no-store"})

    @staticmethod
    async def _json(request: web.Request) -> dict:
        try:
            text = await request.text()
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise web.HTTPBadRequest(text="request body must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        return payload
