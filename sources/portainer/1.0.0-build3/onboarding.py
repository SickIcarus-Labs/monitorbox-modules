from __future__ import annotations

import json
import re
from typing import Any, Mapping

from ...plugin_api import (
    AddObjectIntent,
    ConnectionPlan,
    ConnectionRequest,
    CredentialSecretWrite,
    DiscoveryConfidence,
    DiscoveryEvidence,
    DiscoveryRequest,
    FacetContext,
    IdentityKey,
    PresentationDescriptor,
    PresentationField,
    RuntimeIntent,
)

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _slug(value: Any) -> str:
    text = _ID_CLEAN_RE.sub("_", str(value or "portainer").casefold()).strip("_")
    if not text:
        text = "portainer"
    if not text[0].isalpha():
        text = f"portainer_{text}"
    return text[:64]


def _unique_object_id(context: FacetContext, base: str = "portainer") -> str:
    clean = _slug(base)
    site = next(
        (
            item
            for item in context.current_config.get("sites", [])
            if isinstance(item, Mapping) and item.get("id") == context.site_id
        ),
        None,
    )
    used = {
        str(item.get("id"))
        for item in (site.get("objects", []) if isinstance(site, Mapping) else [])
        if isinstance(item, Mapping)
    }
    if clean not in used:
        return clean
    index = 2
    while True:
        suffix = f"_{index}"
        candidate = f"{clean[:64-len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        index += 1


def _environment_ids(value: Any) -> list[int]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",") if item.strip()]
        try:
            result = [int(item) for item in raw]
        except ValueError as exc:
            raise ValueError("Portainer environment IDs must be comma-separated positive integers") from exc
    elif isinstance(value, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        result = list(value)
    else:
        raise ValueError("Portainer environment IDs must be comma-separated positive integers")
    if any(item <= 0 for item in result):
        raise ValueError("Portainer environment IDs must be positive integers")
    return list(dict.fromkeys(result))


def _merged_values(request: ConnectionRequest) -> dict[str, Any]:
    values = dict(request.candidate.values)
    values.update(dict(request.values))
    return values


def _normalized(request: ConnectionRequest) -> dict[str, Any]:
    values = _merged_values(request)
    base_url = values.get("base_url")
    if not base_url and request.candidate.endpoint.casefold().startswith(("http://", "https://")):
        base_url = request.candidate.endpoint
    base_url = _text(base_url, "Portainer URL").rstrip("/")
    if not base_url.casefold().startswith(("http://", "https://")):
        raise ValueError("Portainer URL must use http:// or https://")
    verify_tls = values.get("verify_tls", True)
    if not isinstance(verify_tls, bool):
        raise ValueError("Portainer verify_tls must be boolean")
    return {
        "label": _text(values.get("label", "Docker via Portainer"), "Portainer label"),
        "base_url": base_url,
        "api_key": _text(values.get("api_key"), "Portainer API key"),
        "verify_tls": verify_tls,
        "environment_ids": _environment_ids(values.get("environment_ids", "")),
    }


def _looks_like_portainer(response: Any) -> bool:
    if response is None or not (200 <= int(response.status) < 500):
        return False
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, Mapping):
        keys = {str(key).casefold() for key in payload}
        if "version" in keys and ({"instanceid", "edition"} & keys):
            return True
    headers = getattr(response, "headers", {})
    server = str(headers.get("server", "") if isinstance(headers, Mapping) else "").casefold()
    return "portainer" in server


class PortainerIntegration:
    """Provider-local Portainer discovery, onboarding identity, and runtime intent."""

    async def detect(self, request: DiscoveryRequest, context: FacetContext, probe) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        result: list[DiscoveryEvidence] = []
        for scheme, port in (("https", 9443), ("http", 9000)):
            if not await probe.tcp_open(host, port):
                continue
            endpoint = f"{scheme}://{host}:{port}"
            response = await probe.http_get(f"{endpoint}/api/status")
            if _looks_like_portainer(response):
                result.append(
                    DiscoveryEvidence(
                        plugin_id="portainer",
                        system_id=request.system_id,
                        kind="portainer",
                        label="Docker via Portainer",
                        endpoint=endpoint,
                        confidence=DiscoveryConfidence.DETECTED,
                        evidence="Portainer API status endpoint identified the service",
                        default_selected=True,
                        values={"base_url": endpoint},
                    )
                )
            else:
                result.append(
                    DiscoveryEvidence(
                        plugin_id="portainer",
                        connection_plugin_id="http",
                        system_id=request.system_id,
                        kind="http",
                        label=f"HTTP(S) service on {port}",
                        endpoint=endpoint,
                        confidence=DiscoveryConfidence.POSSIBLE,
                        evidence=f"TCP/{port} is open but the service was not positively identified",
                        default_selected=False,
                        values={"url": endpoint},
                    )
                )
        return tuple(result)

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = _text(local.get("agent_id") if isinstance(local, Mapping) else None, "local agent id")
        prefix = re.sub(r"[^A-Z0-9_]+", "_", object_id.upper()).strip("_") or "PORTAINER"
        api_key_env = f"MONITORBOX_{prefix}_API_KEY"
        api_key_secret = _slug(f"{object_id}_api_key")
        config: dict[str, Any] = {
            "base_url": values["base_url"],
            "api_key_env": api_key_env,
            "operation": "inventory",
            "verify_tls": values["verify_tls"],
            "scheduler_jitter_seconds": 10,
            "scheduler_failure_backoff_factor": 2,
            "scheduler_failure_backoff_max_seconds": 300,
        }
        if values["environment_ids"]:
            config["environment_ids"] = list(values["environment_ids"])
        obj = {
            "id": object_id,
            "label": values["label"],
            "kind": "integration",
            "address": values["base_url"],
            "depends_on": [request.candidate.system_id],
            "icon": "portainer",
            "capabilities": [{
                "id": "docker_inventory",
                "kind": "docker_inventory",
                "label": "Docker inventory via Portainer",
                "enabled": True,
                "providers": [{
                    "id": "portainer",
                    "label": "Docker inventory via Portainer",
                    "adapter": "portainer",
                    "agent_id": agent_id,
                    "check_id": f"{object_id}_inventory",
                    "enabled": True,
                    "interval_seconds": 60,
                    "timeout_seconds": 15,
                    "config": config,
                }],
            }],
        }
        return ConnectionPlan(
            plugin_id="portainer",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            secret_writes=(CredentialSecretWrite(secret_id=api_key_secret, value=values["api_key"], env_name=api_key_env),),
            object_ids=(object_id,),
        )

    def identities(self, evidence, context: FacetContext) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            endpoint = str(evidence.values.get("base_url") or evidence.endpoint).rstrip("/")
            return (IdentityKey("portainer-endpoint", endpoint.casefold(), 100),)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="portainer",
            title="Docker via Portainer",
            fields=(
                PresentationField(key="base_url", label="Portainer URL", required=True),
                PresentationField(key="api_key", label="API key", required=True, secret=True),
                PresentationField(key="environment_ids", label="Environment IDs"),
                PresentationField(key="verify_tls", label="Verify TLS"),
            ),
            provenance_keys=("transport", "authoritative"),
        )

    def build_runtime_intent(self, request: ConnectionRequest, context: FacetContext) -> RuntimeIntent:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = local.get("agent_id") if isinstance(local, Mapping) else None
        prefix = re.sub(r"[^A-Z0-9_]+", "_", object_id.upper()).strip("_") or "PORTAINER"
        config: dict[str, Any] = {
            "base_url": values["base_url"],
            "api_key_env": f"MONITORBOX_{prefix}_API_KEY",
            "operation": "inventory",
            "verify_tls": values["verify_tls"],
            "scheduler_jitter_seconds": 10,
            "scheduler_failure_backoff_factor": 2,
            "scheduler_failure_backoff_max_seconds": 300,
        }
        if values["environment_ids"]:
            config["environment_ids"] = list(values["environment_ids"])
        return RuntimeIntent(
            plugin_id="portainer",
            checks=({
                "id": f"{object_id}_inventory",
                "adapter": "portainer",
                "object_id": object_id,
                "agent_id": agent_id,
                "interval_seconds": 60,
                "timeout_seconds": 15,
                "config": config,
            },),
        )
