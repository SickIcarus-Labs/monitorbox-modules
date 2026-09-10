from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Mapping

import aiohttp

from ...model import State
from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult
from .discovery import unifi_evidence, wan_interface_addresses
from .phase2_policy import UniFiPhase2RuntimeExecutor, _inventory_authority, _port_index
from .phase3_recovery import annotate_inventory_provenance
from .runtime import _result
from .vertical_runtime import normalize_unifi_ports

_AUTH_MODES = frozenset({"username_password", "api_key"})
_OFFICIAL_PREFIX = "/proxy/network/integration"


def auth_mode(options: Mapping[str, Any]) -> str:
    """Return explicit auth backend; missing keeps immutable legacy configs valid."""
    mode = str(options.get("auth_mode") or "username_password").strip().casefold()
    if mode not in _AUTH_MODES:
        raise RuntimeError(f"unsupported UniFi auth_mode: {mode!r}")
    return mode


def topology_port_roles(payload: Any) -> dict[tuple[str, int], str]:
    """Project only provider-explicit WIRED physical topology onto both switch ports."""
    if not isinstance(payload, Mapping):
        return {}
    edges = payload.get("edges")
    if not isinstance(edges, list):
        return {}
    roles: dict[tuple[str, int], str] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        if str(edge.get("type") or "").strip().upper() != "WIRED":
            continue
        child_mac = str(edge.get("downlinkMac") or "").strip().casefold()
        parent_mac = str(edge.get("uplinkMac") or "").strip().casefold()
        child_idx = _port_index(edge.get("downlinkPortNumber"))
        parent_idx = _port_index(edge.get("uplinkPortNumber"))
        if not child_mac or not parent_mac or child_idx is None or parent_idx is None:
            continue
        roles[(child_mac, child_idx)] = "uplink"
        roles[(parent_mac, parent_idx)] = "infrastructure"
    return roles


def apply_topology_roles(ports: Any, payload: Any) -> list[dict[str, Any]]:
    normalized = [dict(item) for item in ports if isinstance(item, Mapping)] if isinstance(ports, list) else []
    roles = topology_port_roles(payload)
    for port in normalized:
        mac = str(port.get("device_mac") or "").strip().casefold()
        idx = _port_index(port.get("port_idx"))
        if idx is None:
            continue
        role = roles.get((mac, idx))
        if role is None:
            continue
        port["port_idx"] = idx
        port["infrastructure_role"] = role
        if role == "uplink":
            port["is_uplink"] = True
    return normalized


def _page_rows(payload: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"UniFi Integration API {where} response is not an object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError(f"UniFi Integration API {where} response has no data list")
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def _media(connector: Any, max_speed: Any = None) -> str:
    value = str(connector or "").strip().upper()
    if value == "RJ45":
        speed = int(max_speed) if isinstance(max_speed, (int, float)) and not isinstance(max_speed, bool) else None
        return {
            100: "FE",
            1000: "GE",
            2500: "2P5GE",
            5000: "5GE",
            10000: "10GE",
        }.get(speed, "RJ45")
    return {
        "SFP": "SFP",
        "SFPPLUS": "SFP+",
        "SFP28": "SFP28",
    }.get(value, value)


class UniFiApiMigrationRuntimeExecutor(UniFiPhase2RuntimeExecutor):
    """Dual-backend UniFi provider qualified by the Broad Leaf 10.6.101 census.

    Primary backend selection is explicit. API-key mode never silently falls back
    to the legacy session backend. Capabilities proven legacy-only may use an
    independently configured legacy-read companion; companion loss degrades only
    those capabilities.
    """

    def __init__(self) -> None:
        super().__init__()
        self._official_context: dict[tuple[str, str, str, bool], tuple[float, str, str]] = {}

    async def close(self, context: RuntimeExecutionContext) -> None:
        self._official_context.clear()
        await super().close(context)

    @staticmethod
    def _official_key(options: Mapping[str, Any]) -> tuple[str, str, str, bool]:
        return (
            str(options.get("base_url") or "").rstrip("/").casefold(),
            str(options.get("api_key_env") or ""),
            str(options.get("site") or "default"),
            bool(options.get("verify_tls", False)),
        )

    @staticmethod
    def _api_key(options: Mapping[str, Any]) -> str:
        env_name = str(options.get("api_key_env") or "").strip()
        if not env_name:
            raise RuntimeError("api_key auth requires api_key_env")
        try:
            value = os.environ[env_name]
        except KeyError as exc:
            raise RuntimeError(f"credential environment variable is missing: {env_name}") from exc
        if not value:
            raise RuntimeError(f"credential environment variable is empty: {env_name}")
        return value

    async def _official_get(self, options: Mapping[str, Any], path: str) -> Any:
        if self.session is None:
            raise RuntimeError("UniFi runtime executor is not started")
        if not path.startswith("/"):
            raise RuntimeError("Integration API path must be absolute")
        base = str(options.get("base_url") or "").rstrip("/")
        prefix = str(options.get("official_prefix") or _OFFICIAL_PREFIX).rstrip("/")
        if prefix != _OFFICIAL_PREFIX:
            raise RuntimeError(f"unsupported qualified UniFi Integration API prefix: {prefix}")
        headers = {
            "Accept": "application/json",
            "X-API-Key": self._api_key(options),
        }
        async with self.session.get(
            base + prefix + path,
            headers=headers,
            ssl=None if self._verify_tls(options) else False,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"{prefix}{path} returned HTTP {response.status}")
            try:
                return await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError) as exc:
                raise RuntimeError(f"{prefix}{path} returned incompatible JSON") from exc

    async def _qualified_context(self, options: Mapping[str, Any]) -> tuple[str, str]:
        key = self._official_key(options)
        cached = self._official_context.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] <= 30.0:
            return cached[1], cached[2]

        info = await self._official_get(options, "/v1/info")
        if not isinstance(info, Mapping):
            raise RuntimeError("UniFi Integration API /v1/info response is not an object")
        version = str(info.get("applicationVersion") or "").strip()
        if not version:
            raise RuntimeError("UniFi Integration API /v1/info lacks applicationVersion")

        sites = _page_rows(await self._official_get(options, "/v1/sites?limit=200"), "sites")
        if not sites:
            raise RuntimeError("UniFi Integration API returned no sites")
        requested_id = str(options.get("official_site_id") or "").strip()
        requested = str(options.get("site") or "default").strip()
        selected: Mapping[str, Any] | None = None
        if requested_id:
            selected = next((row for row in sites if str(row.get("id") or "") == requested_id), None)
            if selected is None:
                raise RuntimeError("configured official_site_id is not present in UniFi site inventory")
        else:
            matches = [
                row for row in sites
                if requested in {
                    str(row.get("id") or ""),
                    str(row.get("internalReference") or ""),
                    str(row.get("name") or ""),
                }
            ]
            if len(matches) == 1:
                selected = matches[0]
            elif len(sites) == 1:
                selected = sites[0]
            else:
                raise RuntimeError("UniFi site selection is ambiguous; configure official_site_id")
        site_id = str(selected.get("id") or "").strip()
        if not site_id:
            raise RuntimeError("selected UniFi site lacks id")
        self._official_context[key] = (now, version, site_id)
        return version, site_id

    @staticmethod
    def _legacy_companion(options: Mapping[str, Any]) -> dict[str, Any] | None:
        raw = options.get("legacy_read")
        if not isinstance(raw, Mapping) or raw.get("enabled") is not True:
            return None
        username_env = str(raw.get("username_env") or "").strip()
        password_env = str(raw.get("password_env") or "").strip()
        if not username_env or not password_env:
            raise RuntimeError(
                "legacy_read.enabled requires explicit username_env and password_env"
            )
        return {
            "base_url": str(options.get("base_url") or "").rstrip("/"),
            "site": str(raw.get("site") or options.get("site") or "default"),
            "username_env": username_env,
            "password_env": password_env,
            "verify_tls": bool(options.get("verify_tls", False)),
        }

    async def _legacy_topology(self, options: Mapping[str, Any]) -> Any:
        companion = self._legacy_companion(options)
        if companion is None:
            raise RuntimeError("explicit legacy-read companion is not configured")
        site = str(companion.get("site") or "default")
        return await super()._get(
            companion, f"/proxy/network/v2/api/site/{site}/topology"
        )

    @staticmethod
    def _inject_topology_uplinks(
        raw_devices: list[dict[str, Any]], topology: Any
    ) -> None:
        if not isinstance(topology, Mapping):
            return
        by_mac = {
            str(item.get("mac") or "").strip().casefold(): item
            for item in raw_devices
            if str(item.get("mac") or "").strip()
        }
        for edge in topology.get("edges", []):
            if not isinstance(edge, Mapping) or str(edge.get("type") or "").upper() != "WIRED":
                continue
            child_mac = str(edge.get("downlinkMac") or "").strip().casefold()
            parent_mac = str(edge.get("uplinkMac") or "").strip().casefold()
            child_idx = _port_index(edge.get("downlinkPortNumber"))
            parent_idx = _port_index(edge.get("uplinkPortNumber"))
            child = by_mac.get(child_mac)
            if child is None or parent_mac not in by_mac or child_idx is None or parent_idx is None:
                continue
            child_port = next(
                (
                    p for p in child.get("port_table", [])
                    if isinstance(p, Mapping) and _port_index(p.get("port_idx")) == child_idx
                ),
                None,
            )
            child["uplink"] = {
                "port_idx": child_idx,
                "uplink_mac": parent_mac,
                "uplink_remote_port": parent_idx,
                "up": bool(child_port and child_port.get("up") is True),
                "speed": child_port.get("speed") if child_port else None,
                "max_speed": child_port.get("max_speed") if child_port else None,
            }

    @staticmethod
    def _raw_official_device(
        overview: Mapping[str, Any], detail: Mapping[str, Any], stats: Any
    ) -> dict[str, Any]:
        source = dict(overview)
        source.update(dict(detail))
        raw_ports = (
            source.get("interfaces", {}).get("ports", [])
            if isinstance(source.get("interfaces"), Mapping)
            else []
        )
        port_table: list[dict[str, Any]] = []
        for raw in raw_ports if isinstance(raw_ports, list) else []:
            if not isinstance(raw, Mapping):
                continue
            idx = _port_index(raw.get("idx"))
            if idx is None:
                continue
            port_table.append({
                "port_idx": idx,
                "name": f"Port {idx}",
                "up": str(raw.get("state") or "").upper() == "UP",
                "speed": raw.get("speedMbps"),
                "max_speed": raw.get("maxSpeedMbps"),
                "media": _media(raw.get("connector"), raw.get("maxSpeedMbps")),
                "connector": raw.get("connector"),
            })
        stat = dict(stats) if isinstance(stats, Mapping) else {}
        return {
            "provider_id": source.get("id"),
            "mac": source.get("macAddress"),
            "name": source.get("name"),
            "model": source.get("model"),
            "ip": source.get("ipAddress"),
            "state": 1 if str(source.get("state") or "").upper() == "ONLINE" else 0,
            "adopted": True,
            "supported": source.get("supported"),
            "firmware_version": source.get("firmwareVersion"),
            "port_table": port_table,
            "cpu_utilization_pct": stat.get("cpuUtilizationPct"),
            "memory_utilization_pct": stat.get("memoryUtilizationPct"),
            "uptime_sec": stat.get("uptimeSec"),
            # Do not project official uplink.deviceId into a port role. The
            # qualified schema lacks local/remote port identity.
            "official_uplink_device_id": (
                source.get("uplink", {}).get("deviceId")
                if isinstance(source.get("uplink"), Mapping)
                else None
            ),
        }

    async def _official_raw_devices(
        self, options: Mapping[str, Any], site_id: str
    ) -> list[dict[str, Any]]:
        payload = await self._official_get(
            options, f"/v1/sites/{site_id}/devices?limit=200"
        )
        overview = _page_rows(payload, "devices")
        result: list[dict[str, Any]] = []
        for row in overview:
            device_id = str(row.get("id") or "").strip()
            if not device_id:
                continue
            detail = await self._official_get(
                options, f"/v1/sites/{site_id}/devices/{device_id}"
            )
            if not isinstance(detail, Mapping):
                raise RuntimeError("UniFi Integration API device detail is not an object")
            stats: Any = {}
            try:
                stats = await self._official_get(
                    options,
                    f"/v1/sites/{site_id}/devices/{device_id}/statistics/latest",
                )
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc):
                    raise
            result.append(self._raw_official_device(row, detail, stats))
        if overview and not result:
            raise RuntimeError("UniFi Integration API device inventory lacks stable ids")
        return result

    async def _companion_rich_context(
        self, options: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        companion = self._legacy_companion(options)
        if companion is None:
            return [], [], "not_configured"
        site = str(companion.get("site") or "default")
        prefix = f"/proxy/network/api/s/{site}/"
        try:
            health_payload, networks_payload, connections_payload = await asyncio.gather(
                super()._get(companion, prefix + "stat/health"),
                super()._get(companion, prefix + "rest/networkconf"),
                super()._get(companion, f"/proxy/network/v2/api/site/{site}/vpn/connections"),
            )
        except Exception as exc:
            return [], [], f"{type(exc).__name__}: {exc}"[:300]
        health = health_payload.get("data", []) if isinstance(health_payload, Mapping) else []
        configs = networks_payload.get("data", []) if isinstance(networks_payload, Mapping) else []
        connections = connections_payload.get("connections", []) if isinstance(connections_payload, Mapping) else []
        connection_by_id: dict[str, Mapping[str, Any]] = {}
        for item in connections if isinstance(connections, list) else []:
            if not isinstance(item, Mapping):
                continue
            for key in ("network_id", "id", "_id"):
                value = item.get(key)
                if value not in (None, ""):
                    connection_by_id[str(value)] = item
        vpns: list[dict[str, Any]] = []
        for raw in configs if isinstance(configs, list) else []:
            if not isinstance(raw, Mapping) or raw.get("purpose") not in {"site-vpn", "vpn-client"}:
                continue
            identifier = str(raw.get("_id") or "")
            connection = connection_by_id.get(identifier, {})
            enabled = bool(raw.get("enabled", True))
            status = "paused" if not enabled else str(connection.get("status", "unknown")).lower()
            vpns.append({
                "id": "unifi_vpn_" + identifier,
                "name": str(raw.get("name") or identifier),
                "role": raw.get("purpose"),
                "enabled": enabled,
                "status": status,
                "operational": None if not enabled else status == "connected",
                "remote_site_id": raw.get("sdwan_remote_site_id"),
                "remote_subnets": raw.get("remote_vpn_subnets") or [],
                "local_tunnel_subnet": raw.get("ip_subnet"),
            })
        return (
            [dict(item) for item in health if isinstance(item, Mapping)],
            vpns,
            None,
        )

    async def _api_inventory(
        self, request: RuntimeExecutionRequest, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult:
        start = time.monotonic()
        options = request.options
        version, site_id = await self._qualified_context(options)
        raw_devices = await self._official_raw_devices(options, site_id)

        topology: Any = None
        topology_error: str | None = None
        if self._legacy_companion(options) is not None:
            try:
                topology = await self._legacy_topology(options)
                self._inject_topology_uplinks(raw_devices, topology)
            except Exception as exc:
                topology_error = f"{type(exc).__name__}: {exc}"[:300]
        else:
            topology_error = "not_configured"

        expectations = self._derive_expectations(raw_devices, options, context)
        object_ids = {
            str(key).lower(): str(value)
            for key, value in dict(options.get("device_object_ids", {})).items()
        }
        front_names = {str(item) for item in options.get("front_device_names", [])}
        edge_names = {str(item) for item in options.get("edge_switch_names", [])}
        devices: list[dict[str, Any]] = []
        offline_count = 0
        degraded_count = 0
        for raw in raw_devices:
            mac = str(raw.get("mac") or "").lower()
            name = str(raw.get("name") or raw.get("model") or mac or "unknown")
            connected = raw.get("state") == 1
            uplink = raw.get("uplink") if isinstance(raw.get("uplink"), Mapping) else {}
            speed = uplink.get("speed")
            expected = expectations.get(mac)
            issues: list[str] = []
            if not connected:
                issues.append("UniFi reports device disconnected")
                offline_count += 1
            if connected and uplink and uplink.get("up") is False:
                issues.append("Uplink is down")
            if connected and expected and isinstance(speed, (int, float)) and speed < expected:
                issues.append(f"Uplink negotiated {speed:g} Mbps; expected {expected:g} Mbps")
            state = "offline" if not connected else "degraded" if issues else "healthy"
            if state == "degraded":
                degraded_count += 1
            devices.append({
                "id": "unifi_device_" + mac.replace(":", ""),
                "object_id": object_ids.get(mac) or object_ids.get(name.lower()) or "unifi_device_" + mac.replace(":", ""),
                "name": name,
                "model": raw.get("model"),
                "ip": raw.get("ip"),
                "mac": mac,
                "connected": connected,
                "state": state,
                "issues": issues,
                "uplink_speed_mbps": speed,
                "expected_uplink_speed_mbps": expected,
                "temperature_c": None,
                "radios": [],
                "front_page": name in front_names,
                "snmp_applicability": "not_applicable" if name in edge_names else "capable",
                "cpu_utilization_pct": raw.get("cpu_utilization_pct"),
                "memory_utilization_pct": raw.get("memory_utilization_pct"),
                "uptime_sec": raw.get("uptime_sec"),
            })

        ports = normalize_unifi_ports(raw_devices, device_object_ids=object_ids)
        ports = apply_topology_roles(ports, topology)
        health, vpns, rich_error = await self._companion_rich_context(options)
        metadata: dict[str, Any] = {
            "source_available": True,
            "site": str(options.get("site") or "default"),
            "official_site_id": site_id,
            "network_application_version": version,
            "auth_mode": "api_key",
            "provider_backend": "integration_api",
            "devices": devices,
            "ports": ports,
            "vpns": vpns,
            "health": health,
            "link_expectations": expectations,
            "wan_interface_addresses": sorted(wan_interface_addresses(health)),
            "capabilities": {
                "device_inventory": "official",
                "device_statistics": "official",
                "clients": "official",
                "switch_port_state": "official_partial_admin_state_unavailable",
                "physical_topology": (
                    "legacy_read" if topology is not None else "unavailable"
                ),
                "traffic_flows": (
                    "legacy_read" if self._legacy_companion(options) is not None else "unavailable"
                ),
                "rich_wan_vpn_status": (
                    "legacy_read" if rich_error is None else "unavailable"
                ),
            },
        }
        if topology_error:
            metadata["topology_capability_error"] = topology_error
        if rich_error:
            metadata["rich_wan_vpn_capability_error"] = rich_error
        raw_vpn_expectations = options.get("vpn_expectations", [])
        vpn_expectations = (
            [dict(item) for item in raw_vpn_expectations if isinstance(item, Mapping)]
            if isinstance(raw_vpn_expectations, list)
            else []
        )
        if vpn_expectations:
            metadata["vpn_components"] = self._vpn_components(vpns, vpn_expectations)
        metadata = _inventory_authority(metadata)
        evidence = unifi_evidence(devices, ports, health)
        metadata["discovery_evidence"] = [item.as_dict() for item in evidence]
        annotate_inventory_provenance(metadata, request.check_id)
        state = State.DEGRADED if offline_count or degraded_count else State.HEALTHY
        summary = f"UniFi operational via Integration API; {len(devices)} devices"
        if offline_count or degraded_count:
            summary += f"; {offline_count} offline, {degraded_count} degraded"
        return _result(
            start,
            state,
            summary,
            {
                "device_count": float(len(devices)),
                "connected_devices": float(sum(bool(item["connected"]) for item in devices)),
                "offline_devices": float(offline_count),
                "degraded_devices": float(degraded_count),
                "vpn_count": float(len(vpns)),
                "port_count": float(len(ports)),
            },
            metadata,
        )

    async def _api_clients(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        start = time.monotonic()
        options = request.options
        version, site_id = await self._qualified_context(options)
        rows = _page_rows(
            await self._official_get(options, f"/v1/sites/{site_id}/clients?limit=200"),
            "clients",
        )
        clients = []
        for raw in rows:
            clients.append({
                "id": raw.get("id"),
                "mac": raw.get("macAddress"),
                "ip": raw.get("ipAddress"),
                "name": raw.get("name"),
                "hostname": raw.get("name"),
                "type": raw.get("type"),
                "is_wired": str(raw.get("type") or "").upper() == "WIRED",
                "uplink_device_id": raw.get("uplinkDeviceId"),
                "access": raw.get("access"),
                "connected_at": raw.get("connectedAt"),
            })
        return _result(
            start,
            State.HEALTHY,
            f"UniFi returned {len(clients)} client(s) via Integration API",
            metadata={
                "runtime_operation": "clients",
                "clients": clients,
                "auth_mode": "api_key",
                "provider_backend": "integration_api",
                "network_application_version": version,
            },
        )

    async def _api_port_state(
        self, request: RuntimeExecutionRequest, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult:
        start = time.monotonic()
        inventory = await self._api_inventory(request, context)
        ports = inventory.metadata.get("ports", [])
        wanted_mac = str(request.options.get("device_mac") or "").strip().casefold()
        wanted_idx = _port_index(request.options.get("port_idx"))
        port = next(
            (
                item for item in ports
                if isinstance(item, Mapping)
                and str(item.get("device_mac") or "").casefold() == wanted_mac
                and _port_index(item.get("port_idx")) == wanted_idx
            ),
            None,
        )
        if port is None:
            return RuntimeExecutionResult(
                state=State.FAILED.value,
                summary="Configured switch port is missing from UniFi inventory",
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": True,
                    "missing": True,
                    "device_mac": wanted_mac,
                    "port_idx": wanted_idx,
                    "auth_mode": "api_key",
                },
            )
        linked = port.get("linked") is True
        speed = port.get("speed_mbps")
        if not linked:
            # Integration API 10.6.101 does not expose administrative enable/
            # disable truth; DOWN therefore cannot be called a target failure.
            return RuntimeExecutionResult(
                state=State.UNKNOWN.value,
                summary="Switch port is down; Integration API does not expose administrative state",
                duration_ms=(time.monotonic() - start) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": False,
                    "failure_kind": "monitor_dependency",
                    "capability_gap": "port_admin_state",
                    "device_mac": wanted_mac,
                    "port_idx": wanted_idx,
                    "auth_mode": "api_key",
                },
            )
        metrics = {"linked": 1.0}
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            metrics["speed_mbps"] = float(speed)
        return RuntimeExecutionResult(
            state=State.HEALTHY.value,
            summary=(
                f"Switch port link up at {float(speed):g} Mbps"
                if isinstance(speed, (int, float)) and speed
                else "Switch port link up"
            ),
            duration_ms=(time.monotonic() - start) * 1000,
            metrics=metrics,
            metadata={
                "provider": "unifi",
                "authoritative": True,
                "device_mac": wanted_mac,
                "port_idx": wanted_idx,
                "linked": True,
                "auth_mode": "api_key",
            },
        )

    async def _api_traffic_flows(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        start = time.monotonic()
        companion = self._legacy_companion(request.options)
        if companion is None:
            raise RuntimeError(
                "traffic flows are legacy-only and explicit legacy-read companion is not configured"
            )
        flows = await super()._traffic_flows(companion)
        return _result(
            start,
            State.HEALTHY,
            f"UniFi returned {len(flows)} traffic flow(s) via explicit legacy-read capability",
            metadata={
                "runtime_operation": "traffic_flows",
                "flows": flows,
                "auth_mode": "api_key",
                "provider_backend": "integration_api",
                "capability_backend": "legacy_read",
            },
        )

    async def _legacy_inventory_with_topology(
        self, request: RuntimeExecutionRequest, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult:
        result = await super().execute(request, context)
        runtime_operation = str(request.options.get("runtime_operation", "")).strip()
        operation = str(request.options.get("operation", "inventory")).strip().casefold()
        if runtime_operation or operation != "inventory" or result.metadata.get("source_available") is not True:
            return result
        metadata = dict(result.metadata)
        capabilities = dict(metadata.get("capabilities") or {})
        capabilities["physical_topology"] = "legacy"
        site = str(request.options.get("site") or "default")
        try:
            topology = await super()._get(
                request.options, f"/proxy/network/v2/api/site/{site}/topology"
            )
            ports = apply_topology_roles(metadata.get("ports", []), topology)
            metadata["ports"] = ports
            metadata["discovery_evidence"] = [
                item.as_dict()
                for item in unifi_evidence(
                    metadata.get("devices", []), ports, metadata.get("health", [])
                )
            ]
        except Exception as exc:
            capabilities["physical_topology"] = "unavailable"
            metadata["topology_capability_error"] = f"{type(exc).__name__}: {exc}"[:300]
        metadata["auth_mode"] = "username_password"
        metadata["provider_backend"] = "legacy_session"
        metadata["capabilities"] = capabilities
        annotate_inventory_provenance(metadata, request.check_id)
        return RuntimeExecutionResult(
            state=result.state,
            summary=result.summary,
            duration_ms=result.duration_ms,
            metrics=dict(result.metrics),
            metadata=metadata,
        )

    async def execute(
        self, request: RuntimeExecutionRequest, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult:
        if request.adapter != "unifi":
            raise ValueError(f"UniFi executor cannot run adapter {request.adapter!r}")
        mode = auth_mode(request.options)
        if mode == "username_password":
            return await self._legacy_inventory_with_topology(request, context)

        started = time.monotonic()
        try:
            runtime_operation = str(request.options.get("runtime_operation", "")).strip()
            operation = str(request.options.get("operation", "inventory")).strip().casefold()
            if runtime_operation == "clients":
                return await self._api_clients(request)
            if runtime_operation == "traffic_flows":
                return await self._api_traffic_flows(request)
            if runtime_operation:
                return _result(
                    started,
                    State.FAILED,
                    f"Unsupported UniFi runtime operation: {runtime_operation}",
                    metadata={"failure_kind": "unsupported_runtime_operation"},
                )
            if operation == "port_state":
                return await self._api_port_state(request, context)
            if operation != "inventory":
                return _result(
                    started,
                    State.FAILED,
                    f"Unsupported UniFi operation: {operation}",
                    metadata={"failure_kind": "unsupported_runtime_operation"},
                )
            return await self._api_inventory(request, context)
        except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            detail = f"{type(exc).__name__}: {exc}"[:300]
            return RuntimeExecutionResult(
                state=State.UNKNOWN.value,
                summary=f"UniFi provider unavailable: {detail}"[:400],
                duration_ms=(time.monotonic() - started) * 1000,
                metadata={
                    "provider": "unifi",
                    "authoritative": False,
                    "failure_kind": "monitor_dependency",
                    "provider_error_type": type(exc).__name__,
                    "auth_mode": "api_key",
                    "provider_backend": "integration_api",
                },
            )


__all__ = [
    "UniFiApiMigrationRuntimeExecutor",
    "apply_topology_roles",
    "auth_mode",
    "topology_port_roles",
]
