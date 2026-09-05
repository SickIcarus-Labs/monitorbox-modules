from __future__ import annotations

from ...plugin_api import IntegrationDefinition, ModuleManifest, PluginMetadata
from .adoption import ScryptedCandidateAdoption
from .onboarding import ScryptedIntegration
from .runtime import (
    MODULE_BUILD,
    MODULE_ID,
    MODULE_VERSION,
    ScryptedRuntimeExecutor,
)

_SCRYPTED = ScryptedIntegration()
_SCRYPTED_RUNTIME = ScryptedRuntimeExecutor()
_SCRYPTED_ADOPTION = ScryptedCandidateAdoption()

PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="scrypted", display_name="Scrypted"),
    connection_kinds=("scrypted",),
    runtime_adapter_kinds=("scrypted",),
    discovery=_SCRYPTED,
    connection=_SCRYPTED,
    validation=_SCRYPTED,
    identity=_SCRYPTED,
    presentation=_SCRYPTED,
    runtime=_SCRYPTED,
    runtime_executor=_SCRYPTED_RUNTIME,
    candidate_adoption=_SCRYPTED_ADOPTION,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="Scrypted Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.scrypted:PLUGIN"},
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
    "ScryptedCandidateAdoption",
    "ScryptedIntegration",
    "ScryptedRuntimeExecutor",
]
