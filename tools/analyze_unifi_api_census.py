#!/usr/bin/env python3
"""Analyze a sanitized UniFi migration census for #170/#228.

Produces a deterministic capability matrix plus an evidence inventory. It never
promotes a capability to "authoritative topology" automatically; #170 authority
still requires review of the actual provider relationship represented by the
sanitized records.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

CAPABILITIES = (
    ("application_info", "Application/version"),
    ("api_schema", "Controller API schema"),
    ("sites", "Sites"),
    ("device_inventory", "Device inventory"),
    ("device_inventory_topology_ports", "Legacy device/topology/ports"),
    ("device_detail_topology_ports", "Official device detail/topology/ports"),
    ("device_statistics", "Device statistics"),
    ("client_inventory", "Connected clients"),
    ("network_detail", "Network detail"),
    ("network_detail_vpn_config", "Legacy network/VPN config"),
    ("wan_detail", "WAN detail"),
    ("health_wan", "Legacy health/WAN"),
    ("vpn_site_to_site", "Official site-to-site VPN"),
    ("vpn_connections", "Legacy VPN connections"),
    ("switch_stacks", "Switch stacks"),
    ("mc_lag_domains", "MC-LAG domains"),
    ("topology", "Legacy topology"),
    ("traffic_flows", "Legacy traffic flows"),
)

TOPOLOGY_TERMS = (
    "uplink", "downlink", "peer", "remote", "lldp", "neighbor", "neighbour",
    "topology", "stack", "lag", "aggregate", "aggregation", "trunk", "port",
    "connector",
)


def records_by_capability(data: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in data.get("records", []):
        if isinstance(item, Mapping):
            grouped[str(item.get("capability") or "")].append(item)
    return grouped


def record_success(item: Mapping[str, Any]) -> bool:
    return item.get("status") == 200 and item.get("json") is not None


def summarize_capability(items: Iterable[Mapping[str, Any]]) -> tuple[int, int, int]:
    rows = list(items)
    ok = sum(1 for item in rows if record_success(item))
    http = sum(1 for item in rows if "status" in item)
    errors = sum(1 for item in rows if "error" in item)
    return ok, http, errors


def walk_paths(value: Any, *, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value):
            child = value[key]
            child_path = f"{path}.{key}"
            yield child_path, child
            yield from walk_paths(child, path=child_path)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}[{idx}]"
            yield child_path, child
            yield from walk_paths(child, path=child_path)


def topology_evidence(data: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in data.get("records", []):
        if not isinstance(record, Mapping) or record.get("json") is None:
            continue
        backend = str(record.get("backend") or "")
        capability = str(record.get("capability") or "")
        request_path = str(record.get("path") or "")
        for json_path, value in walk_paths(record["json"]):
            key = json_path.rsplit(".", 1)[-1].casefold()
            if not any(term in key for term in TOPOLOGY_TERMS):
                continue
            value_type = type(value).__name__
            row = (backend, capability, request_path, f"{json_path} [{value_type}]")
            if row not in seen:
                seen.add(row)
                rows.append(row)
    return rows


def classify_official_legacy(
    grouped: Mapping[str, list[Mapping[str, Any]]],
    official_caps: Iterable[str],
    legacy_caps: Iterable[str],
) -> str:
    official_ok = any(
        record_success(item)
        for cap in official_caps
        for item in grouped.get(cap, [])
        if str(item.get("backend") or "").casefold() == "official"
    )
    legacy_ok = any(
        record_success(item)
        for cap in legacy_caps
        for item in grouped.get(cap, [])
        if str(item.get("backend") or "").casefold() == "legacy"
    )
    if official_ok and legacy_ok:
        return "both observed; semantic parity requires review"
    if official_ok:
        return "official observed; legacy equivalent not observed here"
    if legacy_ok:
        return "legacy-only in this census"
    return "not demonstrated"


PARITY_ROWS = (
    ("Application/version", ("application_info",), ("application_info",)),
    ("Device inventory", ("device_inventory",), ("device_inventory_topology_ports",)),
    ("Device statistics", ("device_statistics",), ("device_inventory_topology_ports",)),
    ("Connected clients", ("client_inventory",), ("client_inventory",)),
    ("Network/WAN", ("network_detail", "wan_detail"), ("network_detail_vpn_config", "health_wan")),
    ("VPN", ("vpn_site_to_site",), ("vpn_connections", "network_detail_vpn_config")),
    ("Switch/topology", ("device_detail_topology_ports", "switch_stacks", "mc_lag_domains"), ("device_inventory_topology_ports", "topology")),
    ("Traffic flows", (), ("traffic_flows",)),
)


def render(data: Mapping[str, Any]) -> str:
    grouped = records_by_capability(data)
    lines = [
        "# UniFi migration census analysis",
        "",
        "This is a deterministic evidence summary. It does **not** decide that any topology field is authoritative for #170.",
        "",
        "## Capability observations",
        "",
        "| Capability | Successful JSON observations | HTTP observations | Errors |",
        "| --- | ---: | ---: | ---: |",
    ]
    for cap, label in CAPABILITIES:
        ok, http, errors = summarize_capability(grouped.get(cap, []))
        lines.append(f"| {label} | {ok} | {http} | {errors} |")

    lines.extend([
        "",
        "## Provisional parity matrix",
        "",
        "| MonitorBox dependency | Census disposition |",
        "| --- | --- |",
    ])
    for label, official_caps, legacy_caps in PARITY_ROWS:
        lines.append(f"| {label} | {classify_official_legacy(grouped, official_caps, legacy_caps)} |")

    evidence = topology_evidence(data)
    lines.extend([
        "",
        "## Topology-related field inventory",
        "",
        "These are candidate evidence locations only. Field-name resemblance is **not** authority.",
        "",
        "| Backend | Capability | Request path | JSON path/type |",
        "| --- | --- | --- | --- |",
    ])
    if evidence:
        for backend, capability, request_path, json_path in evidence:
            request_path = request_path.replace("|", "\\|")
            json_path = json_path.replace("|", "\\|")
            lines.append(f"| {backend} | {capability} | `{request_path}` | `{json_path}` |")
    else:
        lines.append("| — | — | — | No topology-like fields observed |")

    lines.extend([
        "",
        "## #170 authority decision",
        "",
        "**UNRESOLVED — physical/provider-semantic review required.**",
        "",
        "Resolve only after proving that the sanitized provider relationship for the known fixture-edge Port 9 ↔ fixture-core link is explicit, stable, and distinguishable from adjacent ordinary access/unknown ports without names or port-number heuristics.",
        "",
        "Permitted dispositions:",
        "",
        "1. official API supplies authoritative equivalent;",
        "2. official API supplies authoritative but differently-shaped evidence;",
        "3. official API is insufficient and topology remains explicitly legacy-read/deferred while other #228 capabilities migrate.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("census", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    data = json.loads(args.census.read_text())
    if not isinstance(data, Mapping):
        raise SystemExit("census root must be an object")
    if data.get("format") != "monitorbox-unifi-census-v2":
        raise SystemExit("expected monitorbox-unifi-census-v2")
    text = render(data)
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
