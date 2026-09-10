from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from typing import Any

STARTUP_JITTER_CAP_SECONDS = 15.0
STARTUP_RETRY_MIN_SECONDS = 5.0
STARTUP_RETRY_MAX_SECONDS = 10.0
STARTUP_ACQUISITION_WINDOW_SECONDS = 60.0
_CHILD_OPERATIONS = frozenset({"camera_state", "snapshot", "stream"})


def _finite_non_negative(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _phase_fraction(check_id: str) -> float:
    digest = hashlib.sha256(str(check_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


class ScryptedStartupSchedule:
    """Provider-owned current-boot acquisition policy for camera child checks."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started_at = clock()
        self._hydrated: set[str] = set()

    def reset(self) -> None:
        self._started_at = self._clock()
        self._hydrated.clear()

    def observe(self, request, result) -> None:
        operation = str(request.options.get("operation", ""))
        if operation not in _CHILD_OPERATIONS:
            return
        if str(result.state).casefold() != "unknown":
            self._hydrated.add(str(request.check_id))

    def hydrated(self, check_id: str) -> bool:
        return str(check_id) in self._hydrated

    def _active(self, request) -> bool:
        if str(request.options.get("operation", "")) not in _CHILD_OPERATIONS:
            return False
        if self.hydrated(str(request.check_id)):
            return False
        elapsed = max(0.0, self._clock() - self._started_at)
        return elapsed < STARTUP_ACQUISITION_WINDOW_SECONDS

    def reduce_delay(self, request, *, phase: str, delay_seconds: float) -> float:
        base = _finite_non_negative(delay_seconds)
        if base is None:
            return delay_seconds
        if base == 0 or not self._active(request):
            return base

        if phase == "initial":
            configured = _finite_non_negative(
                request.options.get("scheduler_jitter_seconds", 0)
            )
            if configured in (None, 0) or configured <= STARTUP_JITTER_CAP_SECONDS:
                return base
            # Core has already deterministically selected one point in the configured
            # jitter window. Scale that point into the smaller provider bootstrap
            # window so legacy 30/90/240-second jitter keeps its relative phase rather
            # than collapsing all camera children into one burst at the cap.
            return base * (STARTUP_JITTER_CAP_SECONDS / configured)

        if phase == "interval":
            fraction = _phase_fraction(str(request.check_id))
            retry = STARTUP_RETRY_MIN_SECONDS + (
                STARTUP_RETRY_MAX_SECONDS - STARTUP_RETRY_MIN_SECONDS
            ) * fraction
            return min(base, retry)

        return base


__all__ = [
    "STARTUP_ACQUISITION_WINDOW_SECONDS",
    "STARTUP_JITTER_CAP_SECONDS",
    "STARTUP_RETRY_MAX_SECONDS",
    "STARTUP_RETRY_MIN_SECONDS",
    "ScryptedStartupSchedule",
]
