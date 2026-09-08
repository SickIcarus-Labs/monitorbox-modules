from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping, Sequence

from aiohttp import web

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_BACKEND_TRANSPORT = "backend_transport"


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


def _integration_provider(working: dict[str, Any], site_id: str) -> tuple[str, dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for obj in _site(working, site_id).get("objects", []):
        if not isinstance(obj, dict):
            continue
        for provider in _providers(obj):
            if provider.get("adapter") != "portainer":
                continue
            config = provider.get("config", {})
            if isinstance(config, Mapping) and config.get("operation", "inventory") != "inventory":
                continue
            matches.append(provider)
    if len(matches) != 1:
        raise web.HTTPBadRequest(
            text=(
                "portainer discovery adoption requires exactly one configured "
                f"inventory provider; found {len(matches)}"
            )
        )
    agent_id = matches[0].get("agent_id")
    if not isinstance(agent_id, str):
        raise web.HTTPBadRequest(text="portainer inventory provider has no valid agent")
    return agent_id, matches[0]


def _backend_monitoring_endpoints(candidate: Any) -> tuple[dict[str, Any], ...]:
    """Return provider-proven direct TCP endpoints that are safe to persist.

    Portainer proves the published transport and the environment host, but not
    the application protocol. Adoption therefore persists TCP reachability only;
    HTTP(S) remains separate evidence unless another provider proves it.
    """
    evidence = _candidate_source(candidate, "portainer")
    if evidence is None:
        return ()
    metadata = getattr(evidence, "metadata", {})
    raw = metadata.get("backend_monitoring_endpoints", []) if isinstance(metadata, Mapping) else []
    if not isinstance(raw, list):
        return ()
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("endpoint_role") or "backend_monitoring").strip().casefold() != "backend_monitoring":
            continue
        if str(item.get("protocol") or "tcp").strip().casefold() != "tcp":
            continue
        host = str(item.get("host") or "").strip()
        public_port = item.get("public_port")
        if (
            not host
            or isinstance(public_port, bool)
            or not isinstance(public_port, int)
            or not 1 <= public_port <= 65535
        ):
            continue
        identity = (host, public_port)
        if identity in seen:
            continue
        seen.add(identity)
        endpoint: dict[str, Any] = {
            "host": host,
            "public_port": public_port,
            "protocol": "tcp",
            "endpoint_role": "backend_monitoring",
        }
        private_port = item.get("private_port")
        if (
            isinstance(private_port, int)
            and not isinstance(private_port, bool)
            and 1 <= private_port <= 65535
        ):
            endpoint["private_port"] = private_port
        host_source = item.get("host_source")
        if isinstance(host_source, str) and host_source.strip():
            endpoint["host_source"] = host_source.strip()
        result.append(endpoint)
    return tuple(sorted(result, key=lambda item: (item["host"], item["public_port"])))


def _single_backend_monitoring_endpoint(candidate: Any) -> dict[str, Any] | None:
    endpoints = _backend_monitoring_endpoints(candidate)
    return endpoints[0] if len(endpoints) == 1 else None


def _selected_capabilities(candidate: Any, selected: Sequence[str] | None) -> tuple[str, ...]:
    allowed = PortainerCandidateAdoption().adoptable_capabilities(candidate)
    if not allowed:
        raise web.HTTPBadRequest(
            text=f"discovery candidate {getattr(candidate, 'candidate_id', '<unknown>')} has no safely auto-configurable abilities"
        )
    if selected is None:
        return allowed
    if isinstance(selected, (str, bytes)) or not all(isinstance(item, str) for item in selected):
        raise web.HTTPBadRequest(text="selected discovery abilities must be a string list")
    unknown = set(selected).difference(allowed)
    if unknown:
        raise web.HTTPBadRequest(text="unsupported discovery abilities: " + ", ".join(sorted(unknown)))
    chosen = tuple(item for item in allowed if item in set(selected))
    if "docker_workload" not in chosen:
        raise web.HTTPBadRequest(text="Portainer discovery requires the Docker workload ability")
    return chosen


def _backend_transport_capability(
    *,
    object_id: str,
    agent_id: str,
    endpoint: Mapping[str, Any],
    policy: str,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "host": str(endpoint["host"]),
        "port": int(endpoint["public_port"]),
        "protocol": "tcp",
        "endpoint_role": "backend_monitoring",
        "source": "portainer_published_port",
    }
    if "private_port" in endpoint:
        config["private_port"] = int(endpoint["private_port"])
    if "host_source" in endpoint:
        config["host_source"] = str(endpoint["host_source"])

    capability: dict[str, Any] = {
        "id": _BACKEND_TRANSPORT,
        "kind": _BACKEND_TRANSPORT,
        "label": "Backend transport",
        "enabled": True,
        "providers": [{
            "id": "direct_tcp",
            "label": "Direct backend TCP",
            "adapter": "tcp",
            "agent_id": agent_id,
            "check_id": f"{object_id}_backend_tcp",
            "enabled": True,
            "interval_seconds": 30,
            "timeout_seconds": 5,
            "config": config,
        }],
    }
    if policy == "optional":
        capability["importance"] = "not_required"
    return capability


def _workload_object(
    working: dict[str, Any],
    site_id: str,
    object_id: str,
    label: str,
    candidate: Any,
    policy: str,
    selected_capabilities: Sequence[str],
) -> dict[str, Any]:
    if policy not in {"optional", "required"}:
        raise web.HTTPBadRequest(text="Docker workload policy must be optional or required")
    evidence = _candidate_source(candidate, "portainer")
    if evidence is None:
        raise web.HTTPBadRequest(text="Portainer workload discovery evidence is missing")
    agent_id, inventory_provider = _integration_provider(working, site_id)
    inventory_config = inventory_provider.get("config", {})
    if not isinstance(inventory_config, Mapping):
        raise web.HTTPBadRequest(text="Portainer inventory provider has invalid configuration")
    environment_provider_id = evidence.metadata.get("environment_provider_id")
    if isinstance(environment_provider_id, bool) or not isinstance(environment_provider_id, int) or environment_provider_id <= 0:
        raise web.HTTPBadRequest(
            text="Portainer workload discovery is missing its native environment identity; refresh Discoveries"
        )
    environment_key = evidence.metadata.get("environment_key")
    if not isinstance(environment_key, str) or not environment_key.strip():
        raise web.HTTPBadRequest(
            text="Portainer workload discovery is missing its environment key; refresh Discoveries"
        )
    config = {
        "base_url": inventory_config.get("base_url"),
        "api_key_env": inventory_config.get("api_key_env"),
        "verify_tls": bool(inventory_config.get("verify_tls", True)),
        "environment_ids": [environment_provider_id],
        "operation": "workload",
        "workload_identity": evidence.source_id,
        "environment_key": environment_key.strip(),
        "policy": policy,
    }
    capabilities: list[dict[str, Any]] = [{
        "id": "docker_workload",
        "kind": "docker_workload",
        "label": "Docker workload",
        "enabled": True,
        "providers": [{
            "id": "portainer",
            "label": "Docker workload via Portainer",
            "adapter": "portainer",
            "agent_id": agent_id,
            "check_id": f"{object_id}_docker",
            "enabled": True,
            "interval_seconds": 30,
            "timeout_seconds": 15,
            "config": config,
        }],
    }]
    if _BACKEND_TRANSPORT in selected_capabilities:
        endpoint = _single_backend_monitoring_endpoint(candidate)
        if endpoint is None:
            raise web.HTTPBadRequest(
                text="Portainer backend transport is ambiguous; refresh Discoveries or deselect Backend transport"
            )
        capabilities.append(
            _backend_transport_capability(
                object_id=object_id,
                agent_id=agent_id,
                endpoint=endpoint,
                policy=policy,
            )
        )
    return {
        "id": object_id,
        "label": label,
        "kind": "service",
        "presentation": {
            "group": "docker",
            "environment": evidence.metadata.get("environment"),
            "compose_project": evidence.metadata.get("compose_project"),
        },
        "capabilities": capabilities,
    }


class PortainerCandidateAdoption:
    """Provider-owned adoption policy for authenticated Portainer workload evidence."""

    def adoptable_capabilities(self, candidate: Any) -> tuple[str, ...]:
        if getattr(candidate, "kind", None) != "service":
            return ()
        evidence = _candidate_source(candidate, "portainer")
        if evidence is None:
            return ()
        suggested = set(getattr(candidate, "suggested_capabilities", ()) or ())
        if "docker_workload" not in suggested:
            return ()
        result = ["docker_workload"]
        if (
            _BACKEND_TRANSPORT in suggested
            and _single_backend_monitoring_endpoint(candidate) is not None
        ):
            result.append(_BACKEND_TRANSPORT)
        return tuple(result)

    def identity_matches(self, obj: Mapping[str, Any], candidate: Any) -> bool:
        evidence = _candidate_source(candidate, "portainer")
        if evidence is None:
            return False
        for provider in _providers(obj):
            config = provider.get("config", {})
            if (
                provider.get("adapter") == "portainer"
                and isinstance(config, Mapping)
                and config.get("workload_identity") == evidence.source_id
            ):
                return True
        return False

    def policy_hint(self, candidate: Any) -> str | None:
        evidence = _candidate_source(candidate, "portainer")
        if evidence is None:
            return None
        explicit = evidence.metadata.get("policy_hint")
        if explicit in {"optional", "required"}:
            return str(explicit)
        hint = evidence.metadata.get("required_hint")
        if hint is True:
            return "required"
        if hint is False:
            return "optional"
        return None

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
        if getattr(candidate, "kind", None) != "service" or _candidate_source(candidate, "portainer") is None:
            raise web.HTTPBadRequest(text="Portainer discovery adoption requires Portainer service evidence")
        selected = _selected_capabilities(candidate, capabilities)
        working = copy.deepcopy(working)
        site = _site(working, site_id)
        existing_ids = {
            str(obj.get("id"))
            for obj in site.get("objects", [])
            if isinstance(obj, dict) and isinstance(obj.get("id"), str)
        }
        addresses = tuple(getattr(candidate, "addresses", ()) or ())
        seed = addresses[0] if addresses else str(getattr(candidate, "candidate_id", "workload"))
        object_id = _unique_object_id(label, seed, existing_ids)
        resolved_policy = policy or self.policy_hint(candidate) or "optional"
        obj = _workload_object(
            working,
            site_id,
            object_id,
            label,
            candidate,
            resolved_policy,
            selected,
        )
        site.setdefault("objects", []).append(obj)
        obj["discovery"] = {
            "sources": sorted(
                {f"{e.source}:{e.source_id}" for e in getattr(candidate, "evidence", ())}
            ),
            "mac": getattr(candidate, "mac", None),
        }
        return object_id, working
