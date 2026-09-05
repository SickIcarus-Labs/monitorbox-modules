from __future__ import annotations

from ...plugin_api import IntegrationDefinition, ModuleManifest, PluginMetadata
from .adoption import UniFiCandidateAdoption
from .discovery_runtime import UniFiRuntimeExecutor
from .onboarding import UniFiIntegration
from .runtime import MODULE_BUILD, MODULE_ID, MODULE_VERSION

_UNIFI_RUNTIME = UniFiRuntimeExecutor()
_UNIFI = UniFiIntegration()
_UNIFI_ADOPTION = UniFiCandidateAdoption()

PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="unifi", display_name="UniFi Network"),
    connection_kinds=("unifi",),
    runtime_adapter_kinds=("unifi",),
    discovery=_UNIFI,
    connection=_UNIFI,
    validation=_UNIFI,
    identity=_UNIFI,
    presentation=_UNIFI,
    runtime=_UNIFI,
    runtime_executor=_UNIFI_RUNTIME,
    candidate_adoption=_UNIFI_ADOPTION,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="UniFi Network Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.unifi:PLUGIN"},
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
    "UniFiCandidateAdoption",
    "UniFiIntegration",
    "UniFiRuntimeExecutor",
]
