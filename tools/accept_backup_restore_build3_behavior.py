#!/usr/bin/env python3
"""Exercise managed Backup / Restore 1.0.2 build 3 restore behavior.

The package runs without the bundled factory module. Core is represented only by
its provider-blind appliance archive and quiesced restore-handoff contracts.
"""

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
PACKAGE = f"{MODULE_ID}-1.0.2-build3.zip"
API = "/api/v2/config/backup-restore"


class FakeApplianceBackupError(ValueError):
    pass


class FakeApplianceBackupManager:
    """Minimal stand-in for Core's provider-blind exact archive primitive."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def create(self, output: Path):
        output = Path(output)
        manifest = {
            "format": "monitorbox-appliance-backup",
            "version": 1,
            "core": {"version": "2.3.1", "build": "0566"},
            "installation_id": "managed-build3-acceptance",
            "canonical_revision": 8,
            "canonical_hash": "sha256:" + "1" * 64,
            "installation_fingerprint": "sha256:" + "2" * 64,
            "files": {"config.yaml": {"type": "file", "size": 10, "sha256": "3" * 64}},
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("root/config.yaml", "schema: 1\n")
        return self.inspect(output)

    def inspect(self, archive_path: Path):
        archive_path = Path(archive_path)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if "manifest.json" not in archive.namelist():
                    raise FakeApplianceBackupError("missing manifest")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != "monitorbox-appliance-backup":
                    raise FakeApplianceBackupError("unsupported appliance backup format")
                total = sum(info.file_size for info in archive.infolist())
        except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise FakeApplianceBackupError("invalid appliance backup ZIP") from exc
        return SimpleNamespace(
            manifest=manifest,
            file_count=1,
            total_bytes=total,
        )


class FakeHandoffStatus:
    def __init__(self, request_id: str, *, phase: str = "pending") -> None:
        self.request_id = request_id
        self.phase = phase
        self.archive_sha256 = "4" * 64
        self.installation_fingerprint = "sha256:" + "2" * 64
        self.canonical_revision = 8
        self.core_version = "2.3.1"
        self.core_build = "0566"

    def public(self):
        return {
            "request_id": self.request_id,
            "phase": self.phase,
            "archive_sha256": self.archive_sha256,
            "installation_fingerprint": self.installation_fingerprint,
            "canonical_revision": self.canonical_revision,
            "core_version": self.core_version,
            "core_build": self.core_build,
        }


class FakeApplianceRestoreHandoff:
    """Stand-in for Core's durable, provider-blind restore handoff."""

    prepared: list[dict] = []
    current: FakeHandoffStatus | None = None

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def prepare(self, archive: Path):
        archive = Path(archive)
        inspection = FakeApplianceBackupManager(self.root).inspect(archive)
        request_id = f"request-{len(type(self).prepared) + 1}"
        status = FakeHandoffStatus(request_id)
        type(self).prepared.append(
            {
                "path": archive,
                "bytes": archive.read_bytes(),
                "manifest": inspection.manifest,
                "status": status,
            }
        )
        type(self).current = status
        return status

    def pending(self):
        return type(self).current

    def last_result(self):
        return None


class FakeAuth:
    def require(self, _request: web.Request, *, csrf: bool = False):
        return SimpleNamespace(actor="admin", csrf=csrf)


def _install_core_stubs() -> None:
    monitorbox = types.ModuleType("monitorbox")
    monitorbox.__path__ = []
    v2 = types.ModuleType("monitorbox.v2")
    v2.__path__ = []
    appliance = types.ModuleType("monitorbox.v2.appliance_backup")
    appliance.ApplianceBackupError = FakeApplianceBackupError
    appliance.ApplianceBackupManager = FakeApplianceBackupManager
    handoff = types.ModuleType("monitorbox.v2.appliance_restore_handoff")
    handoff.ApplianceRestoreHandoff = FakeApplianceRestoreHandoff
    monitorbox.v2 = v2
    v2.appliance_backup = appliance
    v2.appliance_restore_handoff = handoff
    sys.modules["monitorbox"] = monitorbox
    sys.modules["monitorbox.v2"] = v2
    sys.modules["monitorbox.v2.appliance_backup"] = appliance
    sys.modules["monitorbox.v2.appliance_restore_handoff"] = handoff


async def _exercise(root: Path, package_path: Path) -> None:
    _install_core_stubs()
    FakeApplianceRestoreHandoff.prepared.clear()
    FakeApplianceRestoreHandoff.current = None
    sys.path.insert(0, str(package_path))
    restarts: list[bool] = []
    try:
        module = importlib.import_module("monitorbox_backup_restore_b3")
        assert module.MODULE_ID == MODULE_ID
        assert module.MODULE_VERSION == "1.0.2"
        assert module.MODULE_BUILD == 3

        app = web.Application()
        platform = SimpleNamespace(
            root=root,
            auth=FakeAuth(),
            request_restart=lambda: restarts.append(True),
        )
        module.install(app, platform=platform)

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            page = await client.get("/backup-restore")
            assert page.status == 200
            text = await page.text()
            assert "Restore from file" in text
            assert "Restore &amp; restart" in text
            assert "/restore/file/preview" in text
            assert "/restore/confirm" in text
            assert "/import" not in text
            assert 'id="import"' not in text
            assert "Imported backup" not in text

            removed_import = await client.post(
                f"{API}/import",
                data=b"not-used",
                headers={"Content-Type": "application/zip"},
            )
            assert removed_import.status == 404

            created = await client.post(f"{API}/backups", json={"label": "Restore source"})
            assert created.status == 201, await created.text()
            record = await created.json()
            backup_id = record["backup_id"]
            assert record["kind"] == "manual"
            vault_archive = root / "saved-backups" / f"{backup_id}.zip"
            assert vault_archive.is_file()

            exported = vault_archive.read_bytes()
            before = await client.get(f"{API}/backups")
            assert len((await before.json())["backups"]) == 1

            file_preview = await client.post(
                f"{API}/restore/file/preview",
                data=exported,
                headers={
                    "Content-Type": "application/zip",
                    "X-MonitorBox-Filename": "external-backup.zip",
                },
            )
            assert file_preview.status == 201, await file_preview.text()
            file_candidate = await file_preview.json()
            assert file_candidate["source_label"] == "external-backup.zip"
            assert file_candidate["canonical_revision"] == 8
            assert file_candidate["installation_fingerprint"] == "sha256:" + "2" * 64

            still_one = await client.get(f"{API}/backups")
            assert len((await still_one.json())["backups"]) == 1, (
                "restore-from-file must never insert the uploaded archive into the saved vault"
            )

            missing_ack = await client.post(
                f"{API}/restore/confirm",
                json={"restore_token": file_candidate["restore_token"]},
            )
            assert missing_ack.status == 400

            confirm_file = await client.post(
                f"{API}/restore/confirm",
                json={
                    "restore_token": file_candidate["restore_token"],
                    "acknowledgement": "restore",
                },
            )
            assert confirm_file.status == 202, await confirm_file.text()
            file_handoff = FakeApplianceRestoreHandoff.prepared[-1]
            assert file_handoff["bytes"] == exported
            assert not file_handoff["path"].exists(), (
                "transient restore upload must be deleted after Core takes durable ownership"
            )

            vault_preview = await client.post(f"{API}/backups/{backup_id}/restore/preview")
            assert vault_preview.status == 200, await vault_preview.text()
            vault_candidate = await vault_preview.json()
            assert vault_candidate["source_label"] == "Restore source"
            confirm_vault = await client.post(
                f"{API}/restore/confirm",
                json={
                    "restore_token": vault_candidate["restore_token"],
                    "acknowledgement": "restore",
                },
            )
            assert confirm_vault.status == 202, await confirm_vault.text()
            vault_handoff = FakeApplianceRestoreHandoff.prepared[-1]
            assert vault_handoff["bytes"] == exported
            assert vault_handoff["path"] == vault_archive
            assert vault_archive.is_file(), "vault restore must not consume the saved backup"

            status = await client.get(f"{API}/restore/status")
            assert status.status == 200
            status_payload = await status.json()
            assert status_payload["pending"]["request_id"] == vault_handoff["status"].request_id

            after = await client.get(f"{API}/backups")
            backups = (await after.json())["backups"]
            assert len(backups) == 1
            assert all(item["kind"] != "imported" for item in backups)

            await asyncio.sleep(0.65)
            assert restarts == [True, True]
        finally:
            await client.close()
    finally:
        sys.path.remove(str(package_path))


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    package_path = root / "packages" / PACKAGE
    if not package_path.is_file():
        raise SystemExit(f"build package first: {package_path}")
    with tempfile.TemporaryDirectory(prefix="backup-restore-build3-") as raw:
        asyncio.run(_exercise(Path(raw), package_path))
    print("Backup / Restore 1.0.2 build 3 restore behavior acceptance passed")


if __name__ == "__main__":
    main()
