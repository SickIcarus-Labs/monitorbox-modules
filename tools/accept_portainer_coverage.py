#!/usr/bin/env python3
"""Provider-local acceptance for Portainer v1.1.0 monitoring coverage evidence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sources" / "portainer" / "1.1.0-build6" / "suggestions.py"


def _load():
    spec = importlib.util.spec_from_file_location("portainer_coverage_candidate", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workload(identity: str, label: str, *, environment: str = "Goliath") -> dict:
    return {
        "identity": identity,
        "label": label,
        "environment": environment,
        "environment_key": environment.casefold(),
        "environment_provider_id": 42,
        "environment_url": f"tcp://{environment.casefold()}:2375",
        "deployment_kind": "compose",
        "compose_project": label,
        "compose_service": label,
        "required_hint": None,
        "containers": [],
        "images": [f"example/{label}:latest"],
        "published_ports": [],
    }


def main() -> None:
    suggestions = _load()
    rows = suggestions.generic_workload_evidence(
        [
            _workload("compose:goliath:qbittorrent:qbittorrent", "qbittorrent"),
            _workload("compose:goliath:radarr:radarr", "radarr"),
        ],
        authoritative=True,
    )
    assert len(rows) == 2
    for row in rows:
        assert row["source"] == "portainer"
        assert row["suggested_capabilities"] == ["docker_workload"]
        metadata = row["metadata"]
        assert metadata["authoritative"] is True
        coverage = metadata.get("monitoring_coverage")
        assert coverage == {
            "status": "covered",
            "kind": "provider_inventory",
            "source_label": "Portainer",
        }
        # The generic coverage contract must not expose provider-native routing
        # identity or imply canonical configuration/adoption.
        assert set(coverage) == {"status", "kind", "source_label"}
        assert "provider_id" not in coverage
        assert "environment_url" not in coverage
        assert "configured_object_id" not in coverage
        assert "canonical" not in coverage

    # Partial inventory authority does not erase the fact that each emitted row
    # was actually observed. The outer evidence keeps the full-inventory truth
    # separately so consumers can present degraded provider authority if useful.
    partial = suggestions.generic_workload_evidence(
        [_workload("compose:arrrrr2:plex:plex", "plex", environment="Arrrrr2")],
        authoritative=False,
    )
    assert partial[0]["metadata"]["authoritative"] is False
    assert partial[0]["metadata"]["monitoring_coverage"]["status"] == "covered"

    print(
        "Portainer v1.1.0 coverage acceptance: PASS "
        "(provider-backed coverage + canonical/adoption separation + bounded metadata)"
    )


if __name__ == "__main__":
    main()
