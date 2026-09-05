from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
_AUTH_DENIAL_INITIAL_BACKOFF_SECONDS = 30.0
_AUTH_DENIAL_MAX_BACKOFF_SECONDS = 300.0
_RATE_LIMIT_BACKOFF_SECONDS = (60.0, 120.0, 240.0, 300.0, 600.0, 1200.0, 1800.0)
_MAX_RETRY_AFTER_SECONDS = 3600.0


class UniFiRuntimeExecutor(_VerticalUniFiRuntimeExecutor):
    """UniFi executor with provider-owned recovery and conservative auth retries.

    UniFi authentication/session state is ephemeral observer state. Rejected
    cached sessions are discarded, but failed logins are rate limited locally
    so concurrent inventory fan-out and fast monitoring cadence cannot keep a
    controller-side login lockout alive. Repeated HTTP 429 responses use an
    intentionally long bounded schedule because UniFi's limiter window is not
    documented and can outlive a five-minute retry ceiling.
    """

    def __init__(self) -> None:
        super().__init__()
        # base_url -> (cooldown_until_monotonic, next_backoff_seconds, reason)
        self._auth_cooldown: dict[str, tuple[float, float, str]] = {}

    async def close(self, context: RuntimeExecutionContext) -> None:
        self._auth_cooldown.clear()
        await super().close(context)

    @staticmethod
    def _auth_denial(exc: BaseException) -> bool:
        detail = str(exc)
        return any(f"HTTP {status}" in detail for status in _AUTH_DENIAL_HTTP_STATUSES)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float | None:
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        try:
            seconds = float(text)
        except ValueError:
            try:
                when = parsedate_to_datetime(text)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                seconds = (when - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return min(_MAX_RETRY_AFTER_SECONDS, max(1.0, seconds))

    @staticmethod
    def _next_rate_limit_backoff(current: float) -> float:
        for candidate in _RATE_LIMIT_BACKOFF_SECONDS:
            if candidate > current:
                return candidate
        return _RATE_LIMIT_BACKOFF_SECONDS[-1]

    def _record_auth_cooldown(
        self,
        base: str,
        *,
        status: int,
        retry_after: str | None = None,
    ) -> float:
        previous = self._auth_cooldown.get(base)
        reason = f"HTTP {status}"

        if status == 429:
            requested = self._retry_after_seconds(retry_after)
            if requested is not None:
                delay = requested
                next_delay = self._next_rate_limit_backoff(delay)
            elif previous is not None and previous[2] == reason:
                delay = max(_RATE_LIMIT_BACKOFF_SECONDS[0], previous[1])
                next_delay = self._next_rate_limit_backoff(delay)
            else:
                delay = _RATE_LIMIT_BACKOFF_SECONDS[0]
                next_delay = _RATE_LIMIT_BACKOFF_SECONDS[1]
        else:
            if previous is not None and previous[2] == reason:
                delay = max(_AUTH_DENIAL_INITIAL_BACKOFF_SECONDS, previous[1])
            else:
                delay = _AUTH_DENIAL_INITIAL_BACKOFF_SECONDS
            next_delay = min(
                _AUTH_DENIAL_MAX_BACKOFF_SECONDS,
                max(_AUTH_DENIAL_INITIAL_BACKOFF_SECONDS, delay * 2.0),
            )

        self._auth_cooldown[base] = (time.monotonic() + delay, next_delay, reason)
        return delay

    def _cooldown_remaining(self, base: str) -> tuple[float, str] | None:
        record = self._auth_cooldown.get(base)
        if record is None:
            return None
        remaining = record[0] - time.monotonic()
        if remaining <= 0:
            return None
        return remaining, record[2]

    async def _login(self, options: Mapping[str, Any]) -> dict[str, str]:
        if self.session is None:
            raise RuntimeError("UniFi runtime executor is not started")
        base = str(options["base_url"]).rstrip("/")
        async with self._auth_lock:
            cached = self._auth.get(base)
            if cached is not None:
                return cached

            cooldown = self._cooldown_remaining(base)
            if cooldown is not None:
                remaining, reason = cooldown
                raise RuntimeError(
                    f"UniFi authentication cooldown active after {reason}; "
                    f"retry in {math.ceil(remaining)}s"
                )

            try:
                username = os.environ[str(options["username_env"])]
                password = os.environ[str(options["password_env"])]
            except KeyError as exc:
                raise RuntimeError(
                    f"credential environment variable is missing: {exc.args[0]}"
                ) from exc

            async with self.session.post(
                base + "/api/auth/login",
                json={"username": username, "password": password, "remember": False},
                ssl=None if self._verify_tls(options) else False,
            ) as response:
                await response.read()
                cookie = response.headers.get("Set-Cookie")
                csrf = response.headers.get("X-Csrf-Token")
                if response.status == 429:
                    delay = self._record_auth_cooldown(
                        base,
                        status=429,
                        retry_after=response.headers.get("Retry-After"),
                    )
                    raise RuntimeError(
                        "UniFi authentication rate limited (HTTP 429); "
                        f"retry in {math.ceil(delay)}s"
                    )
                if response.status != 200 or not cookie or not csrf:
                    if response.status in _AUTH_DENIAL_HTTP_STATUSES:
                        delay = self._record_auth_cooldown(
                            base,
                            status=response.status,
                        )
                        raise RuntimeError(
                            f"UniFi authentication returned HTTP {response.status}; "
                            f"retry in {math.ceil(delay)}s"
                        )
                    raise RuntimeError(
                        f"UniFi authentication returned HTTP {response.status}"
                    )

            headers = {
                "Cookie": cookie.split(";", 1)[0],
                "X-Csrf-Token": csrf,
            }
            self._auth_cooldown.pop(base, None)
            self._auth[base] = headers
            return headers

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
