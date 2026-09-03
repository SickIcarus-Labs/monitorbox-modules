from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Mapping
from urllib.parse import quote

import aiohttp

from .runtime import PortainerRuntimeExecutor

_DIAGNOSTIC_CACHE_SECONDS = 5.0
_DIAGNOSTIC_REQUEST_TIMEOUT_SECONDS = 2.5
_RESTART_WINDOW_SECONDS = 300.0
_CRASH_RESTART_DELTA = 2
_ACTIVE_CRASH_RESTART_COUNT = 3
_MAX_DIAGNOSTIC_CONTAINERS = 8
_MAX_DIAGNOSTIC_CONCURRENCY = 4
_MAX_LOG_BYTES = 16 * 1024
_MAX_LOG_CHARS = 4096
_LOG_TAIL_LINES = 40

_SECRET_KEYS = r"password|passwd|pwd|token|api[_-]?key|secret|authorization"
_JSON_DOUBLE_SECRET_RE = re.compile(
    rf'(?i)"({_SECRET_KEYS})"(\s*:\s*)"(?:\\.|[^"\\])*"'
)
_JSON_SINGLE_SECRET_RE = re.compile(
    rf"(?i)'({_SECRET_KEYS})'(\s*:\s*)'(?:\\.|[^'\\])*'"
)
_JSON_BARE_SECRET_RE = re.compile(
    rf'(?i)"({_SECRET_KEYS})"(\s*:\s*)(?!["\'])([^,}}\r\n]+)'
)
_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?im)\b(authorization)(\s*:\s*)[^\r\n]+"
)
_DOUBLE_QUOTED_SECRET_ASSIGNMENT_RE = re.compile(
    rf'(?i)\b({_SECRET_KEYS})(\s*[:=]\s*|\s+)"(?:\\.|[^"\\])*"'
)
_SINGLE_QUOTED_SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({_SECRET_KEYS})(\s*[:=]\s*|\s+)'(?:\\.|[^'\\])*'"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({_SECRET_KEYS})(\s*[:=]\s*|\s+)([^\"'\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;\"']+")
_URL_USERINFO_RE = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.IGNORECASE)


def _diagnostic_candidate(container: Mapping[str, Any]) -> bool:
    state = str(container.get("state") or "").strip().casefold()
    health = str(container.get("health") or "").strip().casefold()
    return state in {"restarting", "dead"} or health in {"unhealthy", "starting"}


def _diagnostic_priority(container: Mapping[str, Any]) -> tuple[int, str]:
    state = str(container.get("state") or "").strip().casefold()
    health = str(container.get("health") or "").strip().casefold()
    if state in {"restarting", "dead"}:
        priority = 0
    elif health == "unhealthy":
        priority = 1
    else:
        priority = 2
    return priority, str(container.get("name") or container.get("provider_id") or "")


def _bounded_int(value: Any, *, minimum: int = 0, maximum: int = 2**31 - 1) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not minimum <= value <= maximum:
        return None
    return value


def _redact_log_tail(value: str) -> str:
    text = value.replace("\x00", "")
    text = _URL_USERINFO_RE.sub(r"\1[REDACTED]@", text)
    text = _JSON_DOUBLE_SECRET_RE.sub(
        lambda match: f'"{match.group(1)}"{match.group(2)}"[REDACTED]"',
        text,
    )
    text = _JSON_SINGLE_SECRET_RE.sub(
        lambda match: f"'{match.group(1)}'{match.group(2)}'[REDACTED]'",
        text,
    )
    text = _JSON_BARE_SECRET_RE.sub(
        lambda match: f'"{match.group(1)}"{match.group(2)}[REDACTED]',
        text,
    )
    text = _AUTHORIZATION_HEADER_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )
    text = _DOUBLE_QUOTED_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f'{match.group(1)}{match.group(2)}"[REDACTED]"',
        text,
    )
    text = _SINGLE_QUOTED_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}'[REDACTED]'",
        text,
    )
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )
    return text[-_MAX_LOG_CHARS:]


def _decode_docker_log_stream(payload: bytes) -> str:
    """Decode Docker raw-stream frames when complete, otherwise fall back to text."""
    parts: list[bytes] = []
    cursor = 0
    framed = False
    while cursor + 8 <= len(payload):
        header = payload[cursor : cursor + 8]
        stream = header[0]
        size = int.from_bytes(header[4:8], "big")
        end = cursor + 8 + size
        if stream not in {0, 1, 2} or header[1:4] != b"\x00\x00\x00" or end > len(payload):
            break
        framed = True
        parts.append(payload[cursor + 8 : end])
        cursor = end
    raw = b"".join(parts) if framed and cursor == len(payload) else payload
    return raw.decode("utf-8", errors="replace")


class PortainerLifecycleRuntimeExecutor(PortainerRuntimeExecutor):
    """Provider-local lifecycle evidence and bounded anomaly diagnostics.

    Normal healthy inventory remains the certified one-list-call-per-environment path.
    Per-container inspect is reserved for suspicious list-state evidence, capped per
    inventory, and log tails are fetched only after a concrete anomaly is confirmed.
    """

    diagnostic_cache_seconds = _DIAGNOSTIC_CACHE_SECONDS
    diagnostic_request_timeout_seconds = _DIAGNOSTIC_REQUEST_TIMEOUT_SECONDS
    restart_window_seconds = _RESTART_WINDOW_SECONDS
    max_diagnostic_containers = _MAX_DIAGNOSTIC_CONTAINERS
    max_diagnostic_concurrency = _MAX_DIAGNOSTIC_CONCURRENCY

    def __init__(self) -> None:
        super().__init__()
        self._diagnostic_cache: dict[tuple[str, int, str], tuple[float, dict[str, Any]]] = {}
        self._restart_observations: dict[tuple[str, int, str], tuple[float, int]] = {}

    async def _base_inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        return await super()._inventory(options)

    def _prune_diagnostic_state(self, now: float) -> None:
        retention = max(60.0, self.restart_window_seconds * 2.0)
        self._diagnostic_cache = {
            key: value
            for key, value in self._diagnostic_cache.items()
            if now - value[0] <= retention
        }
        self._restart_observations = {
            key: value
            for key, value in self._restart_observations.items()
            if now - value[0] <= retention
        }

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        inventory = await self._base_inventory(options)
        self._prune_diagnostic_state(time.monotonic())
        workloads = inventory.get("workloads")
        if not isinstance(workloads, list):
            return inventory

        candidates: list[tuple[dict[str, Any], dict[str, Any], int]] = []
        for workload in workloads:
            if not isinstance(workload, dict):
                continue
            environment_provider_id = workload.get("environment_provider_id")
            if isinstance(environment_provider_id, bool) or not isinstance(environment_provider_id, int):
                continue
            containers = workload.get("containers")
            if not isinstance(containers, list):
                continue
            for container in containers:
                if isinstance(container, dict) and _diagnostic_candidate(container):
                    candidates.append((workload, container, environment_provider_id))

        if not candidates:
            inventory["lifecycle_diagnostics"] = {
                "candidate_containers": 0,
                "inspected_containers": 0,
                "truncated": False,
            }
            return inventory

        candidates.sort(key=lambda row: _diagnostic_priority(row[1]))
        selected = candidates[: self.max_diagnostic_containers]
        semaphore = asyncio.Semaphore(self.max_diagnostic_concurrency)

        async def enrich(
            workload: dict[str, Any],
            container: dict[str, Any],
            environment_provider_id: int,
        ) -> None:
            async with semaphore:
                lifecycle = await self._container_lifecycle(
                    options,
                    workload=workload,
                    container=container,
                    environment_provider_id=environment_provider_id,
                )
            if lifecycle:
                container["lifecycle"] = lifecycle

        await asyncio.gather(*(enrich(*row) for row in selected))
        inventory["lifecycle_diagnostics"] = {
            "candidate_containers": len(candidates),
            "inspected_containers": len(selected),
            "truncated": len(candidates) > len(selected),
        }
        return inventory

    async def _container_lifecycle(
        self,
        options: Mapping[str, Any],
        *,
        workload: Mapping[str, Any],
        container: Mapping[str, Any],
        environment_provider_id: int,
    ) -> dict[str, Any]:
        base = str(options.get("base_url") or "").rstrip("/")
        provider_id = str(container.get("provider_id") or "").strip()
        if not base or not provider_id:
            return {}
        key = (base, environment_provider_id, provider_id)
        now = time.monotonic()
        cached = self._diagnostic_cache.get(key)
        if cached is not None and now - cached[0] < self.diagnostic_cache_seconds:
            return dict(cached[1])

        try:
            inspect = await self._inspect_container(options, environment_provider_id, provider_id)
        except Exception as exc:
            result = {"inspect_error": type(exc).__name__}
            self._diagnostic_cache[key] = (now, result)
            return dict(result)
        if not isinstance(inspect, Mapping):
            result = {"inspect_error": "invalid_payload"}
            self._diagnostic_cache[key] = (now, result)
            return dict(result)

        state_raw = inspect.get("State")
        state = state_raw if isinstance(state_raw, Mapping) else {}
        health_raw = state.get("Health")
        health = health_raw if isinstance(health_raw, Mapping) else {}
        restart_count = _bounded_int(inspect.get("RestartCount"))
        exit_code = _bounded_int(state.get("ExitCode"), maximum=255)
        failing_streak = _bounded_int(health.get("FailingStreak"))
        state_status = str(state.get("Status") or container.get("state") or "").strip().casefold()
        health_status = str(health.get("Status") or container.get("health") or "").strip().casefold()
        oom_killed = state.get("OOMKilled") is True
        dead = state.get("Dead") is True or state_status == "dead"
        restarting = state.get("Restarting") is True or state_status == "restarting"
        nonzero_exit = state_status in {"exited", "dead"} and exit_code not in {None, 0}

        restart_delta: int | None = None
        observation_window_seconds: float | None = None
        crash_loop = False
        if restart_count is not None:
            previous = self._restart_observations.get(key)
            if previous is not None:
                previous_at, previous_count = previous
                elapsed = max(0.0, now - previous_at)
                if elapsed <= self.restart_window_seconds and restart_count >= previous_count:
                    restart_delta = restart_count - previous_count
                    observation_window_seconds = round(elapsed, 3)
                    crash_loop = restart_delta >= _CRASH_RESTART_DELTA
            if restarting and restart_count >= _ACTIVE_CRASH_RESTART_COUNT:
                crash_loop = True
            self._restart_observations[key] = (now, restart_count)

        confirmed_anomaly = bool(
            crash_loop
            or oom_killed
            or dead
            or restarting
            or health_status == "unhealthy"
            or nonzero_exit
        )
        result: dict[str, Any] = {
            "state": state_status or None,
            "health": health_status or None,
            "restart_count": restart_count,
            "restart_delta": restart_delta,
            "observation_window_seconds": observation_window_seconds,
            "crash_loop": crash_loop,
            "oom_killed": oom_killed,
            "nonzero_exit": nonzero_exit,
            "exit_code": exit_code,
            "failing_streak": failing_streak,
            "started_at": str(state.get("StartedAt") or "") or None,
            "finished_at": str(state.get("FinishedAt") or "") or None,
            "confirmed_anomaly": confirmed_anomaly,
        }
        if confirmed_anomaly:
            try:
                log_tail = await self._container_log_tail(
                    options,
                    environment_provider_id,
                    provider_id,
                )
            except Exception as exc:
                result["log_error"] = type(exc).__name__
            else:
                if log_tail:
                    result["log_tail"] = log_tail
                    result["log_tail_redacted"] = True

        self._diagnostic_cache[key] = (now, result)
        return dict(result)

    async def _inspect_container(
        self,
        options: Mapping[str, Any],
        environment_provider_id: int,
        container_provider_id: str,
    ) -> Any:
        base, headers, verify_tls = self._connection(options)
        timeout = aiohttp.ClientTimeout(total=self.diagnostic_request_timeout_seconds)
        container_id = quote(container_provider_id, safe="")
        url = (
            f"{base}/api/endpoints/{environment_provider_id}/docker/"
            f"containers/{container_id}/json"
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self._get(session, url, headers, verify_tls)

    async def _container_log_tail(
        self,
        options: Mapping[str, Any],
        environment_provider_id: int,
        container_provider_id: str,
    ) -> str:
        base, headers, verify_tls = self._connection(options)
        timeout = aiohttp.ClientTimeout(total=self.diagnostic_request_timeout_seconds)
        container_id = quote(container_provider_id, safe="")
        url = (
            f"{base}/api/endpoints/{environment_provider_id}/docker/"
            f"containers/{container_id}/logs?stdout=1&stderr=1&tail={_LOG_TAIL_LINES}&timestamps=1"
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            payload = await self._get_bounded_bytes(session, url, headers, verify_tls)
        return _redact_log_tail(_decode_docker_log_stream(payload))

    @staticmethod
    def _connection(options: Mapping[str, Any]) -> tuple[str, dict[str, str], bool]:
        base = str(options.get("base_url") or "").rstrip("/")
        api_key_env = str(options.get("api_key_env") or "")
        api_key = os.environ.get(api_key_env)
        if not base or not api_key_env or not api_key:
            raise RuntimeError("Portainer diagnostic connection is unavailable")
        return (
            base,
            {"X-API-Key": api_key, "Accept": "application/json"},
            bool(options.get("verify_tls", True)),
        )

    @staticmethod
    async def _get_bounded_bytes(
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        verify_tls: bool,
    ) -> bytes:
        async with session.get(
            url,
            headers=headers,
            ssl=None if verify_tls else False,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"container logs returned HTTP {response.status}")
            tail = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                tail.extend(chunk)
                if len(tail) > _MAX_LOG_BYTES:
                    del tail[: len(tail) - _MAX_LOG_BYTES]
            return bytes(tail)


__all__ = [
    "PortainerLifecycleRuntimeExecutor",
    "_decode_docker_log_stream",
    "_diagnostic_candidate",
    "_redact_log_tail",
]
