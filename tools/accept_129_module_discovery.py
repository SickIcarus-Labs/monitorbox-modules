#!/usr/bin/env python3
"""Cross-contract acceptance for generic Portainer -> Scrypted module suggestion evidence."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
PORTAINER_SOURCE = ROOT / "sources" / "portainer" / "1.2.0-build8" / "suggestions.py"
SCRYPTED_STAGER = ROOT / "tools" / "stage_129_scrypted.py"


def _values(facts: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = facts.get(key)
    if isinstance(raw, list):
        return tuple(str(item).casefold() for item in raw)
    if raw is None:
        return ()
    return (str(raw).casefold(),)


def _rule_matches(rule: Mapping[str, Any], facts: Mapping[str, Any]) -> bool:
    predicates = rule.get("all")
    if not isinstance(predicates, list) or not predicates:
        return False
    for predicate in predicates:
        if not isinstance(predicate, Mapping):
            return False
        fact = str(predicate.get("fact") or "")
        op = str(predicate.get("op") or "")
        expected = str(predicate.get("value") or "").casefold()
        values = _values(facts, fact)
        if op == "equals":
            matched = expected in values
        elif op == "contains":
            matched = any(expected in value for value in values)
        else:
            raise AssertionError(f"unexpected #129 match operator: {op!r}")
        if not matched:
            return False
    return True


def _outcome(declaration: Mapping[str, Any], facts: Mapping[str, Any]) -> str:
    matched = [
        str(rule.get("confidence") or "")
        for rule in declaration.get("matches", [])
        if isinstance(rule, Mapping) and _rule_matches(rule, facts)
    ]
    if "detected" in matched:
        return "detected"
    if "possible" in matched:
        return "possible"
    return "no_match"


def accept() -> None:
    portainer_text = PORTAINER_SOURCE.read_text(encoding="utf-8")
    if "scrypted" in portainer_text.casefold():
        raise AssertionError("Portainer build8 source contains downstream Scrypted product logic")

    portainer = runpy.run_path(str(PORTAINER_SOURCE))
    generic_workload_evidence = portainer["generic_workload_evidence"]
    connection_suggestions = portainer["connection_suggestions"]
    recursive_suggestions = portainer["recursive_suggestions"]

    workload = {
        "identity": "env-1:compose:scrypted",
        "label": "camera workload",
        "images": ["ghcr.io/koush/scrypted:latest"],
        "compose_service": "scrypted",
        "deployment_kind": "compose",
        "containers": [{"state": "running"}],
        "published_ports": [
            {"protocol": "tcp", "public_port": 10443, "private_port": 10443},
            {"protocol": "tcp", "public_port": 11080, "private_port": 11080},
        ],
    }
    evidence = generic_workload_evidence([workload], authoritative=True)
    if len(evidence) != 1:
        raise AssertionError(f"expected one generic workload evidence row, got {evidence!r}")
    row = evidence[0]
    facts = row.get("capability_facts")
    if not isinstance(facts, Mapping):
        raise AssertionError("Portainer build8 omitted generic capability_facts")
    if connection_suggestions(workload) != () or recursive_suggestions(row) != ():
        raise AssertionError("Portainer build8 retained product-specific recursive suggestion behavior")
    if "connection_suggestions" in row.get("metadata", {}):
        raise AssertionError("Portainer build8 leaked legacy connection suggestions into metadata")

    expected_facts = {
        "workload.image": ["ghcr.io/koush/scrypted:latest"],
        "workload.compose_service": "scrypted",
        "workload.deployment_kind": "compose",
        "workload.running": True,
        "network.port": [10443, 11080],
    }
    if dict(facts) != expected_facts:
        raise AssertionError(f"Portainer generic capability facts changed: {facts!r}")

    scrypted = runpy.run_path(str(SCRYPTED_STAGER))
    declaration = scrypted["CAPABILITY_DETECTION"]
    hints = declaration.get("discovery_hints", {})
    if hints.get("tcp_ports") != [10443, 11080]:
        raise AssertionError(f"Scrypted scan hints changed: {hints!r}")
    if _outcome(declaration, facts) != "detected":
        raise AssertionError("generic Portainer workload evidence no longer detects Scrypted candidate")
    if _outcome(declaration, {"network.port": [10443]}) != "possible":
        raise AssertionError("Scrypted port-only evidence must remain possible, not detected")
    if _outcome(declaration, {"network.port": [11080]}) != "possible":
        raise AssertionError("Scrypted HTTP port-only evidence must remain possible, not detected")
    if _outcome(declaration, {"network.port": [443]}) != "no_match":
        raise AssertionError("unrelated open port unexpectedly qualifies Scrypted")

    print("#129 generic Portainer -> signed Scrypted discovery acceptance: PASS", flush=True)


def main() -> None:
    accept()


if __name__ == "__main__":
    main()
