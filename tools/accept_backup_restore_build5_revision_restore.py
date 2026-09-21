#!/usr/bin/env python3
"""Acceptance for Backup / Restore 1.0.4 build 5 retained-revision restore UX."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "tools" / "build_first_party_backup_restore_b5.py"
TARGET = "com.sickicarus.monitorbox.backup-restore-1.0.4-build5.zip"
APP = "monitorbox_backup_restore_b5_application.py"
ENTRY = "monitorbox_backup_restore_b5.py"


def _page_from_source(source: str) -> str:
    tree = ast.parse(source, filename=APP)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "_PAGE" for target in node.targets):
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise AssertionError("_PAGE is not a string")
                return value
    raise AssertionError("build 5 application does not define _PAGE")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-br-b5-") as raw:
        output = Path(raw)
        subprocess.run(
            [sys.executable, str(BUILDER), "--output-dir", str(output)],
            check=True,
            cwd=ROOT,
        )
        package = output / TARGET
        assert package.is_file(), package

        with zipfile.ZipFile(package, "r") as archive:
            names = set(archive.namelist())
            expected = {
                "monitorbox_backup_restore_b5.py",
                "monitorbox_backup_restore_b5_application.py",
                "monitorbox_backup_restore_b5_destinations.py",
                "monitorbox_backup_restore_b5_management.py",
                "monitorbox_backup_restore_b5_policy.py",
                "monitorbox_backup_restore_b5_scheduler.py",
                "monitorbox_backup_restore_b5_vault.py",
            }
            assert names == expected, (sorted(names), sorted(expected))
            for name in names:
                compile(archive.read(name).decode("utf-8"), name, "exec")
            entry = archive.read(ENTRY).decode("utf-8")
            application = archive.read(APP).decode("utf-8")

        assert 'MODULE_VERSION = "1.0.4"' in entry
        assert "MODULE_BUILD = 5" in entry
        assert "monitorbox_backup_restore_b5_application" in entry

        page = _page_from_source(application)
        assert 'href="/settings"' in page
        assert "<h1>Backup &amp; Restore</h1>" in page
        assert "<h2>Retained revisions</h2>" in page
        assert "Restore as new revision" in page
        assert "Source canonical revision:" in page
        assert "Retained basename:" in page
        assert "committed as a <strong>new</strong> revision" in page
        assert "Existing revision/generation history is not rewound" in page

        # Valid snapshots receive the destructive action; invalid snapshots remain
        # visible for diagnosis but cannot call the restore function.
        assert "row.className='revision'+(item.valid?'':' invalid')" in page
        assert "if(item.valid){const button=document.createElement('button')" in page
        assert "Invalid retained revision" in page
        assert ("$" + "{item.error||'validation failed'}") in page

        # The managed surface must use Core's existing protected retained-revision
        # restore authority, not invent a module-owned mutation endpoint.
        expected_endpoint = (
            "/api/v2/config/revisions/"
            + "$"
            + "{encodeURIComponent(item.name)}/restore"
        )
        assert expected_endpoint in page
        assert "method:'POST'" in page
        assert "X-MonitorBox-CSRF" in page
        assert "data.source_revision" in page
        assert "data.applied_revision" in page
        assert "data.runtime_generation" in page
        assert "data.runtime_reconcile" in page
        assert "setTimeout(()=>location.reload(),7000)" in page

        # Recovery-bundle upload remains a distinct workflow.
        assert "/api/v2/config/recovery/restore" in page
        assert 'id="bundle"' in page
        assert 'id="configRestore"' in page

        # /settings/recovery deliberately remains the complete managed recovery
        # operator surface rather than exposing two nominal pages with different
        # functionality.
        assert 'request.path == "/settings/recovery"' in application

        scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.DOTALL)
        assert len(scripts) == 1
        script = output / "backup-restore-build5.js"
        script.write_text(scripts[0], encoding="utf-8")
        subprocess.run(["node", "--check", str(script)], check=True)

    print(
        "Backup / Restore 1.0.4 build5 #354 acceptance: PASS "
        "(package shape + managed retained-revision action + destructive dialog + "
        "Core authority endpoint + invalid diagnostic-only rows + JS syntax)"
    )


if __name__ == "__main__":
    main()
