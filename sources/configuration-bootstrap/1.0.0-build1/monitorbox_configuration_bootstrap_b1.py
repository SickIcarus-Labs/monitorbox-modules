"""Managed Configuration/Bootstrap 1.0.0 build 1 over the certified factory seed.

The factory seed establishes the provider-neutral Configuration/Bootstrap
contract shipped with MonitorBox 2.3. Managed releases are the executable
authority selected by Module Management and may replace/overlay that behavior
without a Core rebuild, while this first release deliberately preserves the
certified seed semantics exactly.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox.v2.modules.configuration_bootstrap import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
)
from monitorbox.v2.modules.configuration_bootstrap import application as factory

_EXPECTED_FACTORY = (
    "com.sickicarus.monitorbox.configuration-bootstrap",
    "1.0.0",
    1,
)
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED_FACTORY:
    raise ImportError(
        "managed Configuration/Bootstrap 1.0.0 build 1 requires the certified "
        "MonitorBox 2.3 factory Configuration/Bootstrap 1.0.0 build 1 seed"
    )


def install(
    app: web.Application,
    *,
    platform,
    controller,
    plugin_registry=None,
) -> None:
    """Activate the certified Configuration/Bootstrap product contract."""

    factory.install(
        app,
        platform=platform,
        controller=controller,
        plugin_registry=plugin_registry,
    )


__all__ = ["install"]
