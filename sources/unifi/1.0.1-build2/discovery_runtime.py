from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

import aiohttp

from ...plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)
from .discovery import unifi_evidence
from .vertical_runtime import UniFiRuntimeExecutor as _VerticalUniFiRuntimeExecutor

_AUTH_DENIAL_HTTP_STATUSES = {401, 403}


class UniFiRuntimeExecutor(_VerticalUniFiRuntimeExecutor):
    """UniFi executor with provider-owned recovery and discovery projection.

    UniFi authentication/session state is ephemeral observer state. A rejected
    cached session must never become durable authority: discard it, retry one
    fresh login when appropriate, and classify unresolved provider/auth loss as
    UNKNOWN rather than fabricating a target failure.
    """

    @staticmethod
    def _auth_denial(exc: BaseException) -> bool:
        detail = str(exc)
        if "UniFi authentication returned HTTP" in detail:
            return True
        return any(f"HTTP {status}" in detail for status in _AUTH_DENIAL_HTTP_STATUSES)

    def _invalidate_auth(
        self,
        options: Mapping[str, Any],
        *,
        path: str | None = None,
    ) -> None:
        base = str(options.get("base_url") or "").rstrip("/")
        if base:
            self._auth.pop(base, None)
        if path and self._is_device_inventory(path):
            self._device_snapshots.pop(self._snapshot_key(options, path), None)

    async def _get(self, options: Mapping[str, Any], path: str) -> Any:
        base = str(options.get("base_url") or "").rstrip("/")
        had_cached_auth = bool(base and base in self._auth)
        try:
            return await super()._get(options, path)
        except RuntimeError as exc:
            if not self._auth_denial(exc):
                raise
            self._invalidate_auth(options, path=path)
            if not had_cached_auth:
                raise

        try:
            return await super()._get(options, path)
        except RuntimeError as exc:
            if self._auth_denial(exc):
                self._invalidate_auth(options, path=path)
            raise

    async def _traffic_flows(self, options: Mapping[str, Any]) -> list[dict[str, Any]]:
        base = str(options.get("base_url") or "").rstrip("/")
        had_cached_auth = bool(base and base in self._auth)
        try:
            return await super()._traffic_flows(options)
        except RuntimeError as exc:
            if not self._auth_denial(exc):
                raise
            self._invalidate_auth(options)
            if not had_cached_auth:
                raise

        try:
            return await super()._traffic_flows(options)
        except RuntimeError as exc:
            if self._auth_denial(exc):
                self._invalidate_auth(options)
            raise

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        started = time.monotonic()
        try:
            result = await super().execute(request, context)
        except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            detail = f"{type(exc).__name__}: {exc}"[:300]
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"UniFi provider unavailable: {detail}"[:400],
                duration_ms=(time.monotonic() - started) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": False,
                    "failure_kind": "monitor_dependency",
                    "provider_error_type": type(exc).__name__,
                },
            )

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
