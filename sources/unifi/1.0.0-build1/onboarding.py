from __future__ import annotations

import asyncio
import copy
import os
import re
import secrets
import tempfile
from pathlib import Path
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
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeIntent,
    ValidationResult,
)
from .runtime import MODULE_ID, UniFiRuntimeExecutor

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")
_ENV_SAFE_RE = re.compile(r"[^A-Z0-9_]+")
_ACCEPTED_STATES = frozenset({"healthy", "degraded"})
_TLS_TRUST_MARKERS = (
    "self-signed certificate",
    "self signed certificate",
    "unable to get local issuer certificate",
    "unable to verify the first certificate",
    "certificate chain too long",
    "unknown ca",
)
_ENV_LOCK = asyncio.Lock()


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


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


def _slug(value: Any) -> str:
    result = _ID_CLEAN_RE.sub("_", str(value or "unifi").casefold()).strip("_") or "unifi"
    if not result[0].isalpha():
        result = f"unifi_{result}"
    return result[:64]


def _env_prefix(value: str) -> str:
    result = _ENV_SAFE_RE.sub("_", value.upper()).strip("_")
    if not result or not result[0].isalpha():
        result = "INTEGRATION_" + result
    return result


def _unique_object_id(context: FacetContext, base: str = "unifi") -> str:
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


def _merged_values(request: ConnectionRequest) -> dict[str, Any]:
    values = dict(request.candidate.values)
    values.update(dict(request.values))
    return values


def _normalized(request: ConnectionRequest) -> dict[str, Any]:
    values = _merged_values(request)
    base_url = values.get("base_url")
    if not base_url and request.candidate.endpoint.casefold().startswith(("http://", "https://")):
        base_url = request.candidate.endpoint
    base_url = _text(base_url, "UniFi base URL").rstrip("/")
    if not base_url.casefold().startswith(("http://", "https://")):
        raise ValueError("UniFi base URL must use http:// or https://")
    return {
        "label": _text(values.get("label", "UniFi Network"), "UniFi label"),
        "base_url": base_url,
        "username": _text(values.get("username"), "UniFi username"),
        "password": _text(values.get("password"), "UniFi password"),
        "network_site": _text(values.get("network_site", "default"), "UniFi site"),
        "verify_tls": _boolean(values.get("verify_tls", False), "verify_tls"),
    }


def _looks_like_unifi(response: Any) -> bool:
    if not (200 <= int(response.status) < 500):
        return False
    try:
        import json

        payload = json.loads(response.body)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, Mapping):
        application = str(
            payload.get("application")
            or payload.get("app")
            or payload.get("name")
            or ""
        ).casefold()
        if "unifi" in application and "network" in application:
            return True
    server = str(response.headers.get("server", "")).casefold()
    return "unifi" in server


def _provider_config(
    values: Mapping[str, Any],
    *,
    username_env: str,
    password_env: str,
) -> dict[str, Any]:
    return {
        "base_url": values["base_url"],
        "site": values["network_site"],
        "username_env": username_env,
        "password_env": password_env,
        "verify_tls": bool(values["verify_tls"]),
    }


def _scrub(value: Any, protected: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {str(key): _scrub(item, protected) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, protected) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, protected) for item in value)
    if isinstance(value, str):
        result = value
        for secret in protected:
            if secret:
                result = result.replace(secret, "[protected]")
        return result
    return value


class UniFiIntegration:
    """Provider-local UniFi discovery, onboarding, validation and presentation policy."""

    async def detect(
        self,
        request: DiscoveryRequest,
        context: FacetContext,
        probe,
    ) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        if not await probe.tcp_open(host, 443):
            return ()
        for path in ("/status", "/api/status"):
            response = await probe.http_get(f"https://{host}{path}")
            if response and _looks_like_unifi(response):
                return (
                    DiscoveryEvidence(
                        plugin_id="unifi",
                        system_id=request.system_id,
                        kind="unifi",
                        label="UniFi Network",
                        confidence=DiscoveryConfidence.DETECTED,
                        endpoint=f"https://{host}",
                        evidence="UniFi Network status endpoint identified the controller",
                        default_selected=True,
                        values={
                            "base_url": f"https://{host}",
                            "network_site": "default",
                            "verify_tls": True,
                        },
                    ),
                )
        return ()

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = _text(local.get("agent_id") if isinstance(local, Mapping) else None, "local agent id")
        prefix = _env_prefix(object_id)
        username_env = f"MONITORBOX_{prefix}_USERNAME"
        password_env = f"MONITORBOX_{prefix}_PASSWORD"
        username_secret = _slug(f"{object_id}_username")
        password_secret = _slug(f"{object_id}_password")
        obj = {
            "id": object_id,
            "label": values["label"],
            "kind": "integration",
            "address": values["base_url"],
            "depends_on": [request.candidate.system_id],
            "capabilities": [
                {
                    "id": "unifi_network",
                    "kind": "unifi_network",
                    "label": "UniFi Network",
                    "enabled": True,
                    "providers": [
                        {
                            "id": "unifi",
                            "label": "UniFi Network",
                            "adapter": "unifi",
                            "agent_id": agent_id,
                            "check_id": f"{object_id}_network",
                            "enabled": True,
                            "interval_seconds": 30,
                            "timeout_seconds": 10,
                            "config": _provider_config(
                                values,
                                username_env=username_env,
                                password_env=password_env,
                            ),
                        }
                    ],
                }
            ],
        }
        return ConnectionPlan(
            plugin_id="unifi",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            secret_writes=(
                CredentialSecretWrite(
                    secret_id=username_secret,
                    value=values["username"],
                    env_name=username_env,
                ),
                CredentialSecretWrite(
                    secret_id=password_secret,
                    value=values["password"],
                    env_name=password_env,
                ),
            ),
            object_ids=(object_id,),
        )

    async def validate(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> ValidationResult:
        values = _normalized(request)
        first = await self._validate_once(request, context, values)
        if first.accepted:
            return first
        if values["verify_tls"] and any(
            marker in first.summary.casefold() for marker in _TLS_TRUST_MARKERS
        ):
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
                    summary=(
                        "Validated after accepting the provider's untrusted local TLS certificate: "
                        + fallback.summary
                    )[:400],
                    observation=observation,
                    metadata={"transport": "unifi", "tls_trust_fallback": True},
                    values=normalized_values,
                )
        return first

    async def _validate_once(
        self,
        request: ConnectionRequest,
        context: FacetContext,
        values: Mapping[str, Any],
    ) -> ValidationResult:
        del context
        username_env = f"MONITORBOX_ONBOARDING_{secrets.token_hex(12).upper()}"
        password_env = f"MONITORBOX_ONBOARDING_{secrets.token_hex(12).upper()}"
        temporary = {
            username_env: str(values["username"]),
            password_env: str(values["password"]),
        }
        protected = tuple(temporary.values())
        options = _provider_config(
            values,
            username_env=username_env,
            password_env=password_env,
        )
        execution = RuntimeExecutionRequest(
            check_id="unifi_validation",
            object_id=request.candidate.system_id,
            adapter="unifi",
            timeout_seconds=10,
            options=options,
        )
        executor = UniFiRuntimeExecutor()
        result = None
        with tempfile.TemporaryDirectory(prefix="monitorbox-unifi-validation-") as temp:
            execution_context = RuntimeExecutionContext(
                module_id=MODULE_ID,
                package_root=str(Path(temp) / "package"),
                state_root=str(Path(temp) / "state"),
            )
            async with _ENV_LOCK:
                previous = {name: os.environ.get(name) for name in temporary}
                try:
                    os.environ.update(temporary)
                    await executor.start(execution_context)
                    try:
                        async with asyncio.timeout(execution.timeout_seconds):
                            result = await executor.execute(execution, execution_context)
                    except TimeoutError:
                        result = None
                except Exception as exc:
                    public = {
                        "state": "failed",
                        "summary": f"{type(exc).__name__}: {exc}"[:400],
                        "duration_ms": 0,
                        "metrics": {},
                        "metadata": {"failure_kind": "adapter_exception"},
                    }
                    public = _scrub(public, protected)
                    return ValidationResult(
                        accepted=False,
                        state="failed",
                        summary=str(public["summary"]),
                        observation=public,
                        metadata={"transport": "unifi"},
                        values=dict(values),
                    )
                finally:
                    try:
                        await executor.close(execution_context)
                    finally:
                        for name, old in previous.items():
                            if old is None:
                                os.environ.pop(name, None)
                            else:
                                os.environ[name] = old
        if result is None:
            public = {
                "state": "failed",
                "summary": "Timed out after 10s",
                "duration_ms": 10000,
                "metrics": {},
                "metadata": {},
            }
        else:
            public = result.public()
        public = _scrub(public, protected)
        state = str(public.get("state") or "failed")
        summary = str(public.get("summary") or "UniFi validation completed")[:400]
        return ValidationResult(
            accepted=state in _ACCEPTED_STATES,
            state=state,
            summary=summary,
            observation=public,
            metadata={"transport": "unifi"},
            values=dict(values),
        )

    def identities(self, evidence, context: FacetContext) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            endpoint = str(evidence.values.get("base_url") or evidence.endpoint).rstrip("/")
            return (IdentityKey("unifi-endpoint", endpoint.casefold(), 100),)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="unifi",
            title="UniFi Network",
            fields=(
                PresentationField(key="base_url", label="UniFi base URL", required=True),
                PresentationField(key="username", label="Username", required=True, secret=True),
                PresentationField(key="password", label="Password", required=True, secret=True),
                PresentationField(key="network_site", label="UniFi site", required=True),
                PresentationField(key="verify_tls", label="Verify TLS", field_type="boolean"),
            ),
            provenance_keys=("transport", "tls_trust_fallback"),
        )

    def build_runtime_intent(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> RuntimeIntent:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = local.get("agent_id") if isinstance(local, Mapping) else None
        prefix = _env_prefix(object_id)
        return RuntimeIntent(
            plugin_id="unifi",
            checks=(
                {
                    "id": f"{object_id}_network",
                    "adapter": "unifi",
                    "object_id": object_id,
                    "agent_id": agent_id,
                    "interval_seconds": 30,
                    "timeout_seconds": 10,
                    "config": _provider_config(
                        values,
                        username_env=f"MONITORBOX_{prefix}_USERNAME",
                        password_env=f"MONITORBOX_{prefix}_PASSWORD",
                    ),
                },
            ),
        )
