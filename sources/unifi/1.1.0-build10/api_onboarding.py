from __future__ import annotations

import asyncio
import copy
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ...plugin_api import (
    AddObjectIntent,
    ConnectionPlan,
    ConnectionRequest,
    CredentialSecretWrite,
    FacetContext,
    PresentationDescriptor,
    PresentationField,
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeIntent,
    ValidationResult,
)
from .api_migration import UniFiApiMigrationRuntimeExecutor
from .onboarding import (
    UniFiIntegration as _LegacyUniFiIntegration,
    _ACCEPTED_STATES,
    _ENV_LOCK,
    _TLS_TRUST_MARKERS,
    _boolean,
    _env_prefix,
    _merged_values,
    _scrub,
    _slug,
    _text,
    _unique_object_id,
)
from .runtime import MODULE_ID


def _normalized_dual(request: ConnectionRequest) -> dict[str, Any]:
    values = _merged_values(request)
    base_url = values.get("base_url")
    if not base_url and request.candidate.endpoint.casefold().startswith(("http://", "https://")):
        base_url = request.candidate.endpoint
    base_url = _text(base_url, "UniFi base URL").rstrip("/")
    if not base_url.casefold().startswith(("http://", "https://")):
        raise ValueError("UniFi base URL must use http:// or https://")
    mode = str(values.get("auth_mode") or "username_password").strip().casefold()
    if mode not in {"username_password", "api_key"}:
        raise ValueError("UniFi auth mode must be username_password or api_key")
    normalized: dict[str, Any] = {
        "label": _text(values.get("label", "UniFi Network"), "UniFi label"),
        "base_url": base_url,
        "auth_mode": mode,
        "network_site": _text(values.get("network_site", "default"), "UniFi site"),
        "verify_tls": _boolean(values.get("verify_tls", False), "verify_tls"),
        "legacy_read_enabled": _boolean(
            values.get("legacy_read_enabled", False), "legacy_read_enabled"
        ),
    }
    if mode == "username_password":
        normalized["username"] = _text(values.get("username"), "UniFi username")
        normalized["password"] = _text(values.get("password"), "UniFi password")
        normalized["legacy_read_enabled"] = False
    else:
        normalized["api_key"] = _text(values.get("api_key"), "UniFi Integration API key")
        if normalized["legacy_read_enabled"]:
            normalized["legacy_read_username"] = _text(
                values.get("legacy_read_username"), "legacy-read username"
            )
            normalized["legacy_read_password"] = _text(
                values.get("legacy_read_password"), "legacy-read password"
            )
    return normalized


def _provider_config_dual(
    values: Mapping[str, Any],
    *,
    username_env: str | None = None,
    password_env: str | None = None,
    api_key_env: str | None = None,
    legacy_username_env: str | None = None,
    legacy_password_env: str | None = None,
) -> dict[str, Any]:
    mode = str(values["auth_mode"])
    result: dict[str, Any] = {
        "base_url": values["base_url"],
        "site": values["network_site"],
        "auth_mode": mode,
        "verify_tls": bool(values["verify_tls"]),
    }
    if mode == "username_password":
        if not username_env or not password_env:
            raise ValueError("legacy auth requires username/password environment references")
        result["username_env"] = username_env
        result["password_env"] = password_env
        return result
    if not api_key_env:
        raise ValueError("api-key auth requires api_key environment reference")
    result["api_key_env"] = api_key_env
    result["official_prefix"] = "/proxy/network/integration"
    if values.get("legacy_read_enabled") is True:
        if not legacy_username_env or not legacy_password_env:
            raise ValueError("legacy-read companion requires explicit environment references")
        result["legacy_read"] = {
            "enabled": True,
            "site": values["network_site"],
            "username_env": legacy_username_env,
            "password_env": legacy_password_env,
        }
    return result


class UniFiApiIntegration(_LegacyUniFiIntegration):
    """Onboarding/configuration surface for explicit UniFi dual-backend auth."""

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized_dual(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = _text(
            local.get("agent_id") if isinstance(local, Mapping) else None,
            "local agent id",
        )
        prefix = _env_prefix(object_id)
        secret_writes: list[CredentialSecretWrite] = []
        kwargs: dict[str, str | None] = {
            "username_env": None,
            "password_env": None,
            "api_key_env": None,
            "legacy_username_env": None,
            "legacy_password_env": None,
        }
        if values["auth_mode"] == "username_password":
            kwargs["username_env"] = f"MONITORBOX_{prefix}_USERNAME"
            kwargs["password_env"] = f"MONITORBOX_{prefix}_PASSWORD"
            secret_writes.extend((
                CredentialSecretWrite(
                    secret_id=_slug(f"{object_id}_username"),
                    value=values["username"],
                    env_name=kwargs["username_env"],
                ),
                CredentialSecretWrite(
                    secret_id=_slug(f"{object_id}_password"),
                    value=values["password"],
                    env_name=kwargs["password_env"],
                ),
            ))
        else:
            kwargs["api_key_env"] = f"MONITORBOX_{prefix}_API_KEY"
            secret_writes.append(
                CredentialSecretWrite(
                    secret_id=_slug(f"{object_id}_api_key"),
                    value=values["api_key"],
                    env_name=kwargs["api_key_env"],
                )
            )
            if values.get("legacy_read_enabled") is True:
                kwargs["legacy_username_env"] = f"MONITORBOX_{prefix}_LEGACY_READ_USERNAME"
                kwargs["legacy_password_env"] = f"MONITORBOX_{prefix}_LEGACY_READ_PASSWORD"
                secret_writes.extend((
                    CredentialSecretWrite(
                        secret_id=_slug(f"{object_id}_legacy_read_username"),
                        value=values["legacy_read_username"],
                        env_name=kwargs["legacy_username_env"],
                    ),
                    CredentialSecretWrite(
                        secret_id=_slug(f"{object_id}_legacy_read_password"),
                        value=values["legacy_read_password"],
                        env_name=kwargs["legacy_password_env"],
                    ),
                ))
        provider_config = _provider_config_dual(values, **kwargs)
        obj = {
            "id": object_id,
            "label": values["label"],
            "kind": "integration",
            "address": values["base_url"],
            "depends_on": [request.candidate.system_id],
            "capabilities": [{
                "id": "unifi_network",
                "kind": "unifi_network",
                "label": "UniFi Network",
                "enabled": True,
                "providers": [{
                    "id": "unifi",
                    "label": "UniFi Network",
                    "adapter": "unifi",
                    "agent_id": agent_id,
                    "check_id": f"{object_id}_network",
                    "enabled": True,
                    "interval_seconds": 30,
                    "timeout_seconds": 10,
                    "config": provider_config,
                }],
            }],
        }
        return ConnectionPlan(
            plugin_id="unifi",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            secret_writes=tuple(secret_writes),
            object_ids=(object_id,),
        )

    async def validate(
        self, request: ConnectionRequest, context: FacetContext
    ) -> ValidationResult:
        values = _normalized_dual(request)
        first = await self._validate_dual_once(request, context, values)
        if first.accepted:
            return first
        if values["verify_tls"] and any(
            marker in first.summary.casefold() for marker in _TLS_TRUST_MARKERS
        ):
            fallback_values = dict(values)
            fallback_values["verify_tls"] = False
            fallback = await self._validate_dual_once(request, context, fallback_values)
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
                    metadata={
                        "transport": "unifi",
                        "auth_mode": values["auth_mode"],
                        "tls_trust_fallback": True,
                    },
                    values=normalized_values,
                )
        return first

    async def _validate_dual_once(
        self,
        request: ConnectionRequest,
        context: FacetContext,
        values: Mapping[str, Any],
    ) -> ValidationResult:
        del context
        temp_names: dict[str, str] = {}
        kwargs: dict[str, str | None] = {
            "username_env": None,
            "password_env": None,
            "api_key_env": None,
            "legacy_username_env": None,
            "legacy_password_env": None,
        }

        def bind(arg: str, value: str) -> None:
            env_name = f"MONITORBOX_ONBOARDING_{secrets.token_hex(12).upper()}"
            kwargs[arg] = env_name
            temp_names[env_name] = value

        if values["auth_mode"] == "username_password":
            bind("username_env", str(values["username"]))
            bind("password_env", str(values["password"]))
        else:
            bind("api_key_env", str(values["api_key"]))
            if values.get("legacy_read_enabled") is True:
                bind("legacy_username_env", str(values["legacy_read_username"]))
                bind("legacy_password_env", str(values["legacy_read_password"]))
        protected = tuple(temp_names.values())
        options = _provider_config_dual(values, **kwargs)
        execution = RuntimeExecutionRequest(
            check_id="unifi_validation",
            object_id=request.candidate.system_id,
            adapter="unifi",
            timeout_seconds=10,
            options=options,
        )
        executor = UniFiApiMigrationRuntimeExecutor()
        result = None
        with tempfile.TemporaryDirectory(prefix="monitorbox-unifi-validation-") as temp:
            execution_context = RuntimeExecutionContext(
                module_id=MODULE_ID,
                package_root=str(Path(temp) / "package"),
                state_root=str(Path(temp) / "state"),
            )
            async with _ENV_LOCK:
                previous = {name: os.environ.get(name) for name in temp_names}
                try:
                    os.environ.update(temp_names)
                    await executor.start(execution_context)
                    try:
                        async with asyncio.timeout(execution.timeout_seconds):
                            result = await executor.execute(execution, execution_context)
                    except TimeoutError:
                        result = None
                except Exception as exc:
                    public = _scrub({
                        "state": "failed",
                        "summary": f"{type(exc).__name__}: {exc}"[:400],
                        "duration_ms": 0,
                        "metrics": {},
                        "metadata": {"failure_kind": "adapter_exception"},
                    }, protected)
                    return ValidationResult(
                        accepted=False,
                        state="failed",
                        summary=str(public["summary"]),
                        observation=public,
                        metadata={
                            "transport": "unifi",
                            "auth_mode": values["auth_mode"],
                        },
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
        public = (
            {
                "state": "failed",
                "summary": "Timed out after 10s",
                "duration_ms": 10000,
                "metrics": {},
                "metadata": {},
            }
            if result is None
            else result.public()
        )
        public = _scrub(public, protected)
        state = str(public.get("state") or "failed")
        summary = str(public.get("summary") or "UniFi validation completed")[:400]
        return ValidationResult(
            accepted=state in _ACCEPTED_STATES,
            state=state,
            summary=summary,
            observation=public,
            metadata={
                "transport": "unifi",
                "auth_mode": values["auth_mode"],
            },
            values=dict(values),
        )

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="unifi",
            title="UniFi Network",
            fields=(
                PresentationField(key="base_url", label="UniFi base URL", required=True),
                PresentationField(
                    key="auth_mode",
                    label="Authentication mode",
                    required=True,
                    choices=("api_key", "username_password"),
                    help_text="Choose explicitly. API-key mode never silently falls back to a user session.",
                ),
                PresentationField(
                    key="api_key",
                    label="Integration API key",
                    secret=True,
                    help_text="Required only for api_key mode.",
                ),
                PresentationField(
                    key="username",
                    label="Username",
                    secret=True,
                    help_text="Required only for username_password mode.",
                ),
                PresentationField(
                    key="password",
                    label="Password",
                    secret=True,
                    help_text="Required only for username_password mode.",
                ),
                PresentationField(
                    key="legacy_read_enabled",
                    label="Enable explicit legacy-read companion",
                    field_type="boolean",
                    help_text=(
                        "Optional in API-key mode. Required for provider-authoritative physical "
                        "topology, detailed traffic flows, and rich WAN/VPN status on Network 10.6.101."
                    ),
                ),
                PresentationField(
                    key="legacy_read_username",
                    label="Legacy-read username",
                    secret=True,
                    help_text="Required only when the explicit legacy-read companion is enabled.",
                ),
                PresentationField(
                    key="legacy_read_password",
                    label="Legacy-read password",
                    secret=True,
                    help_text="Required only when the explicit legacy-read companion is enabled.",
                ),
                PresentationField(
                    key="network_site", label="UniFi site", required=True
                ),
                PresentationField(
                    key="verify_tls", label="Verify TLS", field_type="boolean"
                ),
            ),
            provenance_keys=(
                "transport",
                "auth_mode",
                "tls_trust_fallback",
                "provider_backend",
            ),
        )

    def build_runtime_intent(
        self, request: ConnectionRequest, context: FacetContext
    ) -> RuntimeIntent:
        values = _normalized_dual(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = local.get("agent_id") if isinstance(local, Mapping) else None
        prefix = _env_prefix(object_id)
        kwargs: dict[str, str | None] = {
            "username_env": None,
            "password_env": None,
            "api_key_env": None,
            "legacy_username_env": None,
            "legacy_password_env": None,
        }
        if values["auth_mode"] == "username_password":
            kwargs["username_env"] = f"MONITORBOX_{prefix}_USERNAME"
            kwargs["password_env"] = f"MONITORBOX_{prefix}_PASSWORD"
        else:
            kwargs["api_key_env"] = f"MONITORBOX_{prefix}_API_KEY"
            if values.get("legacy_read_enabled") is True:
                kwargs["legacy_username_env"] = f"MONITORBOX_{prefix}_LEGACY_READ_USERNAME"
                kwargs["legacy_password_env"] = f"MONITORBOX_{prefix}_LEGACY_READ_PASSWORD"
        return RuntimeIntent(
            plugin_id="unifi",
            checks=({
                "id": f"{object_id}_network",
                "adapter": "unifi",
                "object_id": object_id,
                "agent_id": agent_id,
                "interval_seconds": 30,
                "timeout_seconds": 10,
                "config": _provider_config_dual(values, **kwargs),
            },),
        )


__all__ = [
    "UniFiApiIntegration",
    "_normalized_dual",
    "_provider_config_dual",
]
