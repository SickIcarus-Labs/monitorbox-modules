"""Managed Backup / Restore 1.0.1 build 2.

This release is independently executable. It consumes only MonitorBox Core's
provider-blind appliance backup primitive plus the runtime-provided configuration
platform; it does not delegate to or import the bundled Backup / Restore factory
implementation.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox_backup_restore_b2_application import BackupRestoreApplication
from monitorbox_backup_restore_b2_management import BackupRestoreManagement

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
MODULE_VERSION = "1.0.1"
MODULE_BUILD = 2
ADMIN_API_PREFIX = "/api/v2/config/backup-restore"


def _install_admin_routes(
    app: web.Application,
    application: BackupRestoreApplication,
    management: BackupRestoreManagement,
) -> None:
    prefix = ADMIN_API_PREFIX
    app.router.add_get(f"{prefix}/backups", application.list_backups)
    app.router.add_post(f"{prefix}/backups", application.create_backup)
    app.router.add_post(f"{prefix}/import", application.import_backup)
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
