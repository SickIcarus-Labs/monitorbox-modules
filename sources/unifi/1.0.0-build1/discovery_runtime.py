from __future__ import annotations

from ...plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)
from .discovery import unifi_evidence
from .vertical_runtime import UniFiRuntimeExecutor as _VerticalUniFiRuntimeExecutor


class UniFiRuntimeExecutor(_VerticalUniFiRuntimeExecutor):
    """UniFi executor with provider-owned post-runtime discovery projection."""

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        runtime_operation = str(request.options.get("runtime_operation", "")).strip()
        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if runtime_operation or operation != "inventory":
            return result

        metadata = dict(result.metadata)
        evidence = unifi_evidence(
            metadata.get("devices", []),
            metadata.get("ports", []),
        )
        metadata["discovery_evidence"] = [item.as_dict() for item in evidence]
        return RuntimeExecutionResult(
            state=result.state,
            summary=result.summary,
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )


__all__ = ["UniFiRuntimeExecutor"]
