#!/usr/bin/env python3
"""Side-by-side Broad Leaf UniFi census for MonitorBox #170/#228.

Uses the bounded transport/auth primitives in unifi_api_census.py, but adds the
migration-specific discovery/fan-out required by docs/UNIFI-API-MIGRATION.md.
Only GETs are plan-driven. The one provider-data POST is a fixed, empty-body
legacy traffic-flows read used by the current MonitorBox UniFi module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import unifi_api_census as base

UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
MAC_RE = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
IP_KEY_RE = re.compile(r"(^|_)(ip|ipv4|ipv6|ip_address|ipaddr)($|_)")
IPV4_RE = re.compile(
    r"(?<![0-9])(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}(?![0-9])"
)
SAFE_STRING_KEYS = {
    "applicationversion", "firmwareversion", "model", "modelkey",
    "type", "devicetype", "state", "status", "role", "purpose",
    "connector", "media", "standard", "band", "wlanstandard",
    "code", "statusname",
}
NAME_KEYS = {
    "name", "hostname", "displayname", "devicename", "sitename",
    "ssid", "wlanname", "clientname", "username", "user", "email",
    "description",
}


def compact(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


class StrictSanitizer(base.Sanitizer):
    """Default-deny arbitrary strings while preserving provider semantics."""

    def _scalar(self, key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if value in self._aliases:
            return f"<alias:{self._aliases[value]}>"
        key_c = compact(key)
        key_f = key.casefold()
        if base._sensitive_key(key):
            return "<redacted>"
        if "mac" in key_c:
            return f"<mac:{self._digest('mac', value.casefold())}>"
        if IP_KEY_RE.search(key_f) or key_c in {
            "ipaddress", "ipv4address", "ipv6address"
        }:
            return f"<ip:{self._digest('ip', value.casefold())}>"
        if key_c in {"serial", "serialnumber"}:
            return f"<serial:{self._digest('serial', value)}>"
        if key_c == "id" or key_c.endswith("id"):
            return f"<id:{self._digest('id', value)}>"
        if key_c in NAME_KEYS:
            return f"<name:{self._digest('name', value)}>"
        if key_c in SAFE_STRING_KEYS:
            return value
        return f"<str:{self._digest('str', value)}>"

    def text(self, value: str) -> str:
        text = str(value)
        for raw, alias in self._aliases.items():
            text = text.replace(raw, f"<alias:{alias}>")
        text = UUID_RE.sub(
            lambda m: f"<id:{self._digest('id', m.group(0))}>", text
        )
        text = MAC_RE.sub(
            lambda m: f"<mac:{self._digest('mac', m.group(0).casefold())}>",
            text,
        )
        text = IPV4_RE.sub(
            lambda m: f"<ip:{self._digest('ip', m.group(0))}>", text
        )
        return text


def decode(result: Mapping[str, Any]) -> tuple[Any, str | None]:
    raw = result.get("body", b"")
    if not isinstance(raw, bytes):
        return None, "body was not bytes"
    if result.get("truncated"):
        return None, "response exceeded capture limit"
    ctype = str(result.get("content_type") or "").casefold()
    if "json" not in ctype and raw.lstrip()[:1] not in {b"{", b"["}:
        return None, None
    try:
        return json.loads(raw.decode()), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def record_result(
    result: Mapping[str, Any],
    *,
    backend: str,
    capability: str,
    method: str,
    path: str,
    sanitizer: StrictSanitizer,
) -> tuple[dict[str, Any], Any]:
    raw = result.get("body", b"")
    payload, parse_error = decode(result)
    item: dict[str, Any] = {
        "backend": backend,
        "capability": capability,
        "method": method,
        "path": sanitizer.text(path),
        "status": int(result["status"]),
        "elapsed_ms": result["elapsed_ms"],
        "content_type": result["content_type"],
        "bytes_captured": len(raw) if isinstance(raw, bytes) else 0,
        "truncated": bool(result["truncated"]),
        "body_sha256": hashlib.sha256(raw).hexdigest()
        if isinstance(raw, bytes) else None,
        "response_headers": sanitizer.sanitize(result["headers"]),
        "json": sanitizer.sanitize(payload) if payload is not None else None,
    }
    if parse_error:
        item["parse_error"] = parse_error
    return item, payload


def get_probe(
    records: list[dict[str, Any]],
    client: base.BackendClient,
    *,
    backend: str,
    capability: str,
    path: str,
    sanitizer: StrictSanitizer,
) -> tuple[Any, int | None]:
    try:
        result = client.request(path, method="GET")
        item, payload = record_result(
            result, backend=backend, capability=capability, method="GET",
            path=path, sanitizer=sanitizer,
        )
        records.append(item)
        return payload, int(result["status"])
    except (OSError, urllib.error.URLError, TimeoutError, base.CensusError) as exc:
        records.append({
            "backend": backend,
            "capability": capability,
            "method": "GET",
            "path": sanitizer.text(path),
            "error": sanitizer.text(f"{type(exc).__name__}: {exc}"[:400]),
        })
        return None, None


def traffic_probe(
    records: list[dict[str, Any]],
    client: base.BackendClient,
    *,
    backend: str,
    path: str,
    sanitizer: StrictSanitizer,
) -> None:
    """Execute the exact current read-only legacy traffic-flow query."""
    if not re.fullmatch(r"/proxy/network/v2/api/site/[^/]+/traffic-flows", path):
        raise base.CensusError("traffic POST path escaped fixed read-only surface")
    req = urllib.request.Request(
        client._url(path),
        data=b"{}",
        headers={**client.headers, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        try:
            response = client.opener.open(
                req, timeout=client.controller.timeout_seconds
            )
        except urllib.error.HTTPError as exc:
            response = exc
        elapsed = (time.monotonic() - started) * 1000
        with response:
            raw = response.read(client.controller.max_bytes + 1)
            truncated = len(raw) > client.controller.max_bytes
            if truncated:
                raw = raw[:client.controller.max_bytes]
            result = {
                "status": int(response.status),
                "elapsed_ms": round(elapsed, 3),
                "content_type": response.headers.get("Content-Type", ""),
                "headers": dict(response.headers.items()),
                "body": raw,
                "truncated": truncated,
            }
        item, _ = record_result(
            result, backend=backend, capability="traffic_flows",
            method="POST", path=path, sanitizer=sanitizer,
        )
        records.append(item)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        records.append({
            "backend": backend,
            "capability": "traffic_flows",
            "method": "POST",
            "path": sanitizer.text(path),
            "error": sanitizer.text(f"{type(exc).__name__}: {exc}"[:400]),
        })


def items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(x) for x in payload if isinstance(x, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "sites", "devices", "clients"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(x) for x in value if isinstance(x, Mapping)]
    return []


def path_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return urllib.parse.quote(value.strip(), safe="")


def bounded(raw: Any, default: int, maximum: int, label: str) -> int:
    value = default if raw is None else int(raw)
    if not 1 <= value <= maximum:
        raise base.CensusError(f"{label} must be between 1 and {maximum}")
    return value


def official(
    controller: base.Controller,
    cfg: Mapping[str, Any],
    sanitizer: StrictSanitizer,
    secrets: list[str],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    name = str(cfg.get("name") or "official")
    client = base._client_for_backend(controller, cfg, secrets)
    raw_prefixes = cfg.get(
        "prefixes", ["/integration", "/proxy/network/integration"]
    )
    if not isinstance(raw_prefixes, Sequence) or isinstance(
        raw_prefixes, (str, bytes)
    ):
        raise base.CensusError("official.prefixes must be a list")
    prefixes = [
        str(p).rstrip("/") for p in raw_prefixes if str(p).startswith("/")
    ]
    selected = None
    for prefix in prefixes:
        payload, status = get_probe(
            records, client, backend=name, capability="application_info",
            path=f"{prefix}/v1/info", sanitizer=sanitizer,
        )
        if selected is None and status == 200 and isinstance(payload, Mapping):
            selected = prefix
    if selected is None:
        return {"selected_prefix": None, "site_count": 0, "device_count": 0}

    for path in (
        "/proxy/network/api-docs/integration.json",
        f"{selected}/openapi.json",
        f"{selected}/v1/openapi.json",
        f"{selected}/swagger.json",
    ):
        get_probe(
            records, client, backend=name, capability="api_schema",
            path=path, sanitizer=sanitizer,
        )

    sites_payload, _ = get_probe(
        records, client, backend=name, capability="sites",
        path=f"{selected}/v1/sites?limit=200", sanitizer=sanitizer,
    )
    site_rows = items(sites_payload)
    max_sites = bounded(cfg.get("max_sites"), 8, 32, "official.max_sites")
    max_devices = bounded(
        cfg.get("max_devices"), 64, 256, "official.max_devices"
    )
    total_devices = 0
    for site in site_rows[:max_sites]:
        sid = path_id(site.get("id"))
        if sid is None:
            continue
        sb = f"{selected}/v1/sites/{sid}"
        device_payload, _ = get_probe(
            records, client, backend=name, capability="device_inventory",
            path=f"{sb}/devices?limit=200", sanitizer=sanitizer,
        )
        device_rows = items(device_payload)
        total_devices += len(device_rows)
        for capability, suffix in (
            ("client_inventory", "/clients?limit=200"),
            ("network_detail", "/networks?limit=200"),
            ("wan_detail", "/wans?limit=200"),
            ("vpn_site_to_site", "/vpn/site-to-site-tunnels?limit=200"),
            ("switch_stacks", "/switching/switch-stacks?limit=200"),
            ("mc_lag_domains", "/switching/mc-lag-domains?limit=200"),
        ):
            get_probe(
                records, client, backend=name, capability=capability,
                path=sb + suffix, sanitizer=sanitizer,
            )
        for device in device_rows[:max_devices]:
            did = path_id(device.get("id"))
            if did is None:
                continue
            db = f"{sb}/devices/{did}"
            get_probe(
                records, client, backend=name,
                capability="device_detail_topology_ports",
                path=db, sanitizer=sanitizer,
            )
            for suffix in ("/statistics", "/statistics/latest"):
                get_probe(
                    records, client, backend=name,
                    capability="device_statistics",
                    path=db + suffix, sanitizer=sanitizer,
                )
    return {
        "selected_prefix": selected,
        "site_count": len(site_rows),
        "device_count": total_devices,
    }


def legacy(
    controller: base.Controller,
    cfg: Mapping[str, Any],
    sanitizer: StrictSanitizer,
    secrets: list[str],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    name = str(cfg.get("name") or "legacy")
    client = base._client_for_backend(controller, cfg, secrets)
    site = str(cfg.get("site") or "default").strip()
    if not site or "/" in site:
        raise base.CensusError("legacy.site must be a single site reference")
    site_q = urllib.parse.quote(site, safe="")
    p1 = f"/proxy/network/api/s/{site_q}"
    p2 = f"/proxy/network/v2/api/site/{site_q}"
    for capability, path in (
        ("console_system_info", "/api/system"),
        ("application_info", f"{p1}/stat/sysinfo"),
        ("device_inventory_topology_ports", f"{p1}/stat/device"),
        ("client_inventory", f"{p1}/stat/sta"),
        ("health_wan", f"{p1}/stat/health"),
        ("network_detail_vpn_config", f"{p1}/rest/networkconf"),
        ("vpn_connections", f"{p2}/vpn/connections"),
        ("topology", f"{p2}/topology"),
    ):
        get_probe(
            records, client, backend=name, capability=capability,
            path=path, sanitizer=sanitizer,
        )
    traffic_probe(
        records, client, backend=name,
        path=f"{p2}/traffic-flows", sanitizer=sanitizer,
    )
    return {"site_configured": True}


def collect(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("preset") != "network-api-migration":
        raise base.CensusError(
            "migration collector requires preset='network-api-migration'"
        )
    raw_controller = plan.get("controller")
    if not isinstance(raw_controller, Mapping):
        raise base.CensusError("plan.controller must be an object")
    controller = base._controller(raw_controller)
    raw_aliases = plan.get("aliases")
    if raw_aliases is not None and not isinstance(raw_aliases, Mapping):
        raise base.CensusError("plan.aliases must be an object")
    sanitizer = StrictSanitizer(
        raw_aliases if isinstance(raw_aliases, Mapping) else None
    )
    records: list[dict[str, Any]] = []
    secrets: list[str] = []
    metadata: dict[str, Any] = {}

    for key, fn in (("official", official), ("legacy", legacy)):
        cfg = plan.get(key)
        if not isinstance(cfg, Mapping):
            continue
        try:
            metadata[key] = fn(
                controller, cfg, sanitizer, secrets, records
            )
        except (
            OSError, urllib.error.URLError, TimeoutError, base.CensusError
        ) as exc:
            records.append({
                "backend": str(cfg.get("name") or key),
                "capability": "authentication_or_discovery",
                "path": f"<{key}-preset>",
                "error": sanitizer.text(f"{type(exc).__name__}: {exc}"[:400]),
            })

    if not metadata and not records:
        raise base.CensusError("plan requires official and/or legacy config")
    output = {
        "format": "monitorbox-unifi-census-v2",
        "controller": {
            "scheme": controller.origin[0],
            "verify_tls": controller.verify_tls,
        },
        "preset": "network-api-migration",
        "metadata": metadata,
        "records": records,
    }
    serialized = json.dumps(output, sort_keys=True, separators=(",", ":"))
    base._assert_no_secret_leak(serialized, secrets)
    return output


def report(data: Mapping[str, Any]) -> str:
    lines = [
        "# UniFi API census capability observations", "",
        "HTTP success is observation only; it does not establish parity or "
        "#170 topology authority.", "",
        "| Backend | Capability | Method | HTTP/result | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in data.get("records", []):
        if not isinstance(item, Mapping):
            continue
        result = (
            f"HTTP {item['status']}" if "status" in item
            else str(item.get("error") or "error").replace("|", "\\|")
        )
        lines.append(
            f"| {item.get('backend','')} | {item.get('capability','')} | "
            f"{item.get('method','')} | {result} | `{item.get('path','')}` |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text())
        if not isinstance(plan, Mapping):
            raise base.CensusError("plan root must be an object")
        data = collect(plan)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "census.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n"
        )
        (args.output_dir / "CAPABILITY-OBSERVATIONS.md").write_text(
            report(data)
        )
        print(f"wrote sanitized census to {args.output_dir}")
        return 0
    except (
        OSError, ValueError, TypeError, json.JSONDecodeError, base.CensusError
    ) as exc:
        print(f"census failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
