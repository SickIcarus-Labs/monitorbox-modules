"""Successor first-party application module requalification tests."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_successor_first_party_modules as subject
import native_json_backup_vault as json_vault
from portable_contracts import parse_json, verify_embedded_contract


class SuccessorFirstPartyModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = subject._parse_authority()

    def test_exact_ten_module_authority_and_core3_runtime_contract(self) -> None:
        self.assertEqual(subject.FIRST_PARTY_IDS, frozenset(self.records))
        for artifact_id, record in self.records.items():
            runtime = record["module_runtime"]
            self.assertEqual(artifact_id, runtime["module_id"])
            self.assertEqual(record["version"], runtime["version"])
            self.assertEqual(record["build"], runtime["build"])
            self.assertEqual(">=3.0.0 <4.0.0", runtime["requires_core"])
            self.assertEqual(">=1 <2", runtime["requires_runtime_api"])
            self.assertEqual(
                subject._expected_platform_dependencies(artifact_id),
                record["platform"]["dependencies"],
            )

    def test_native_json_backup_restore_has_new_independent_module_version(self) -> None:
        backup = self.records[subject.BACKUP_RESTORE_ID]
        self.assertEqual("1.0.7", backup["version"])
        self.assertEqual(9, backup["build"])
        self.assertEqual(9, backup["module_runtime"]["build"])

    def test_native_json_restore_copy_is_concise_without_changing_reset_behavior(self) -> None:
        assets = subject.ROOT / "tools" / "ui-assets" / "backup-restore"
        html = (assets / "backup-restore.html").read_text("utf-8")
        js = (assets / "backup-restore.js").read_text("utf-8")
        self.assertIn('id="restoreButton"', html)
        self.assertIn('>Restore configuration</button>', html)
        self.assertNotIn("Restore configuration (clear history)", html)
        self.assertNotIn("Restore discards historical telemetry", html)
        self.assertIn(
            "Replace this appliance's configuration with the selected JSON?", js
        )
        self.assertNotIn("DISCARD historical telemetry", js)
        self.assertNotIn("clears telemetry history", js)
        # This is strictly a copy change. Restore still replaces settings
        # and directs Supervisor to reset historical observations.
        self.assertIn("reset_history: true", js)

    def test_json_restore_defaults_to_saved_channel_instead_of_stable(self) -> None:
        # A signed Dev/Beta JSON backup must remain on its saved channel
        # unless the operator explicitly selects a different release channel.
        js = (subject.ROOT / "tools" / "ui-assets" / "backup-restore"
              / "backup-restore.js").read_text("utf-8")
        self.assertIn('channel.replaceChildren(new Option("Stable (default)", "stable"))', js)
        self.assertIn('if (saved === "beta" || saved === "dev")', js)
        self.assertIn(
            'channel.add(new Option("Use saved " + saved.toUpperCase() '
            '+ " channel", saved, true, true))',
            js,
        )
        self.assertIn('channel: el("channel").value, reset_history: true', js)

    def test_native_json_backup_module_never_starts_zip_scheduler_or_routes(self) -> None:
        backup = self.records[subject.BACKUP_RESTORE_ID]
        with tempfile.TemporaryDirectory(prefix="successor-native-json-br-") as folder:
            built = subject.build_package(backup, Path(folder), release_eligible=False)
            with zipfile.ZipFile(built) as archive:
                source = archive.read(subject.BACKUP_RESTORE_ENTRYPOINT_MEMBER).decode("utf-8")
                self.assertIn('if (platform.root / "portable").is_dir():', source)
                self.assertIn('raise web.HTTPFound(location="/settings/restore-json")', source)
                self.assertIn('app.router.add_get("/backup-restore", native_json_page)', source)
                self.assertIn('native_saved_create', source)
                self.assertIn('platform.portable_json(request)', source)
                self.assertIn('csrf=True', source)
                self.assertIn('/api/v2/config/backup-restore/json/saved', source)
                self.assertIn('native_schedule_save', source)
                self.assertIn('native_schedule_run', source)
                self.assertIn('JsonBackupScheduler(platform, vault)', source)
                runtime = archive.read("monitorbox_backup_restore_b9_json.py")
                self.assertEqual(runtime, (subject.ROOT / "tools" / "native_json_backup_vault.py").read_bytes())
                before = source.index('if (platform.root / "portable").is_dir():')
                native_return = source.index('        return\n', before)
                legacy = source.index('    management = BackupRestoreManagement(platform)', before)
                self.assertLess(before, native_return)
                self.assertLess(native_return, legacy)
                self.assertNotIn("_install_admin_routes(", source[before:native_return])
                self.assertNotIn("management.scheduler.install(", source[before:native_return])
                self.assertIn("_install_admin_routes(app, application, management)", source[legacy:])


    def test_json_vault_retains_exact_verified_payload_and_private_modes(self) -> None:
        import stat
        data = {
            "schemaVersion": "monitorbox.portable/v1",
            "modules": [{"id": "com.sickicarus.monitorbox.backup-restore"}],
            "credentials": {"provider": {"value": "secret-must-not-be-logged"}},
        }
        payload = (json.dumps(data, indent=2) + "\n").encode()
        filename = "monitorbox-config_3.0.0_20261012-210201.json"
        with tempfile.TemporaryDirectory(prefix="mb-json-vault-") as directory:
            vault = json_vault.JsonBackupVault(Path(directory))
            self.assertEqual([], vault.list())
            record = vault.create(payload, filename)
            saved, content = vault.read(record["id"])
            self.assertEqual(payload, content)
            self.assertEqual(filename, saved["filename"])
            self.assertEqual("manual", saved["kind"])
            self.assertEqual([record], vault.list())
            vault_path = Path(directory) / "backups" / "portable-json"
            self.assertEqual(0o700, stat.S_IMODE(vault_path.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE((vault_path / (record["id"] + ".json")).stat().st_mode))
            self.assertNotIn("secret-must-not-be-logged", json.dumps(record))
            vault.delete(record["id"])
            self.assertEqual([], vault.list())
            with self.assertRaises(json_vault.JsonBackupError):
                vault.read(record["id"])

    def test_json_vault_ignores_orphan_and_rejects_tamper_and_traversal(self) -> None:
        payload = b'{"schemaVersion":"monitorbox.portable/v1","modules":[],"credentials":{"x":{"value":"s"}}}'
        filename = "monitorbox-config_3.0.0_20261012-210201.json"
        with tempfile.TemporaryDirectory(prefix="mb-json-integrity-") as directory:
            vault = json_vault.JsonBackupVault(Path(directory))
            for invalid in ("../secret", "a", "20261012T210201000000Z-abcdef1234567890/../foo"):
                with self.assertRaises(json_vault.JsonBackupError):
                    vault.read(invalid)
            with self.assertRaises(json_vault.JsonBackupError):
                vault.create(payload, filename + "+0000")
            with self.assertRaises(json_vault.JsonBackupError):
                vault.create(payload.replace(b'"credentials"', b'"adminIdentity"'), filename)
            first = vault.create(payload, filename)
            store = Path(directory) / "backups" / "portable-json"
            data = store / (first["id"] + ".json")
            data.write_bytes(payload + b" ")
            self.assertEqual([], vault.list())
            with self.assertRaises(json_vault.JsonBackupError):
                vault.read(first["id"])
            data.write_bytes(payload)
            self.assertEqual([first], vault.list())
            orphan = store / "20261012T210201000000Z-abcdef1234567890.json"
            orphan.write_bytes(payload)
            self.assertEqual([first], vault.list())


    def test_json_scheduler_policy_validation_and_daily_retention(self) -> None:
        import asyncio
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        policy = {"enabled": True, "time": "02:00", "retention_count": 1, "destination_path": ""}
        doc = {
            "schemaVersion": "monitorbox.portable/v1",
            "modules": [{"id": json_vault.MODULE_ID, "settings": {"jsonBackups": policy}}],
            "credentials": {"provider": {"value": "private"}},
        }
        class Export:
            def __init__(self):
                self.body = (json.dumps(doc) + "\n").encode()
                self.headers = {"Content-Disposition": 'attachment; filename="monitorbox-config_3.0.0_20261012-030000.json"'}
        class Platform:
            def export_verified_portable_json(self):
                return Export()
        with tempfile.TemporaryDirectory(prefix="mb-json-schedule-") as path:
            vault = json_vault.JsonBackupVault(Path(path))
            scheduler = json_vault.JsonBackupScheduler(Platform(), vault)
            tz = ZoneInfo("America/Chicago")
            with patch.object(json_vault, "appliance_now", return_value=datetime(2026, 10, 12, 3, 1, tzinfo=tz)):
                first = asyncio.run(scheduler.run_due())
                self.assertTrue(first["created"])
                self.assertEqual("2026-10-12", first["backup"]["local_day"])
                second = asyncio.run(scheduler.run_due())
                self.assertFalse(second["created"])
                self.assertEqual("already_created_today", second["reason"])
            with patch.object(json_vault, "appliance_now", return_value=datetime(2026, 10, 13, 3, 1, tzinfo=tz)):
                third = asyncio.run(scheduler.run_due())
                self.assertTrue(third["created"])
            records = vault.list()
            self.assertEqual(1, len(records))
            self.assertEqual("2026-10-13", records[0]["local_day"])
        for bad in (
            {"enabled": "true", "time": "02:00", "retention_count": 7, "destination_path": ""},
            {"enabled": True, "time": "25:00", "retention_count": 7, "destination_path": ""},
            {"enabled": True, "time": "02:00", "retention_count": 0, "destination_path": ""},
            {"enabled": True, "time": "02:00", "retention_count": 7, "destination_path": "/tmp", "secret": "x"},
            {"enabled": True, "time": "02:00", "retention_count": 7, "destination_path": "relative"},
            {"enabled": True, "time": "02:00", "retention_count": 7, "destination_path": "/tmp/../tmp"},
        ):
            with self.assertRaises(json_vault.JsonBackupError):
                json_vault.checked_json_policy(bad)

    def test_json_scheduler_run_now_preserves_manual_backups(self) -> None:
        import asyncio
        from datetime import datetime, timezone
        from unittest.mock import patch
        doc = {
            "schemaVersion": "monitorbox.portable/v1",
            "modules": [{"id": json_vault.MODULE_ID, "settings": {}}],
            "credentials": {},
        }
        class Export:
            def __init__(self):
                self.body = json.dumps(doc).encode()
                self.headers = {"Content-Disposition": 'attachment; filename="monitorbox-config_3.0.0_20261012-050100.json"'}
        class Platform:
            def export_verified_portable_json(self):
                return Export()
        with tempfile.TemporaryDirectory(prefix="mb-json-run-now-") as path:
            vault = json_vault.JsonBackupVault(Path(path))
            manual = vault.create(Export().body, "monitorbox-config_3.0.0_20261012-050100.json")
            scheduler = json_vault.JsonBackupScheduler(Platform(), vault)
            with patch.object(json_vault, "appliance_now", return_value=datetime(2026, 10, 12, 5, 1, tzinfo=timezone.utc)):
                self.assertEqual("disabled", asyncio.run(scheduler.run_due())["reason"])
                result = asyncio.run(scheduler.run_due(force=True))
                self.assertTrue(result["created"])
            self.assertEqual(2, len(vault.list()))
            self.assertEqual("manual", vault.read(manual["id"])[0]["kind"])


    def test_json_scheduler_external_copy_does_not_overwrite_and_excludes_appliance_root(self) -> None:
        import asyncio
        from datetime import datetime, timezone
        from unittest.mock import patch
        import stat
        with tempfile.TemporaryDirectory(prefix="mb-json-root-") as root:
            with tempfile.TemporaryDirectory(prefix="mb-json-mounted-") as destination:
                policy = {
                    "enabled": True, "time": "02:00", "retention_count": 2,
                    "destination_path": destination,
                }
                document = {
                    "schemaVersion": "monitorbox.portable/v1",
                    "modules": [{"id": json_vault.MODULE_ID, "settings": {"jsonBackups": policy}}],
                    "credentials": {"provider": {"value": "sensitive"}},
                }
                raw = json.dumps(document).encode()
                filename = "monitorbox-config_3.0.0_20261012-050100.json"
                class Response:
                    body = raw
                    headers = {"Content-Disposition": 'attachment; filename="' + filename + '"'}
                class Platform:
                    def export_verified_portable_json(self):
                        return Response()
                vault = json_vault.JsonBackupVault(Path(root))
                scheduler = json_vault.JsonBackupScheduler(Platform(), vault)
                with patch.object(json_vault, "appliance_now", return_value=datetime(2026, 10, 12, 5, 1, tzinfo=timezone.utc)):
                    result = asyncio.run(scheduler.run_due())
                self.assertTrue(result["created"])
                self.assertIsNone(result["destination_error"])
                copied = Path(destination) / filename
                self.assertEqual(raw, copied.read_bytes())
                self.assertEqual(0o600, stat.S_IMODE(copied.stat().st_mode))
                self.assertEqual(1, len(vault.list()))
                with patch.object(json_vault, "appliance_now", return_value=datetime(2026, 10, 12, 5, 2, tzinfo=timezone.utc)):
                    repeat = asyncio.run(scheduler.run_due(force=True))
                self.assertTrue(repeat["created"])
                self.assertIn("external copy failed", repeat["destination_error"])
                self.assertEqual(raw, copied.read_bytes())
                with self.assertRaises(json_vault.JsonBackupError):
                    scheduler.check_destination(str(Path(root) / "backups"))

    def test_signed_native_json_routes_use_auth_and_core_verified_export(self) -> None:
        """Execute the packaged native route branch, not only string assertions."""
        import asyncio
        import sys
        import types
        from unittest.mock import patch

        backup = self.records[subject.BACKUP_RESTORE_ID]
        with tempfile.TemporaryDirectory(prefix="mb-native-json-route-") as directory:
            package = subject.build_package(backup, Path(directory), release_eligible=False)
            with zipfile.ZipFile(package) as archive:
                source = archive.read(subject.BACKUP_RESTORE_ENTRYPOINT_MEMBER).decode()
            start = source.index('    if (platform.root / "portable").is_dir():')
            end = source.index('    management = BackupRestoreManagement(platform)', start)
            code = "def mount_native(app, platform):\n" + source[start:end]

            class HttpError(Exception):
                def __init__(self, text=None, location=None, **_kw):
                    self.text = text
                    self.location = location

            class Response:
                def __init__(self, body=b"", content_type=None, headers=None,
                             status=200, payload=None):
                    self.body = body
                    self.content_type = content_type
                    self.headers = headers or {}
                    self.status = status
                    self.payload = payload

            class Web:
                Request = object
                HTTPFound = HttpError
                HTTPConflict = HttpError
                HTTPNotFound = HttpError
                HTTPBadRequest = HttpError
                HTTPRequestEntityTooLarge = HttpError
                @staticmethod
                def middleware(fn):
                    return fn
                @staticmethod
                def json_response(data, status=200, headers=None):
                    return Response(status=status, payload=data, headers=headers)

            Web.Response = Response

            class Router:
                def __init__(self):
                    self.routes = {}
                def add_get(self, path, fn):
                    self.routes["GET", path] = fn
                def add_post(self, path, fn):
                    self.routes["POST", path] = fn
                def add_put(self, path, fn):
                    self.routes["PUT", path] = fn
                def add_delete(self, path, fn):
                    self.routes["DELETE", path] = fn

            class App:
                def __init__(self):
                    self.router = Router()
                    self.middlewares = []
                    self.on_startup = []
                    self.on_cleanup = []

            class Request:
                def __init__(self, *, csrf=True, body=b"", backup_id=None):
                    self.csrf = csrf
                    self.match_info = {"backup_id": backup_id}
                    self.content_length = len(body)
                    self._body = body
                async def read(self):
                    return self._body

            class Auth:
                def require(self, request, *, csrf=False):
                    if csrf and not request.csrf:
                        raise HttpError("administrator CSRF required")

            original = {
                "schemaVersion": "monitorbox.portable/v1",
                "modules": [{"id": json_vault.MODULE_ID, "settings": {}}],
                "credentials": {"provider": {"value": "private-signed-credential"}},
            }
            filename = "monitorbox-config_3.0.0_20261012-210000.json"
            class Platform:
                def __init__(self, root):
                    self.root = root
                    self.auth = Auth()
                    self.applied = None
                async def portable_json(self, request):
                    self.auth.require(request)
                    return self.export_verified_portable_json()
                def export_verified_portable_json(self):
                    return Response(
                        body=(json.dumps(original) + "\n").encode(),
                        headers={"Content-Disposition": 'attachment; filename="' + filename + '"'},
                    )
                async def _apply_native_portable(self, doc, *, detail):
                    self.applied = doc
                    return Response(payload={"accepted": True, **detail}, status=202)

            root = Path(directory) / "config"
            (root / "portable").mkdir(parents=True)
            app = App()
            platform = Platform(root)
            ns = {"web": Web}
            with patch.dict(sys.modules, {"monitorbox_backup_restore_b9_json": json_vault}):
                exec(compile(code, "<signed-native-br>", "exec"), ns)
                ns["mount_native"](app, platform)
            base = "/api/v2/config/backup-restore/json"
            routes = app.router.routes
            self.assertIn(("POST", base + "/saved"), routes)
            self.assertIn(("GET", base + "/saved"), routes)
            self.assertIn(("PUT", base + "/policy"), routes)
            self.assertIn(("POST", base + "/run"), routes)
            with self.assertRaises(HttpError):
                asyncio.run(routes["POST", base + "/saved"](Request(csrf=False)))
            created = asyncio.run(routes["POST", base + "/saved"](Request()))
            self.assertEqual(201, created.status)
            entry_id = created.payload["id"]
            self.assertIn(filename, created.payload["filename"])
            listed = asyncio.run(routes["GET", base + "/saved"](Request()))
            self.assertEqual(1, len(listed.payload["backups"]))
            self.assertRegex(listed.payload["backups"][0]["created_local"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            downloaded = asyncio.run(routes["GET", base + "/saved/{backup_id}"](Request(backup_id=entry_id)))
            self.assertIn(b"private-signed-credential", downloaded.body)
            self.assertEqual(0, json.loads(downloaded.body).get("adminIdentity", 0))
            policy = {"enabled": True, "time": "03:00", "retention_count": 3, "destination_path": ""}
            outcome = asyncio.run(routes["PUT", base + "/policy"](
                Request(body=json.dumps(policy).encode())))
            self.assertEqual(202, outcome.status)
            module = next(row for row in platform.applied["modules"] if row["id"] == json_vault.MODULE_ID)
            self.assertEqual(policy, module["settings"]["jsonBackups"])
            deleted = asyncio.run(routes["DELETE", base + "/saved/{backup_id}"](Request(backup_id=entry_id)))
            self.assertEqual(True, deleted.payload["deleted"])
            self.assertEqual([], asyncio.run(routes["GET", base + "/saved"](Request())).payload["backups"])


    def test_successor_ui_advances_for_scaffold_lifecycle_operator_contract(self) -> None:
        ui = self.records[subject.UI_ID]
        self.assertEqual("1.18.6", ui["version"])
        self.assertEqual(64, ui["build"])
        self.assertEqual("1.18.6", ui["module_runtime"]["version"])
        self.assertEqual(64, ui["module_runtime"]["build"])

    def test_scaffold_distribution_copy_does_not_inherit_false_legacy_failure(self) -> None:
        ui = self.records[subject.UI_ID]
        with tempfile.TemporaryDirectory(prefix="ui59-distribution-") as folder:
            built = subject.build_package(ui, Path(folder), release_eligible=False)
            with zipfile.ZipFile(built) as archive:
                name = next(x for x in archive.namelist()
                            if x.endswith(subject.UI_MODULES_MEMBER_SUFFIX))
                source = archive.read(name).decode("utf-8")
        self.assertIn('const distributionReady = scaffoldLifecycle || (catalogRefresh && packageInstall);', source)
        self.assertIn('if (scaffoldLifecycle && !repositoryError) {', source)
        self.assertIn('copy.textContent = "Signed module distribution is available through Supervisor.', source)
        self.assertIn('capabilities.dataset.state = distributionReady && !repositoryError ? "ready" : "limited";', source)
        self.assertIn('const packageInstall = Boolean(current.package_install);', source)

    def test_ui60_serves_versioned_modules_script_from_runtime_adapter(self) -> None:
        ui = self.records[subject.UI_ID]
        with tempfile.TemporaryDirectory(prefix="ui60-cache-contract-") as root:
            pkg = subject.build_package(ui, Path(root), release_eligible=True)
            with zipfile.ZipFile(pkg) as archive:
                adapter = archive.read("monitorbox_ui_b54/__init__.py").decode()
                dashboard = archive.read("monitorbox_ui_b54/assets/dashboard.html").decode()
                js = archive.read("monitorbox_ui_b54/assets/modules.js").decode()
        # These are the URL fragments used by the actual /modules HTTP adapter.
        self.assertIn('"modules.js": "text/javascript"', adapter)
        self.assertIn("?v=1.18.6-64", adapter)
        self.assertNotIn("?v=1.17.1-54", adapter)
        self.assertIn("?v=1.18.6-64", dashboard)
        self.assertNotIn("?v=1.17.1-54", dashboard)
        self.assertIn("const distributionReady = scaffoldLifecycle", js)
        self.assertIn("platform_update_count", js)

    def test_ui_owned_backup_page_preserves_protected_core_json_logic(self) -> None:
        ui = self.records[subject.UI_ID]
        with tempfile.TemporaryDirectory(prefix="ui61-json-page-") as root:
            pkg = subject.build_package(ui, Path(root), release_eligible=True)
            with zipfile.ZipFile(pkg) as archive:
                adapter = archive.read("monitorbox_ui_b54/__init__.py").decode()
                html = archive.read("monitorbox_ui_b54/assets/backup-restore.html").decode()
                css = archive.read("monitorbox_ui_b54/assets/backup-restore.css").decode()
                js = archive.read("monitorbox_ui_b54/assets/backup-restore.js").decode()
        self.assertIn("native_json_backup_restore_ui", adapter)
        self.assertIn('<title>MonitorBox Restore JSON</title>', adapter)
        self.assertIn('"/settings/restore-json"', adapter)
        self.assertIn("response.text = page", adapter)
        self.assertNotIn("start = core_html.find", adapter)
        self.assertIn('app.middlewares.append(native_json_backup_restore_ui)', adapter)
        self.assertIn("1.18.6-64", html)
        self.assertNotIn("1.17.1-54", html)
        self.assertIn("Download configuration JSON", html)
        self.assertIn('id="saveLocalJson"', html)
        self.assertIn('id="savedRecords"', html)
        self.assertIn('id="scheduleTime"', html)
        self.assertIn('id="scheduleRetention"', html)
        self.assertIn('id="scheduleDestination"', html)
        self.assertIn('destination_path: el("scheduleDestination").value.trim()', js)
        self.assertIn('id="runScheduleNow"', html)
        self.assertIn('/api/v2/config/backup-restore/json/saved', js)
        self.assertIn('scheduleApi + "/policy"', js)
        self.assertIn('selectRestoreDocument', js)
        self.assertIn(">Restore configuration</button>", html)
        self.assertNotIn("Restore configuration (clear history)", html)
        self.assertNotIn("Save JSON (retain history)", html)
        self.assertNotIn('id="jsonEditor"', html)
        self.assertIn('id="restoreButton"', html)
        self.assertIn('id="status"', html)
        self.assertIn("/api/v2/config/portable-json", js)
        self.assertNotIn("/api/v2/config/backup-restore/backups", js)  # old ZIP API forbidden
        self.assertIn(".mb-br-page", css)
        self.assertNotIn("application/zip", html + css + js)
        self.assertNotIn("Appliance backups", html)
        node = shutil.which("node")
        if node:
            with tempfile.TemporaryDirectory(prefix="ui64-javascript-") as raw:
                script = Path(raw) / "backup-restore.js"
                script.write_text(js, encoding="utf-8")
                syntax = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
                self.assertEqual(0, syntax.returncode, syntax.stderr)
        self.assertNotIn('id="loadCurrent"', html)
        self.assertNotIn('id="reviewButton"', html)
        self.assertNotIn("<textarea", html)
        self.assertIn("X-MonitorBox-CSRF", js)
        self.assertIn("restore-status", js)

    def test_ui62_normal_page_reuses_shared_dark_document_canvas(self) -> None:
        """Regression: UI61 cards were dark but bare HTML body was white in Safari."""
        ui = self.records[subject.UI_ID]
        with tempfile.TemporaryDirectory(prefix="ui62-canvas-regression-") as root:
            pkg = subject.build_package(ui, Path(root), release_eligible=True)
            with zipfile.ZipFile(pkg) as archive:
                html = archive.read("monitorbox_ui_b54/assets/backup-restore.html").decode()
                css = archive.read("monitorbox_ui_b54/assets/backup-restore.css").decode()

        # Generic MonitorBox app/settings shell CSS paints its own header,
        # not the document. Every independently packaged normal HTML surface
        # must explicitly reset body margins and use the same dark canvas.
        self.assertIn('<body class="mb-br-surface">', html)
        self.assertIn('backup-restore.css?v=1.18.6-64', html)
        self.assertIn('--mb-br-bg:var(--mb-shell-bg,#07111f)', css)
        self.assertIn('--mb-br-text:var(--mb-shell-text,#edf4ff)', css)
        self.assertIn('body.mb-br-surface {', css)
        body_rule = css.split('body.mb-br-surface {', 1)[1].split('}', 1)[0]
        for required in ('margin:0;', 'background:var(--mb-br-bg);',
                         'color:var(--mb-br-text);', 'min-height:100vh;'):
            self.assertIn(required, body_rule)
        self.assertIn('html {', css)
        self.assertIn('width:min(100%,1120px)', css)
        self.assertIn('background:var(--mb-br-panel)', css)
        self.assertNotIn('background:white', css)

    def test_ui_normal_backup_page_delegates_to_core_and_preserves_fallback(self) -> None:
        import asyncio
        import types

        ui = self.records[subject.UI_ID]
        with tempfile.TemporaryDirectory(prefix="ui61-native-render-") as raw:
            pkg = subject.build_package(ui, Path(raw), release_eligible=False)
            with zipfile.ZipFile(pkg) as archive:
                source = archive.read("monitorbox_ui_b54/__init__.py").decode()
                html = archive.read("monitorbox_ui_b54/assets/backup-restore.html").decode()
        start = source.index("@web.middleware" + chr(10) + "async def native_json_backup_restore_ui")
        end = source.index(chr(10) + "def install(app: web.Application) -> None:", start)
        code = source[start:end]

        class Response:
            status = 200
            content_type = "text/html"
            def __init__(self, text):
                self.text = text
                self.headers = {}
            @property
            def body(self):
                return self.text.encode()

        ns = {
            "web": types.SimpleNamespace(
                middleware=lambda fn: fn, Request=object, Response=Response),
            "_resource": lambda path: types.SimpleNamespace(
                read_text=lambda encoding: html if path == "backup-restore.html" else None),
        }
        exec(compile(code, "<ui61-backup-presentation>", "exec"), ns)
        render = ns["native_json_backup_restore_ui"]
        core = ('<title>MonitorBox Restore JSON</title><script>'
                'fetch("/api/v2/config/restore-json");'
                'fetch("/api/v2/config/portable-json");'
                "el('saveButton').onclick=()=>{};"
                '</script>')
        async def serve(request):
            return Response(core)

        native = asyncio.run(render(types.SimpleNamespace(
            path="/settings/restore-json", method="GET"), serve))
        self.assertIn("Download configuration JSON", native.text)
        self.assertIn('id="restoreButton"', native.text)
        self.assertNotIn('id="saveButton"', native.text)
        self.assertNotIn('id="jsonEditor"', native.text)
        self.assertNotIn("el('saveButton').onclick", native.text)
        self.assertNotIn("CORE_JSON_ACTIONS", native.text)
        self.assertEqual("no-store", native.headers["Cache-Control"])

        for path in ("/settings/recovery", "/settings", "/"):
            fallback = asyncio.run(render(types.SimpleNamespace(
                path=path, method="GET"), serve))
            self.assertEqual(core, fallback.text)
        changed = "<title>Unreviewed Core UI</title><script>unknown()</script>"
        async def changed_core(request):
            return Response(changed)
        result = asyncio.run(render(types.SimpleNamespace(
            path="/settings/restore-json", method="GET"), changed_core))
        self.assertEqual(changed, result.text)

    def test_successor_portainer_advances_for_bounded_parallel_inventory(self) -> None:
        portainer = self.records[subject.PORTAINER_ID]
        self.assertEqual(11, portainer["build"])
        self.assertEqual(11, portainer["module_runtime"]["build"])

    def test_scrypted_requires_node24_but_other_modules_do_not(self) -> None:
        scrypted = self.records[subject.SCRYPTED_ID]
        self.assertEqual(10, scrypted["build"])
        self.assertEqual(
            [
                {
                    "artifact_id": subject.CORE_ID,
                    "version_range": ">=3.0.0 <4.0.0",
                },
                {
                    "artifact_id": subject.NODE_RUNTIME_ID,
                    "version_range": ">=24.0.0 <25.0.0",
                },
            ],
            scrypted["platform"]["dependencies"],
        )
        for artifact_id, record in self.records.items():
            if artifact_id == subject.SCRYPTED_ID:
                continue
            self.assertNotIn(
                subject.NODE_RUNTIME_ID,
                {item["artifact_id"] for item in record["platform"]["dependencies"]},
            )

    def test_successor_scrypted_scaffold_ipc_uses_short_private_socket(self) -> None:
        record = self.records[subject.SCRYPTED_ID]
        with tempfile.TemporaryDirectory(prefix="successor-scrypted-ipc-") as raw:
            root = Path(raw)
            package = subject.build_package(
                record, root / "package", release_eligible=False
            )
            with zipfile.ZipFile(package) as archive:
                decoded = archive.read(subject.SCRYPTED_RUNTIME_MEMBER).decode("utf-8")

            start = decoded.index("def resolve_managed_socket(")
            return_line = "    return str(socket_path)\n"
            end = decoded.index(return_line, start) + len(return_line)
            namespace = {
                "Any": object,
                "Path": Path,
                "hashlib": hashlib,
                "os": os,
                "_LEGACY_SOCKET": "/run/monitorbox-scrypted/bridge.sock",
                "_SUCCESSOR_SOCKET_DEFAULT": "/tmp/monitorbox-scrypted/bridge.sock",
                "_UNIX_PATH_MAX_BYTES": 107,
                "_legacy_resolve_managed_socket": lambda requested, state_root: str(requested),
            }
            exec(compile(decoded[start:end], "<successor-scrypted-ipc>", "exec"), namespace)

            state_root = (
                root
                / ("scaffold-live-state-" + "a" * 80)
                / ("generation-slot-" + "b" * 80)
                / "state"
                / "agent"
                / "module-state"
                / subject.SCRYPTED_ID
            )
            legacy = "/run/monitorbox-scrypted/bridge.sock"
            with patch.dict(
                os.environ,
                {"MONITORBOX_ARTIFACT_ID": subject.SCRYPTED_ID},
                clear=False,
            ):
                resolved = namespace["resolve_managed_socket"](legacy, str(state_root))
                defaulted = namespace["resolve_managed_socket"](
                    "/tmp/monitorbox-scrypted/bridge.sock", str(state_root)
                )

            self.assertEqual(resolved, defaulted)
            self.assertTrue(resolved.startswith("/tmp/mb-scrypted-"), resolved)
            self.assertNotIn(str(state_root), resolved)
            self.assertLessEqual(len(os.fsencode(resolved)), 107)
            self.assertEqual(0o700, Path(resolved).parent.stat().st_mode & 0o777)

            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                unix_socket.bind(resolved)
            finally:
                unix_socket.close()
                Path(resolved).unlink(missing_ok=True)

    def test_authority_pins_exact_accepted_predecessor_digests(self) -> None:
        for record in self.records.values():
            path = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            raw = path.read_bytes()
            self.assertEqual(
                record["predecessor"]["sha256"],
                hashlib.sha256(raw).hexdigest(),
                path.name,
            )

    def test_builds_are_deterministic_and_preserve_predecessor_members(self) -> None:
        with tempfile.TemporaryDirectory(prefix="successor-mod-a-") as a_dir, \
             tempfile.TemporaryDirectory(prefix="successor-mod-b-") as b_dir:
            a = Path(a_dir)
            b = Path(b_dir)
            first = subject.build_all(a)
            second = subject.build_all(b)
            self.assertEqual(10, len(first))
            self.assertEqual(
                {path.name for path in first},
                {path.name for path in second},
            )
            for left in first:
                right = b / left.name
                self.assertEqual(left.read_bytes(), right.read_bytes(), left.name)

                artifact_id = next(
                    key for key, record in self.records.items()
                    if left.name == (
                        f"{key}-{record['version']}-build{record['build']}.zip"
                    )
                )
                record = self.records[artifact_id]
                predecessor = (
                    subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
                )
                with zipfile.ZipFile(predecessor, "r") as old, \
                     zipfile.ZipFile(left, "r") as new:
                    old_names = old.namelist()
                    new_names = new.namelist()
                    extra_ui_assets = (
                        [
                            "monitorbox_ui_b54/assets/backup-restore.html",
                            "monitorbox_ui_b54/assets/backup-restore.css",
                            "monitorbox_ui_b54/assets/backup-restore.js",
                        ] if artifact_id == subject.UI_ID else []
                    )
                    self.assertEqual(
                        sorted(old_names + ["package.json", "portable-config.json"]
                               + extra_ui_assets
                               + (["monitorbox_backup_restore_b9_json.py"]
                                  if artifact_id == subject.BACKUP_RESTORE_ID else [])),
                        sorted(new_names),
                    )
                    for name in old_names:
                        if (
                            artifact_id == subject.BACKUP_RESTORE_ID
                            and name == subject.BACKUP_RESTORE_ENTRYPOINT_MEMBER
                        ):
                            self.assertNotEqual(old.read(name), new.read(name))
                            overlay = new.read(name).decode("utf-8")
                            self.assertIn("native_json_recovery", overlay)
                            self.assertIn("native_json_page", overlay)
                            self.assertIn('"/settings/restore-json"', overlay)
                        elif (
                            artifact_id == subject.PORTAINER_ID
                            and name == subject.PORTAINER_RUNTIME_MEMBER
                        ):
                            predecessor_runtime = old.read(name)
                            successor_runtime = new.read(name)
                            self.assertNotEqual(predecessor_runtime, successor_runtime)
                            decoded = successor_runtime.decode("utf-8")
                            self.assertIn("import asyncio", decoded)
                            self.assertIn("aiohttp.ClientTimeout(total=5)", decoded)
                            self.assertIn("await asyncio.gather(", decoded)
                            self.assertIn("return_exceptions=True", decoded)
                            self.assertIn(
                                "for row, container_result in zip(rows, container_results):",
                                decoded,
                            )
                            self.assertNotIn(
                                "timeout = aiohttp.ClientTimeout(total=15)", decoded
                            )
                        elif (
                            artifact_id == subject.SCRYPTED_ID
                            and name == subject.SCRYPTED_RUNTIME_MEMBER
                        ):
                            predecessor_runtime = old.read(name)
                            successor_runtime = new.read(name)
                            self.assertNotEqual(predecessor_runtime, successor_runtime)
                            decoded = successor_runtime.decode("utf-8")
                            self.assertIn("MONITORBOX_MODULE_NODE_LOADER", decoded)
                            self.assertIn("MONITORBOX_MODULE_NODE_LIBRARY_PATH", decoded)
                            self.assertIn("*node_command", decoded)
                            self.assertIn(
                                '_DEFAULT_SOCKET = "/tmp/monitorbox-scrypted/bridge.sock"',
                                decoded,
                            )
                            self.assertIn(
                                "socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)",
                                decoded,
                            )
                            self.assertNotIn(
                                '_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"',
                                decoded,
                            )
                            self.assertIn(
                                'shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))',
                                decoded,
                            )
                            self.assertIn("_UNIX_PATH_MAX_BYTES = 107", decoded)
                            self.assertIn('Path("/tmp") / f"mb-scrypted-{digest}"', decoded)
                            self.assertIn("sun_path storage", decoded)
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith(subject.UI_MODULES_MEMBER_SUFFIX)
                        ):
                            predecessor_ui = old.read(name)
                            successor_ui = new.read(name)
                            self.assertNotEqual(predecessor_ui, successor_ui)
                            decoded = successor_ui.decode("utf-8")
                            self.assertIn("scaffold_lifecycle", decoded)
                            self.assertIn("platform_update_count", decoded)
                            self.assertIn("scaffold_activation_scheduled", decoded)
                            self.assertIn(
                                "Applying compatible signed MonitorBox updates", decoded
                            )
                            self.assertIn(
                                "updateAll.disabled = !authenticated || !csrfToken || !updatePlane",
                                decoded,
                            )
                            self.assertNotIn(
                                "updateAll.disabled = !authenticated || !csrfToken || !packageInstall || updates === 0 || busy;",
                                decoded,
                            )
                            self.assertIn("RELEASE_CHANNEL_API", decoded)
                            self.assertIn("release_channels", decoded)
                            self.assertIn("preferred_channel", decoded)
                            self.assertIn("changeReleaseChannel", decoded)
                            self.assertIn("modules-release-channel", decoded)
                            self.assertIn("Repositories enabled:", decoded)
                            self.assertIn("verifyChannelCommit", decoded)
                            self.assertIn('window.confirm("Switch MonitorBox to "', decoded)
                            self.assertIn("channelAuthority.preferred_channel", decoded)
                            self.assertIn('option.disabled = !allowed.includes(channel)', decoded)
                            self.assertNotIn('capabilities.append(releaseControl)', decoded)
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith("/assets/configuration-peer-navigation.js")
                        ):
                            before = old.read(name).decode("utf-8")
                            after = new.read(name).decode("utf-8")
                            self.assertNotEqual(before, after)
                            self.assertIn("['recovery', 'Backup', '/settings/recovery'],", after)
                            self.assertIn("pathname.startsWith('/settings/restore-json')", after)
                            self.assertNotIn("['recovery', 'Recovery', '/settings/recovery'],", after)
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith("/assets/app-shell.js")
                        ):
                            predecessor_shell = old.read(name)
                            successor_shell = new.read(name)
                            self.assertNotEqual(predecessor_shell, successor_shell)
                            decoded = successor_shell.decode("utf-8")
                            self.assertIn("channelResult", decoded)
                            self.assertIn("release.preferred_channel", decoded)
                            self.assertIn("monitorbox:channel-committed", decoded)
                            self.assertIn("restore-json", decoded)
                            self.assertIn("identity.channel = ''", decoded)
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith("/assets/app-shell.css")
                        ):
                            before = old.read(name).decode("utf-8")
                            after = new.read(name).decode("utf-8")
                            self.assertNotEqual(before, after)
                            self.assertIn("#796: fixed normal application chrome", after)
                            self.assertIn("height:64px; min-height:64px", after)
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith(subject.UI_MODULES_CSS_MEMBER_SUFFIX)
                        ):
                            predecessor_css = old.read(name)
                            successor_css = new.read(name)
                            self.assertNotEqual(predecessor_css, successor_css)
                            decoded = successor_css.decode("utf-8")
                            self.assertIn(".modules-release-channel {", decoded)
                            self.assertIn(".modules-release-channel select {", decoded)
                        elif (
                            artifact_id == subject.UI_ID
                            and name in (
                                "monitorbox_ui_b54/__init__.py",
                                "monitorbox_ui_b54/assets/dashboard.html",
                            )
                        ):
                            before = old.read(name)
                            after = new.read(name)
                            original = b"1.17.1-54"
                            selected = f"{record['version']}-{record['build']}".encode("ascii")
                            count = 12 if name.endswith("/__init__.py") else 8
                            self.assertEqual(count, before.count(original), name)
                            self.assertEqual(count, after.count(selected), name)
                            self.assertNotIn(original, after)
                            expected = before.replace(original, selected)
                            if name.endswith("/__init__.py"):
                                self.assertIn("native_json_backup_restore_ui", after.decode())
                                self.assertIn('app.middlewares.append(native_json_backup_restore_ui)', after.decode())
                                self.assertIn('"backup-restore.js": "text/javascript"', after.decode())
                                self.assertIn('"backup-restore.css": "text/css"', after.decode())
                                self.assertNotEqual(expected, after)
                            else:
                                self.assertEqual(expected, after)
                        elif (
                            artifact_id == subject.UI_ID
                            and b"1.17.1-54" in old.read(name)
                        ):
                            expected = old.read(name).replace(
                                b"1.17.1-54", f"{record['version']}-{record['build']}".encode()
                            )
                            self.assertEqual(expected, new.read(name), name)
                        else:
                            self.assertEqual(old.read(name), new.read(name), name)

                    manifest = json.loads(new.read("package.json"))
                    self.assertFalse(manifest["release_eligible"])
                    self.assertEqual(
                        "successor-module-requalification",
                        manifest["packaging_stage"],
                    )
                    self.assertEqual(artifact_id, manifest["artifact_id"])
                    self.assertEqual(record["version"], manifest["version"])
                    self.assertEqual(record["build"], manifest["build"])
                    self.assertEqual(record["module_runtime"], manifest["module_runtime"])
                    self.assertEqual(
                        record["predecessor"]["sha256"],
                        manifest["provenance"]["predecessor_sha256"],
                    )

                    portable = new.read("portable-config.json")
                    capability = verify_embedded_contract(
                        portable,
                        artifact_id=artifact_id,
                        version=record["version"],
                        build=record["build"],
                    )
                    self.assertEqual(1, capability["protocol"])

    def test_release_eligible_override_changes_only_manifest_gate(self) -> None:
        artifact_id = "com.sickicarus.monitorbox.wol"
        record = self.records[artifact_id]
        with tempfile.TemporaryDirectory(prefix="successor-eligible-") as directory:
            target = subject.build_package(
                record, Path(directory), release_eligible=True
            )
            with zipfile.ZipFile(target, "r") as archive:
                manifest = json.loads(archive.read("package.json"))
                self.assertTrue(manifest["release_eligible"])
                self.assertEqual(
                    record["predecessor"]["sha256"],
                    manifest["provenance"]["predecessor_sha256"],
                )
                portable = parse_json(archive.read("portable-config.json"))
                self.assertEqual(record["build"], portable["build"])

    def test_tampered_predecessor_is_rejected_before_output(self) -> None:
        record = self.records["com.sickicarus.monitorbox.wol"]
        with tempfile.TemporaryDirectory(prefix="successor-tamper-") as root, \
             tempfile.TemporaryDirectory(prefix="successor-output-") as out:
            fake_root = Path(root)
            source = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            (fake_root / source.name).write_bytes(source.read_bytes() + b"tamper")
            with patch.object(subject, "PREDECESSOR_ROOT", fake_root):
                with self.assertRaisesRegex(subject.SuccessorModuleError, "digest"):
                    subject.build_package(
                        record, Path(out), release_eligible=False
                    )
            self.assertEqual([], list(Path(out).iterdir()))

    def test_predecessor_with_existing_successor_metadata_is_rejected(self) -> None:
        record = self.records["com.sickicarus.monitorbox.wol"]
        with tempfile.TemporaryDirectory(prefix="successor-meta-") as root:
            fake_root = Path(root)
            source = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            with zipfile.ZipFile(source, "r") as old:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as new:
                    for item in old.infolist():
                        new.writestr(item.filename, old.read(item))
                    new.writestr("package.json", "{}")
            payload = buffer.getvalue()
            fake = fake_root / source.name
            fake.write_bytes(payload)
            altered = json.loads(json.dumps(record))
            altered["predecessor"]["sha256"] = hashlib.sha256(payload).hexdigest()
            with patch.object(subject, "PREDECESSOR_ROOT", fake_root):
                with self.assertRaisesRegex(subject.SuccessorModuleError, "unsafe predecessor"):
                    subject._predecessor_members(altered)


if __name__ == "__main__":
    unittest.main()
