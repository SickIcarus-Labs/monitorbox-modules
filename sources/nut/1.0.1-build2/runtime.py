from __future__ import annotations

import asyncio
import shlex
import time
from contextlib import suppress
from typing import Any

from monitorbox.v2.plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)

_CRITICAL_STATUS = frozenset({"LB", "OVER", "FSD", "OFF"})
_DEGRADED_STATUS = frozenset({"RB", "BYPASS"})
_SEVERE_ALARM_MARKERS = (
    "shutdown",
    "overload",
    "low battery",
    "output off",
    "critical",
)
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_VARIABLES = 2048


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000


async def _nut_vars(host: str, port: int, ups: str) -> dict[str, str]:
    writer = None
    values: dict[str, str] = {}
    received = 0
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(f"LIST VAR {ups}\n".encode("ascii"))
        await writer.drain()
        while True:
            raw = await reader.readline()
            if not raw:
                raise OSError("NUT server closed response")
            received += len(raw)
            if received > _MAX_RESPONSE_BYTES or len(values) > _MAX_VARIABLES:
                raise OSError("NUT response exceeded safety limit")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == f"END LIST VAR {ups}":
                return values
            if line.startswith("ERR "):
                raise OSError(line)
            if line == f"BEGIN LIST VAR {ups}":
                continue
            try:
                parts = shlex.split(line)
            except ValueError:
                continue
            if len(parts) >= 4 and parts[:2] == ["VAR", ups]:
                values[parts[2]] = parts[3]
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()


def _classify(
    values: dict[str, str],
    *,
    host: str,
    ups: str,
    started: float,
) -> RuntimeExecutionResult:
    metrics: dict[str, float] = {}
    for key, value in values.items():
        try:
            metrics[key] = float(value)
        except ValueError:
            pass

    status = set(values.get("ups.status", "").split())
    alarm = values.get("ups.alarm", "").strip()
    critical = status & _CRITICAL_STATUS
    degraded = status & _DEGRADED_STATUS
    severe_alarm = bool(
        alarm and any(marker in alarm.casefold() for marker in _SEVERE_ALARM_MARKERS)
    )
    power_source = "battery" if "OB" in status else "utility" if "OL" in status else "unknown"

    if critical or severe_alarm:
        state, health = "failed", "critical"
    elif degraded or alarm:
        state, health = "degraded", "degraded"
    elif status:
        state, health = "healthy", "healthy"
    else:
        state, health = "unknown", "unknown"

    if critical or severe_alarm:
        summary = f"UPS critical: {alarm[:160] if severe_alarm else ' '.join(sorted(critical))}"
    elif alarm:
        summary = f"UPS alarm: {alarm[:160]}"
    elif degraded:
        summary = f"UPS needs attention: {' '.join(sorted(degraded))}"
    elif power_source == "battery":
        summary = "Operating on battery"
    elif power_source == "utility":
        summary = "Utility power"
    else:
        summary = f"UPS status unknown: {' '.join(sorted(status)) or 'no status'}"

    metadata_keys = {
        "ups.status",
        "ups.alarm",
        "ups.model",
        "ups.serial",
        "ups.mfr",
        "ups.test.result",
        "battery.type",
        "battery.charger.status",
        "driver.name",
        "driver.version",
    }
    metadata: dict[str, Any] = {
        key: value for key, value in values.items() if key in metadata_keys
    }
    metadata.update(
        {
            "power_source": power_source,
            "ups_health": health,
            "status_tokens": sorted(status),
            "nut_host": host,
            "nut_ups": ups,
            "provider": "nut",
        }
    )
    if state == "unknown":
        metadata["failure_kind"] = "provider_semantics_unknown"

    return RuntimeExecutionResult(
        state=state,
        summary=summary,
        duration_ms=_elapsed_ms(started),
        metrics=metrics,
        metadata=metadata,
    )


class NutRuntimeExecutor:
    """Self-contained managed NUT runtime executor over bounded TCP."""

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        del context
        started = time.monotonic()
        if request.adapter != "nut":
            raise ValueError(f"NUT executor cannot run adapter {request.adapter!r}")

        options = dict(request.options)
        host = str(options.get("host") or "").strip()
        ups = str(options.get("ups") or "").strip()
        try:
            port = int(options.get("port", 3493))
        except (TypeError, ValueError):
            port = 0
        if not host or not ups or not 1 <= port <= 65535:
            return RuntimeExecutionResult(
                state="unknown",
                summary="NUT monitor configuration is incomplete or invalid",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "nut"},
            )

        error: Exception | None = None
        values: dict[str, str] = {}
        for attempt in range(2):
            try:
                values = await _nut_vars(host, port, ups)
                error = None
                break
            except (OSError, ValueError) as exc:
                error = exc
                if attempt == 0:
                    await asyncio.sleep(0.1)
        if error is not None:
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"NUT monitoring unavailable: {str(error)[:180]}",
                duration_ms=_elapsed_ms(started),
                metadata={
                    "failure_kind": "monitor_dependency",
                    "provider": "nut",
                    "nut_host": host,
                    "nut_ups": ups,
                },
            )

        return _classify(values, host=host, ups=ups, started=started)


__all__ = ["NutRuntimeExecutor"]
