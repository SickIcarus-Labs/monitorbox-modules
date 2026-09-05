"""Managed Configuration/Bootstrap first-party module, v1.0.0 build 1.

The package owns normal configuration workflow composition and policy while
reusing Core's provider-blind transaction/auth/session primitives.
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
    """Compose normal Configuration/Bootstrap product surfaces."""

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
