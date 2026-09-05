"""Managed Backup / Restore 1.0.0 build 1 over the certified factory seed.

The factory seed establishes the Backup / Restore product contract shipped with
MonitorBox 2.3. Managed releases are the executable authority selected by Module
Management and may replace/overlay that behavior without a Core rebuild, while
this first release deliberately preserves the certified seed semantics exactly.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox.v2.modules.backup_restore import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
    install as factory_install,
)

_EXPECTED_FACTORY = (
    "com.sickicarus.monitorbox.backup-restore",
    "1.0.0",
    1,
)
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED_FACTORY:
    raise ImportError(
        "managed Backup / Restore 1.0.0 build 1 requires the certified "
        "MonitorBox 2.3 factory Backup / Restore 1.0.0 build 1 seed"
    )


def install(app: web.Application, *, platform) -> None:
    """Activate the certified Backup / Restore product contract."""

    factory_install(app, platform=platform)


__all__ = ["install"]
