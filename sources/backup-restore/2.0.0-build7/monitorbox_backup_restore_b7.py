"""Backup / Restore 2.0.0 build 7 — UNSIGNED v3 candidate.

This candidate intentionally exposes no native restore transaction. Enabling a
v2 restore handoff on successor architecture would be unsafe. Do not publish
or install until campaign #691 restore, admin identity and physical gates pass.
"""
from __future__ import annotations

from monitorbox_backup_restore_b7_application import NativeBackupApplication
from monitorbox_backup_restore_b7_native_operator import NativeBackupOperator
from monitorbox_backup_restore_b7_native_schedule import NativeScheduledBackup
from monitorbox_backup_restore_b7_native_workflow import NativeBackupWorkflow
from monitorbox_backup_restore_b7_policy import BackupPolicyStore
from monitorbox_backup_restore_b7_restore_preflight import NativeRestorePreflight

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
MODULE_VERSION = "2.0.0"
MODULE_BUILD = 7
REQUIRES_CORE = ">=3.0.0 <4.0.0"


def install(app, *, platform) -> None:
    """Install only the trusted Core-owned, generation-scoped v3 capabilities."""
    if platform.native_full_archive is None:
        raise RuntimeError("Backup/Restore v3 requires a native Supervisor")
    workflow = NativeBackupWorkflow(platform)
    schedule = NativeScheduledBackup(workflow, BackupPolicyStore(platform.root))
    operator = NativeBackupOperator(platform, workflow=workflow, scheduled=schedule)
    operator.install(app)
    NativeBackupApplication(platform, workflow, schedule).install(app)
    NativeRestorePreflight(platform, workflow).install(app)


__all__ = ["install", "MODULE_ID", "MODULE_VERSION", "MODULE_BUILD"]
