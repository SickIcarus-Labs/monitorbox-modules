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

import build_first_party_nut_b3 as nut_builder
import build_first_party_portainer_b9 as portainer_builder
import build_first_party_scrypted_230 as scrypted_builder
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


def _assert_detection(name: str, declaration: Mapping[str, Any], ports: list[int]) -> None:
    hints = declaration.get("discovery_hints", {})
    if hints.get("schema") != 1 or hints.get("tcp_ports") != ports:
        raise AssertionError(f"{name} scan hints changed: {hints!r}")
    for port in ports:
        if _outcome(declaration, {"network.port": [port]}) != "possible":
            raise AssertionError(f"{name} TCP/{port} must produce possible capability match")
    if _outcome(declaration, {"network.port": [443]}) != "no_match":
        raise AssertionError(f"{name} unexpectedly matches unrelated TCP/443 evidence")


def accept() -> None:
    _assert_detection("Portainer", stager.PORTAINER_DETECTION, [9000, 9443])
    _assert_detection("NUT", stager.NUT_DETECTION, [3493])
    _assert_detection("Scrypted", stager.SCRYPTED_DETECTION, [10443, 11080])
    scan_plan = sorted({
        port
        for declaration in (stager.PORTAINER_DETECTION, stager.NUT_DETECTION, stager.SCRYPTED_DETECTION)
        for port in declaration["discovery_hints"]["tcp_ports"]
    })
    if scan_plan != [3493, 9000, 9443, 10443, 11080]:
        raise AssertionError(f"#59 union/dedupe scan plan changed: {scan_plan!r}")

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

    print("#59 signed hints + provider-owned bootstrap discovery acceptance: PASS", flush=True)


if __name__ == "__main__":
    accept()
