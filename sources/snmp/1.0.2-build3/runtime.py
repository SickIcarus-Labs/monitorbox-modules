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

# QNAP NAS.mib (QTS-MIB) exposes storagepoolStatus at this table for both QTS
# and QuTS hero. The same numeric value can mean different things by platform:
# status 4 is REMOVING_TIER on QTS but SCRUBBING on QuTS hero. Never classify
# the number alone. firmwareVersion is under the same read-only QNAP MIB and
# QuTS hero releases use the h<major>.<minor>... version identity.
_QNAP_QUTSHERO_POOL_STATUS_PREFIX = "1.3.6.1.4.1.55062.2.10.7.1.5."
_QNAP_FIRMWARE_VERSION_OID = ".1.3.6.1.4.1.55062.2.12.6.0"
_QNAP_QUTSHERO_SCRUBBING = "4"
_QNAP_QUTSHERO_KNOWN_POOL_STATUSES = frozenset(
    {
        "-4",  # SED_LOCKED
        "-3",  # ERROR
        "-2",  # NOT_READY
        "-1",  # WARNING
        "0",   # READY
        "1",   # RESILVERING
        "2",   # EXPORTING
        "3",   # REMOVING
        "4",   # SCRUBBING
        "5",   # CREATING
        "6",   # SED_LOCKING
        "7",   # SED_UNLOCKING
        "8",   # STOPPING
        "9",   # STOPPED
        "10",  # STARTING
        "11",  # IMPORTING
        "12",  # READONLY
        "13",  # PRUNING
        "14",  # TUNING
        "255", # NONE_STATUS (0xFF)
    }
)
_QUTSHERO_VERSION_RE = re.compile(r"(?:^|[^a-z0-9])h\d+\.", re.IGNORECASE)


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


def _is_qnap_qutshero_pool_status_oid(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lstrip(".")
    if not normalized.startswith(_QNAP_QUTSHERO_POOL_STATUS_PREFIX):
        return False
    index = normalized.removeprefix(_QNAP_QUTSHERO_POOL_STATUS_PREFIX)
    return bool(index) and index.isdigit()


def _looks_like_quts_hero_firmware(value: str) -> bool:
    return bool(_QUTSHERO_VERSION_RE.search(value.strip()))


def _record_scrub_metadata(
    metadata: dict[str, Any],
    fields: list[str],
    firmware_version: str,
) -> None:
    metadata["qnap_storage_profile"] = "quts_hero"
    metadata["qnap_firmware_version"] = firmware_version[:200]
    metadata["maintenance_kind"] = "scrub"
    metadata["maintenance_state"] = "Scrubbing"
    metadata["maintenance_health_neutral"] = True
    metadata["maintenance_fields"] = list(fields)
    metadata["maintenance"] = {
        "provider": "qnap-qutshero",
        "kind": "scrub",
        "state": "Scrubbing",
        "health_neutral": True,
        "fields": list(fields),
    }


class SnmpRuntimeExecutor:
    """Module-owned bounded SNMP runtime execution.

    Target assertions remain actionable failures. Loss of the SNMP provider or
    local SNMP transport is observer loss and is therefore UNKNOWN rather than a
    fabricated hard failure of the monitored System.

    QuTS hero pool status is the one vendor state machine interpreted here.
    QNAP's documented SCRUBBING value is health-neutral only after the same
    endpoint positively identifies a QuTS hero firmware version. Undocumented
    pool values are UNKNOWN; every other assertion mismatch remains actionable.
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

        transport_args = tuple(args)
        query_args = (*transport_args, f"{host}:{port}", *oids.values())

        async def execute_command(command_args: tuple[str, ...]) -> tuple[int, str, str]:
            if not secret_config:
                return await _command(*command_args)
            with tempfile.TemporaryDirectory(prefix="monitorbox-snmp-runtime-") as directory:
                path = Path(directory) / "snmp.conf"
                path.write_text("\n".join(secret_config) + "\n")
                path.chmod(0o600)
                command_env = {**os.environ, "SNMPCONFPATH": directory}
                return await _command(*command_args, env=command_env)

        try:
            code, stdout, stderr = await asyncio.wait_for(
                execute_command(query_args),
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
        semantic_unknown: list[str] = []
        status4_fields: list[str] = []
        for name, expected in dict(options.get("expected", {})).items():
            allowed = expected if isinstance(expected, list) else [expected]
            actual = normalized.get(name, "<missing>")
            if actual in {str(item) for item in allowed}:
                continue

            oid = oids.get(name)
            if _is_qnap_qutshero_pool_status_oid(oid):
                if actual == _QNAP_QUTSHERO_SCRUBBING:
                    status4_fields.append(name)
                    continue
                if actual not in _QNAP_QUTSHERO_KNOWN_POOL_STATUSES:
                    semantic_unknown.append(f"{name}={actual[:80]}")
                    continue

            failures.append(f"{name}={actual[:80]}")

        # A real assertion fault always wins over maintenance or semantic
        # uncertainty. This prevents an active maintenance value from masking
        # any other independently abnormal value in the same SNMP check.
        if failures:
            return RuntimeExecutionResult(
                state="failed",
                summary=f"SNMP assertion failed: {', '.join(failures)[:400]}",
                duration_ms=_elapsed_ms(started),
                metrics=metrics,
                metadata=metadata,
            )

        if semantic_unknown:
            metadata["failure_kind"] = "provider_semantics_unknown"
            metadata["qnap_pool_status_unknown"] = list(semantic_unknown)
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"QNAP storage pool status is unrecognized: {', '.join(semantic_unknown)[:360]}",
                duration_ms=_elapsed_ms(started),
                metrics=metrics,
                metadata=metadata,
            )

        if status4_fields:
            # QNAP assigns status 4 different meanings on QTS and QuTS hero.
            # Probe firmwareVersion from the same endpoint before calling it a
            # scrub. This extra read happens only while status 4 is present and
            # remains inside Core's provider-blind watchdog budget.
            remaining = outer_timeout - (_elapsed_ms(started) / 1000.0)
            firmware_version = ""
            if remaining > 0.06:
                firmware_args = (
                    *transport_args,
                    f"{host}:{port}",
                    _QNAP_FIRMWARE_VERSION_OID,
                )
                try:
                    firmware_code, firmware_stdout, _ = await asyncio.wait_for(
                        execute_command(firmware_args),
                        timeout=min(1.0, max(0.05, remaining * 0.8)),
                    )
                    if firmware_code == 0:
                        firmware_values = firmware_stdout.splitlines()
                        if len(firmware_values) == 1:
                            firmware_version = firmware_values[0].strip().strip('"')
                except (TimeoutError, OSError):
                    firmware_version = ""

            if firmware_version:
                metadata["qnap_firmware_version"] = firmware_version[:200]
            if firmware_version and _looks_like_quts_hero_firmware(firmware_version):
                _record_scrub_metadata(metadata, status4_fields, firmware_version)
                return RuntimeExecutionResult(
                    state="healthy",
                    summary="QNAP storage maintenance: Scrubbing",
                    duration_ms=_elapsed_ms(started),
                    metrics=metrics,
                    metadata=metadata,
                )

            metadata["failure_kind"] = "provider_semantics_unknown"
            metadata["qnap_pool_status_unresolved"] = [
                f"{name}={_QNAP_QUTSHERO_SCRUBBING}" for name in status4_fields
            ]
            if firmware_version:
                metadata["qnap_storage_profile"] = "non_quts_hero_or_unrecognized"
            return RuntimeExecutionResult(
                state="unknown",
                summary="QNAP storage pool status 4 requires platform-specific interpretation",
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
