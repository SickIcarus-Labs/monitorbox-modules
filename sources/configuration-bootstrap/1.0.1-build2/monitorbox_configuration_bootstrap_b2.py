"""Managed Configuration/Bootstrap 1.0.1 build 2.

This release removes the dependency on MonitorBox Core's retired factory
Configuration/Bootstrap seed. The managed module owns normal configuration
composition directly and delegates only to provider-blind Core workflow
primitives. Provider authority enters exclusively through the admitted
PluginRegistry supplied by Core.
"""

from __future__ import annotations

from aiohttp import web

from monitorbox.v2.guided_setup_ui import GuidedSetupUi
from monitorbox.v2.policy_ui import PolicyUi
from monitorbox.v2.quick_add_ui import QuickAddUi
from monitorbox.v2.safe_discovery_ui import AbilityDiscoveryUi
from monitorbox.v2.setup_appliance_credentials_ui import SetupAwareApplianceCredentialsUi
from monitorbox.v2.setup_config_ui import SetupAwareConfigUi
from monitorbox.v2.setup_draft_ui import SetupDraftUi


def install(
    app: web.Application,
    *,
    platform,
    controller,
    plugin_registry=None,
) -> None:
    """Compose the normal managed Configuration/Bootstrap workflow."""

    SetupDraftUi(platform).install(app)
    SetupAwareConfigUi(platform, controller).install(app)
    QuickAddUi(
        platform,
        controller,
        plugin_registry=plugin_registry,
    ).install(app)
    SetupAwareApplianceCredentialsUi(platform).install(app)
    AbilityDiscoveryUi(platform, controller).install(app)
    GuidedSetupUi(platform).install(app)
    PolicyUi(platform).install(app)


__all__ = ["install"]
