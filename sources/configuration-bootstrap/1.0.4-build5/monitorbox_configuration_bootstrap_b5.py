"""Managed Configuration/Bootstrap 1.0.4 build 5.

Build 5 preserves the accepted 1.0.3 build-4 onboarding behavior and adds the
read-only local-control-plane projection required by MonitorBox #253.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox_configuration_bootstrap_b4 import install as _install_previous
from monitorbox_configuration_bootstrap_local_access_b5 import LocalAccessUi


def install(
    app: web.Application,
    *,
    platform,
    controller,
    plugin_registry=None,
) -> None:
    _install_previous(
        app,
        platform=platform,
        controller=controller,
        plugin_registry=plugin_registry,
    )
    LocalAccessUi(platform).install(app)


__all__ = ["install"]
