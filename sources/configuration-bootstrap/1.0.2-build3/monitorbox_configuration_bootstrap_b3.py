"""Managed Configuration/Bootstrap 1.0.2 build 3.

Phase 2 keeps MonitorBox Core frozen while restoring one provider-blind Quick Add
orchestration invariant: successful Connection mutation/discovery responses must
be projected through the owning existing-authority summary before they leave the
configuration surface. Core remains the sole owner of reconciliation and
selected-System scoping; this module only wires that existing projector into the
two response paths that predate Core's native summary-projector hook.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from monitorbox.v2.guided_setup_ui import GuidedSetupUi
from monitorbox.v2.policy_ui import PolicyUi
from monitorbox.v2.quick_add_ui import QuickAddUi
from monitorbox.v2.safe_discovery_ui import AbilityDiscoveryUi
from monitorbox.v2.setup_appliance_credentials_ui import SetupAwareApplianceCredentialsUi
from monitorbox.v2.setup_config_ui import SetupAwareConfigUi
from monitorbox.v2.setup_draft_ui import SetupDraftUi

Handler = Callable[[web.Request], Awaitable[web.Response]]


def _project_connection_response(owner: Any, handler: Handler) -> Handler:
    """Project successful Connection responses through existing authority.

    Frozen Core 2.3.1 already owns the correct scoped `_summary()` behavior but
    its Connection API returns `session.summary()` directly from two recursive
    response paths. Decorate only those successful JSON responses. Exceptions,
    status codes, cache headers, and all provider semantics remain Core-owned.
    """

    async def projected(request: web.Request) -> web.Response:
        response = await handler(request)
        if response.status >= 400 or response.content_type != "application/json":
            return response
        text = response.text
        if text is None:
            return response
        payload = json.loads(text)
        if not isinstance(payload, dict) or "session" not in payload:
            return response

        session_id = str(request.match_info.get("session_id") or "")
        session = owner.sessions.get(session_id)
        payload["session"] = owner._summary(session)

        headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold() not in {"content-type", "content-length"}
        }
        return web.json_response(payload, status=response.status, headers=headers)

    return projected


def _wire_scoped_connection_projection(quick_add: QuickAddUi) -> None:
    owner = quick_add.onboarding
    connections = owner.connections

    # Forward compatibility: if a later compatible Core exposes the native
    # projector hook, use it instead of decorating handlers.
    if hasattr(connections, "summary_projector"):
        connections.summary_projector = owner._summary
        return

    connections.validate_and_stage = _project_connection_response(
        owner,
        connections.validate_and_stage,
    )
    connections.resolve_authenticated_discovery = _project_connection_response(
        owner,
        connections.resolve_authenticated_discovery,
    )


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

    quick_add = QuickAddUi(
        platform,
        controller,
        plugin_registry=plugin_registry,
    )
    _wire_scoped_connection_projection(quick_add)
    quick_add.install(app)

    SetupAwareApplianceCredentialsUi(platform).install(app)
    AbilityDiscoveryUi(platform, controller).install(app)
    GuidedSetupUi(platform).install(app)
    PolicyUi(platform).install(app)


__all__ = ["install"]
