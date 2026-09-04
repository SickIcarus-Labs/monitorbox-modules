#!/usr/bin/env python3
"""Provider-local lifecycle acceptance for managed Portainer build 4.

This deliberately runs without MonitorBox Core. It composes the immutable build-2
lifecycle helpers over the build-3 runtime delta used by build 4 and proves the
provider-owned lifecycle contracts required by monitorbox#126.
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
RUNTIME_SOURCE = ROOT / "sources" / "portainer" / "1.0.0-build3" / "runtime.py"
API_KEY_ENV = "MONITORBOX_PORTAINER_LIFECYCLE_ACCEPTANCE_KEY"


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
    service: str,
    *,
    state: str = "running",
    health: str | None = "healthy",
    generation: int = 1,
    project: str = "media",
) -> dict[str, Any]:
    if state == "running":
        status = "Up 10 minutes"
    elif state == "restarting":
        status = "Restarting (1) 2 seconds ago"
    else:
        status = "Exited (1) 1 minute ago"
    if health:
        status += " (health: starting)" if health == "starting" else f" ({health})"
    return {
        "Id": f"{service}-generation-{generation}",
        "Names": [f"/{service}"],
        "Image": f"example/{service}:1",
        "ImageID": f"sha256:{service}{generation}",
        "State": state,
        "Status": status,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
        },
        "Ports": [],
    }


def _inspect(
    *,
    state: str,
    health: str | None,
    restart_count: int = 0,
    exit_code: int = 0,
    oom: bool = False,
    restarting: bool = False,
    dead: bool = False,
) -> dict[str, Any]:
    state_payload: dict[str, Any] = {
        "Status": state,
        "ExitCode": exit_code,
        "OOMKilled": oom,
        "Restarting": restarting,
        "Dead": dead,
        "StartedAt": "2026-09-04T00:00:00Z",
        "FinishedAt": "2026-09-04T00:01:00Z" if state != "running" else "",
    }
    if health is not None:
        state_payload["Health"] = {
            "Status": health,
            "FailingStreak": 0 if health != "unhealthy" else 3,
        }
    return {"RestartCount": restart_count, "State": state_payload}


class LifecycleFixtureMixin:
    endpoints = [
        {
            "Id": 1,
            "Name": "Goliath",
            "ContainerEngine": "docker",
            "URL": "tcp://goliath:2375",
            "Status": 1,
        }
    ]

    def __init__(self, containers, inspect_payloads=None):
        super().__init__()
        self.containers = containers
        self.inspect_payloads = dict(inspect_payloads or {})
        self.inspect_requests: list[str] = []
        self.log_requests: list[str] = []
        self.requested_urls: list[str] = []

    async def _get(self, session, url, headers, verify_tls):
        del session, headers, verify_tls
        self.requested_urls.append(url)
        if url.endswith("/api/endpoints"):
            return list(self.endpoints)
        if url.endswith("/api/endpoints/1/docker/containers/json?all=true"):
            if isinstance(self.containers, BaseException):
                raise self.containers
            return list(self.containers)
        raise AssertionError(f"unexpected Portainer fixture URL: {url}")

    async def _inspect_container(self, options, environment_provider_id, container_provider_id):
        del options
        assert environment_provider_id == 1
        self.inspect_requests.append(container_provider_id)
        payload = self.inspect_payloads.get(container_provider_id)
        if isinstance(payload, BaseException):
            raise payload
        if payload is None:
            raise AssertionError(f"missing inspect fixture for {container_provider_id}")
        return payload

    async def _container_log_tail(self, options, environment_provider_id, container_provider_id):
        del options
        assert environment_provider_id == 1
        self.log_requests.append(container_provider_id)
        return "token=[REDACTED] synthetic crash tail"


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


def _request(identity: str, *, policy: str = "required") -> RuntimeExecutionRequest:
    return RuntimeExecutionRequest(
        "portainer",
        _options(
            operation="workload",
            workload_identity=identity,
            environment_key="goliath",
            policy=policy,
        ),
    )


async def _accept(endpoint, diagnostics, transition) -> None:
    Executor = type(
        "LifecycleFixtureExecutor",
        (LifecycleFixtureMixin, endpoint.PortainerEndpointRuntimeExecutor),
        {},
    )
    os.environ[API_KEY_ENV] = "acceptance-only"
    try:
        # A container can remain in Docker health=starting for a long startup
        # without being declared failed merely because it is still starting.
        slow = _container("slow", health="starting")
        slow_executor = Executor(
            [slow],
            {slow["Id"]: _inspect(state="running", health="starting")},
        )
        slow_result = await slow_executor.execute(
            RuntimeExecutionRequest("portainer", _options()), RuntimeExecutionContext()
        )
        assert slow_result.state == "healthy"
        assert slow_result.metrics["starting_containers"] == 1.0
        assert slow_result.metadata.get("lifecycle_anomalies") in (None, [])
        assert slow_executor.inspect_requests == [slow["Id"]]
        assert slow_executor.log_requests == []

        # Active restart churn is confirmed provider-native lifecycle evidence.
        # Only then may bounded diagnostic logs be requested.
        crash = _container("crashy", state="restarting", health=None)
        crash_executor = Executor(
            [crash],
            {
                crash["Id"]: _inspect(
                    state="restarting",
                    health=None,
                    restart_count=4,
                    exit_code=1,
                    restarting=True,
                )
            },
        )
        crash_result = await crash_executor.execute(
            RuntimeExecutionRequest("portainer", _options()), RuntimeExecutionContext()
        )
        assert crash_result.state == "degraded"
        lifecycle = crash_result.metadata["lifecycle_anomalies"][0]
        assert lifecycle["kind"] == "crash_loop"
        assert lifecycle["restart_count"] == 4
        assert crash_executor.inspect_requests == [crash["Id"]]
        assert crash_executor.log_requests == [crash["Id"]]

        # OOM/non-zero exit truth survives into a required targeted workload
        # failure; diagnostics remain provider-local and bounded.
        stopped = _container("worker", state="exited", health=None)
        stopped_identity = "compose:goliath:media:worker"
        required = Executor(
            [stopped],
            {
                stopped["Id"]: _inspect(
                    state="exited",
                    health=None,
                    exit_code=137,
                    oom=True,
                )
            },
        )
        required_result = await required.execute(
            _request(stopped_identity, policy="required"), RuntimeExecutionContext()
        )
        assert required_result.state == "failed"
        assert required_result.metadata["lifecycle_anomalies"][0]["kind"] == "oom_killed"
        assert required.inspect_requests == [stopped["Id"]]
        assert required.log_requests == [stopped["Id"]]

        # An optional stopped/on-demand workload remains health-neutral and does
        # not trigger the extra targeted inspect path.
        optional = Executor([stopped], {stopped["Id"]: RuntimeError("must not inspect")})
        optional_result = await optional.execute(
            _request(stopped_identity, policy="optional"), RuntimeExecutionContext()
        )
        assert optional_result.state == "healthy"
        assert optional_result.metadata["health_neutral"] is True
        assert optional.inspect_requests == []
        assert optional.log_requests == []

        # A correlated multi-member Compose disruption is a short deployment
        # transition, not two independent hard failures. Single-member loss is
        # intentionally insufficient to activate the transition grace.
        transition_executor = transition.PortainerDeploymentTransitionRuntimeExecutor()
        base = _options()
        before = {
            "successful_environments": {"goliath"},
            "environments": [{"key": "goliath"}],
            "workloads": [
                {
                    "identity": "compose:goliath:ombi:web",
                    "environment_key": "goliath",
                    "compose_project": "ombi",
                    "containers": [{"state": "running"}],
                },
                {
                    "identity": "compose:goliath:ombi:db",
                    "environment_key": "goliath",
                    "compose_project": "ombi",
                    "containers": [{"state": "running"}],
                },
                {
                    "identity": "compose:goliath:ombi:admin",
                    "environment_key": "goliath",
                    "compose_project": "ombi",
                    "containers": [{"state": "running"}],
                },
            ],
        }
        transition_executor._observe_compose_transitions(base, before)
        one_missing = {
            **before,
            "workloads": before["workloads"][1:],
        }
        transition_executor._observe_compose_transitions(base, one_missing)
        assert transition_executor._transition_for(base, "compose:goliath:ombi:web") is None
        two_missing = {
            **before,
            "workloads": before["workloads"][2:],
        }
        transition_executor._observe_compose_transitions(base, two_missing)
        web_transition = transition_executor._transition_for(
            base, "compose:goliath:ombi:web"
        )
        db_transition = transition_executor._transition_for(
            base, "compose:goliath:ombi:db"
        )
        assert web_transition is not None and db_transition is not None
        assert web_transition["kind"] == "compose_multi_member_transition"
        assert web_transition["compose_project"] == "ombi"

        # Provider loss invalidates transition baselines. Recovery cannot be
        # compared against pre-outage state to invent a deployment transition.
        unavailable = {
            "successful_environments": set(),
            "environments": [{"key": "goliath"}],
            "workloads": [],
        }
        transition_executor._observe_compose_transitions(base, unavailable)
        assert transition_executor._transition_for(base, "compose:goliath:ombi:web") is None

        # Hard bounds are part of the provider contract, not test conveniences.
        assert diagnostics._MAX_DIAGNOSTIC_CONTAINERS == 8
        assert diagnostics._MAX_DIAGNOSTIC_CONCURRENCY == 4
        assert diagnostics._MAX_LOG_BYTES == 16 * 1024
        assert diagnostics._MAX_LOG_CHARS == 4096
        assert diagnostics._LOG_TAIL_LINES == 40
        redacted = diagnostics._redact_log_tail(
            "Authorization: Bearer very-secret\npassword=hunter2\nhttps://user:pass@example.test/"
        )
        assert "very-secret" not in redacted
        assert "hunter2" not in redacted
        assert "user:pass" not in redacted
        assert "[REDACTED]" in redacted
    finally:
        os.environ.pop(API_KEY_ENV, None)


def main() -> None:
    _install_stubs()
    prefix = "candidate.integrations.portainer"
    _load(f"{prefix}.suggestions", BASE_SOURCE / "suggestions.py")
    _load(f"{prefix}.runtime", RUNTIME_SOURCE)
    diagnostics = _load(
        f"{prefix}.lifecycle_diagnostics", BASE_SOURCE / "lifecycle_diagnostics.py"
    )
    _load(
        f"{prefix}.expected_state_diagnostics",
        BASE_SOURCE / "expected_state_diagnostics.py",
    )
    transition = _load(
        f"{prefix}.deployment_transition", BASE_SOURCE / "deployment_transition.py"
    )
    _load(f"{prefix}.lifecycle_truth", BASE_SOURCE / "lifecycle_truth.py")
    endpoint = _load(
        f"{prefix}.endpoint_provenance", BASE_SOURCE / "endpoint_provenance.py"
    )
    asyncio.run(_accept(endpoint, diagnostics, transition))
    print(
        "Portainer build-4 lifecycle acceptance: PASS "
        "(slow-start neutrality + crash/OOM truth + bounded diagnostics + "
        "expected-state policy + Compose transition/provider-loss semantics)"
    )


if __name__ == "__main__":
    main()
