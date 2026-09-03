from __future__ import annotations

from typing import Any, Mapping

from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult
from .deployment_transition import PortainerDeploymentTransitionRuntimeExecutor


def _container_lifecycle_anomaly(
    *,
    workload_identity: str,
    container: Mapping[str, Any],
) -> dict[str, Any] | None:
    lifecycle_raw = container.get("lifecycle")
    if not isinstance(lifecycle_raw, Mapping) or lifecycle_raw.get("confirmed_anomaly") is not True:
        return None
    lifecycle = dict(lifecycle_raw)
    if lifecycle.get("crash_loop") is True:
        kind = "crash_loop"
    elif lifecycle.get("oom_killed") is True:
        kind = "oom_killed"
    elif lifecycle.get("nonzero_exit") is True:
        kind = "nonzero_exit"
    else:
        state = str(lifecycle.get("state") or container.get("state") or "").casefold()
        health = str(lifecycle.get("health") or container.get("health") or "").casefold()
        if state in {"restarting", "dead"}:
            kind = state
        elif health == "unhealthy":
            kind = "unhealthy"
        else:
            kind = "lifecycle_anomaly"
    return {
        "kind": kind,
        "workload_identity": workload_identity,
        "container_provider_id": container.get("provider_id"),
        "container_name": container.get("name"),
        "state": lifecycle.get("state") or container.get("state"),
        "health": lifecycle.get("health") or container.get("health"),
        "restart_count": lifecycle.get("restart_count"),
        "restart_delta": lifecycle.get("restart_delta"),
        "observation_window_seconds": lifecycle.get("observation_window_seconds"),
        "oom_killed": lifecycle.get("oom_killed") is True,
        "nonzero_exit": lifecycle.get("nonzero_exit") is True,
        "exit_code": lifecycle.get("exit_code"),
        "failing_streak": lifecycle.get("failing_streak"),
    }


def lifecycle_anomalies(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    workloads_raw = metadata.get("workloads")
    if isinstance(workloads_raw, list):
        workloads = workloads_raw
    elif isinstance(metadata.get("containers"), list):
        workloads = [metadata]
    else:
        return anomalies
    for workload in workloads:
        if not isinstance(workload, Mapping):
            continue
        identity = str(
            workload.get("identity")
            or workload.get("workload_identity")
            or ""
        )
        containers = workload.get("containers")
        if not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, Mapping):
                continue
            anomaly = _container_lifecycle_anomaly(
                workload_identity=identity,
                container=container,
            )
            if anomaly is not None:
                anomalies.append(anomaly)
    return anomalies


class PortainerLifecycleTruthRuntimeExecutor(PortainerDeploymentTransitionRuntimeExecutor):
    """Make confirmed provider lifecycle evidence affect Portainer health truth."""

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        metadata = dict(result.metadata)
        anomalies = lifecycle_anomalies(metadata)
        if not anomalies:
            return result
        metadata["lifecycle_anomalies"] = anomalies

        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if operation == "inventory":
            if result.state in {"unknown", "failed", "degraded"}:
                state = result.state
                summary = result.summary
            else:
                state = "degraded"
                summary = (
                    f"{result.summary}; {len(anomalies)} lifecycle anomaly/anomalies"
                )[:400]
        else:
            if result.state in {"unknown", "failed"}:
                state = result.state
                summary = result.summary
            else:
                state = "failed"
                kind = str(anomalies[0].get("kind") or "lifecycle anomaly").replace("_", " ")
                summary = f"Docker workload {kind}"[:400]

        return RuntimeExecutionResult(
            state=state,
            summary=summary,
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )


__all__ = ["PortainerLifecycleTruthRuntimeExecutor", "lifecycle_anomalies"]
