from __future__ import annotations

import asyncio
import copy
import os
import re
import secrets
from collections.abc import Callable
from typing import Any, Mapping

from ...adapters import AdapterRunner
from ...config import CheckConfig
from ...model import State
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
    IntegrationDefinition,
    ModuleManifest,
    PluginMetadata,
    PresentationDescriptor,
    PresentationField,
    RuntimeIntent,
    ValidationResult,
)

MODULE_ID = "com.sickicarus.monitorbox.http"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")
_ENV_SAFE_RE = re.compile(r"[^A-Z0-9_]+")
_HTTP_HEADER_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_ACCEPTED_STATES = frozenset({State.HEALTHY, State.DEGRADED})
_TLS_TRUST_MARKERS = (
    "self-signed certificate",
    "self signed certificate",
    "unable to get local issuer certificate",
    "unable to verify the first certificate",
    "certificate chain too long",
    "unknown ca",
)
_ENV_LOCK = asyncio.Lock()
_PROBES: tuple[tuple[str, int, str], ...] = (
    ("https", 443, "HTTPS service"),
    ("http", 80, "HTTP service"),
    ("https", 8443, "HTTPS management service"),
    ("https", 9090, "Management service"),
)


def _slug(value: Any) -> str:
    text = _ID_CLEAN_RE.sub("_", str(value or "connection").casefold()).strip("_")
    if not text:
        text = "connection"
    if not text[0].isalpha():
        text = f"connection_{text}"
    return text[:64]


def _unique_object_id(context: FacetContext, base: str) -> str:
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


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _optional_text(value: Any, where: str, *, maximum: int) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{where} must be text")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{where} must be at most {maximum} characters")
    return text


def _header_name(value: Any, where: str) -> str:
    text = _optional_text(value, where, maximum=128)
    if text and not _HTTP_HEADER_RE.fullmatch(text):
        raise ValueError(f"{where} contains an invalid HTTP header name")
    return text


def _boolean(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{where} must be true or false")


def _statuses(value: Any) -> list[int]:
    if isinstance(value, list):
        if not value or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
            raise ValueError("HTTP statuses must be a non-empty integer list or comma-separated set/range")
        statuses = list(value)
    elif isinstance(value, str):
        statuses = []
        for token in (item.strip() for item in value.split(",")):
            if not token:
                continue
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                try:
                    start, end = int(start_text), int(end_text)
                except ValueError as exc:
                    raise ValueError("HTTP status ranges must use integers such as 200-204") from exc
                if end < start or end - start > 99:
                    raise ValueError("HTTP status ranges must be ascending and at most 100 codes wide")
                statuses.extend(range(start, end + 1))
            else:
                try:
                    statuses.append(int(token))
                except ValueError as exc:
                    raise ValueError("HTTP statuses must use integers such as 200,204,401") from exc
        if not statuses:
            raise ValueError("HTTP statuses must not be empty")
    else:
        raise ValueError("HTTP statuses must be a non-empty integer list or comma-separated set/range")
    normalized = sorted(set(statuses))
    if len(normalized) > 100 or any(not 100 <= item <= 599 for item in normalized):
        raise ValueError("HTTP statuses must contain at most 100 codes in the range 100..599")
    return normalized


def _bounded_number(value: Any, where: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{where} must be {minimum:g}..{maximum:g}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} must be {minimum:g}..{maximum:g}") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{where} must be {minimum:g}..{maximum:g}")
    return number


def _env_prefix(value: str) -> str:
    result = _ENV_SAFE_RE.sub("_", value.upper()).strip("_")
    if not result or not result[0].isalpha():
        result = "INTEGRATION_" + result
    return result


def _merged_values(request: ConnectionRequest) -> dict[str, Any]:
    values = dict(request.candidate.values)
    values.update(dict(request.values))
    return values


def _normalized(values: Mapping[str, Any], candidate: DiscoveryEvidence) -> dict[str, Any]:
    url = _text(values.get("url", candidate.endpoint), "HTTP URL")
    if not url.casefold().startswith(("http://", "https://")):
        raise ValueError("HTTP URL must use http:// or https://")
    result: dict[str, Any] = {
        "label": _text(values.get("label", candidate.label or "HTTP(S) service"), "HTTP label"),
        "url": url,
        "statuses": _statuses(values.get("statuses", [200])),
        "follow_redirects": _boolean(values.get("follow_redirects", True), "follow_redirects"),
        "verify_tls": _boolean(values.get("verify_tls", True), "verify_tls"),
        "timeout_seconds": _bounded_number(values.get("timeout_seconds", 5), "HTTP timeout", minimum=0.5, maximum=60),
    }
    contains = _optional_text(values.get("contains"), "HTTP expected body text", maximum=512)
    if contains:
        result["contains"] = contains
    response_name = _header_name(values.get("response_header_name"), "HTTP expected response header")
    response_value = _optional_text(values.get("response_header_value"), "HTTP expected response header value", maximum=512)
    if bool(response_name) != bool(response_value):
        raise ValueError("HTTP response-header assertion requires both header name and expected value")
    if response_name:
        result["response_header_name"] = response_name
        result["response_header_value"] = response_value
    latency = values.get("latency_warning_ms")
    if latency not in (None, ""):
        result["latency_warning_ms"] = _bounded_number(latency, "HTTP latency warning", minimum=1, maximum=300000)
    request_name = _header_name(values.get("request_header_name"), "HTTP protected request header")
    request_value = _optional_text(values.get("request_header_value"), "HTTP protected request header value", maximum=4096)
    if bool(request_name) != bool(request_value):
        raise ValueError("HTTP protected request header requires both header name and value")
    if request_name:
        result["request_header_name"] = request_name
        result["request_header_value"] = request_value
    return result


def _config(values: Mapping[str, Any], *, request_env: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "url": values["url"],
        "method": "GET",
        "statuses": list(values["statuses"]),
        "follow_redirects": bool(values["follow_redirects"]),
        "verify_tls": bool(values["verify_tls"]),
    }
    if values.get("contains"):
        config["contains"] = values["contains"]
    if values.get("response_header_name"):
        config["header"] = {values["response_header_name"]: values["response_header_value"]}
    if "latency_warning_ms" in values:
        config["latency_warning_ms"] = values["latency_warning_ms"]
    if values.get("request_header_name") and request_env:
        config["request_header_name"] = values["request_header_name"]
        config["request_header_value_env"] = request_env
    return config


def _scrub(value: Any, secrets_to_remove: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item, secrets_to_remove) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, secrets_to_remove) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, secrets_to_remove) for item in value)
    if isinstance(value, str):
        result = value
        for secret_value in secrets_to_remove:
            if secret_value:
                result = result.replace(secret_value, "[protected]")
        return result
    return value


class HttpIntegration:
    """Generic HTTP(S) Connection policy over the shared HTTP adapter."""

    def __init__(self, *, runner_factory: Callable[[], AdapterRunner] = AdapterRunner) -> None:
        self._runner_factory = runner_factory

    async def detect(self, request: DiscoveryRequest, context: FacetContext, probe) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        results: list[DiscoveryEvidence] = []
        for scheme, port, hint in _PROBES:
            if not await probe.tcp_open(host, port):
                continue
            endpoint = f"{scheme}://{host}:{port}"
            results.append(
                DiscoveryEvidence(
                    plugin_id="http",
                    system_id=request.system_id,
                    kind="http",
                    label=hint,
                    endpoint=endpoint,
                    confidence=DiscoveryConfidence.POSSIBLE,
                    evidence=f"TCP/{port} is open; product identity requires validation",
                    default_selected=False,
                    values={"url": endpoint},
                )
            )
        return tuple(results)

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized(_merged_values(request), request.candidate)
        object_id = _unique_object_id(context, values["label"] or "service")
        agent_id = _text(context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"), "local agent id")
        secret_writes: tuple[CredentialSecretWrite, ...] = ()
        request_env: str | None = None
        if values.get("request_header_name"):
            request_env = f"MONITORBOX_{_env_prefix(object_id)}_HTTP_HEADER"
            secret_id = _slug(f"{object_id}_http_header")
            secret_writes = (
                CredentialSecretWrite(
                    secret_id=secret_id,
                    value=values["request_header_value"],
                    env_name=request_env,
                ),
            )
        obj: dict[str, Any] = {
            "id": object_id,
            "label": values["label"],
            "kind": "service",
            "depends_on": [request.candidate.system_id],
            "capabilities": [
                {
                    "id": "http",
                    "kind": "http",
                    "label": "HTTP(S) health",
                    "enabled": True,
                    "providers": [
                        {
                            "id": "http",
                            "label": "HTTP(S) health",
                            "adapter": "http",
                            "agent_id": agent_id,
                            "check_id": f"{object_id}_http",
                            "enabled": True,
                            "interval_seconds": 30,
                            "timeout_seconds": values["timeout_seconds"],
                            "config": _config(values, request_env=request_env),
                        }
                    ],
                }
            ],
        }
        return ConnectionPlan(
            plugin_id="http",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            secret_writes=secret_writes,
            object_ids=(object_id,),
        )

    async def validate(self, request: ConnectionRequest, context: FacetContext) -> ValidationResult:
        values = _normalized(_merged_values(request), request.candidate)
        result = await self._validate_once(request, context, values)
        if result.accepted:
            return result
        if values["verify_tls"] and any(marker in result.summary.casefold() for marker in _TLS_TRUST_MARKERS):
            fallback_values = dict(values)
            fallback_values["verify_tls"] = False
            fallback = await self._validate_once(request, context, fallback_values)
            if fallback.accepted:
                observation = copy.deepcopy(dict(fallback.observation))
                metadata = observation.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    observation["metadata"] = metadata
                metadata["tls_trust_fallback"] = True
                normalized_values = dict(fallback.values)
                normalized_values["verify_tls"] = False
                return ValidationResult(
                    accepted=True,
                    state=fallback.state,
                    summary=("Validated after accepting the provider's untrusted local TLS certificate: " + fallback.summary)[:400],
                    observation=observation,
                    metadata={"transport": "http", "tls_trust_fallback": True},
                    values=normalized_values,
                )
        return result

    async def _validate_once(self, request: ConnectionRequest, context: FacetContext, values: Mapping[str, Any]) -> ValidationResult:
        agent_id = _text(context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"), "local agent id")
        temporary_env: dict[str, str] = {}
        secret_values: tuple[str, ...] = ()
        request_env: str | None = None
        if values.get("request_header_name"):
            request_env = f"MONITORBOX_ONBOARDING_{secrets.token_hex(12).upper()}"
            temporary_env[request_env] = values["request_header_value"]
            secret_values = (values["request_header_value"],)
        check = CheckConfig(
            id="http_validation",
            object_id=request.candidate.system_id,
            label="HTTP(S) health",
            adapter="http",
            interval_seconds=30,
            timeout_seconds=values["timeout_seconds"],
            enabled=True,
            options=_config(values, request_env=request_env),
            agent_id=agent_id,
            capability_id=None,
            capability_kind=None,
        )
        runner = self._runner_factory()
        async with _ENV_LOCK:
            previous = {name: os.environ.get(name) for name in temporary_env}
            try:
                for name, value in temporary_env.items():
                    os.environ[name] = value
                await runner.start()
                observation = await runner.run(check)
            finally:
                try:
                    await runner.close()
                finally:
                    for name, old_value in previous.items():
                        if old_value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = old_value
        public = _scrub(observation.as_dict(), secret_values)
        normalized_values = {key: value for key, value in values.items() if key != "request_header_value"}
        if values.get("request_header_value"):
            normalized_values["request_header_value"] = values["request_header_value"]
        return ValidationResult(
            accepted=observation.state in _ACCEPTED_STATES,
            state=observation.state.value,
            summary=str(public.get("summary") or "Provider validation completed")[:400],
            observation=public,
            metadata={"transport": "http"},
            values=normalized_values,
        )

    def identities(self, evidence, context: FacetContext) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            return (IdentityKey("http-url", evidence.endpoint.rstrip("/"), 100),)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="http",
            title="HTTP(S) endpoint",
            fields=(
                PresentationField(key="label", label="Label", required=True),
                PresentationField(key="url", label="URL", required=True),
                PresentationField(key="statuses", label="Accepted statuses", required=True),
                PresentationField(key="verify_tls", label="Verify TLS", field_type="boolean", required=True),
                PresentationField(key="follow_redirects", label="Follow redirects", field_type="boolean", required=True),
                PresentationField(key="contains", label="Expected body text"),
                PresentationField(key="response_header_name", label="Expected response header"),
                PresentationField(key="response_header_value", label="Expected response header value"),
                PresentationField(key="latency_warning_ms", label="Latency warning (ms)", field_type="number"),
                PresentationField(key="request_header_name", label="Protected request header"),
                PresentationField(key="request_header_value", label="Protected request header value", secret=True),
            ),
            provenance_keys=("transport", "tls_trust_fallback"),
        )

    def build_runtime_intent(self, request: ConnectionRequest, context: FacetContext) -> RuntimeIntent:
        values = _normalized(_merged_values(request), request.candidate)
        object_id = _unique_object_id(context, values["label"] or "service")
        request_env = None
        if values.get("request_header_name"):
            request_env = f"MONITORBOX_{_env_prefix(object_id)}_HTTP_HEADER"
        return RuntimeIntent(
            plugin_id="http",
            checks=(
                {
                    "id": f"{object_id}_http",
                    "adapter": "http",
                    "object_id": object_id,
                    "agent_id": context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
                    "interval_seconds": 30,
                    "timeout_seconds": values["timeout_seconds"],
                    "config": _config(values, request_env=request_env),
                },
            ),
        )


_HTTP = HttpIntegration()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="http", display_name="HTTP(S) endpoint"),
    connection_kinds=("http", "http_service"),
    discovery=_HTTP,
    connection=_HTTP,
    validation=_HTTP,
    identity=_HTTP,
    presentation=_HTTP,
    runtime=_HTTP,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="HTTP(S) Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.http:PLUGIN"},
    requires_core=">=2.2.2 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
)

__all__ = [
    "HttpIntegration",
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_MANIFEST",
    "MODULE_VERSION",
    "PLUGIN",
]
