"""Managed Configuration/Bootstrap 1.0.3 build 4.

Supersedes build 3 after Broad Leaf physical acceptance exposed a legacy
canonical-authority shape that frozen Core cannot project: migration-era managed
providers may have adapter + host but omit port because the provider supplied its
default. Bootstrap remains provider-blind. It reconciles that incomplete canonical
identity only when one selected System + adapter + host maps to exactly one
observed candidate socket; ambiguous cases fail closed.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from aiohttp import web

from monitorbox.v2.connection_endpoint_identity import connection_socket_identity
from monitorbox.v2.guided_setup_ui import GuidedSetupUi
from monitorbox.v2.onboarding_existing_connections import ExistingConnection
from monitorbox.v2.onboarding_generator import OnboardingMode
from monitorbox.v2.operator_ontology import SYSTEM_KINDS
from monitorbox.v2.plugin_api.runtime_execution import CORE_NATIVE_ADAPTERS
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
    """Constrain Quick Add Connection presentation to selected Systems."""

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


def _providers(obj: Mapping[str, Any]):
    for capability in obj.get("capabilities", []):
        if not isinstance(capability, Mapping):
            continue
        for provider in capability.get("providers", []):
            if isinstance(provider, Mapping):
                yield provider


def _owner_system_id(
    obj: Mapping[str, Any],
    systems: Mapping[str, Mapping[str, Any]],
) -> str | None:
    object_id = str(obj.get("id") or "")
    if object_id in systems:
        return object_id
    dependencies = obj.get("depends_on", [])
    if not isinstance(dependencies, list):
        return None
    owners = [str(item) for item in dependencies if str(item) in systems]
    return owners[0] if len(owners) == 1 else None


def _normalized_host(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    host = value.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.casefold().rstrip(".")
    return host or None


def _legacy_host_only_authority(
    session: Any,
    payload: dict[str, Any],
) -> tuple[ExistingConnection, ...]:
    """Resolve incomplete canonical host-only identity from unique observed sockets.

    This is deliberately provider-blind. No default ports or adapter-specific
    protocol knowledge are admitted. Canonical authority contributes System,
    adapter, host and object ownership; current discovery contributes the socket.
    Both sides must be unique at that structural key or no reconciliation occurs.
    """

    scope = _active_quick_add_scope(session)
    rows = payload.get("connections")
    document = session.generated.config
    if not scope or not isinstance(rows, list) or not isinstance(document, Mapping):
        return ()

    wanted = set(scope)
    observed: dict[
        tuple[str, str, str],
        dict[tuple[str, int], list[dict[str, Any]]],
    ] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("already_configured") is True:
            continue
        system_id = str(row.get("system_id") or "")
        kind = str(row.get("kind") or "").strip().casefold()
        if system_id not in wanted or not kind:
            continue
        socket = connection_socket_identity(row.get("endpoint"))
        if socket is None:
            continue
        host, _port = socket
        observed.setdefault((system_id, kind, host), {}).setdefault(socket, []).append(row)

    canonical: dict[
        tuple[str, str, str],
        list[tuple[str, str]],
    ] = {}
    for site in document.get("sites", []):
        if not isinstance(site, Mapping):
            continue
        objects = [item for item in site.get("objects", []) if isinstance(item, Mapping)]
        systems = {
            str(item.get("id")): item
            for item in objects
            if str(item.get("kind") or "") in SYSTEM_KINDS
        }
        for obj in objects:
            object_id = str(obj.get("id") or "")
            object_is_system = object_id in systems
            system_id = _owner_system_id(obj, systems)
            if not system_id or system_id not in wanted:
                continue
            for provider in _providers(obj):
                kind = str(provider.get("adapter") or "").strip().casefold()
                if not kind:
                    continue
                if object_is_system and kind in CORE_NATIVE_ADAPTERS:
                    continue
                config = provider.get("config")
                if not isinstance(config, Mapping):
                    continue

                # Core already handles any provider with an explicit endpoint or
                # a valid host+port pair. This fallback is only for legacy
                # host-only canonical authority.
                if any(
                    isinstance(config.get(key), str) and str(config.get(key)).strip()
                    for key in ("endpoint", "base_url", "url")
                ):
                    continue
                if config.get("port") not in (None, ""):
                    continue
                host = _normalized_host(config.get("host"))
                if host is None:
                    continue
                key = (system_id, kind, host)
                canonical.setdefault(key, []).append(
                    (
                        object_id or system_id,
                        str(provider.get("label") or obj.get("label") or kind),
                    )
                )

    recovered: list[ExistingConnection] = []
    for key, canonical_rows in canonical.items():
        sockets = observed.get(key, {})
        if len(sockets) != 1:
            continue
        owners = {object_id for object_id, _label in canonical_rows}
        if len(owners) != 1:
            continue
        _socket, candidate_rows = next(iter(sockets.items()))
        endpoints = {
            str(row.get("endpoint") or "").strip()
            for row in candidate_rows
            if isinstance(row.get("endpoint"), str) and str(row.get("endpoint")).strip()
        }
        if len(endpoints) != 1:
            continue
        labels = sorted({label for _object_id, label in canonical_rows if label})
        recovered.append(
            ExistingConnection(
                system_id=key[0],
                kind=key[1],
                label=labels[0] if labels else key[1],
                endpoint=next(iter(endpoints)),
                object_id=next(iter(owners)),
                configured_values={},
            )
        )

    return tuple(
        sorted(
            recovered,
            key=lambda item: (item.system_id, item.kind, item.endpoint, item.object_id),
        )
    )


def _supplement_legacy_host_authority(
    session: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark uniquely reconciled host-only legacy candidates as configured."""

    rows = payload.get("connections")
    if not isinstance(rows, list):
        return payload

    for existing in _legacy_host_only_authority(session, payload):
        socket = connection_socket_identity(existing.endpoint)
        if socket is None:
            continue
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("system_id") or "") == existing.system_id
            and str(row.get("kind") or "").strip().casefold() == existing.kind
            and connection_socket_identity(row.get("endpoint")) == socket
        ]
        if not matches:
            continue
        for row in matches:
            row["already_configured"] = True
            row["configured_object_id"] = existing.object_id
            row["configured_values"] = copy.deepcopy(dict(existing.configured_values))

    rows.sort(
        key=lambda row: (
            bool(row.get("already_configured")) if isinstance(row, dict) else False,
            str(row.get("system_label") or row.get("system_id") or "")
            if isinstance(row, dict)
            else "",
            str(row.get("kind") or "") if isinstance(row, dict) else "",
            str(row.get("endpoint") or "") if isinstance(row, dict) else "",
        )
    )
    return payload


def _project_connection_response(owner: Any, handler: Handler) -> Handler:
    """Project successful legacy Connection responses through Bootstrap policy."""

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
    core_summary = owner._summary

    def scoped_summary(session: Any) -> dict[str, Any]:
        payload = core_summary(session)
        payload = _supplement_legacy_host_authority(session, payload)
        return _scope_existing_authority(session, payload)

    owner._summary = scoped_summary

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
