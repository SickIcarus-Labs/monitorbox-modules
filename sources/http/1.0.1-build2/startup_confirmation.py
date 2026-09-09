from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from monitorbox.v2.adapters import AdapterRunner
from monitorbox.v2.config import CheckConfig
from monitorbox.v2.model import State
from monitorbox.v2.plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult

LEGACY_SELF_CHECK_ID = "monitorbox_api"
LEGACY_STARTUP_CONFIRMATION_SECONDS = 10.0
MAX_STARTUP_CONFIRMATION_SECONDS = 30.0


def startup_confirmation_seconds(request: RuntimeExecutionRequest) -> float:
    raw: Any = request.options.get("startup_confirmation_seconds")
    if raw in (None, ""):
        return LEGACY_STARTUP_CONFIRMATION_SECONDS if request.check_id == LEGACY_SELF_CHECK_ID else 0.0
    if isinstance(raw, bool):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    return min(value, MAX_STARTUP_CONFIRMATION_SECONDS)


class HttpRuntimeExecutor:
    """HTTP transport execution plus bounded, check-local startup confirmation."""

    def __init__(
        self,
        *,
        runner_factory: Callable[[], AdapterRunner] = AdapterRunner,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runner_factory = runner_factory
        self._clock = clock
        self._runner: AdapterRunner | None = None
        self._started_at: float | None = None
        self._seen_success: set[str] = set()

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context
        if self._runner is not None:
            return
        self._runner = self._runner_factory()
        await self._runner.start()
        self._started_at = self._clock()
        self._seen_success.clear()

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context
        runner, self._runner = self._runner, None
        self._started_at = None
        self._seen_success.clear()
        if runner is not None:
            await runner.close()

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        del context
        if request.adapter != "http":
            raise ValueError(f"HTTP executor cannot run adapter {request.adapter!r}")
        runner = self._runner
        if runner is None or self._started_at is None:
            raise RuntimeError("HTTP runtime executor is not started")

        check = CheckConfig(
            id=request.check_id,
            object_id=request.object_id,
            label="HTTP(S) health",
            adapter="http",
            interval_seconds=30.0,
            timeout_seconds=float(request.timeout_seconds),
            enabled=True,
            options=dict(request.options),
            agent_id=str(request.agent_id or ""),
            capability_id=request.capability_id,
            capability_kind=request.capability_kind,
        )
        observation = await runner.run(check)
        state = observation.state
        if state in {State.HEALTHY, State.DEGRADED}:
            self._seen_success.add(request.check_id)
            return self._result(observation)

        confirmation = startup_confirmation_seconds(request)
        elapsed = max(0.0, self._clock() - self._started_at)
        if (
            confirmation > 0
            and request.check_id not in self._seen_success
            and elapsed < confirmation
        ):
            metadata = dict(observation.metadata)
            metadata.update(
                {
                    "failure_kind": "startup_readiness",
                    "startup_confirmation_pending": True,
                    "startup_confirmation_seconds": confirmation,
                    "startup_elapsed_seconds": elapsed,
                    "underlying_state": state.value,
                    "underlying_summary": observation.summary[:240],
                }
            )
            return RuntimeExecutionResult(
                state=State.UNKNOWN.value,
                summary="HTTP endpoint is initializing or reconnecting; startup failure awaits confirmation",
                duration_ms=float(observation.duration_ms),
                metrics=dict(observation.metrics),
                metadata=metadata,
            )
        return self._result(observation)

    @staticmethod
    def _result(observation) -> RuntimeExecutionResult:
        return RuntimeExecutionResult(
            state=observation.state.value,
            summary=str(observation.summary),
            duration_ms=float(observation.duration_ms),
            metrics=dict(observation.metrics),
            metadata=dict(observation.metadata),
        )


__all__ = [
    "HttpRuntimeExecutor",
    "LEGACY_SELF_CHECK_ID",
    "LEGACY_STARTUP_CONFIRMATION_SECONDS",
    "MAX_STARTUP_CONFIRMATION_SECONDS",
    "startup_confirmation_seconds",
]
