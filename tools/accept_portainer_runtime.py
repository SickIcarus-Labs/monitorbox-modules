#!/usr/bin/env python3
"""Provider-local acceptance for managed Portainer build 3 runtime truth.

The test deliberately runs without MonitorBox Core. It loads build 3's changed
runtime over the immutable build-2 helper source and proves the provider-local
contracts that previously allowed a 20/20 false green.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASE_SOURCE = ROOT / "sources" / "portainer" / "1.0.0-build2"
DELTA_SOURCE = ROOT / "sources" / "portainer" / "1.0.0-build3"
API_KEY_ENV = "MONITORBOX_PORTAINER_ACCEPTANCE_KEY"


@dataclass
class RuntimeExecutionRequest:
    adapter: str
    options: dict[str, Any]


class RuntimeExecutionContext:
    pass


@dataclass
class RuntimeExecutionResult:
    state: str
    summary: str
    duration_ms: float
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _install_stubs() -> None:
    for name in ("candidate", "candidate.integrations", "candidate.integrations.portainer"):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module

    plugin_api = types.ModuleType("candidate.plugin_api")
    plugin_api.RuntimeExecutionContext = RuntimeExecutionContext
    plugin_api.RuntimeExecutionRequest = RuntimeExecutionRequest
    plugin_api.RuntimeExecutionResult = RuntimeExecutionResult
    sys.modules[plugin_api.__name__] = plugin_api

    aiohttp = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class ClientSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    aiohttp.ClientTimeout = ClientTimeout
    aiohttp.ClientSession = ClientSession
    sys.modules["aiohttp"] = aiohttp


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _container(
    prefix: str,
    number: int,
    *,
    generation: int = 1,
    unhealthy: bool = False,
    standalone: bool = False,
) -> dict[str, Any]:
    service = f"svc{number:02d}"
    labels = {} if standalone else {
        "com.docker.compose.project": prefix,
        "com.docker.compose.service": service,
    }
    return {
        "Id": f"{prefix}-{number}-generation-{generation}",
        "Names": [f"/{prefix}-{service}"],
        "Image": f"example/{service}:1",
        "ImageID": f"sha256:{prefix}{number:02d}",
        "State": "running",
        "Status": "Up 1 hour (unhealthy)" if unhealthy else "Up 1 hour (healthy)",
        "Labels": labels,
        "Ports": [],
    }


def _fixture(*, generation: int = 1) -> dict[int, list[dict[str, Any]]]:
    return {
        1: [
            _container(
                "goliath",
                number,
                generation=generation,
                unhealthy=number == 21,
            )
            for number in range(1, 22)
        ],
        2: [
            _container(
                "arrrrr2",
                number,
                generation=generation,
                standalone=number == 16,
            )
            for number in range(1, 17)
        ],
    }


class FixtureExecutorMixin:
    endpoints = [
        {"Id": 1, "Name": "Goliath", "ContainerEngine": "docker", "URL": "tcp://goliath:2375", "Status": 1},
        {"Id": 2, "Name": "Arrrrr2", "ContainerEngine": "docker", "URL": "tcp://arrrrr2:2375", "Status": 1},
    ]

    def __init__(self, payloads):
        super().__init__()
        self.payloads = payloads
        self.requested_urls: list[str] = []

    async def _get(self, session, url, headers, verify_tls):
        del session, headers, verify_tls
        self.requested_urls.append(url)
        if url.endswith("/api/endpoints"):
            return list(self.endpoints)
        for provider_id in (1, 2):
            marker = f"/api/endpoints/{provider_id}/docker/containers/json?all=true"
            if url.endswith(marker):
                payload = self.payloads[provider_id]
                if isinstance(payload, BaseException):
                    raise payload
                return list(payload)
        raise AssertionError(f"unexpected Portainer fixture URL: {url}")


def _options(**overrides):
    options = {
        "base_url": "https://portainer.example",
        "api_key_env": API_KEY_ENV,
        "verify_tls": True,
        "operation": "inventory",
        "environment_ids": [1],
    }
    options.update(overrides)
    return options


def _request(identity: str, environment_key: str, policy: str = "required"):
    return RuntimeExecutionRequest(
        "portainer",
        _options(
            operation="workload",
            environment_ids=[2],
            workload_identity=identity,
            environment_key=environment_key,
            policy=policy,
        ),
    )


async def _accept(runtime) -> None:
    Executor = type("FixtureExecutor", (FixtureExecutorMixin, runtime.PortainerRuntimeExecutor), {})
    os.environ[API_KEY_ENV] = "acceptance-only"
    try:
        fixture = _fixture()
        executor = Executor(fixture)
        inventory = await executor._inventory(_options())
        workloads = inventory["workloads"]

        # Inventory authority scans every visible Docker environment even when
        # an individual workload check is configured for a subset.
        assert len(workloads) == 37
        assert len(inventory["_workloads_by_identity"]) == 37
        assert {row["environment_provider_id"] for row in workloads} == {1, 2}
        container_urls = [url for url in executor.requested_urls if "/containers/json" in url]
        assert len(container_urls) == 2
        assert all(url.endswith("containers/json?all=true") for url in container_urls)

        # Provider evidence consistently preserves Compose project/service
        # provenance while leaving a standalone container explicitly standalone.
        compose = [row for row in workloads if row["deployment_kind"] == "compose"]
        standalone = [row for row in workloads if row["deployment_kind"] == "standalone"]
        assert len(compose) == 36
        assert len(standalone) == 1
        assert all(row["compose_project"] and row["compose_service"] for row in compose)
        assert standalone[0]["compose_project"] is None
        assert standalone[0]["compose_service"] is None
        assert standalone[0]["label"] == "arrrrr2-svc16"

        observation = await executor.execute(
            RuntimeExecutionRequest("portainer", _options()), RuntimeExecutionContext()
        )
        assert observation.state == "degraded"
        assert observation.metrics["containers"] == 37.0
        assert observation.metrics["unhealthy_containers"] == 1.0
        anomaly = next(
            item
            for item in observation.metadata["runtime_anomalies"]
            if item["kind"] == "unhealthy"
        )
        assert anomaly["container_name"] == "goliath-svc21"
        assert len(observation.metadata["discovery_evidence"]) == 37

        # Recreate under entirely new provider/container IDs must retain logical
        # Compose/name identities.
        first_identities = {row["identity"] for row in workloads}
        recreated = Executor(_fixture(generation=2))
        recreated_inventory = await recreated._inventory(_options())
        assert {row["identity"] for row in recreated_inventory["workloads"]} == first_identities
        old_provider_ids = {
            container["provider_id"]
            for workload in workloads
            for container in workload["containers"]
        }
        new_provider_ids = {
            container["provider_id"]
            for workload in recreated_inventory["workloads"]
            for container in workload["containers"]
        }
        assert old_provider_ids.isdisjoint(new_provider_ids)

        # Targeted checks reuse the retained identity index instead of rescanning
        # the 37-row list.
        target = next(
            row
            for row in workloads
            if row["environment_provider_id"] == 2 and row["deployment_kind"] == "compose"
        )
        targeted = await executor.execute(
            _request(target["identity"], target["environment_key"]),
            RuntimeExecutionContext(),
        )
        assert targeted.state == "healthy"
        assert targeted.metadata["identity"] == target["identity"]

        # Provider loss is observation loss, never proof of workload absence.
        unavailable = Executor({1: fixture[1], 2: RuntimeError("fixture unavailable")})
        unknown = await unavailable.execute(
            _request(target["identity"], target["environment_key"]),
            RuntimeExecutionContext(),
        )
        assert unknown.state == "unknown"
        assert unknown.metadata["authoritative"] is False
        assert unknown.metadata.get("missing") is not True

        # Only successful authoritative absence drives required/optional missing
        # policy outcomes.
        absent = Executor({1: fixture[1], 2: []})
        required_missing = await absent.execute(
            _request(target["identity"], target["environment_key"]),
            RuntimeExecutionContext(),
        )
        assert required_missing.state == "failed"
        assert required_missing.metadata["missing"] is True

        optional_missing = await absent.execute(
            _request(target["identity"], target["environment_key"], "optional"),
            RuntimeExecutionContext(),
        )
        assert optional_missing.state == "healthy"
        assert optional_missing.metadata["retired"] is True
        assert optional_missing.metadata["health_neutral"] is True
    finally:
        os.environ.pop(API_KEY_ENV, None)


def main() -> None:
    _install_stubs()
    _load("candidate.integrations.portainer.suggestions", BASE_SOURCE / "suggestions.py")
    runtime = _load("candidate.integrations.portainer.runtime", DELTA_SOURCE / "runtime.py")
    asyncio.run(_accept(runtime))
    print(
        "Portainer build-3 provider runtime acceptance: PASS "
        "(37-container coverage + beyond-20 anomaly + Compose provenance + "
        "stable identity + provider-loss truth)"
    )


if __name__ == "__main__":
    main()
