from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping

from monitorbox.v2.plugin_api import (
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
    "request timed out",
)

_QNAP_QUTSHERO_POOL_STATUS_PREFIX = "1.3.6.1.4.1.55062.2.10.7.1.5."
_QNAP_FIRMWARE_VERSION_OID = ".1.3.6.1.4.1.55062.2.12.6.0"
_QNAP_QUTSHERO_SCRUBBING = "4"
_QNAP_QUTSHERO_KNOWN_POOL_STATUSES = frozenset(
    {
        "-4", "-3", "-2", "-1", "0", "1", "2", "3", "4", "5", "6",
        "7", "8", "9", "10", "11", "12", "13", "14", "255",
    }
)
_QUTSHERO_VERSION_RE = re.compile(r"(?:^|[^a-z0-9])h\d+\.", re.IGNORECASE)

_AUTH_PROTOCOL_NAMES = {
    "MD5": "USM_AUTH_HMAC96_MD5",
    "SHA": "USM_AUTH_HMAC96_SHA",
    "SHA1": "USM_AUTH_HMAC96_SHA",
    "SHA-1": "USM_AUTH_HMAC96_SHA",
    "SHA224": "USM_AUTH_HMAC128_SHA224",
    "SHA-224": "USM_AUTH_HMAC128_SHA224",
    "SHA256": "USM_AUTH_HMAC192_SHA256",
    "SHA-256": "USM_AUTH_HMAC192_SHA256",
    "SHA384": "USM_AUTH_HMAC256_SHA384",
    "SHA-384": "USM_AUTH_HMAC256_SHA384",
    "SHA512": "USM_AUTH_HMAC384_SHA512",
    "SHA-512": "USM_AUTH_HMAC384_SHA512",
}
_PRIV_PROTOCOL_NAMES = {
    "DES": "USM_PRIV_CBC56_DES",
    "3DES": "USM_PRIV_CBC168_3DES",
    "AES": "USM_PRIV_CFB128_AES",
    "AES128": "USM_PRIV_CFB128_AES",
    "AES-128": "USM_PRIV_CFB128_AES",
    "AES192": "USM_PRIV_CFB192_AES",
    "AES-192": "USM_PRIV_CFB192_AES",
    "AES256": "USM_PRIV_CFB256_AES",
    "AES-256": "USM_PRIV_CFB256_AES",
}


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000


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


def _record_scrub_metadata(metadata: dict[str, Any], fields: list[str], firmware_version: str) -> None:
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


def _pysnmp_api():
    # Imported lazily so the module loader can produce a precise provider error if
    # a package artifact is incomplete rather than making Core own this dependency.
    from pysnmp.hlapi.v3arch import asyncio as hlapi

    return hlapi


def _protocol(hlapi, raw: Any, table: Mapping[str, str], *, kind: str):
    key = str(raw or "").strip().upper()
    attribute = table.get(key)
    if attribute is None:
        raise ValueError(f"unsupported SNMPv3 {kind} protocol {raw!r}")
    return getattr(hlapi, attribute)


def _credential_data(hlapi, options: Mapping[str, Any]) -> tuple[Any, tuple[str, ...]]:
    version = str(options.get("version", "3")).strip().casefold()
    protected: list[str] = []
    if version in {"1", "2", "2c"}:
        env_name = str(options.get("community_env") or "").strip()
        if not env_name:
            raise KeyError("community_env")
        community = os.environ[env_name]
        protected.append(community)
        return hlapi.CommunityData(community, mpModel=0 if version == "1" else 1), tuple(protected)
    if version != "3":
        raise ValueError(f"unsupported SNMP version {version!r}")

    username_env = str(options.get("username_env") or "").strip()
    if not username_env:
        raise KeyError("username_env")
    username = os.environ[username_env]
    protected.append(username)

    auth_env = str(options.get("auth_password_env") or "").strip()
    priv_env = str(options.get("privacy_password_env") or "").strip()
    auth_password = os.environ[auth_env] if auth_env else None
    privacy_password = os.environ[priv_env] if priv_env else None
    if auth_password:
        protected.append(auth_password)
    if privacy_password:
        protected.append(privacy_password)

    kwargs: dict[str, Any] = {}
    if auth_password is not None:
        kwargs["authKey"] = auth_password
        kwargs["authProtocol"] = _protocol(
            hlapi,
            options.get("auth_protocol", "SHA"),
            _AUTH_PROTOCOL_NAMES,
            kind="authentication",
        )
    if privacy_password is not None:
        if auth_password is None:
            raise ValueError("SNMPv3 privacy requires authentication")
        kwargs["privKey"] = privacy_password
        kwargs["privProtocol"] = _protocol(
            hlapi,
            options.get("privacy_protocol", "AES"),
            _PRIV_PROTOCOL_NAMES,
            kind="privacy",
        )
    return hlapi.UsmUserData(username, **kwargs), tuple(protected)


async def _query(
    engine: Any,
    *,
    host: str,
    port: int,
    timeout: float,
    retries: int,
    options: Mapping[str, Any],
    oids: tuple[str, ...],
) -> tuple[list[str] | None, str | None, bool, tuple[str, ...]]:
    """Return values, error detail, transport-loss flag, protected values."""
    hlapi = _pysnmp_api()
    credentials, protected = _credential_data(hlapi, options)
    target = await hlapi.UdpTransportTarget.create(
        (host, port),
        timeout=max(0.05, timeout),
        retries=max(0, retries),
    )
    varbinds = tuple(
        hlapi.ObjectType(hlapi.ObjectIdentity(str(oid).strip())) for oid in oids
    )
    error_indication, error_status, error_index, returned = await hlapi.get_cmd(
        engine,
        credentials,
        target,
        hlapi.ContextData(),
        *varbinds,
        lookupMib=False,
    )
    if error_indication:
        detail = _scrub_detail(str(error_indication), protected)
        lowered = detail.casefold()
        transport_loss = any(marker in lowered for marker in _TRANSPORT_FAILURE_MARKERS)
        # Authentication/USM engine-discovery loss is still observer loss rather
        # than proof the monitored System itself failed.
        if any(marker in lowered for marker in ("authorization", "authentication", "unknown user", "not in time window", "usm")):
            transport_loss = True
        return None, detail, transport_loss, protected
    if error_status:
        detail = str(error_status.prettyPrint())
        if error_index:
            detail = f"{detail} at varbind {int(error_index)}"
        return None, _scrub_detail(detail, protected), False, protected

    values: list[str] = []
    for varbind in returned:
        try:
            value = varbind[1]
        except Exception as exc:
            return None, f"invalid SNMP varbind: {type(exc).__name__}", False, protected
        pretty = value.prettyPrint() if hasattr(value, "prettyPrint") else str(value)
        values.append(str(pretty))
    return values, None, False, protected


class SnmpRuntimeExecutor:
    """Self-contained managed SNMP v1/v2c/v3 executor using vendored PySNMP."""

    def __init__(self) -> None:
        self._engine = None

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context
        hlapi = _pysnmp_api()
        self._engine = hlapi.SnmpEngine()

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context
        if self._engine is not None:
            self._engine.close_dispatcher()
            self._engine = None

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        del context
        started = time.monotonic()
        if request.adapter != "snmp":
            raise ValueError(f"SNMP executor cannot run adapter {request.adapter!r}")
        if self._engine is None:
            raise RuntimeError("SNMP runtime executor is not started")

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
        if not isinstance(raw_oids, dict) or not raw_oids or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in raw_oids.items()
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
        if not 1 <= port <= 65535:
            return RuntimeExecutionResult(
                state="unknown",
                summary="SNMP monitor configuration has an invalid port",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )

        outer_timeout = max(0.1, float(request.timeout_seconds))
        query_timeout = max(0.05, outer_timeout * 0.9 / (retries + 1))
        try:
            values, detail, transport_loss, protected = await _query(
                self._engine,
                host=host,
                port=port,
                timeout=query_timeout,
                retries=retries,
                options=options,
                oids=tuple(oids.values()),
            )
        except KeyError as exc:
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"SNMP credential environment variable is missing: {exc.args[0]}",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )
        except ValueError as exc:
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"SNMP monitor configuration is invalid: {str(exc)[:180]}",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_configuration", "provider": "snmp"},
            )
        except Exception as exc:
            detail = _scrub_detail(str(exc), ())
            return RuntimeExecutionResult(
                state="unknown",
                summary=f"SNMP monitoring unavailable: {detail or type(exc).__name__}",
                duration_ms=_elapsed_ms(started),
                metadata={"failure_kind": "monitor_dependency", "provider": "snmp"},
            )

        if values is None:
            detail = _scrub_detail(detail or "provider rejected query", protected)
            if transport_loss:
                return RuntimeExecutionResult(
                    state="unknown",
                    summary="SNMP monitoring unavailable: provider did not respond or authenticate",
                    duration_ms=_elapsed_ms(started),
                    metadata={"failure_kind": "monitor_dependency", "provider": "snmp"},
                )
            return RuntimeExecutionResult(
                state="failed",
                summary=f"SNMP query failed: {detail}",
                duration_ms=_elapsed_ms(started),
                metadata={"provider": "snmp"},
            )

        if len(values) != len(oids):
            return RuntimeExecutionResult(
                state="failed",
                summary="SNMP returned an unexpected value count",
                duration_ms=_elapsed_ms(started),
                metadata={"provider": "snmp"},
            )

        metrics: dict[str, float] = {}
        metadata: dict[str, Any] = {"provider": "snmp", "transport": "pysnmp"}
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
            remaining = outer_timeout - (_elapsed_ms(started) / 1000.0)
            firmware_version = ""
            if remaining > 0.06:
                try:
                    firmware_values, _, _, _ = await _query(
                        self._engine,
                        host=host,
                        port=port,
                        timeout=min(1.0, max(0.05, remaining * 0.8)),
                        retries=0,
                        options=options,
                        oids=(_QNAP_FIRMWARE_VERSION_OID,),
                    )
                    if firmware_values and len(firmware_values) == 1:
                        firmware_version = firmware_values[0].strip().strip('"')
                except Exception:
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
