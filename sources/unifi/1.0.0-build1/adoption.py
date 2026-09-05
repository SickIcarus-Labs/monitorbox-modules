from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping, Sequence

from aiohttp import web

from ...discovery import DiscoveryCandidate, DiscoveryEvidence

_IMPORTANCE = frozenset({"required", "not_required", "ignored"})
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class UniFiCandidateAdoption:
    """Provider-owned adoption of UniFi inventory children.

    Runtime discovery review is still Core-owned. This facet owns only the
    UniFi-specific identity and canonical construction required to turn stable
    switch-port evidence into a monitored child Object.
    """

    @staticmethod
    def _evidence(candidate: DiscoveryCandidate) -> DiscoveryEvidence | None:
        if candidate.kind != "network_port":
            return None
        return next((item for item in candidate.evidence if item.source == "unifi"), None)

    def adoptable_capabilities(self, candidate: DiscoveryCandidate) -> tuple[str, ...]:
        return ("port_state",) if self._evidence(candidate) is not None else ()

    def identity_matches(
        self,
        obj: Mapping[str, Any],
        candidate: DiscoveryCandidate,
    ) -> bool:
        evidence = self._evidence(candidate)
        if evidence is None:
            return False
        device_mac = str(evidence.metadata.get("device_mac") or "").strip().casefold()
        port_idx = evidence.metadata.get("port_idx")
        if not device_mac or isinstance(port_idx, bool) or not isinstance(port_idx, int):
            return False
        for provider in _providers(obj):
            if provider.get("adapter") != "unifi":
                continue
            config = provider.get("config", {})
            if not isinstance(config, Mapping) or config.get("operation") != "port_state":
                continue
            if (
                str(config.get("device_mac") or "").strip().casefold() == device_mac
                and config.get("port_idx") == port_idx
            ):
                return True
        return False

    def adopt_candidate(
        self,
        working: dict[str, Any],
        *,
        site_id: str,
        candidate: DiscoveryCandidate,
        label: str,
        policy: str | None = None,
        capabilities: Sequence[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        del policy
        evidence = self._evidence(candidate)
        if evidence is None:
            raise web.HTTPBadRequest(text="UniFi switch-port candidate has no UniFi evidence")

        allowed = self.adoptable_capabilities(candidate)
        selected = _selected_capabilities(allowed, capabilities)
        if selected != ("port_state",):
            raise web.HTTPBadRequest(text="UniFi switch-port discovery requires the Port state ability")

        metadata = evidence.metadata
        device_mac = str(metadata.get("device_mac") or "").strip().casefold()
        port_idx = metadata.get("port_idx")
        if not device_mac or isinstance(port_idx, bool) or not isinstance(port_idx, int):
            raise web.HTTPBadRequest(text="UniFi switch-port evidence has no stable port identity")
        importance = str(metadata.get("initial_importance") or "required")
        if importance not in _IMPORTANCE:
            importance = "required"

        site = _site(working, site_id)
        existing_ids = {
            str(obj.get("id"))
            for obj in site.get("objects", [])
            if isinstance(obj, dict) and isinstance(obj.get("id"), str)
        }
        object_id = _unique_object_id(label, evidence.source_id, existing_ids)
        agent_id, inventory_provider = _inventory_provider(working, site_id)
        inventory_config = inventory_provider.get("config", {})
        if not isinstance(inventory_config, Mapping):
            raise web.HTTPBadRequest(text="UniFi inventory provider has invalid configuration")
        required_keys = ("base_url", "username_env", "password_env")
        if any(not inventory_config.get(key) for key in required_keys):
            raise web.HTTPBadRequest(text="UniFi inventory provider is missing connection credentials")

        config = {
            "base_url": inventory_config["base_url"],
            "site": inventory_config.get("site", "default"),
            "username_env": inventory_config["username_env"],
            "password_env": inventory_config["password_env"],
            "verify_tls": bool(inventory_config.get("verify_tls", False)),
            "operation": "port_state",
            "device_mac": device_mac,
            "port_idx": port_idx,
        }
        obj = {
            "id": object_id,
            "label": label,
            "kind": "network_port",
            "enabled": True,
            "importance": importance,
            "capabilities": [
                {
                    "id": "port_state",
                    "kind": "port_state",
                    "label": "Port state",
                    "enabled": True,
                    "providers": [
                        {
                            "id": "unifi",
                            "label": "Port state via UniFi Network",
                            "adapter": "unifi",
                            "agent_id": agent_id,
                            "check_id": f"{object_id}_port_state",
                            "enabled": True,
                            "interval_seconds": 30,
                            "timeout_seconds": 10,
                            "config": config,
                        }
                    ],
                }
            ],
            "discovery": {
                "sources": sorted(
                    {f"{item.source}:{item.source_id}" for item in candidate.evidence}
                ),
                "mac": None,
            },
        }
        result = copy.deepcopy(working)
        _site(result, site_id).setdefault("objects", []).append(obj)
        return object_id, result


def _selected_capabilities(
    allowed: tuple[str, ...],
    selected: Sequence[str] | None,
) -> tuple[str, ...]:
    if selected is None:
        return allowed
    if isinstance(selected, (str, bytes)) or not all(isinstance(item, str) for item in selected):
        raise web.HTTPBadRequest(text="selected discovery abilities must be a string list")
    requested = set(selected)
    unknown = requested.difference(allowed)
    if unknown:
        raise web.HTTPBadRequest(
            text="unsupported discovery abilities: " + ", ".join(sorted(unknown))
        )
    chosen = tuple(item for item in allowed if item in requested)
    if not chosen:
        raise web.HTTPBadRequest(text="select at least one monitoring ability or uncheck Monitor")
    return chosen


def _providers(obj: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    raw_capabilities = obj.get("capabilities", [])
    if not isinstance(raw_capabilities, list):
        return
    for capability in raw_capabilities:
        if not isinstance(capability, Mapping):
            continue
        raw_providers = capability.get("providers", [])
        if not isinstance(raw_providers, list):
            continue
        for provider in raw_providers:
            if isinstance(provider, Mapping):
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


def _inventory_provider(
    working: dict[str, Any],
    site_id: str,
) -> tuple[str, Mapping[str, Any]]:
    matches: list[Mapping[str, Any]] = []
    for obj in _site(working, site_id).get("objects", []):
        if not isinstance(obj, Mapping):
            continue
        for provider in _providers(obj):
            if provider.get("adapter") != "unifi":
                continue
            config = provider.get("config", {})
            if not isinstance(config, Mapping) or config.get("operation", "inventory") != "inventory":
                continue
            matches.append(provider)
    if len(matches) != 1:
        raise web.HTTPBadRequest(
            text="UniFi discovery adoption requires exactly one configured inventory provider; "
            f"found {len(matches)}"
        )
    agent_id = matches[0].get("agent_id")
    if not isinstance(agent_id, str):
        raise web.HTTPBadRequest(text="UniFi inventory provider has no valid agent")
    return agent_id, matches[0]


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
