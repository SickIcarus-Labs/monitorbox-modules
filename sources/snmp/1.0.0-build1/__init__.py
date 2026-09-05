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
    AddCapabilityIntent,
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

MODULE_ID = "com.sickicarus.monitorbox.snmp"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1

_ENV_SAFE_RE = re.compile(r"[^A-Z0-9_]+")
_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")
_ACCEPTED_STATES = frozenset({State.HEALTHY, State.DEGRADED})
_ENV_LOCK = asyncio.Lock()


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _port(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("SNMP port must be an integer")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("SNMP port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SNMP port must be in 1..65535")
    return port


def _slug(value: Any) -> str:
    text = _ID_CLEAN_RE.sub("_", str(value or "snmp").casefold()).strip("_") or "snmp"
    if not text[0].isalpha():
        text = f"snmp_{text}"
    return text[:64]


def _env_prefix(value: str) -> str:
    result = _ENV_SAFE_RE.sub("_", value.upper()).strip("_")
    if not result or not result[0].isalpha():
        result = "SYSTEM_" + result
    return result


def _choice(value: Any, where: str, allowed: set[str]) -> str:
    text = _text(value, where).upper()
    if text not in allowed:
        raise ValueError(f"{where} must be one of {', '.join(sorted(allowed))}")
    return text


def _merged_values(request: ConnectionRequest) -> dict[str, Any]:
    values = dict(request.candidate.values)
    values.update(dict(request.values))
    return values


def _normalized(request: ConnectionRequest) -> dict[str, Any]:
    values = _merged_values(request)
    mode = str(values.get("snmp_mode") or "community").strip().casefold()
    if mode not in {"community", "v3"}:
        raise ValueError("SNMP mode must be community or v3")
    result: dict[str, Any] = {
        "host": _text(values.get("host") or request.candidate.endpoint.removeprefix("udp://").split(":", 1)[0], "SNMP host"),
        "port": _port(values.get("port", 161)),
        "snmp_mode": mode,
    }
    if mode == "community":
        result["community"] = _text(values.get("community"), "SNMP community")
        version = str(values.get("validated_version") or "2c").strip().casefold()
        if version not in {"1", "2c"}:
            raise ValueError("validated SNMP community version must be 2c or 1")
        result["validated_version"] = version
        return result

    result["username"] = _text(values.get("username"), "SNMPv3 username")
    auth_password = values.get("auth_password")
    privacy_password = values.get("privacy_password")
    if privacy_password and not auth_password:
        raise ValueError("SNMPv3 privacy requires an authentication password")
    if auth_password:
        result["auth_password"] = _text(auth_password, "SNMPv3 authentication password")
        result["auth_protocol"] = _choice(
            values.get("auth_protocol", "SHA"),
            "SNMPv3 authentication protocol",
            {"SHA", "MD5"},
        )
    if privacy_password:
        result["privacy_password"] = _text(privacy_password, "SNMPv3 privacy password")
        result["privacy_protocol"] = _choice(
            values.get("privacy_protocol", "AES"),
            "SNMPv3 privacy protocol",
            {"AES", "DES"},
        )
    return result


def _final_bindings(system_id: str, values: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[CredentialSecretWrite, ...]]:
    prefix = _env_prefix(system_id)
    config: dict[str, Any] = {
        "host": values["host"],
        "port": values["port"],
        "oids": {"sys_uptime": ".1.3.6.1.2.1.1.3.0"},
    }
    writes: list[CredentialSecretWrite] = []
    if values["snmp_mode"] == "community":
        env_name = f"MONITORBOX_{prefix}_SNMP_COMMUNITY"
        writes.append(
            CredentialSecretWrite(
                secret_id=_slug(f"{system_id}_snmp_community"),
                value=values["community"],
                env_name=env_name,
            )
        )
        config.update({"version": values["validated_version"], "community_env": env_name})
        return config, tuple(writes)

    username_env = f"MONITORBOX_{prefix}_SNMP_USERNAME"
    writes.append(
        CredentialSecretWrite(
            secret_id=_slug(f"{system_id}_snmp_username"),
            value=values["username"],
            env_name=username_env,
        )
    )
    config.update({"version": "3", "username_env": username_env})
    if values.get("auth_password"):
        auth_env = f"MONITORBOX_{prefix}_SNMP_AUTH_PASSWORD"
        writes.append(
            CredentialSecretWrite(
                secret_id=_slug(f"{system_id}_snmp_auth_password"),
                value=values["auth_password"],
                env_name=auth_env,
            )
        )
        config["auth_password_env"] = auth_env
        config["auth_protocol"] = values["auth_protocol"]
    if values.get("privacy_password"):
        privacy_env = f"MONITORBOX_{prefix}_SNMP_PRIVACY_PASSWORD"
        writes.append(
            CredentialSecretWrite(
                secret_id=_slug(f"{system_id}_snmp_privacy_password"),
                value=values["privacy_password"],
                env_name=privacy_env,
            )
        )
        config["privacy_password_env"] = privacy_env
        config["privacy_protocol"] = values["privacy_protocol"]
    return config, tuple(writes)


def _validation_config(values: Mapping[str, Any], *, version: str | None = None) -> tuple[dict[str, Any], dict[str, str], tuple[str, ...]]:
    config: dict[str, Any] = {
        "host": values["host"],
        "port": values["port"],
        "oids": {"sys_uptime": ".1.3.6.1.2.1.1.3.0"},
    }
    temporary: dict[str, str] = {}
    protected: list[str] = []

    def bind(key: str, value: str) -> None:
        env_name = f"MONITORBOX_ONBOARDING_{secrets.token_hex(12).upper()}"
        config[key] = env_name
        temporary[env_name] = value
        protected.append(value)

    if values["snmp_mode"] == "community":
        config["version"] = version or values["validated_version"]
        bind("community_env", values["community"])
        return config, temporary, tuple(protected)

    config["version"] = "3"
    bind("username_env", values["username"])
    if values.get("auth_password"):
        bind("auth_password_env", values["auth_password"])
        config["auth_protocol"] = values["auth_protocol"]
    if values.get("privacy_password"):
        bind("privacy_password_env", values["privacy_password"])
        config["privacy_protocol"] = values["privacy_protocol"]
    return config, temporary, tuple(protected)


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


class SnmpIntegration:
    """SNMP capability policy attached to an existing declared System."""

    def __init__(self, *, runner_factory: Callable[[], AdapterRunner] = AdapterRunner) -> None:
        self._runner_factory = runner_factory

    async def detect(self, request: DiscoveryRequest, context: FacetContext, probe) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        v3 = await probe.snmp_v3_capable(host, 161)
        if v3 is True:
            return (
                DiscoveryEvidence(
                    plugin_id="snmp",
                    system_id=request.system_id,
                    kind="snmp",
                    label="SNMPv3",
                    confidence=DiscoveryConfidence.DETECTED,
                    endpoint=f"udp://{host}:161",
                    evidence="SNMPv3 engine/report exchange received",
                    default_selected=True,
                    values={"host": host, "port": 161, "snmp_mode": "v3"},
                ),
            )
        return (
            DiscoveryEvidence(
                plugin_id="snmp",
                system_id=request.system_id,
                kind="snmp",
                label="SNMP",
                confidence=DiscoveryConfidence.POSSIBLE,
                endpoint=f"udp://{host}:161",
                evidence=(
                    "SNMPv3 was not positively identified. SNMPv2c requires a community string to validate; "
                    "SNMPv3 remains available as a manual override."
                ),
                default_selected=False,
                values={"host": host, "port": 161, "snmp_mode": "community"},
            ),
        )

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized(request)
        agent_id = _text(
            context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
            "local agent id",
        )
        config, writes = _final_bindings(request.candidate.system_id, values)
        capability = {
            "id": "snmp",
            "kind": "snmp",
            "label": "SNMP",
            "enabled": True,
            "providers": [
                {
                    "id": "snmp",
                    "label": "SNMP",
                    "adapter": "snmp",
                    "agent_id": agent_id,
                    "check_id": f"{request.candidate.system_id}_snmp",
                    "enabled": True,
                    "interval_seconds": 30,
                    "timeout_seconds": 10,
                    "config": config,
                }
            ],
        }
        return ConnectionPlan(
            plugin_id="snmp",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(
                AddCapabilityIntent(
                    site_id=context.site_id,
                    object_id=request.candidate.system_id,
                    capability_data=capability,
                ),
            ),
            secret_writes=writes,
            object_ids=(request.candidate.system_id,),
        )

    async def validate(self, request: ConnectionRequest, context: FacetContext) -> ValidationResult:
        values = _normalized(request)
        agent_id = _text(
            context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
            "local agent id",
        )
        versions = ("2c", "1") if values["snmp_mode"] == "community" else (None,)
        attempted: list[str] = []
        final_observation = None
        final_protected: tuple[str, ...] = ()
        validated_version: str | None = None
        runner = self._runner_factory()
        await runner.start()
        try:
            for version in versions:
                config, temporary, protected = _validation_config(values, version=version)
                check = CheckConfig(
                    id="snmp_validation",
                    object_id=request.candidate.system_id,
                    label="SNMP",
                    adapter="snmp",
                    interval_seconds=30,
                    timeout_seconds=10,
                    enabled=True,
                    options=config,
                    agent_id=agent_id,
                    capability_id=None,
                    capability_kind=None,
                )
                async with _ENV_LOCK:
                    previous = {name: os.environ.get(name) for name in temporary}
                    try:
                        for name, value in temporary.items():
                            os.environ[name] = value
                        observation = await runner.run(check)
                    finally:
                        for name, old in previous.items():
                            if old is None:
                                os.environ.pop(name, None)
                            else:
                                os.environ[name] = old
                final_observation = observation
                final_protected = protected
                if version is not None:
                    attempted.append(version)
                if observation.state in _ACCEPTED_STATES:
                    if version is not None:
                        validated_version = version
                    break
        finally:
            await runner.close()

        if final_observation is None:
            raise RuntimeError("SNMP validation returned no observation")
        accepted = final_observation.state in _ACCEPTED_STATES
        public = _scrub(copy.deepcopy(final_observation.as_dict()), final_protected)
        metadata = public.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            public["metadata"] = metadata
        normalized_values = dict(values)
        summary = str(public.get("summary") or "SNMP validation completed")[:400]
        if values["snmp_mode"] == "community":
            metadata["snmp_attempted_versions"] = list(attempted)
            if validated_version:
                metadata["snmp_validated_version"] = validated_version
                normalized_values["validated_version"] = validated_version
            if validated_version == "1":
                summary = ("SNMPv1 validated after SNMPv2c failed: " + summary)[:400]
            elif not accepted and attempted == ["2c", "1"]:
                summary = ("SNMPv2c and SNMPv1 validation failed: " + summary)[:400]
        return ValidationResult(
            accepted=accepted,
            state=final_observation.state.value,
            summary=summary,
            observation=public,
            metadata={"transport": "snmp", "attempted_versions": list(attempted)},
            values=normalized_values,
        )

    def identities(self, evidence, context: FacetContext) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            values = dict(evidence.values)
            host = str(values.get("host") or evidence.endpoint)
            port = str(values.get("port") or 161)
            return (IdentityKey("snmp-endpoint", f"{host}:{port}", 90),)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="snmp",
            title="SNMP",
            fields=(
                PresentationField(key="host", label="SNMP host", required=True),
                PresentationField(key="port", label="SNMP port", field_type="number", required=True),
                PresentationField(key="snmp_mode", label="SNMP mode", required=True),
                PresentationField(key="community", label="Community", secret=True),
                PresentationField(key="username", label="SNMPv3 username", secret=True),
                PresentationField(key="auth_password", label="SNMPv3 authentication password", secret=True),
                PresentationField(key="auth_protocol", label="Authentication protocol"),
                PresentationField(key="privacy_password", label="SNMPv3 privacy password", secret=True),
                PresentationField(key="privacy_protocol", label="Privacy protocol"),
            ),
            provenance_keys=("transport", "snmp_attempted_versions", "snmp_validated_version"),
        )

    def build_runtime_intent(self, request: ConnectionRequest, context: FacetContext) -> RuntimeIntent:
        values = _normalized(request)
        config, _ = _final_bindings(request.candidate.system_id, values)
        return RuntimeIntent(
            plugin_id="snmp",
            checks=(
                {
                    "id": f"{request.candidate.system_id}_snmp",
                    "adapter": "snmp",
                    "object_id": request.candidate.system_id,
                    "agent_id": context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
                    "interval_seconds": 30,
                    "timeout_seconds": 10,
                    "config": config,
                },
            ),
        )


_SNMP = SnmpIntegration()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="snmp", display_name="SNMP"),
    connection_kinds=("snmp",),
    discovery=_SNMP,
    connection=_SNMP,
    validation=_SNMP,
    identity=_SNMP,
    presentation=_SNMP,
    runtime=_SNMP,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="SNMP Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.snmp:PLUGIN"},
    requires_core=">=2.2.2 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
)

__all__ = [
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_MANIFEST",
    "MODULE_VERSION",
    "PLUGIN",
    "SnmpIntegration",
]
