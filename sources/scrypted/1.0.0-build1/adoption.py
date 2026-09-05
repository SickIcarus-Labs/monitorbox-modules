from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping, Sequence

from aiohttp import web

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _candidate_source(candidate: Any, source: str):
    return next(
        (
            item
            for item in getattr(candidate, "evidence", ())
            if getattr(item, "source", None) == source
        ),
        None,
    )


def _providers(obj: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    for capability in obj.get("capabilities", []):
        if not isinstance(capability, Mapping):
            continue
        for provider in capability.get("providers", []):
            if isinstance(provider, dict):
                yield provider


def _site(working: dict[str, Any], site_id: str) -> dict[str, Any]:
    site = next(
        (
            item
            for item in working.get("sites", [])
            if isinstance(item, dict) and item.get("id") == site_id
        ),
        None,
    )
    if not isinstance(site, dict):
        raise web.HTTPBadRequest(text=f"unknown site {site_id}")
    return site


def _unique_object_id(label: str, seed: str, existing: set[str]) -> str:
    base = _SLUG_RE.sub("_", label.casefold()).strip("_")
    if not base or not base[0].isalpha():
        base = "object_" + _SLUG_RE.sub("_", seed.casefold()).strip("_")
    base = base[:56] or "object"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base[:55]}_{suffix}"
        suffix += 1
    return candidate


def _integration_provider(
    working: dict[str, Any],
    site_id: str,
) -> tuple[str, dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for obj in _site(working, site_id).get("objects", []):
        if not isinstance(obj, dict):
            continue
        for provider in _providers(obj):
            if provider.get("adapter") != "scrypted":
                continue
            config = provider.get("config", {})
            if isinstance(config, dict) and config.get("operation", "inventory") != "inventory":
                continue
            matches.append(provider)
    if len(matches) != 1:
        raise web.HTTPBadRequest(
            text=(
                "scrypted discovery adoption requires exactly one configured "
                f"inventory provider; found {len(matches)}"
            )
        )
    agent_id = matches[0].get("agent_id")
    if not isinstance(agent_id, str):
        raise web.HTTPBadRequest(text="scrypted inventory provider has no valid agent")
    return agent_id, matches[0]


def _selected_capabilities(
    candidate: Any,
    selected: Sequence[str] | None,
) -> tuple[str, ...]:
    allowed = ScryptedCandidateAdoption().adoptable_capabilities(candidate)
    if not allowed:
        raise web.HTTPBadRequest(
            text=(
                f"discovery candidate {getattr(candidate, 'candidate_id', '<unknown>')} "
                "has no safely auto-configurable abilities"
            )
        )
    if selected is None:
        return allowed
    if isinstance(selected, (str, bytes)) or not all(
        isinstance(item, str) for item in selected
    ):
        raise web.HTTPBadRequest(
            text="selected discovery abilities must be a string list"
        )
    requested = set(selected)
    unknown = requested.difference(allowed)
    if unknown:
        raise web.HTTPBadRequest(
            text="unsupported discovery abilities: " + ", ".join(sorted(unknown))
        )
    chosen = tuple(item for item in allowed if item in requested)
    if not chosen:
        raise web.HTTPBadRequest(
            text="select at least one monitoring ability or uncheck Monitor"
        )
    return chosen


def _camera_object(
    working: dict[str, Any],
    site_id: str,
    object_id: str,
    label: str,
    candidate: Any,
    selected: Sequence[str],
) -> dict[str, Any]:
    evidence = _candidate_source(candidate, "scrypted")
    if evidence is None:
        raise web.HTTPBadRequest(text="Scrypted camera discovery evidence is missing")
    camera_id = str(evidence.source_id)
    agent_id, inventory_provider = _integration_provider(working, site_id)
    inventory_config = inventory_provider.get("config", {})
    if not isinstance(inventory_config, Mapping):
        raise web.HTTPBadRequest(
            text="scrypted inventory provider has invalid configuration"
        )
    socket = str(
        inventory_config.get("socket")
        or "/run/monitorbox-scrypted/bridge.sock"
    )

    def provider(
        capability: str,
        operation: str,
        interval: int,
        timeout: int,
    ) -> dict[str, Any]:
        return {
            "id": "scrypted",
            "label": label,
            "adapter": "scrypted",
            "agent_id": agent_id,
            "check_id": f"{object_id}_{capability}",
            "enabled": True,
            "interval_seconds": interval,
            "timeout_seconds": timeout,
            "config": {
                "socket": socket,
                "operation": operation,
                "camera_id": camera_id,
            },
        }

    definitions = {
        "camera_state": {
            "id": "state",
            "kind": "camera_state",
            "label": "Camera state",
            "provider": provider("state", "camera_state", 16, 8),
        },
        "snapshot": {
            "id": "snapshot",
            "kind": "camera_snapshot",
            "label": "Snapshot acquisition",
            "provider": provider("snapshot", "snapshot", 900, 15),
        },
        "live_view": {
            "id": "stream",
            "kind": "camera_stream",
            "label": "Stream acquisition",
            "provider": provider("stream", "stream", 300, 15),
        },
    }
    capability_rows: list[dict[str, Any]] = []
    for ability in selected:
        definition = definitions[ability]
        capability_rows.append(
            {
                "id": definition["id"],
                "kind": definition["kind"],
                "label": definition["label"],
                "enabled": True,
                "providers": [definition["provider"]],
            }
        )
    return {
        "id": object_id,
        "label": label,
        "kind": "camera",
        "capabilities": capability_rows,
    }


class ScryptedCandidateAdoption:
    """Provider-owned adoption policy for Scrypted camera inventory evidence."""

    def adoptable_capabilities(self, candidate: Any) -> tuple[str, ...]:
        if getattr(candidate, "kind", None) != "camera":
            return ()
        if _candidate_source(candidate, "scrypted") is None:
            return ()
        allowed = ("camera_state", "snapshot", "live_view")
        suggested = set(getattr(candidate, "suggested_capabilities", ()))
        return tuple(item for item in allowed if item in suggested)

    def identity_matches(
        self,
        obj: Mapping[str, Any],
        candidate: Any,
    ) -> bool:
        evidence = _candidate_source(candidate, "scrypted")
        if evidence is None:
            return False
        for provider in _providers(obj):
            config = provider.get("config", {})
            if (
                provider.get("adapter") == "scrypted"
                and isinstance(config, Mapping)
                and config.get("camera_id") == evidence.source_id
            ):
                return True
        return False

    def adopt_candidate(
        self,
        working: dict[str, Any],
        *,
        site_id: str,
        candidate: Any,
        label: str,
        policy: str | None = None,
        capabilities: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        del policy
        if getattr(candidate, "kind", None) != "camera":
            raise web.HTTPBadRequest(
                text=(
                    "discovery candidate kind/source is not adoptable by Scrypted: "
                    f"{getattr(candidate, 'kind', None)}"
                )
            )
        if _candidate_source(candidate, "scrypted") is None:
            raise web.HTTPBadRequest(
                text="Scrypted discovery adoption requires Scrypted evidence"
            )

        working = copy.deepcopy(working)
        site = _site(working, site_id)
        existing_ids = {
            str(obj.get("id"))
            for obj in site.get("objects", [])
            if isinstance(obj, dict) and isinstance(obj.get("id"), str)
        }
        addresses = tuple(getattr(candidate, "addresses", ()) or ())
        seed = (
            addresses[0]
            if addresses
            else str(getattr(candidate, "candidate_id", "camera"))
        )
        object_id = _unique_object_id(label, seed, existing_ids)
        selected = _selected_capabilities(candidate, capabilities)
        obj = _camera_object(
            working,
            site_id,
            object_id,
            label,
            candidate,
            selected,
        )
        site.setdefault("objects", []).append(obj)
        obj["discovery"] = {
            "sources": sorted(
                {
                    f"{e.source}:{e.source_id}"
                    for e in getattr(candidate, "evidence", ())
                }
            ),
            "mac": getattr(candidate, "mac", None),
        }
        return object_id, working
