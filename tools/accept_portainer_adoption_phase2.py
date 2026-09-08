#!/usr/bin/env python3
"""Frozen-Core proof for Portainer Phase-2 direct backend adoption."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from monitorbox.v2.canonical_config import validate_document
from monitorbox.v2.config_compiler import compile_site_manifest

ROOT = Path(__file__).resolve().parent.parent
ADOPTION = ROOT / "sources" / "portainer" / "1.1.1-build7" / "adoption.py"


def _load_adoption():
    spec = importlib.util.spec_from_file_location("portainer_phase2_adoption", ADOPTION)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {ADOPTION}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _working_config() -> dict:
    return {
        "schema_version": 1,
        "metadata": {
            "installation_id": "phase2",
            "controller_epoch": "phase2-proof",
            "revision": 1,
        },
        "sites": [{
            "id": "broadleaf",
            "label": "Broad Leaf",
            "agents": [{"id": "monitor", "label": "Monitor"}],
            "objects": [{
                "id": "portainer",
                "label": "Portainer",
                "kind": "service",
                "capabilities": [{
                    "id": "inventory",
                    "kind": "docker_inventory",
                    "label": "Docker inventory",
                    "enabled": True,
                    "providers": [{
                        "id": "portainer",
                        "label": "Docker via Portainer",
                        "adapter": "portainer",
                        "agent_id": "monitor",
                        "check_id": "portainer_inventory",
                        "enabled": True,
                        "config": {
                            "base_url": "https://192.168.3.20:9443",
                            "api_key_env": "PORTAINER_API_KEY",
                            "verify_tls": False,
                            "operation": "inventory",
                        },
                    }],
                }],
            }],
        }],
    }


def _candidate(*, endpoints: list[dict]) -> SimpleNamespace:
    evidence = SimpleNamespace(
        source="portainer",
        source_id="compose:goliath:ombi:ombi",
        metadata={
            "environment_provider_id": 1,
            "environment_key": "goliath",
            "environment": "Broad Leaf - Goliath",
            "compose_project": "ombi",
            "backend_monitoring_endpoints": endpoints,
            "policy_hint": "required",
        },
    )
    suggested = ["docker_workload"]
    if len(endpoints) == 1:
        suggested.append("backend_transport")
    return SimpleNamespace(
        kind="service",
        candidate_id="portainer:compose:goliath:ombi:ombi",
        label="Ombi",
        addresses=(),
        mac=None,
        evidence=(evidence,),
        suggested_capabilities=tuple(suggested),
    )


def _single_endpoint() -> dict:
    return {
        "host": "192.168.3.20",
        "private_port": 3579,
        "public_port": 3579,
        "protocol": "tcp",
        "host_source": "environment_url",
        "endpoint_role": "backend_monitoring",
    }


def main() -> None:
    adoption_module = _load_adoption()
    adoption = adoption_module.PortainerCandidateAdoption()

    candidate = _candidate(endpoints=[_single_endpoint()])
    assert adoption.adoptable_capabilities(candidate) == (
        "docker_workload",
        "backend_transport",
    )

    object_id, working = adoption.adopt_candidate(
        _working_config(),
        site_id="broadleaf",
        candidate=candidate,
        label="Ombi",
        policy="required",
    )
    assert object_id == "ombi"

    document = validate_document(working)
    manifest = compile_site_manifest(document, "broadleaf")
    checks = [item for item in manifest["checks"] if item["object_id"] == object_id]
    assert {item["adapter"] for item in checks} == {"portainer", "tcp"}

    backend = next(item for item in checks if item["adapter"] == "tcp")
    assert backend["id"] == "ombi_backend_tcp"
    assert backend["agent"] == "monitor"
    assert backend["config"]["host"] == "192.168.3.20"
    assert backend["config"]["port"] == 3579
    assert backend["config"]["endpoint_role"] == "backend_monitoring"
    assert backend["config"]["source"] == "portainer_published_port"
    assert "url" not in backend["config"]
    assert "scheme" not in backend["config"]

    # Operator can retain workload monitoring while declining the extra probe.
    _, docker_only = adoption.adopt_candidate(
        _working_config(),
        site_id="broadleaf",
        candidate=candidate,
        label="Ombi",
        policy="required",
        capabilities=["docker_workload"],
    )
    docker_only_manifest = compile_site_manifest(validate_document(docker_only), "broadleaf")
    docker_only_checks = [
        item for item in docker_only_manifest["checks"]
        if item["object_id"] == "ombi"
    ]
    assert {item["adapter"] for item in docker_only_checks} == {"portainer"}

    # Multiple published ports are not auto-bound to an arbitrary health target.
    ambiguous = _candidate(endpoints=[
        _single_endpoint(),
        {
            "host": "192.168.3.20",
            "private_port": 8080,
            "public_port": 18080,
            "protocol": "tcp",
            "host_source": "environment_url",
            "endpoint_role": "backend_monitoring",
        },
    ])
    assert adoption.adoptable_capabilities(ambiguous) == ("docker_workload",)

    print(
        "Portainer frozen-Core adoption proof: PASS "
        "(one logical Service + independent LAN TCP backend + no TCP→HTTP guess + ambiguity fail-closed)"
    )


if __name__ == "__main__":
    main()
