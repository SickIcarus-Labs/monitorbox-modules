from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from ...plugin_api import (
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)

_TRANSPORT_FAILURE_MARKERS = (
    "timeout",
    "timed out",
    "no response",
    "no route to host",
    "network is unreachable",
    "connection refused",
    "unknown host",
)


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000


async def _command(
    *args: str,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        raise
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


def _scrub_detail(value: str, protected: tuple[str, ...]) -> str:
    result = value
    for secret in protected:
        if secret:
            result = result.replace(secret, "[protected]")
    return result[:180]


class SnmpRuntimeExecutor:
    """Module-owned bounded SNMP runtime execution.

    Target assertions remain actionable failures. Loss of the SNMP provider or
    local SNMP transport is observer loss and is therefore UNKNOWN rather than a
    fabricated hard failure of the monitored System.
    """

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
        options = dict(request.options)
        host = str(options.get("host") or "").strip()
        if not host:
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitor configuration is missing a host",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )

        raw_oids = options.get("oids") or {}
        if (
            not isinstance(raw_oids, dict)
            or not raw_oids
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in raw_oids.items())
        ):
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitor configuration requires a name-to-OID mapping",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )
        oids: dict[str, str] = dict(raw_oids)

        try:
            port = int(options.get("port", 161))
            retries = max(0, int(options.get("retries", 1)))
        except (TypeError, ValueError):
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitor configuration has an invalid port or retry count",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )

        # Core's runtime router remains the hard provider-blind watchdog. Finish
        # protocol retry/transport classification inside that deadline so an
        # unavailable SNMP endpoint cannot escape as generic target_timeout.
        outer_timeout = max(0.1, float(request.timeout_seconds))
        command_timeout = max(0.05, outer_timeout * 0.9)
        attempt_timeout = max(0.05, command_timeout / (retries + 1))
        attempt_timeout_text = f"{attempt_timeout:.3f}".rstrip("0").rstrip(".")
        args = [
            "snmpget",
            "-Oqv",
            "-Ot",
            "-t",
            attempt_timeout_text,
            "-r",
            str(retries),
        ]

        version = str(options.get("version", "3")).strip().casefold()
        secret_config: list[str] = []
        protected: list[str] = []
        try:
            if version == "1":
                community = os.environ[str(options["community_env"])]
                protected.append(community)
                args += ["-v1", "-c", community]
            elif version in {"2", "2c"}:
                community = os.environ[str(options["community_env"])]
                protected.append(community)
                args += ["-v2c", "-c", community]
            elif version == "3":
                username = os.environ[str(options["username_env"])]
                protected.append(username)
                auth_env = options.get("auth_password_env")
                privacy_env = options.get("privacy_password_env")
                level = "authPriv" if privacy_env else "authNoPriv" if auth_env else "noAuthNoPriv"
                args += ["-v3", "-l", level, "-u", username]
                secret_config.append(f"defSecurityName {username}")
                if auth_env:
                    auth_password = os.environ[str(auth_env)]
                    protected.append(auth_password)
                    protocol = str(options.get("auth_protocol", "SHA"))
                    args += ["-a", protocol]
                    secret_config += [
                        f"defAuthType {protocol}",
                        f"defAuthPassphrase {auth_password}",
                    ]
                if privacy_env:
                    privacy_password = os.environ[str(privacy_env)]
                    protected.append(privacy_password)
                    protocol = str(options.get("privacy_protocol", "AES"))
                    args += ["-x", protocol]
                    secret_config += [
                        f"defPrivType {protocol}",
                        f"defPrivPassphrase {privacy_password}",
                    ]
            else:
                return RuntimeExecutionResult(
                    state="unknown",
                    summary=f"Unsupported SNMP version: {version}",
                    duration_ms=_elapsed_ms(started),
                    metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
                )
        except KeyError as exc:
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"SNMP credential environment variable is missing: {exc.args[0]}",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )

        args += [f"{host}:{port}", *oids.values()]

        async def execute_command() -> tuple[int, str, str]:
            if not secret_config:
                return await _command(*args)
            with tempfile.TemporaryDirectory(prefix="monitorbox-snmp-runtime-") as directory:
                path = Path(directory) / "snmp.conf"
                path.write_text("\n".join(secret_config) + "\n")
                path.chmod(0o600)
                command_env = {**os.environ, "SNMPCONFPATH": directory}
                return await _command(*args, env=command_env)

        try:
            code, stdout, stderr = await asyncio.wait_for(
                execute_command(),
                timeout=command_timeout,
            )
        except TimeoutError:
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitoring unavailable: provider did not respond",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_dependency", "provider": "snmp"},
            )
        except OSError:
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitoring unavailable: local transport could not execute",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_dependency", "provider": "snmp"},
            )

        if code:
            detail = _scrub_detail((stderr or stdout).strip(), tuple(protected))
            if any(marker in detail.casefold() for marker in _TRANSPORT_FAILURE_MARKERS):
                return RuntimeExecutionResult(
                    state="unknown",
                    summary="SNMP monitoring unavailable: provider did not respond",
                    duration_ms=_elapsed_ms(started),
                    metadata={"failure_kind": "monitor_dependency", "provider": "snmp"},
                )
            return RuntimeExecutionResult(
                state="failed",
                summary=f"SNMP query failed: {detail or 'provider rejected query'}",
                duration_ms=_elapsed_ms(started),
                metadata={"provider": "snmp"},
            )

        values = stdout.splitlines()
        if len(values) != len(oids):
            return RuntimeExecutionResult(
                state="failed",
                summary="SNMP returned an unexpected value count",
                duration_ms=_elapsed_ms(started),
                metadata={"provider": "snmp"},
            )

        metrics: dict[str, float] = {}
        metadata: dict[str, Any] = {"provider": "snmp"}
        normalized: dict[str, str] = {}
        for (name, _), value in zip(oids.items(), values, strict=True):
            cleaned = value.strip().strip('"')
            normalized[name] = cleaned
            try:
                metrics[name] = float(cleaned)
            except ValueError:
                metadata[name] = cleaned[:200]

        failures: list[str] = []
        for name, expected in dict(options.get("expected", {})).items():
            allowed = expected if isinstance(expected, list) else [expected]
            actual = normalized.get(name, "<missing>")
            if actual not in {str(item) for item in allowed}:
                failures.append(f"{name}={actual[:80]}")
        if failures:
            return RuntimeExecutionResult(
                state="failed",
                summary=f"SNMP assertion failed: {', '.join(failures)[:400]}",
                duration_ms=_elapsed_ms(started),
                metrics=metrics,
                metadata=metadata,
            )

        return RuntimeExecutionResult(
            state="healthy",
            summary=f"SNMP returned {len(values)} value(s)",
            duration_ms=_elapsed_ms(started),
            metrics=metrics,
            metadata=metadata,
        )


__all__ = ["SnmpRuntimeExecutor"]
