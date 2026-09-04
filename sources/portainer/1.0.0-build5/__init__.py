from __future__ import annotations

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
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 5


class _PortainerRuntimeDiscoveryExecutor(PortainerEndpointRuntimeExecutor):
    """Keep inventory ownership discoverable even when Portainer is unavailable.

    Core recognizes runtime discovery authorities by the provider-neutral
    ``discovery_evidence`` result shape. A failed first inventory has no workload
    projection, so emit an empty evidence list while keeping it explicitly
    non-authoritative. Workload checks remain ordinary runtime observations.
    """

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


_PORTAINER = PortainerIntegration()
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
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.portainer:PLUGIN"},
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
    "PortainerCandidateAdoption",
    "PortainerCandidateReview",
    "PortainerEndpointRuntimeExecutor",
    "PortainerIntegration",
    "PortainerRuntimeExecutor",
    "PortainerValidation",
]
