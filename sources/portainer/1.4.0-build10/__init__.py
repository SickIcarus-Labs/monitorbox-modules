from __future__ import annotations

from dataclasses import replace

from ...plugin_api import (
    IntegrationDefinition,
    ModuleManifest,
    PluginMetadata,
    RuntimeExecutionResult,
)
from .adoption import PortainerCandidateAdoption
from .endpoint_provenance import PortainerEndpointRuntimeExecutor
from .onboarding import PortainerIntegration
from .review import PortainerCandidateReview
from .runtime import PortainerRuntimeExecutor
from .validation import PortainerValidation

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.4.0"
MODULE_BUILD = 10


class _PortainerRuntimeDiscoveryExecutor(PortainerEndpointRuntimeExecutor):
    """Keep inventory ownership discoverable even when Portainer is unavailable."""

    async def execute(self, request, context) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        if str(request.options.get("operation", "inventory")) != "inventory":
            return result
        metadata = dict(result.metadata)
        metadata.setdefault("discovery_evidence", [])
        return RuntimeExecutionResult(
            state=result.state,
            summary=result.summary,
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )


class _PortainerIntegration(PortainerIntegration):
    """Portainer presentation with correctly typed generic operator fields."""

    def describe(self, context):
        descriptor = super().describe(context)
        fields = tuple(
            replace(field, field_type="boolean")
            if field.key == "verify_tls"
            else field
            for field in descriptor.fields
        )
        return replace(descriptor, fields=fields)


_PORTAINER = _PortainerIntegration()
_PORTAINER_VALIDATION = PortainerValidation()
_PORTAINER_RUNTIME = _PortainerRuntimeDiscoveryExecutor()
_PORTAINER_ADOPTION = PortainerCandidateAdoption()
_PORTAINER_REVIEW = PortainerCandidateReview()

PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="portainer", display_name="Portainer"),
    discovery=_PORTAINER,
    connection=_PORTAINER,
    validation=_PORTAINER_VALIDATION,
    identity=_PORTAINER,
    presentation=_PORTAINER,
    runtime=_PORTAINER,
    runtime_executor=_PORTAINER_RUNTIME,
    candidate_adoption=_PORTAINER_ADOPTION,
    candidate_review=_PORTAINER_REVIEW,
    connection_kinds=("portainer",),
    runtime_adapter_kinds=("portainer",),
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="Portainer Integration",
    description="Monitors Docker environments and workload health through Portainer inventory.",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.portainer:PLUGIN"},
    requires_core=">=2.4.0 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
    capability_detection={
        "schema": 2,
        "discovery_hints": {
            "schema": 1,
            "tcp_ports": [9000, 9443],
        },
        "matches": [
            {
                "id": "legacy-http-port",
                "confidence": "possible",
                "all": [
                    {"fact": "network.port", "op": "equals", "value": "9000"}
                ],
            },
            {
                "id": "https-port",
                "confidence": "possible",
                "all": [
                    {"fact": "network.port", "op": "equals", "value": "9443"}
                ],
            },
        ],
    },
)

__all__ = [
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_MANIFEST",
    "MODULE_VERSION",
    "PLUGIN",
    "PortainerCandidateAdoption",
    "PortainerCandidateReview",
    "PortainerEndpointRuntimeExecutor",
    "PortainerIntegration",
    "PortainerRuntimeExecutor",
    "PortainerValidation",
]
