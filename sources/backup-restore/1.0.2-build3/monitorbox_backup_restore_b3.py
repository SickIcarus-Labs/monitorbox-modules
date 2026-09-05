"""Managed Backup / Restore 1.0.2 build 3.

Build 3 keeps backup policy, vault management, scheduling, destinations and
operator restore UX in the independently managed module. Whole-appliance
activation is delegated only to Core's provider-blind quiesced restore handoff.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox_backup_restore_b3_application import BackupRestoreApplication
from monitorbox_backup_restore_b3_management import BackupRestoreManagement

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
MODULE_VERSION = "1.0.2"
MODULE_BUILD = 3
ADMIN_API_PREFIX = "/api/v2/config/backup-restore"


def _install_admin_routes(
    app: web.Application,
    application: BackupRestoreApplication,
    management: BackupRestoreManagement,
) -> None:
    prefix = ADMIN_API_PREFIX
    app.router.add_get(f"{prefix}/backups", application.list_backups)
    app.router.add_post(f"{prefix}/backups", application.create_backup)
    app.router.add_get(f"{prefix}/backups/{{backup_id}}", application.inspect_backup)
    app.router.add_get(
        f"{prefix}/backups/{{backup_id}}/download",
        application.download_backup,
    )
    app.router.add_post(
        f"{prefix}/backups/{{backup_id}}/rename",
        application.rename_backup,
    )
    app.router.add_post(
        f"{prefix}/backups/{{backup_id}}/copy",
        application.copy_backup,
    )
    app.router.add_delete(
        f"{prefix}/backups/{{backup_id}}",
        application.delete_backup,
    )
    app.router.add_post(
        f"{prefix}/backups/{{backup_id}}/restore/preview",
        application.preview_vault_restore,
    )
    app.router.add_post(
        f"{prefix}/restore/file/preview",
        application.preview_file_restore,
    )
    app.router.add_post(f"{prefix}/restore/confirm", application.confirm_restore)
    app.router.add_get(f"{prefix}/restore/status", application.restore_status)

    app.router.add_get(f"{prefix}/policy", management.get_policy)
    app.router.add_put(f"{prefix}/policy", management.put_policy)
    app.router.add_get(f"{prefix}/schedule", management.get_schedule)
    app.router.add_post(f"{prefix}/schedule/run", management.run_schedule)
    app.router.add_post(
        f"{prefix}/backups/{{backup_id}}/destination",
        management.publish_destination,
    )


def install(app: web.Application, *, platform) -> None:
    """Install the managed Backup / Restore product on the supplied platform."""

    management = BackupRestoreManagement(platform)
    application = BackupRestoreApplication(platform)
    management.scheduler.install(app)
    application.install_page(app)
    _install_admin_routes(app, application, management)


__all__ = [
    "ADMIN_API_PREFIX",
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_VERSION",
    "install",
]
