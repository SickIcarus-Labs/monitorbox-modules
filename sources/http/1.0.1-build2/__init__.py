from __future__ import annotations

from monitorbox.v2.plugin_api import IntegrationDefinition, ModuleManifest, PluginMetadata

from ._base import HttpIntegration, MODULE_ID
from .startup_confirmation import HttpRuntimeExecutor

MODULE_VERSION = "1.0.1"
MODULE_BUILD = 2

_HTTP = HttpIntegration()
_EXECUTOR = HttpRuntimeExecutor()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="http", display_name="HTTP(S) endpoint"),
    connection_kinds=("http", "http_service"),
    runtime_adapter_kinds=("http",),
    discovery=_HTTP,
    connection=_HTTP,
    validation=_HTTP,
    identity=_HTTP,
    presentation=_HTTP,
    runtime=_HTTP,
    runtime_executor=_EXECUTOR,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="HTTP(S) Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox_http_v101_b2:PLUGIN"},
    requires_core=">=2.3.1 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
)

__all__ = ["HttpIntegration", "MODULE_BUILD", "MODULE_ID", "MODULE_MANIFEST", "MODULE_VERSION", "PLUGIN"]
