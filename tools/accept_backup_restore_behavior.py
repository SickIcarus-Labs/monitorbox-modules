#!/usr/bin/env python3
"""Exercise managed Backup / Restore build 2 without the bundled factory module."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
PACKAGE = f"{MODULE_ID}-1.0.1-build2.zip"
API = "/api/v2/config/backup-restore"


class FakeApplianceBackupError(ValueError):
    pass


class FakeApplianceBackupManager:
    """Minimal stand-in for the provider-blind Core archive primitive."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def create(self, output: Path):
        output = Path(output)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"format": "monitorbox-appliance-backup"}))
            archive.writestr("root/config.yaml", "schema: 1\n")
        return self.inspect(output)

    def inspect(self, archive_path: Path):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if "manifest.json" not in archive.namelist():
                    raise FakeApplianceBackupError("missing manifest")
                total = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile as exc:
            raise FakeApplianceBackupError("invalid ZIP") from exc
        return SimpleNamespace(
            manifest={
                "format": "monitorbox-appliance-backup",
                "version": 1,
                "core": {"version": "2.3.0", "build": "0565"},
                "installation_id": "managed-module-acceptance",
                "canonical_revision": 7,
                "installation_fingerprint": "sha256:" + "0" * 64,
            },
            file_count=2,
            total_bytes=total,
        )


def _install_core_stub() -> None:
    monitorbox = types.ModuleType("monitorbox")
    monitorbox.__path__ = []
    v2 = types.ModuleType("monitorbox.v2")
    v2.__path__ = []
    appliance = types.ModuleType("monitorbox.v2.appliance_backup")
    appliance.ApplianceBackupError = FakeApplianceBackupError
    appliance.ApplianceBackupManager = FakeApplianceBackupManager
    monitorbox.v2 = v2
    v2.appliance_backup = appliance
    sys.modules["monitorbox"] = monitorbox
    sys.modules["monitorbox.v2"] = v2
    sys.modules["monitorbox.v2.appliance_backup"] = appliance


class FakeAuth:
    def require(self, _request: web.Request, *, csrf: bool = False):
        return SimpleNamespace(actor="admin", csrf=csrf)


async def _exercise(root: Path, package_path: Path) -> None:
    _install_core_stub()
    sys.path.insert(0, str(package_path))
    try:
        module = importlib.import_module("monitorbox_backup_restore_b2")
        assert module.MODULE_ID == MODULE_ID
        assert module.MODULE_VERSION == "1.0.1"
        assert module.MODULE_BUILD == 2

        app = web.Application()
        platform = SimpleNamespace(root=root, auth=FakeAuth())
        module.install(app, platform=platform)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            page = await client.get("/backup-restore")
            assert page.status == 200
            text = await page.text()
            assert "Admin authenticated" in text
            assert 'accept=".zip,application/zip"' in text
            assert ".mbbackup" not in text
            assert API in text

            legacy = await client.get("/api/v2/backup-restore/backups")
            assert legacy.status == 404

            created = await client.post(f"{API}/backups", json={"label": "Managed ZIP"})
            assert created.status == 201
            record = await created.json()
            backup_id = record["backup_id"]
            assert record["kind"] == "manual"
            assert (root / "saved-backups" / f"{backup_id}.zip").is_file()

            downloaded = await client.get(f"{API}/backups/{backup_id}/download")
            assert downloaded.status == 200
            assert downloaded.headers["Content-Type"].startswith("application/zip")
            assert downloaded.headers["Content-Disposition"] == (
                f'attachment; filename="{backup_id}.zip"'
            )
            exported = await downloaded.read()

            imported = await client.post(
                f"{API}/import?label=Round%20trip",
                data=exported,
                headers={"Content-Type": "application/zip"},
            )
            assert imported.status == 201
            imported_record = await imported.json()
            assert imported_record["kind"] == "imported"
            assert (root / "saved-backups" / f"{imported_record['backup_id']}.zip").is_file()

            policy = await client.get(f"{API}/policy")
            assert policy.status == 200
            payload = await policy.json()
            assert payload["cloud_support"] is False
            assert payload["supported_destinations"] == ["filesystem"]

            scheduled = await client.post(f"{API}/schedule/run")
            assert scheduled.status == 200
            scheduled_payload = await scheduled.json()
            assert scheduled_payload["created"] is True
            scheduled_id = scheduled_payload["backup"]["backup_id"]
            assert (root / "saved-backups" / f"{scheduled_id}.zip").is_file()
        finally:
            await client.close()
    finally:
        sys.path.remove(str(package_path))


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    package_path = root / "packages" / PACKAGE
    if not package_path.is_file():
        raise SystemExit(f"build package first: {package_path}")
    with tempfile.TemporaryDirectory(prefix="backup-restore-managed-") as raw:
        asyncio.run(_exercise(Path(raw), package_path))
    print("Backup / Restore 1.0.1 build 2 managed behavior acceptance passed")


if __name__ == "__main__":
    main()
