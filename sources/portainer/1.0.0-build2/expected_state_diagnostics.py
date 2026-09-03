from __future__ import annotations

from typing import Any, Mapping

from .lifecycle_diagnostics import PortainerLifecycleRuntimeExecutor


class PortainerExpectedStateDiagnosticsRuntimeExecutor(PortainerLifecycleRuntimeExecutor):
    """Use configured lifecycle intent only to bound additional provider evidence.

    Inventory remains policy-neutral. For a targeted required workload that is
    already known to be non-running, inspect only that workload's containers so
    the failure can carry exit/OOM evidence. Optional stopped/on-demand workloads
    deliberately do not trigger this extra diagnostic read.
    """

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        inventory = await super()._inventory(options)
        operation = str(options.get("operation", "inventory")).strip().casefold()
        policy = str(options.get("policy", "optional")).strip().casefold()
        target_identity = str(options.get("workload_identity") or "").strip()
        if operation == "inventory" or policy != "required" or not target_identity:
            return inventory

        workloads = inventory.get("workloads")
        if not isinstance(workloads, list):
            return inventory
        target = next(
            (
                workload
                for workload in workloads
                if isinstance(workload, dict)
                and str(workload.get("identity") or "") == target_identity
            ),
            None,
        )
        if target is None:
            return inventory
        environment_provider_id = target.get("environment_provider_id")
        if isinstance(environment_provider_id, bool) or not isinstance(environment_provider_id, int):
            return inventory
        containers = target.get("containers")
        if not isinstance(containers, list):
            return inventory

        for container in containers:
            if not isinstance(container, dict) or "lifecycle" in container:
                continue
            state = str(container.get("state") or "unknown").strip().casefold()
            if state == "running":
                continue
            lifecycle = await self._container_lifecycle(
                options,
                workload=target,
                container=container,
                environment_provider_id=environment_provider_id,
            )
            if lifecycle:
                container["lifecycle"] = lifecycle
        return inventory


__all__ = ["PortainerExpectedStateDiagnosticsRuntimeExecutor"]
