#!/usr/bin/env python3
"""Cross-contract acceptance for #59 bootstrap provider hints and ownership."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_first_party_http_b3 as http_builder
import build_first_party_nut_b3 as nut_builder
import build_first_party_portainer_b9 as portainer_builder
import build_first_party_scrypted_230 as scrypted_builder
import build_first_party_snmp_b9 as snmp_builder
import build_first_party_unifi_b11 as unifi_builder
import stage_59_bootstrap_providers as stager


def _values(facts: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = facts.get(key)
    if isinstance(raw, list):
        return tuple(str(item).casefold() for item in raw)
    if raw is None:
        return ()
    return (str(raw).casefold(),)


def _outcome(declaration: Mapping[str, Any], facts: Mapping[str, Any]) -> str:
    matches: list[str] = []
    for rule in declaration.get("matches", []):
        predicates = rule.get("all") if isinstance(rule, Mapping) else None
        if not isinstance(predicates, list) or not predicates:
            continue
        matched = True
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                matched = False
                break
            values = _values(facts, str(predicate.get("fact") or ""))
            expected = str(predicate.get("value") or "").casefold()
            op = str(predicate.get("op") or "")
            if op == "equals":
                ok = expected in values
            elif op == "contains":
                ok = any(expected in value for value in values)
            else:
                raise AssertionError(f"unexpected #59 match operator: {op!r}")
            if not ok:
                matched = False
                break
        if matched:
            matches.append(str(rule.get("confidence") or ""))
    if "detected" in matches:
        return "detected"
    if "possible" in matches:
        return "possible"
    return "no_match"


def _assert_tcp_detection(name: str, declaration: Mapping[str, Any], ports: list[int]) -> None:
    hints = declaration.get("discovery_hints", {})
    if hints.get("schema") != 1 or hints.get("tcp_ports") != ports:
        raise AssertionError(f"{name} scan hints changed: {hints!r}")
    for port in ports:
        if _outcome(declaration, {"network.port": [port]}) != "possible":
            raise AssertionError(f"{name} TCP/{port} must produce possible capability match")


def _assert_snmp_detection() -> None:
    declaration = stager.SNMP_DETECTION
    hints = declaration.get("discovery_hints", {})
    expected = {"schema": 2, "probes": [{"kind": "snmp_v3", "port": 161}]}
    if hints != expected:
        raise AssertionError(f"SNMP bounded probe hints changed: {hints!r}")
    if _outcome(declaration, {"probe.kind": ["snmp_v3"], "probe.result": ["responsive"]}) != "detected":
        raise AssertionError("valid SNMPv3 engine-discovery evidence must produce detected")
    if _outcome(declaration, {"network.port": [161]}) != "no_match":
        raise AssertionError("UDP/161 alone must not identify SNMP")


def accept() -> None:
    _assert_tcp_detection("Portainer", stager.PORTAINER_DETECTION, [9000, 9443])
    _assert_tcp_detection("NUT", stager.NUT_DETECTION, [3493])
    _assert_tcp_detection("Scrypted", stager.SCRYPTED_DETECTION, [10443, 11080])
    _assert_tcp_detection("UniFi", stager.UNIFI_DETECTION, [443])
    _assert_tcp_detection("HTTP", stager.HTTP_DETECTION, [80, 443, 8443, 9090])
    _assert_snmp_detection()

    tcp_plan = sorted({
        port
        for declaration in (
            stager.PORTAINER_DETECTION,
            stager.NUT_DETECTION,
            stager.SCRYPTED_DETECTION,
            stager.UNIFI_DETECTION,
            stager.HTTP_DETECTION,
        )
        for port in declaration["discovery_hints"]["tcp_ports"]
    })
    if tcp_plan != [80, 443, 3493, 8443, 9000, 9090, 9443, 10443, 11080]:
        raise AssertionError(f"#59 union/dedupe TCP scan plan changed: {tcp_plan!r}")

    probes = {(kind, port) for kind, port in [("tcp_connect", value) for value in tcp_plan]}
    probes.add(("snmp_v3", 161))
    if len(probes) != len(tcp_plan) + 1:
        raise AssertionError("#59 generalized scan plan did not deduplicate cleanly")

    portainer_source = portainer_builder._rewrite_source(
        "onboarding.py", portainer_builder._source_files(ROOT)["onboarding.py"]
    ).decode("utf-8")
    if 'connection_plugin_id="http"' in portainer_source:
        raise AssertionError("Portainer inconclusive discovery still delegates to HTTP")
    if 'plugin_id="portainer"' not in portainer_source or 'values={"base_url": endpoint}' not in portainer_source:
        raise AssertionError("Portainer possible discovery is not provider-owned/configurable")
    if "Portainer API status endpoint identified the service" not in portainer_source:
        raise AssertionError("Portainer positive identity probe was lost")

    nut_source = nut_builder._root_source(ROOT).decode("utf-8")
    if 'connection_plugin_id=' in nut_source:
        raise AssertionError("NUT discovery delegates candidate ownership")
    if "TCP/3493 is open but did not identify as NUT" not in nut_source:
        raise AssertionError("NUT provider-owned possible fallback was lost")
    if "NUT server identified itself as" not in nut_source:
        raise AssertionError("NUT positive protocol identity was lost")
    if "capability_detection=" not in nut_source or "Network UPS Tools (NUT)" not in nut_source:
        raise AssertionError("NUT successor metadata/description was not composed")

    scrypted_builder._configure()
    files = scrypted_builder.base._python_source_files(ROOT)
    scrypted_source = scrypted_builder.base._rewrite_source("onboarding.py", files["onboarding.py"]).decode("utf-8")
    if 'connection_plugin_id="http"' in scrypted_source:
        raise AssertionError("Scrypted inconclusive discovery still delegates to HTTP")
    if 'plugin_id="scrypted"' not in scrypted_source or 'values={"base_url": endpoint}' not in scrypted_source:
        raise AssertionError("Scrypted possible discovery is not provider-owned/configurable")
    if "authenticated camera inventory" not in scrypted_source:
        raise AssertionError("Scrypted authenticated validation boundary was lost")

    snmp_builder._configure(ROOT)
    snmp_root = snmp_builder.base._rewrite_source(
        "__init__.py", snmp_builder.base._source_files(ROOT)["__init__.py"]
    ).decode("utf-8")
    if "capability_detection=" not in snmp_root or "Monitors systems and appliances through SNMP." not in snmp_root:
        raise AssertionError("SNMP successor metadata/description was not composed")
    if 'requires_core=">=2.4.0 <3.0.0"' not in snmp_root:
        raise AssertionError("SNMP schema-2 successor did not require the supporting Core")

    unifi_root = unifi_builder._rewrite_source(
        ROOT, "__init__.py", unifi_builder.previous._source_files(ROOT)["__init__.py"]
    ).decode("utf-8")
    if "capability_detection=" not in unifi_root or "Monitors UniFi Network controller" not in unifi_root:
        raise AssertionError("UniFi successor metadata/description was not composed")
    unifi_onboarding = unifi_builder._rewrite_source(
        ROOT, "onboarding.py", unifi_builder.previous._source_files(ROOT)["onboarding.py"]
    ).decode("utf-8")
    if "/status" not in unifi_onboarding:
        raise AssertionError("UniFi installed-provider identity probe was lost")

    http_files = http_builder._package_files(ROOT)
    http_root = http_files[f"{http_builder.IMPORT_PACKAGE}/__init__.py"].decode("utf-8")
    if "capability_detection=" not in http_root or "Monitors HTTP(S) endpoints" not in http_root:
        raise AssertionError("HTTP successor metadata/description was not composed")

    print("#59 all six first-run providers + generalized bounded scan hints: PASS", flush=True)


if __name__ == "__main__":
    accept()
