from __future__ import annotations

import copy
import re
import shlex
from collections.abc import Callable
from typing import Any

from ...adapters import AdapterRunner
from ...config import CheckConfig
from ...model import State
from ...plugin_api import (
    AddObjectIntent,
    ConnectionPlan,
    ConnectionRequest,
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

MODULE_ID = "com.sickicarus.monitorbox.nut"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")
_ACCEPTED_STATES = frozenset({State.HEALTHY, State.DEGRADED})


def _slug(value: str) -> str:
    result = _ID_CLEAN_RE.sub("_", value.strip().casefold()).strip("_") or "ups"
    if not result[0].isalpha():
        result = f"ups_{result}"
    return result[:64]


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _port(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("NUT port must be an integer")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("NUT port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("NUT port must be in 1..65535")
    return port


def _looks_like_nut_version(payload: bytes) -> bool:
    text = payload.decode("utf-8", errors="replace").strip().casefold()
    return bool(text) and (text.startswith("upsd ") or "network ups tools" in text)


def _parse_complete_nut_ups(payload: bytes) -> tuple[dict[str, str], ...]:
    lines = [line.strip() for line in payload.decode("utf-8", errors="replace").splitlines()]
    if "END LIST UPS" not in lines:
        return ()

    rows: list[dict[str, str]] = []
    for line in lines:
        if not line.startswith("UPS "):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 2 or parts[0] != "UPS":
            continue
        ups_id = parts[1].strip()
        if not ups_id:
            continue
        description = parts[2].strip() if len(parts) >= 3 else ""
        row = {"id": ups_id, "description": description}
        if row not in rows:
            rows.append(row)
    return tuple(rows)


class NutIntegration:
    """Vertical NUT onboarding policy over shared bounded/runtime transport."""

    def __init__(self, *, runner_factory: Callable[[], AdapterRunner] = AdapterRunner) -> None:
        self._runner_factory = runner_factory

    async def detect(
        self,
        request: DiscoveryRequest,
        context: FacetContext,
        probe,
    ) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        port = 3493
        if not await probe.tcp_open(host, port):
            return ()

        version = await probe.tcp_exchange(host, port, b"VER\n", limit=4096)
        version_text = version.decode("utf-8", errors="replace").strip()
        if not _looks_like_nut_version(version):
            return (
                DiscoveryEvidence(
                    plugin_id="nut",
                    system_id=request.system_id,
                    kind="tcp",
                    label="TCP service on 3493",
                    endpoint=f"{host}:{port}",
                    confidence=DiscoveryConfidence.POSSIBLE,
                    evidence="TCP/3493 is open but did not identify as NUT",
                    default_selected=False,
                    values={"host": host, "port": port},
                ),
            )

        values: dict[str, Any] = {"host": host, "port": port}
        evidence_text = f"NUT server identified itself as {version_text[:160]}"
        listing = await probe.tcp_exchange_until(
            host,
            port,
            b"LIST UPS\n",
            b"END LIST UPS\n",
            limit=65536,
        )
        ups_options = _parse_complete_nut_ups(listing)
        if ups_options:
            values["ups_options"] = [dict(item) for item in ups_options]
            if len(ups_options) == 1:
                values["ups"] = ups_options[0]["id"]
            noun = "device" if len(ups_options) == 1 else "devices"
            evidence_text += f"; enumerated {len(ups_options)} UPS {noun}"

        return (
            DiscoveryEvidence(
                plugin_id="nut",
                system_id=request.system_id,
                kind="nut",
                label="UPS via NUT",
                endpoint=f"{host}:{port}",
                confidence=DiscoveryConfidence.DETECTED,
                evidence=evidence_text,
                default_selected=True,
                values=values,
            ),
        )

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = dict(request.candidate.values)
        values.update(dict(request.values))
        host = _text(values.get("host"), "NUT host")
        port = _port(values.get("port", 3493))
        ups = _text(values.get("ups"), "NUT UPS name")
        label = _text(values.get("label") or request.candidate.label or ups, "NUT label")
        object_id = _slug(str(values.get("id") or label or ups))
        agent_id = _text(
            context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
            "local agent id",
        )

        obj = {
            "id": object_id,
            "label": label,
            "kind": "ups",
            "address": host,
            "depends_on": [request.candidate.system_id],
            "capabilities": [
                {
                    "id": "nut",
                    "kind": "ups",
                    "label": "UPS status",
                    "enabled": True,
                    "providers": [
                        {
                            "id": "nut",
                            "label": "UPS status",
                            "adapter": "nut",
                            "agent_id": agent_id,
                            "check_id": object_id,
                            "enabled": True,
                            "interval_seconds": 15,
                            "timeout_seconds": 5,
                            "config": {"host": host, "port": port, "ups": ups},
                        }
                    ],
                }
            ],
        }
        return ConnectionPlan(
            plugin_id="nut",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            object_ids=(object_id,),
        )

    async def validate(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> ValidationResult:
        values = dict(request.candidate.values)
        values.update(dict(request.values))
        host = _text(values.get("host"), "NUT host")
        port = _port(values.get("port", 3493))
        ups = _text(values.get("ups"), "NUT UPS name")
        agent_id = _text(
            context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
            "local agent id",
        )
        check = CheckConfig(
            id="nut_validation",
            object_id=request.candidate.system_id,
            label="UPS status",
            adapter="nut",
            interval_seconds=15,
            timeout_seconds=5,
            enabled=True,
            options={"host": host, "port": port, "ups": ups},
            agent_id=agent_id,
            capability_id=None,
            capability_kind=None,
        )
        runner = self._runner_factory()
        try:
            await runner.start()
            observation = await runner.run(check)
        finally:
            await runner.close()
        public = copy.deepcopy(observation.as_dict())
        return ValidationResult(
            accepted=observation.state in _ACCEPTED_STATES,
            state=observation.state.value,
            summary=str(public.get("summary") or "NUT validation completed")[:400],
            observation=public,
            metadata={"transport": "nut"},
            values={"host": host, "port": port, "ups": ups},
        )

    def identities(self, evidence, context: FacetContext) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            values = dict(evidence.values)
            host = str(values.get("host") or evidence.endpoint)
            port = str(values.get("port") or 3493)
            ups = str(values.get("ups") or "")
            keys = [IdentityKey("nut-endpoint", f"{host}:{port}", 90)]
            if ups:
                keys.insert(0, IdentityKey("nut-ups", f"{host}:{port}/{ups}", 100))
            return tuple(keys)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="nut",
            title="UPS via NUT",
            fields=(
                PresentationField(key="host", label="NUT host", required=True),
                PresentationField(key="port", label="NUT port", field_type="number", required=True),
                PresentationField(key="ups", label="UPS name", required=True),
            ),
            provenance_keys=("transport", "ups_count"),
        )

    def build_runtime_intent(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> RuntimeIntent:
        values = dict(request.candidate.values)
        values.update(dict(request.values))
        host = _text(values.get("host"), "NUT host")
        port = _port(values.get("port", 3493))
        ups = _text(values.get("ups"), "NUT UPS name")
        object_id = _slug(str(values.get("id") or values.get("label") or request.candidate.label or ups))
        return RuntimeIntent(
            plugin_id="nut",
            checks=(
                {
                    "id": object_id,
                    "adapter": "nut",
                    "object_id": object_id,
                    "agent_id": context.current_config.get("runtime", {}).get("local_agent", {}).get("agent_id"),
                    "interval_seconds": 15,
                    "timeout_seconds": 5,
                    "config": {"host": host, "port": port, "ups": ups},
                },
            ),
        )


_NUT = NutIntegration()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="nut", display_name="UPS via NUT"),
    connection_kinds=("nut",),
    discovery=_NUT,
    connection=_NUT,
    validation=_NUT,
    identity=_NUT,
    presentation=_NUT,
    runtime=_NUT,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="NUT UPS Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.nut:PLUGIN"},
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
    "NutIntegration",
    "PLUGIN",
]
