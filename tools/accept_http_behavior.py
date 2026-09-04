#!/usr/bin/env python3
"""Behavioral acceptance for managed HTTP v1.0.0 build 1.

The immutable source blob is byte-identical to certified Core 0556. This harness
supplies only the provider-blind Core interfaces needed to execute the managed
artifact, so repository CI does not require credentials for the private Core
repository.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

HTTP_PACKAGE = "com.sickicarus.monitorbox.http-1.0.0-build1.zip"
SECRET = "http-behavior-secret-must-not-leak"


def install_core_contract_stubs() -> ModuleType:
    monitorbox = ModuleType("monitorbox")
    monitorbox.__path__ = []
    v2 = ModuleType("monitorbox.v2")
    v2.__path__ = []
    adapters = ModuleType("monitorbox.v2.adapters")
    config = ModuleType("monitorbox.v2.config")
    model = ModuleType("monitorbox.v2.model")
    plugin_api = ModuleType("monitorbox.v2.plugin_api")

    class AdapterRunner:
        pass

    @dataclass(frozen=True)
    class CheckConfig:
        id: str
        object_id: str
        label: str
        adapter: str
        interval_seconds: float
        timeout_seconds: float
        enabled: bool
        options: Mapping[str, Any]
        agent_id: str | None = None
        capability_id: str | None = None
        capability_kind: str | None = None

    class State(str, Enum):
        HEALTHY = "healthy"
        DEGRADED = "degraded"
        UNKNOWN = "unknown"
        UNAVAILABLE = "unavailable"

    class DiscoveryConfidence(str, Enum):
        DETECTED = "detected"
        POSSIBLE = "possible"

    @dataclass(frozen=True)
    class PluginMetadata:
        plugin_id: str
        display_name: str
        api_version: int = 1

    @dataclass(frozen=True)
    class FacetContext:
        site_id: str
        current_config: Mapping[str, Any]
        current_revision: int
        current_hash: str

    @dataclass(frozen=True)
    class DiscoveryRequest:
        system_id: str
        label: str
        address: str
        kind: str = "host"

    @dataclass(frozen=True)
    class DiscoveryEvidence:
        plugin_id: str
        system_id: str
        kind: str
        label: str
        endpoint: str
        confidence: DiscoveryConfidence
        evidence: str
        connection_plugin_id: str | None = None
        default_selected: bool = False
        values: Mapping[str, Any] = field(default_factory=dict)
        provenance: Mapping[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class ConnectionRequest:
        candidate: DiscoveryEvidence
        values: Mapping[str, Any]

    @dataclass(frozen=True)
    class CredentialSecretWrite:
        secret_id: str
        value: str
        env_name: str

        def public(self) -> dict[str, str]:
            return {"secret_id": self.secret_id, "env_name": self.env_name}

    @dataclass(frozen=True)
    class AddObjectIntent:
        site_id: str
        object_data: Mapping[str, Any]

    @dataclass(frozen=True)
    class ConnectionPlan:
        plugin_id: str
        system_id: str
        operations: tuple[Any, ...]
        secret_writes: tuple[Any, ...] = ()
        expected_revision: int | None = None
        expected_config_hash: str | None = None
        allowed_existing_object_ids: tuple[str, ...] = ()
        object_ids: tuple[str, ...] = ()

        def public(self) -> dict[str, Any]:
            return {
                "plugin_id": self.plugin_id,
                "system_id": self.system_id,
                "operation_count": len(self.operations),
                "secret_writes": [item.public() for item in self.secret_writes],
                "expected_revision": self.expected_revision,
                "expected_config_hash": self.expected_config_hash,
                "object_ids": list(self.object_ids),
            }

    @dataclass(frozen=True)
    class ValidationResult:
        accepted: bool
        state: str
        summary: str
        observation: Mapping[str, Any] = field(default_factory=dict)
        metadata: Mapping[str, Any] = field(default_factory=dict)
        values: Mapping[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class IdentityKey:
        namespace: str
        value: str
        strength: int = 100

    @dataclass(frozen=True)
    class PresentationField:
        key: str
        label: str
        field_type: str = "text"
        required: bool = False
        secret: bool = False
        choices: tuple[str, ...] = ()
        help_text: str = ""

    @dataclass(frozen=True)
    class PresentationDescriptor:
        plugin_id: str
        title: str
        fields: tuple[PresentationField, ...] = ()
        provenance_keys: tuple[str, ...] = ()

    @dataclass(frozen=True)
    class RuntimeIntent:
        plugin_id: str
        checks: tuple[Mapping[str, Any], ...] = ()
        watchers: tuple[Mapping[str, Any], ...] = ()
        metadata: Mapping[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: PluginMetadata
        connection_kinds: tuple[str, ...] = ()
        discovery: Any = None
        connection: Any = None
        validation: Any = None
        identity: Any = None
        inventory: Any = None
        presentation: Any = None
        runtime: Any = None
        adoption: Any = None

    @dataclass(frozen=True)
    class ModuleManifest:
        module_id: str
        display_name: str
        version: str
        build: int
        module_type: str
        entrypoints: Mapping[str, str]
        requires_core: str
        requires_runtime_api: str
        state_schema: int
        publisher_id: str
        schema: int = 1
        dependencies: tuple[str, ...] = ()
        permissions: tuple[str, ...] = ()
        lifecycle_policy: str = "optional"

    adapters.AdapterRunner = AdapterRunner
    config.CheckConfig = CheckConfig
    model.State = State
    for value in (
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
    ):
        setattr(plugin_api, value.__name__, value)

    sys.modules.update(
        {
            "monitorbox": monitorbox,
            "monitorbox.v2": v2,
            "monitorbox.v2.adapters": adapters,
            "monitorbox.v2.config": config,
            "monitorbox.v2.model": model,
            "monitorbox.v2.plugin_api": plugin_api,
        }
    )
    return plugin_api


class Probe:
    async def tcp_open(self, host: str, port: int) -> bool:
        if host != "service.example.test":
            raise AssertionError(f"unexpected discovery host {host!r}")
        return port == 443


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / HTTP_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed HTTP package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_http_b1")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.http":
        raise AssertionError("managed HTTP module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed HTTP release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.entrypoints != {"integration": "monitorbox_http_b1:PLUGIN"}:
        raise AssertionError("managed HTTP manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed HTTP Core compatibility changed")

    context = plugin_api.FacetContext(
        site_id="lab",
        current_config={
            "sites": [{"id": "lab", "objects": []}],
            "runtime": {"local_agent": {"agent_id": "monitor"}},
        },
        current_revision=7,
        current_hash="http-behavior-hash",
    )
    candidate = plugin_api.DiscoveryEvidence(
        plugin_id="http",
        system_id="service_host",
        kind="http",
        label="HTTPS service",
        endpoint="https://service.example.test:443",
        confidence=plugin_api.DiscoveryConfidence.POSSIBLE,
        evidence="acceptance fixture",
        values={"url": "https://service.example.test:443"},
    )
    request = plugin_api.ConnectionRequest(
        candidate=candidate,
        values={
            "label": "Managed HTTP service",
            "statuses": "200,204,401-402",
            "timeout_seconds": 7,
            "follow_redirects": False,
            "verify_tls": True,
            "contains": "ready",
            "response_header_name": "X-Service",
            "response_header_value": "monitorbox",
            "latency_warning_ms": 900,
            "request_header_name": "Authorization",
            "request_header_value": SECRET,
        },
    )

    integration = managed.HttpIntegration()
    discovered = await integration.detect(
        plugin_api.DiscoveryRequest(
            system_id="service_host",
            label="Service host",
            address="service.example.test",
        ),
        context,
        Probe(),
    )
    if len(discovered) != 1:
        raise AssertionError(f"expected one bounded HTTP discovery candidate, got {len(discovered)}")
    evidence = discovered[0]
    if evidence.endpoint != "https://service.example.test:443" or evidence.default_selected:
        raise AssertionError("HTTP discovery endpoint/selection contract changed")

    plan = integration.plan(request, context)
    if plan.plugin_id != "http" or plan.system_id != "service_host":
        raise AssertionError("HTTP connection plan ownership changed")
    if plan.expected_revision != 7 or plan.expected_config_hash != "http-behavior-hash":
        raise AssertionError("HTTP plan lost optimistic transaction guards")
    if len(plan.operations) != 1 or len(plan.secret_writes) != 1:
        raise AssertionError("HTTP plan must emit one object intent and one protected-header secret")
    if SECRET in json.dumps(plan.public(), sort_keys=True):
        raise AssertionError("HTTP connection plan public diagnostics leaked protected header value")

    object_data = plan.operations[0].object_data
    provider = object_data["capabilities"][0]["providers"][0]
    provider_config = provider["config"]
    if provider["adapter"] != "http":
        raise AssertionError("HTTP plan stopped targeting the shared provider-blind HTTP adapter")
    if provider_config["statuses"] != [200, 204, 401, 402]:
        raise AssertionError(f"HTTP status normalization changed: {provider_config['statuses']!r}")
    if provider_config["follow_redirects"] is not False or provider_config["verify_tls"] is not True:
        raise AssertionError("HTTP redirect/TLS policy changed")
    if provider_config["header"] != {"X-Service": "monitorbox"}:
        raise AssertionError("HTTP response-header assertion changed")
    if provider_config["request_header_name"] != "Authorization":
        raise AssertionError("HTTP protected request-header name changed")
    if "request_header_value" in provider_config or SECRET in json.dumps(object_data, sort_keys=True):
        raise AssertionError("HTTP protected request-header value entered canonical object intent")

    runtime = integration.build_runtime_intent(request, context)
    if runtime.plugin_id != "http" or len(runtime.checks) != 1:
        raise AssertionError("HTTP runtime intent shape changed")
    check = runtime.checks[0]
    if check["adapter"] != "http" or check["agent_id"] != "monitor":
        raise AssertionError("HTTP runtime intent lost generic adapter/agent ownership")
    if check["config"].get("request_header_value_env") != "MONITORBOX_MANAGED_HTTP_SERVICE_HTTP_HEADER":
        raise AssertionError("HTTP runtime intent protected-header binding changed")

    presentation = integration.describe(context)
    fields = {item.key: item for item in presentation.fields}
    if not fields["request_header_value"].secret:
        raise AssertionError("HTTP protected request-header value is no longer presented as secret")
    if presentation.provenance_keys != ("transport", "tls_trust_fallback"):
        raise AssertionError("HTTP presentation provenance contract changed")

    identities = integration.identities(candidate, context)
    if len(identities) != 1 or identities[0].namespace != "http-url":
        raise AssertionError("HTTP identity namespace changed")
    if identities[0].value != "https://service.example.test:443":
        raise AssertionError("HTTP URL identity normalization changed")


def main() -> None:
    asyncio.run(accept())
    print("managed HTTP behavioral acceptance: PASS")


if __name__ == "__main__":
    main()
