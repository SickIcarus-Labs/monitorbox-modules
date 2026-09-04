#!/usr/bin/env python3
"""Behavioral acceptance for managed HTTP v1.0.0 build 1 against Core 0556."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from monitorbox.v2.plugin_api import (
    ConnectionRequest,
    DiscoveryConfidence,
    DiscoveryEvidence,
    DiscoveryRequest,
    FacetContext,
)

HTTP_PACKAGE = "com.sickicarus.monitorbox.http-1.0.0-build1.zip"
SECRET = "http-behavior-secret-must-not-leak"


class Probe:
    async def tcp_open(self, host: str, port: int) -> bool:
        if host != "service.example.test":
            raise AssertionError(f"unexpected discovery host {host!r}")
        return port == 443


def context() -> FacetContext:
    return FacetContext(
        site_id="lab",
        current_config={
            "sites": [{"id": "lab", "objects": []}],
            "runtime": {"local_agent": {"agent_id": "monitor"}},
        },
        current_revision=7,
        current_hash="http-behavior-hash",
    )


def candidate() -> DiscoveryEvidence:
    return DiscoveryEvidence(
        plugin_id="http",
        system_id="service_host",
        kind="http",
        label="HTTPS service",
        endpoint="https://service.example.test:443",
        confidence=DiscoveryConfidence.POSSIBLE,
        evidence="acceptance fixture",
        values={"url": "https://service.example.test:443"},
    )


def request() -> ConnectionRequest:
    return ConnectionRequest(
        candidate=candidate(),
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


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / HTTP_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed HTTP package is missing: {package}")
    sys.path.insert(0, str(package))

    import monitorbox_http_b1 as managed

    if managed.MODULE_ID != "com.sickicarus.monitorbox.http":
        raise AssertionError("managed HTTP module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed HTTP release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.entrypoints != {"integration": "monitorbox_http_b1:PLUGIN"}:
        raise AssertionError("managed HTTP manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed HTTP Core compatibility changed")

    integration = managed.HttpIntegration()
    discovered = await integration.detect(
        DiscoveryRequest(
            system_id="service_host",
            label="Service host",
            address="service.example.test",
        ),
        context(),
        Probe(),
    )
    if len(discovered) != 1:
        raise AssertionError(f"expected one bounded HTTP discovery candidate, got {len(discovered)}")
    evidence = discovered[0]
    if evidence.endpoint != "https://service.example.test:443":
        raise AssertionError(f"unexpected HTTP discovery endpoint {evidence.endpoint!r}")
    if evidence.default_selected:
        raise AssertionError("generic HTTP discovery must remain explicitly opt-in")

    plan = integration.plan(request(), context())
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
    config = provider["config"]
    if provider["adapter"] != "http":
        raise AssertionError("HTTP plan stopped targeting the shared provider-blind HTTP adapter")
    if config["statuses"] != [200, 204, 401, 402]:
        raise AssertionError(f"HTTP status normalization changed: {config['statuses']!r}")
    if config["follow_redirects"] is not False or config["verify_tls"] is not True:
        raise AssertionError("HTTP redirect/TLS policy changed")
    if config["header"] != {"X-Service": "monitorbox"}:
        raise AssertionError("HTTP response-header assertion changed")
    if config["request_header_name"] != "Authorization":
        raise AssertionError("HTTP protected request-header name changed")
    if "request_header_value" in config or SECRET in json.dumps(object_data, sort_keys=True):
        raise AssertionError("HTTP protected request-header value entered canonical object intent")

    runtime = integration.build_runtime_intent(request(), context())
    if runtime.plugin_id != "http" or len(runtime.checks) != 1:
        raise AssertionError("HTTP runtime intent shape changed")
    check = runtime.checks[0]
    if check["adapter"] != "http" or check["agent_id"] != "monitor":
        raise AssertionError("HTTP runtime intent lost generic adapter/agent ownership")
    if check["config"].get("request_header_value_env") != "MONITORBOX_MANAGED_HTTP_SERVICE_HTTP_HEADER":
        raise AssertionError("HTTP runtime intent protected-header binding changed")

    presentation = integration.describe(context())
    fields = {item.key: item for item in presentation.fields}
    if not fields["request_header_value"].secret:
        raise AssertionError("HTTP protected request-header value is no longer presented as secret")
    if presentation.provenance_keys != ("transport", "tls_trust_fallback"):
        raise AssertionError("HTTP presentation provenance contract changed")

    identities = integration.identities(candidate(), context())
    if len(identities) != 1 or identities[0].namespace != "http-url":
        raise AssertionError("HTTP identity namespace changed")
    if identities[0].value != "https://service.example.test:443":
        raise AssertionError("HTTP URL identity normalization changed")


def main() -> None:
    asyncio.run(accept())
    print("managed HTTP behavioral acceptance against Core 0556: PASS")


if __name__ == "__main__":
    main()
