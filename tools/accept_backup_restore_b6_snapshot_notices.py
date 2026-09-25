#!/usr/bin/env python3
"""#88 unsigned b6 exact-parent package and actual browser restore warnings."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
import build_first_party_backup_restore_b6 as builder

ROOT = Path(__file__).resolve().parent.parent
MODULE = "com.sickicarus.monitorbox.backup-restore"


def _page(source: str) -> str:
    tree = ast.parse(source)
    values = [
        node.value for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name) and target.id == "_PAGE"
    ]
    assert len(values) == 1
    return ast.literal_eval(values[0])


def package_contract() -> str:
    original = builder.PREDECESSOR.read_bytes()
    with tempfile.TemporaryDirectory(prefix="mb-br-b6-") as temp:
        root = Path(temp)
        first = builder.build(root / "a").read_bytes()
        second = builder.build(root / "b").read_bytes()
        assert first == second, "candidate archive is not reproducible"
    assert builder.PREDECESSOR.read_bytes() == original, "signed b5 was modified"
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = set(archive.namelist())
        assert names == {name.replace(builder.SOURCE_PREFIX, builder.TARGET_PREFIX)
                         for name in builder.EXPECTED}
        entry = archive.read("monitorbox_backup_restore_b6.py").decode()
        application = archive.read("monitorbox_backup_restore_b6_application.py").decode()
        for name in names:
            assert "monitorbox_backup_restore_b5" not in archive.read(name).decode(), name
        assert 'MODULE_VERSION = "1.0.5"' in entry
        assert "MODULE_BUILD = 6" in entry
        assert "MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION != 2" in entry
        assert entry.index("MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION != 2") < entry.index(
            "management = BackupRestoreManagement(platform)"
        )
        assert "/api/v2/config/revisions/" in application
        assert "/api/v2/config/recovery/restore" in application
        page = _page(application)
        assert 'role="alert"' in page and 'aria-live="assertive"' in page
        assert page.count("showPreferenceNotice(data)") >= 3
        assert "restoreSavedNotice()" in page
        assert "Retained configuration revisions capture canonical monitoring" in page
    print(
        "B/R b6 immutable-parent/package: PASS sha256=" +
        hashlib.sha256(first).hexdigest()
    )
    return page


def browser_contract(html: str) -> None:
    from playwright.sync_api import expect

    prelayout = ("This pre-layout snapshot contained no UI preferences; "
                 "current dashboard layout was retained.")
    other = ("This older snapshot lacked preferences for com.example.weather; "
             "their current settings were retained.")
    payload = {"notice": prelayout}

    def respond(route):
        req = route.request
        path = urlparse(req.url).path
        if path == "/backup-restore":
            return route.fulfill(status=200, body=html, content_type="text/html")
        if path == "/api/v2/config/status":
            data = {"authenticated": True}
        elif path == "/api/v2/config/session":
            data = {"csrf_token": "synthetic-csrf"}
        elif path == "/api/v2/config/backup-restore/backups":
            data = {"backups": []}
        elif path == "/api/v2/config/doctor":
            data = {"status": "healthy", "errors": 0, "warnings": 0}
        elif path == "/api/v2/config/revisions":
            data = {"revisions": [{
                "revision": 1, "valid": True,
                "name": "00000001-0123456789abcdef.yaml",
                "content_hash": "0123456789abcdef",
            }]}
        elif path == "/api/v2/config/backup-restore/policy":
            data = {"policy": {
                "enabled": False, "interval_hours": 24, "retention_count": 3,
                "retention_bytes": 1073741824, "destination_path": None,
            }}
        elif path == "/api/v2/config/backup-restore/schedule":
            data = {"status": {}}
        elif path == "/api/v2/config/backup-restore/restore/status":
            data = {"last_result": None}
        elif path.startswith("/api/v2/config/revisions/") and path.endswith("/restore"):
            assert req.headers.get("x-monitorbox-csrf") == "synthetic-csrf"
            data = {
                "restored": True, "source_revision": 1, "applied_revision": 9,
                "runtime_generation": "synthetic", "runtime_reconcile": "restart_scheduled",
                "preferences_restored": payload["notice"] is None,
                "preferences_notice": payload["notice"],
            }
        elif path == "/api/v2/config/recovery/restore":
            assert req.headers.get("x-monitorbox-csrf") == "synthetic-csrf"
            data = {
                "restored": True, "source_revision": 1, "applied_revision": 10,
                "preferences_restored": payload["notice"] is None,
                "preferences_notice": payload["notice"],
            }
        else:
            raise AssertionError(f"Unexpected managed B/R request {req.method} {path}")
        route.fulfill(status=200, body=json.dumps(data), content_type="application/json")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 820, "height": 1050})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", respond)
        page.goto("http://monitorbox.test/backup-restore", wait_until="domcontentloaded")
        page.get_by_role("button", name="Restore as new revision").first.wait_for()
        page.get_by_role("button", name="Restore as new revision").first.click()
        page.locator("#confirmRevisionRestore").click()
        expect(page.locator("#preferencesNotice")).to_be_visible()
        expect(page.locator("#preferencesNoticeText")).to_have_text(prelayout)
        assert page.locator("#revisionState").get_attribute("class").endswith("warn")
        # The existing seven-second controller-restart reload must not erase
        # an important historical/pre-layout warning.
        page.wait_for_timeout(7500)
        expect(page.locator("#preferencesNoticeText")).to_have_text(prelayout)

        payload["notice"] = other
        page.locator("#bundle").set_input_files({
            "name": "synthetic.mbx", "mimeType": "application/zip",
            "buffer": b"synthetic",
        })
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#configRestore").click()
        expect(page.locator("#preferencesNoticeText")).to_have_text(other)
        assert "pre-layout" not in page.locator("#preferencesNoticeText").inner_text()

        payload["notice"] = None
        page.get_by_role("button", name="Restore as new revision").first.click()
        page.locator("#confirmRevisionRestore").click()
        expect(page.locator("#preferencesNotice")).to_be_hidden()
        assert not errors, errors
        browser.close()
    print("B/R b6 iPad-sized Chromium retained and bundle warning acceptance: PASS")


if __name__ == "__main__":
    browser_contract(package_contract())
