"""Managed Configuration/Bootstrap 1.0.2 build 3.

Phase 2 keeps MonitorBox Core frozen while restoring two provider-blind Quick Add
orchestration invariants: successful Connection mutation/discovery responses must
be projected through the owning existing-authority summary, and that projection
must remain constrained to the active selected-System scope. Core remains the
sole owner of canonical reconciliation, identity, credential reuse, and matching;
this module only owns the workflow boundary required by #158.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from monitorbox.v2.guided_setup_ui import GuidedSetupUi
from monitorbox.v2.onboarding_generator import OnboardingMode
from monitorbox.v2.policy_ui import PolicyUi
from monitorbox.v2.quick_add_ui import QuickAddUi
from monitorbox.v2.safe_discovery_ui import AbilityDiscoveryUi
from monitorbox.v2.setup_appliance_credentials_ui import SetupAwareApplianceCredentialsUi
from monitorbox.v2.setup_config_ui import SetupAwareConfigUi
from monitorbox.v2.setup_draft_ui import SetupDraftUi

Handler = Callable[[web.Request], Awaitable[web.Response]]


def _active_quick_add_scope(session: Any) -> tuple[str, ...]:
    if session.generated.mode is not OnboardingMode.QUICK_ADD:
        return ()
    scope = [
        str(item).strip()
        for item in session.detection_system_ids
        if isinstance(item, str) and str(item).strip()
    ]
    if scope:
        return tuple(dict.fromkeys(scope))
    return tuple(
        dict.fromkeys(
            str(candidate.system_id).strip()
            for candidate in session.connection_candidates
            if isinstance(candidate.system_id, str)
            and str(candidate.system_id).strip()
        )
    )


def _scope_existing_authority(session: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Constrain Quick Add Connection presentation to selected Systems.

    Frozen Core 2.3.1's canonical existing-authority projector is correct, but a
    later compatibility runtime deliberately broadens its output back to every
    configured Connection in the selected Site. #158 carries forward the
    certified selected-System contract, so Bootstrap owns the final workflow
    scope boundary without reconstructing provider identity or reconciliation.
    """

    scope = _active_quick_add_scope(session)
    if not scope:
        return payload
    rows = payload.get("connections")
    if not isinstance(rows, list):
        return payload
    wanted = set(scope)
    payload["connections"] = [
        row
        for row in rows
        if not isinstance(row, dict)
        or str(row.get("system_id") or "") in wanted
    ]
    return payload


def _project_connection_response(owner: Any, handler: Handler) -> Handler:
    """Project successful legacy Connection responses through Bootstrap scope."""

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

    # Core 2.3.1 installs a compatibility wrapper that broadens the otherwise
    # correct scoped summary to all configured Connections in the Site. Capture
    # the complete Core projection, then constrain only its Connection rows at
    # this owning workflow boundary. Assigning the function to the instance also
    # keeps start/status/detect summaries under the same selected-System contract.
    core_summary = owner._summary

    def scoped_summary(session: Any) -> dict[str, Any]:
        return _scope_existing_authority(session, core_summary(session))

    owner._summary = scoped_summary

    # Forward compatibility: if a later compatible Core exposes the native
    # response-projector hook, point it at the Bootstrap-scoped owner summary.
    if hasattr(connections, "summary_projector"):
        connections.summary_projector = owner._summary
        return

    # Frozen Core returns raw session.summary() from these two response paths.
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
