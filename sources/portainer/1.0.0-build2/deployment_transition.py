from __future__ import annotations

import time
from typing import Any, Mapping

from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult
from .expected_state_diagnostics import PortainerExpectedStateDiagnosticsRuntimeExecutor

_TRANSITION_WINDOW_SECONDS = 45.0


def _all_running(workload: Mapping[str, Any]) -> bool:
    containers = workload.get("containers")
    if not isinstance(containers, list) or not containers:
        return False
    states = {
        str(container.get("state") or "unknown").strip().casefold()
        for container in containers
        if isinstance(container, Mapping)
    }
    return bool(states) and states <= {"running"}


def _has_confirmed_lifecycle_anomaly(metadata: Mapping[str, Any]) -> bool:
    containers = metadata.get("containers")
    if not isinstance(containers, list):
        return False
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        lifecycle = container.get("lifecycle")
        if isinstance(lifecycle, Mapping) and lifecycle.get("confirmed_anomaly") is True:
            return True
    return False


class PortainerDeploymentTransitionRuntimeExecutor(
    PortainerExpectedStateDiagnosticsRuntimeExecutor
):
    """Recognize short correlated Compose churn without inventing operator intent."""

    transition_window_seconds = _TRANSITION_WINDOW_SECONDS

    def __init__(self) -> None:
        super().__init__()
        self._compose_snapshots: dict[
            tuple[str, str, str], dict[str, bool]
        ] = {}
        self._compose_transitions: dict[
            tuple[str, str, str], tuple[float, set[str]]
        ] = {}
        self._identity_groups: dict[tuple[str, str], tuple[str, str, str]] = {}

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        inventory = await super()._inventory(options)
        self._observe_compose_transitions(options, inventory)
        return inventory

    def _drop_group(self, key: tuple[str, str, str]) -> None:
        self._compose_snapshots.pop(key, None)
        self._compose_transitions.pop(key, None)
        for identity_key, mapped_key in list(self._identity_groups.items()):
            if mapped_key == key:
                self._identity_groups.pop(identity_key, None)

    def _retain_group_identities(
        self,
        key: tuple[str, str, str],
        identities: set[str],
    ) -> None:
        for identity_key, mapped_key in list(self._identity_groups.items()):
            if mapped_key == key and identity_key[1] not in identities:
                self._identity_groups.pop(identity_key, None)

    def _observe_compose_transitions(
        self,
        options: Mapping[str, Any],
        inventory: Mapping[str, Any],
    ) -> None:
        base = str(options.get("base_url") or "").rstrip("/")
        if not base:
            return
        successful_raw = inventory.get("successful_environments")
        successful = (
            {str(item) for item in successful_raw}
            if isinstance(successful_raw, (set, list, tuple))
            else set()
        )
        workloads = inventory.get("workloads")
        if not isinstance(workloads, list):
            return

        declared_environments: set[str] = set()
        environments = inventory.get("environments")
        if isinstance(environments, list):
            declared_environments = {
                str(environment.get("key") or "").strip()
                for environment in environments
                if isinstance(environment, Mapping)
                and str(environment.get("key") or "").strip()
            }
        known_group_keys = (
            set(self._compose_snapshots)
            | set(self._compose_transitions)
            | set(self._identity_groups.values())
        )
        for key in known_group_keys:
            if key[0] == base and (
                key[1] not in declared_environments or key[1] not in successful
            ):
                # A provider-observability gap invalidates the previous running
                # baseline. Never infer a fresh deployment transition by comparing
                # pre-outage state with the first successful post-outage inventory.
                self._drop_group(key)

        current: dict[tuple[str, str, str], dict[str, bool]] = {}
        for workload in workloads:
            if not isinstance(workload, Mapping):
                continue
            environment_key = str(workload.get("environment_key") or "").strip()
            project = str(workload.get("compose_project") or "").strip()
            identity = str(workload.get("identity") or "").strip()
            if not environment_key or not project or not identity:
                continue
            key = (base, environment_key, project)
            current.setdefault(key, {})[identity] = _all_running(workload)
            self._identity_groups[(base, identity)] = key

        now = time.monotonic()
        relevant_keys = {
            key
            for key in set(self._compose_snapshots) | set(current)
            if key[0] == base and key[1] in successful
        }
        for key in relevant_keys:
            previous = self._compose_snapshots.get(key, {})
            present = current.get(key, {})
            for identity in previous:
                self._identity_groups[(base, identity)] = key
            disrupted = {
                identity
                for identity, was_running in previous.items()
                if was_running and not present.get(identity, False)
            }
            active = self._compose_transitions.get(key)
            if len(disrupted) >= 2:
                if active is None:
                    active = (now, set(disrupted))
                else:
                    active = (active[0], set(active[1]) | disrupted)
                self._compose_transitions[key] = active

            active = self._compose_transitions.get(key)
            if active is not None:
                started, affected = active
                if now - started > self.transition_window_seconds:
                    self._compose_transitions.pop(key, None)
                else:
                    unresolved = {
                        identity
                        for identity in affected
                        if not present.get(identity, False)
                    }
                    if unresolved:
                        self._compose_transitions[key] = (started, unresolved)
                    else:
                        self._compose_transitions.pop(key, None)

            active = self._compose_transitions.get(key)
            retained_identities = set(present)
            if active is not None:
                retained_identities.update(active[1])
            self._retain_group_identities(key, retained_identities)
            if present or active is not None:
                self._compose_snapshots[key] = dict(present)
            else:
                self._compose_snapshots.pop(key, None)

    def _transition_for(
        self,
        options: Mapping[str, Any],
        workload_identity: str,
    ) -> dict[str, Any] | None:
        base = str(options.get("base_url") or "").rstrip("/")
        key = self._identity_groups.get((base, workload_identity))
        if key is None:
            return None
        active = self._compose_transitions.get(key)
        if active is None:
            return None
        started, affected = active
        now = time.monotonic()
        age = max(0.0, now - started)
        if age > self.transition_window_seconds or workload_identity not in affected:
            if age > self.transition_window_seconds:
                self._compose_transitions.pop(key, None)
            return None
        return {
            "kind": "compose_multi_member_transition",
            "environment_key": key[1],
            "compose_project": key[2],
            "affected_workload_identities": sorted(affected),
            "age_seconds": round(age, 3),
            "grace_remaining_seconds": round(
                max(0.0, self.transition_window_seconds - age), 3
            ),
        }

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if operation == "inventory":
            active = []
            base = str(request.options.get("base_url") or "").rstrip("/")
            now = time.monotonic()
            for key, (started, affected) in self._compose_transitions.items():
                if key[0] != base or now - started > self.transition_window_seconds:
                    continue
                active.append(
                    {
                        "kind": "compose_multi_member_transition",
                        "environment_key": key[1],
                        "compose_project": key[2],
                        "affected_workload_identities": sorted(affected),
                        "age_seconds": round(max(0.0, now - started), 3),
                    }
                )
            if not active:
                return result
            metadata = dict(result.metadata)
            metadata["deployment_transitions"] = active
            return RuntimeExecutionResult(
                state=result.state,
                summary=result.summary,
                duration_ms=result.duration_ms,
                metrics=dict(result.metrics),
                metadata=metadata,
            )

        policy = str(request.options.get("policy", "optional")).strip().casefold()
        workload_identity = str(request.options.get("workload_identity") or "").strip()
        if (
            policy != "required"
            or not workload_identity
            or result.state != "failed"
            or _has_confirmed_lifecycle_anomaly(result.metadata)
        ):
            return result
        transition = self._transition_for(request.options, workload_identity)
        if transition is None:
            return result
        metadata = dict(result.metadata)
        metadata["deployment_transition"] = transition
        return RuntimeExecutionResult(
            state="degraded",
            summary="Possible Docker Compose deployment transition: required workload temporarily unavailable",
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )


__all__ = ["PortainerDeploymentTransitionRuntimeExecutor"]
