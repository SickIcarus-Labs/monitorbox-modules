from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_AUTH_OBSERVER_LOSS_MARKERS = (
    "authorization",
    "authentication",
    "unknown user",
    "not in time window",
    "usm",
    "wrong snmp pdu digest",
    "wrong digest",
    "wrongdigest",
)


def is_auth_observer_loss(detail: str) -> bool:
    lowered = detail.casefold()
    return any(marker in lowered for marker in _AUTH_OBSERVER_LOSS_MARKERS)


async def with_fresh_engine(
    hlapi: Any,
    operation: Callable[[Any], Awaitable[T]],
) -> T:
    """Execute one wire query with an isolated PySNMP LCD/security-engine state.

    The retired Net-SNMP transport naturally isolated every check in its own
    process. A single long-lived PySNMP SnmpEngine changes that property because
    USM engine discovery and localized-key state are cached in the engine LCD.
    Keep managed transport self-contained while retaining the old per-query
    isolation contract across concurrent endpoints and credentials.
    """

    engine = hlapi.SnmpEngine()
    try:
        return await operation(engine)
    finally:
        engine.close_dispatcher()


__all__ = ["is_auth_observer_loss", "with_fresh_engine"]
