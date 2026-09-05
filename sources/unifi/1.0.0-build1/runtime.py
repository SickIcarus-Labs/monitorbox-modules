from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

import aiohttp

from ...model import State
from ...plugin_api import (
    IntegrationDefinition,
    ModuleManifest,
    PluginMetadata,
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)

MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1
_STATE_FILE = "link-expectations.json"


def _elapsed(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _result(
    start: float,
    state: State,
    summary: str,
    metrics: Mapping[str, float] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeExecutionResult:
    return RuntimeExecutionResult(
        state=state.value,
        summary=summary,
        duration_ms=_elapsed(start),
        metrics=dict(metrics or {}),
        metadata=dict(metadata or {}),
    )


class UniFiRuntimeExecutor:
    """Module-owned UniFi Network execution policy.

    Auth/session and sampling counters are intentionally ephemeral. Learned link
    expectations are restore-required module state and therefore live only under
    the Core-governed ``state_root`` supplied to this executor.
    """

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self._auth: dict[str, dict[str, str]] = {}
        self._auth_lock = asyncio.Lock()
        self._port_counters: dict[str, tuple[float, int]] = {}

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context
        if self.session is not None:
            raise RuntimeError("UniFi runtime executor is already started")
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=5, sock_read=20),
            raise_for_status=False,
        )

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context
        session = self.session
        self.session = None
        self._auth.clear()
        self._port_counters.clear()
        if session is not None:
            await session.close()

    @staticmethod
    def _verify_tls(options: Mapping[str, Any]) -> bool:
        return bool(options.get("verify_tls", False))

    async def _login(self, options: Mapping[str, Any]) -> dict[str, str]:
        if self.session is None:
            raise RuntimeError("UniFi runtime executor is not started")
        base = str(options["base_url"]).rstrip("/")
        async with self._auth_lock:
            cached = self._auth.get(base)
            if cached is not None:
                return cached
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
                if response.status != 200 or not cookie or not csrf:
                    raise RuntimeError(
                        f"UniFi authentication returned HTTP {response.status}"
                    )
            headers = {
                "Cookie": cookie.split(";", 1)[0],
                "X-Csrf-Token": csrf,
            }
            self._auth[base] = headers
            return headers

    async def _get(self, options: Mapping[str, Any], path: str) -> Any:
        if self.session is None:
            raise RuntimeError("UniFi runtime executor is not started")
        base = str(options["base_url"]).rstrip("/")
        for attempt in range(2):
            headers = self._auth.get(base) or await self._login(options)
            async with self.session.get(
                base + path,
                headers=headers,
                ssl=None if self._verify_tls(options) else False,
            ) as response:
                if response.status == 401 and attempt == 0:
                    self._auth.pop(base, None)
                    continue
                if response.status != 200:
                    raise RuntimeError(f"{path} returned HTTP {response.status}")
                return await response.json(content_type=None)
        raise RuntimeError("UniFi authentication failed")

    async def _traffic_flows(self, options: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self.session is None:
            raise RuntimeError("UniFi runtime executor is not started")
        base = str(options["base_url"]).rstrip("/")
        site = str(options.get("site", "default"))
        path = f"/proxy/network/v2/api/site/{site}/traffic-flows"
        for attempt in range(2):
            headers = self._auth.get(base) or await self._login(options)
            async with self.session.post(
                base + path,
                headers=headers,
                json={},
                ssl=None if self._verify_tls(options) else False,
            ) as response:
                if response.status == 401 and attempt == 0:
                    self._auth.pop(base, None)
                    continue
                if response.status != 200:
                    raise RuntimeError(f"{path} returned HTTP {response.status}")
                payload = await response.json(content_type=None)
                data = payload.get("data", []) if isinstance(payload, dict) else []
                return [dict(item) for item in data if isinstance(item, dict)]
        raise RuntimeError("UniFi authentication failed")

    @staticmethod
    def _port_capacity(port: Mapping[str, Any]) -> int | None:
        media = str(port.get("media", "")).upper()
        return {
            "FE": 100,
            "GE": 1000,
            "2P5GE": 2500,
            "5GE": 5000,
            "10GE": 10000,
            "SFP": 1000,
            "SFP+": 10000,
            "SFP28": 25000,
        }.get(media)

    @staticmethod
    def _state_path(context: RuntimeExecutionContext) -> Path:
        return Path(context.state_root) / _STATE_FILE

    def _load_expectations(self, context: RuntimeExecutionContext) -> dict[str, int]:
        path = self._state_path(context)
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                return {}
            return {
                str(key): int(item)
                for key, item in value.items()
                if int(item) > 0
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _save_expectations(
        self,
        context: RuntimeExecutionContext,
        expectations: Mapping[str, int],
    ) -> None:
        path = self._state_path(context)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(
                json.dumps(dict(expectations), sort_keys=True, separators=(",", ":"))
            )
            temp.replace(path)
        except OSError:
            # Preserve 0540 monitor behavior: inability to persist learned state
            # must not make current provider evidence unavailable.
            pass

    def _derive_expectations(
        self,
        raw_devices: list[dict[str, Any]],
        options: Mapping[str, Any],
        context: RuntimeExecutionContext,
    ) -> dict[str, int]:
        learned = self._load_expectations(context)
        explicit = {
            str(key).lower(): int(value)
            for key, value in dict(options.get("expected_uplink_speeds", {})).items()
        }
        by_mac = {
            str(item.get("mac", "")).lower(): item
            for item in raw_devices
        }
        result = dict(learned)
        for child in raw_devices:
            mac = str(child.get("mac", "")).lower()
            if not mac:
                continue
            if mac in explicit:
                result[mac] = explicit[mac]
                continue
            uplink = child.get("uplink") or {}
            parent = by_mac.get(str(uplink.get("uplink_mac", "")).lower())
            child_capacity = uplink.get("max_speed")
            parent_port_idx = uplink.get("uplink_remote_port")
            parent_port = next(
                (
                    item
                    for item in (parent or {}).get("port_table", [])
                    if item.get("port_idx") == parent_port_idx
                ),
                None,
            )
            parent_capacity = self._port_capacity(parent_port or {})
            candidates = [
                int(item)
                for item in (child_capacity, parent_capacity)
                if isinstance(item, (int, float)) and item > 0
            ]
            if candidates:
                inferred = min(candidates)
                # A degraded current negotiation must never teach downward.
                result[mac] = max(result.get(mac, 0), inferred)
        self._save_expectations(context, result)
        return result

    @staticmethod
    def _vpn_matches(vpn: Mapping[str, Any], expectation: Mapping[str, Any]) -> bool:
        for key in ("role", "remote_site_id", "local_tunnel_subnet"):
            wanted = expectation.get(key)
            if wanted is not None and str(vpn.get(key)) != str(wanted):
                return False
        wanted_subnets = expectation.get("remote_subnets")
        if wanted_subnets is not None:
            if {str(item) for item in vpn.get("remote_subnets", [])} != {
                str(item) for item in wanted_subnets
            }:
                return False
        wanted_name = expectation.get("name")
        if wanted_name is not None and str(vpn.get("name", "")).casefold() != str(
            wanted_name
        ).casefold():
            return False
        return True

    @classmethod
    def _vpn_components(
        cls,
        vpns: list[dict[str, Any]],
        expectations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        components: list[dict[str, Any]] = []
        for index, expectation in enumerate(expectations):
            object_id = str(expectation.get("object_id", ""))
            if not object_id:
                continue
            match = next(
                (vpn for vpn in vpns if cls._vpn_matches(vpn, expectation)),
                None,
            )
            label = str(expectation.get("label") or f"VPN path {index + 1}")
            if match is None:
                state = "unknown"
                summary = "Configured VPN path is missing from UniFi inventory"
                metadata: Mapping[str, Any] = {"expectation": expectation}
                component_id = f"unifi-vpn:missing:{index}"
            else:
                enabled = bool(match.get("enabled", True))
                operational = match.get("operational")
                if not enabled:
                    state = "failed"
                    summary = "Configured VPN path is paused or disabled"
                elif operational is True:
                    state = "healthy"
                    summary = "VPN path connected"
                elif operational is False:
                    state = "failed"
                    summary = f"VPN path {match.get('status', 'disconnected')}"
                else:
                    state = "unknown"
                    summary = f"VPN path status {match.get('status', 'unknown')}"
                metadata = match
                component_id = str(match.get("id") or f"unifi-vpn:{index}")
            components.append(
                {
                    "id": component_id,
                    "object_id": object_id,
                    "presentation_object": expectation.get("presentation_object"),
                    "label": label,
                    "state": state,
                    "summary": summary,
                    "redundancy_group": expectation.get("redundancy_group"),
                    "metadata": dict(metadata),
                }
            )
        return components

    async def _inventory(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        start = time.monotonic()
        options = request.options
        site = str(options.get("site", "default"))
        prefix = f"/proxy/network/api/s/{site}/"
        devices_payload, health_payload, networks_payload, connections_payload = (
            await asyncio.gather(
                self._get(options, prefix + "stat/device"),
                self._get(options, prefix + "stat/health"),
                self._get(options, prefix + "rest/networkconf"),
                self._get(options, f"/proxy/network/v2/api/site/{site}/vpn/connections"),
            )
        )
        raw_devices = (
            devices_payload.get("data", [])
            if isinstance(devices_payload, dict)
            else []
        )
        raw_devices = [dict(item) for item in raw_devices if isinstance(item, dict)]
        expectations = self._derive_expectations(raw_devices, options, context)
        object_ids = {
            str(key).lower(): str(value)
            for key, value in dict(options.get("device_object_ids", {})).items()
        }
        front_names = {str(item) for item in options.get("front_device_names", [])}
        edge_names = {str(item) for item in options.get("edge_switch_names", [])}
        sampled = time.monotonic()
        devices: list[dict[str, Any]] = []
        degraded_count = 0
        offline_count = 0
        for raw in raw_devices:
            mac = str(raw.get("mac", "")).lower()
            name = str(raw.get("name") or raw.get("model") or mac or "unknown")
            connected = raw.get("state") == 1 and bool(raw.get("adopted", True))
            uplink = raw.get("uplink") or {}
            speed = uplink.get("speed")
            expected = expectations.get(mac)
            issues: list[str] = []
            if not connected:
                issues.append("UniFi reports device disconnected")
                offline_count += 1
            if connected and uplink.get("up") is False:
                issues.append("Uplink is down")
            if (
                connected
                and expected
                and isinstance(speed, (int, float))
                and speed < expected
            ):
                issues.append(
                    f"Uplink negotiated {speed:g} Mbps; expected {expected:g} Mbps"
                )
            if raw.get("overheating") is True:
                issues.append("Device reports overheating")
            uplink_port = next(
                (port for port in raw.get("port_table", []) if port.get("is_uplink")),
                None,
            )
            error_delta = 0
            if uplink_port:
                key = f"{mac}:{uplink_port.get('port_idx')}"
                errors = int(uplink_port.get("rx_errors", 0) or 0) + int(
                    uplink_port.get("tx_errors", 0) or 0
                )
                previous = self._port_counters.get(key)
                if previous and errors >= previous[1]:
                    seconds = max(0.001, sampled - previous[0])
                    error_delta = errors - previous[1]
                    if error_delta >= 5 and error_delta / seconds >= 0.25:
                        issues.append(
                            f"Uplink physical errors increased by {error_delta}"
                        )
                self._port_counters[key] = (sampled, errors)
            radios: list[dict[str, Any]] = []
            stats = {
                str(item.get("name")): item
                for item in raw.get("radio_table_stats", [])
                if isinstance(item, dict)
            }
            for configured in raw.get("radio_table", []):
                if not isinstance(configured, dict):
                    continue
                radio_name = str(configured.get("name", ""))
                disabled = (
                    configured.get("is_disabled") is True
                    or configured.get("disabled") is True
                )
                operational = (
                    str(stats.get(radio_name, {}).get("state", "")).upper()
                    == "RUN"
                )
                radios.append(
                    {
                        "name": radio_name,
                        "band": configured.get("radio"),
                        "configured_enabled": not disabled,
                        "operational": operational,
                        "channel": stats.get(radio_name, {}).get("channel"),
                    }
                )
                if connected and not disabled and not operational:
                    issues.append(f"Enabled radio {radio_name} is not operational")
            state = "offline" if not connected else "degraded" if issues else "healthy"
            if state == "degraded":
                degraded_count += 1
            devices.append(
                {
                    "id": "unifi_device_" + mac.replace(":", ""),
                    "object_id": object_ids.get(mac)
                    or object_ids.get(name.lower())
                    or "unifi_device_"
                    + mac.replace(":", ""),
                    "name": name,
                    "model": raw.get("model"),
                    "ip": raw.get("ip"),
                    "mac": mac,
                    "connected": connected,
                    "state": state,
                    "issues": issues,
                    "uplink_speed_mbps": speed,
                    "expected_uplink_speed_mbps": expected,
                    "uplink_error_delta": error_delta,
                    "temperature_c": raw.get("general_temperature")
                    or raw.get("temperature"),
                    "radios": radios,
                    "front_page": name in front_names,
                    "snmp_applicability": "not_applicable"
                    if name in edge_names
                    else "capable",
                }
            )

        configs = (
            networks_payload.get("data", [])
            if isinstance(networks_payload, dict)
            else []
        )
        connections = (
            connections_payload.get("connections", [])
            if isinstance(connections_payload, dict)
            else []
        )
        connection_by_id: dict[str, dict[str, Any]] = {}
        for item in connections:
            if not isinstance(item, dict):
                continue
            for key in ("network_id", "id", "_id"):
                value = item.get(key)
                if value not in (None, ""):
                    connection_by_id[str(value)] = item
        vpns: list[dict[str, Any]] = []
        for raw in configs:
            if not isinstance(raw, dict):
                continue
            purpose = raw.get("purpose")
            if purpose not in {"site-vpn", "vpn-client"}:
                continue
            identifier = str(raw.get("_id", ""))
            connection = connection_by_id.get(identifier, {})
            enabled = bool(raw.get("enabled", True))
            status = "paused" if not enabled else str(
                connection.get("status", "unknown")
            ).lower()
            vpns.append(
                {
                    "id": "unifi_vpn_" + identifier,
                    "name": str(raw.get("name") or identifier),
                    "role": purpose,
                    "enabled": enabled,
                    "status": status,
                    "operational": None if not enabled else status == "connected",
                    "remote_site_id": raw.get("sdwan_remote_site_id"),
                    "remote_subnets": raw.get("remote_vpn_subnets") or [],
                    "local_tunnel_subnet": raw.get("ip_subnet"),
                }
            )
        health = (
            health_payload.get("data", [])
            if isinstance(health_payload, dict)
            else []
        )
        metadata: dict[str, Any] = {
            "source_available": True,
            "site": site,
            "devices": devices,
            "vpns": vpns,
            "health": health,
            "link_expectations": expectations,
        }
        raw_vpn_expectations = options.get("vpn_expectations", [])
        vpn_expectations = (
            [dict(item) for item in raw_vpn_expectations if isinstance(item, dict)]
            if isinstance(raw_vpn_expectations, list)
            else []
        )
        if vpn_expectations:
            metadata["vpn_components"] = self._vpn_components(vpns, vpn_expectations)
        state = State.DEGRADED if offline_count or degraded_count else State.HEALTHY
        summary = f"UniFi operational; {len(devices)} devices"
        if offline_count or degraded_count:
            summary += f"; {offline_count} offline, {degraded_count} degraded"
        return _result(
            start,
            state,
            summary,
            {
                "device_count": float(len(devices)),
                "connected_devices": float(
                    sum(bool(item["connected"]) for item in devices)
                ),
                "offline_devices": float(offline_count),
                "degraded_devices": float(degraded_count),
                "vpn_count": float(len(vpns)),
            },
            metadata,
        )

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        if request.adapter != "unifi":
            raise ValueError(f"UniFi executor cannot run adapter {request.adapter!r}")
        operation = str(request.options.get("runtime_operation", "")).strip()
        if not operation:
            return await self._inventory(request, context)

        start = time.monotonic()
        if operation == "clients":
            site = str(request.options.get("site", "default"))
            payload = await self._get(
                request.options,
                f"/proxy/network/api/s/{site}/stat/sta",
            )
            data = payload.get("data", []) if isinstance(payload, dict) else []
            clients = [dict(item) for item in data if isinstance(item, dict)]
            return _result(
                start,
                State.HEALTHY,
                f"UniFi returned {len(clients)} client(s)",
                metadata={"runtime_operation": operation, "clients": clients},
            )
        if operation == "traffic_flows":
            flows = await self._traffic_flows(request.options)
            return _result(
                start,
                State.HEALTHY,
                f"UniFi returned {len(flows)} traffic flow(s)",
                metadata={"runtime_operation": operation, "flows": flows},
            )
        return _result(
            start,
            State.FAILED,
            f"Unsupported UniFi runtime operation: {operation}",
            metadata={"failure_kind": "unsupported_runtime_operation"},
        )


_UNIFI = UniFiRuntimeExecutor()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="unifi", display_name="UniFi Network"),
    runtime_adapter_kinds=("unifi",),
    runtime_executor=_UNIFI,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="UniFi Network Integration",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.unifi:PLUGIN"},
    requires_core=">=2.2.2 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
)

__all__ = [
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_MANIFEST",
    "MODULE_VERSION",
    "PLUGIN",
    "UniFiRuntimeExecutor",
]
