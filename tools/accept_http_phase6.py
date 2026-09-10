#!/usr/bin/env python3
"""Deterministic #166 acceptance for HTTP 1.0.1 build 2."""
from __future__ import annotations

import asyncio
import enum
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path


class State(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DISABLED = "disabled"


@dataclass
class Observation:
    state: State
    summary: str
    duration_ms: float = 1.0
    metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class CheckConfig:
    id: str
    object_id: str
    label: str
    adapter: str
    interval_seconds: float
    timeout_seconds: float
    enabled: bool
    options: dict
    agent_id: str = ""
    capability_id: str | None = None
    capability_kind: str | None = None


@dataclass
class Request:
    check_id: str
    object_id: str = "monitorbox"
    adapter: str = "http"
    timeout_seconds: float = 5.0
    options: dict = field(default_factory=dict)
    agent_id: str = "monitor"
    capability_id: str | None = None
    capability_kind: str | None = None


@dataclass
class Result:
    state: str
    summary: str
    duration_ms: float
    metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class Context:
    pass


class PlaceholderRunner:
    pass


def load_runtime(root: Path):
    modules = {
        "monitorbox": types.ModuleType("monitorbox"),
        "monitorbox.v2": types.ModuleType("monitorbox.v2"),
        "monitorbox.v2.adapters": types.ModuleType("monitorbox.v2.adapters"),
        "monitorbox.v2.config": types.ModuleType("monitorbox.v2.config"),
        "monitorbox.v2.model": types.ModuleType("monitorbox.v2.model"),
        "monitorbox.v2.plugin_api": types.ModuleType("monitorbox.v2.plugin_api"),
    }
    modules["monitorbox.v2.adapters"].AdapterRunner = PlaceholderRunner
    modules["monitorbox.v2.config"].CheckConfig = CheckConfig
    modules["monitorbox.v2.model"].State = State
    modules["monitorbox.v2.plugin_api"].RuntimeExecutionContext = Context
    modules["monitorbox.v2.plugin_api"].RuntimeExecutionRequest = Request
    modules["monitorbox.v2.plugin_api"].RuntimeExecutionResult = Result
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        path = root / "sources/http/1.0.1-build2/startup_confirmation.py"
        spec = importlib.util.spec_from_file_location("phase6_http_runtime", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Runner:
    def __init__(self, observations: list[Observation]) -> None:
        self.observations = list(observations)
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def run(self, check: CheckConfig) -> Observation:
        assert check.adapter == "http"
        return self.observations.pop(0)


async def execute_case(runtime, observations, request, times):
    clock = Clock()
    runner = Runner(observations)
    executor = runtime.HttpRuntimeExecutor(runner_factory=lambda: runner, clock=clock)
    await executor.start(Context())
    output = []
    for value in times:
        clock.now = value
        output.append(await executor.execute(request, Context()))
    await executor.close(Context())
    assert runner.started and runner.closed
    return output


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    runtime = load_runtime(root)
    failed = Observation(State.FAILED, "ClientConnectorError: connect refused")
    healthy = Observation(State.HEALTHY, "HTTP 200 in 3 ms")

    recovered = await execute_case(runtime, [failed, healthy], Request(check_id="monitorbox_api"), [0, 3])
    assert recovered[0].state == "unknown"
    assert recovered[0].metadata["failure_kind"] == "startup_readiness"
    assert recovered[0].metadata["startup_confirmation_pending"] is True
    assert recovered[1].state == "healthy"

    persistent = await execute_case(runtime, [failed, failed], Request(check_id="monitorbox_api"), [0, 11])
    assert [item.state for item in persistent] == ["unknown", "failed"]

    unrelated = await execute_case(runtime, [failed], Request(check_id="unrelated_http"), [0])
    assert unrelated[0].state == "failed"

    after_success = await execute_case(
        runtime,
        [failed, healthy, failed],
        Request(check_id="custom", options={"startup_confirmation_seconds": 5}),
        [0, 1, 2],
    )
    assert [item.state for item in after_success] == ["unknown", "healthy", "failed"]
    assert runtime.startup_confirmation_seconds(
        Request(check_id="custom", options={"startup_confirmation_seconds": 999})
    ) == 30

    wrapper = (root / "sources/http/1.0.1-build2/__init__.py").read_text(encoding="utf-8")
    builder = (root / "tools/build_first_party_http_build2.py").read_text(encoding="utf-8")
    assert 'runtime_adapter_kinds=("http",)' in wrapper
    assert "runtime_executor=_EXECUTOR" in wrapper
    assert 'MODULE_VERSION = "1.0.1"' in wrapper
    assert "MODULE_BUILD = 2" in wrapper
    assert "previous._rewrite_source" in builder
    print("HTTP Phase-6B acceptance: PASS (bounded self-startup confirmation; steady-state failures remain immediate)")


if __name__ == "__main__":
    asyncio.run(main())
