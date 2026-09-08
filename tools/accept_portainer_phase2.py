#!/usr/bin/env python3
"""Phase-2 acceptance for Portainer environment, endpoint, and recovery truth."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sources" / "portainer" / "1.0.0-build3"
DELTA = ROOT / "sources" / "portainer" / "1.1.1-build7"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_endpoint_stub() -> None:
    for name in ("candidate", "candidate.integrations", "candidate.integrations.portainer"):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module

    lifecycle = types.ModuleType("candidate.integrations.portainer.lifecycle_truth")

    class Base:
        async def _inventory(self, options):
            del options
            return {
                "environments": [
                    {"provider_id": 1, "name": "Goliath"},
                    {"provider_id": 2, "name": "Turnberry"},
                ],
                "workloads": [
                    {
                        "identity": "compose:goliath:media:app",
                        "environment_provider_id": 1,
                        "environment_url": "tcp://192.168.3.20:9001",
                        "published_ports": [
                            {"private_port": 8080, "public_port": 18080, "protocol": "tcp"}
                        ],
                        "discovery_actionable": True,
                    },
                    {
                        "identity": "compose:turnberry:media:app",
                        "environment_provider_id": 2,
                        "environment_url": "tcp://192.168.30.20:9001",
                        "published_ports": [
                            {"private_port": 443, "public_port": 8443, "protocol": "tcp"}
                        ],
                        "discovery_actionable": True,
                    },
                    {
                        "identity": "compose:goliath:portainer:portainer",
                        "environment_provider_id": 1,
                        "environment_url": "unix:///var/run/docker.sock",
                        "published_ports": [],
                        "discovery_actionable": False,
                        "discovery_suppression_reason": "authenticated_portainer_controller",
                    },
                ],
            }

    lifecycle.PortainerLifecycleTruthRuntimeExecutor = Base
    sys.modules[lifecycle.__name__] = lifecycle


async def _accept_endpoint_provenance(endpoint_module) -> None:
    executor = endpoint_module.PortainerEndpointRuntimeExecutor()
    scoped = await executor._inventory(
        {"base_url": "https://192.168.3.5:9443", "environment_ids": [1]}
    )
    assert len(scoped["workloads"]) == 3, "raw inventory must retain ignored environments"
    by_id = {item["identity"]: item for item in scoped["workloads"]}
    goliath = by_id["compose:goliath:media:app"]
    turnberry = by_id["compose:turnberry:media:app"]
    controller = by_id["compose:goliath:portainer:portainer"]
    assert goliath["discovery_actionable"] is True
    assert goliath["environment_selected"] is True
    assert turnberry["discovery_actionable"] is False
    assert turnberry["environment_selected"] is False
    assert turnberry["discovery_suppression_reason"] == "environment_not_selected"
    assert controller["discovery_suppression_reason"] == "authenticated_portainer_controller"
    assert scoped["environments"][0]["discovery_selected"] is True
    assert scoped["environments"][1]["discovery_selected"] is False

    endpoint = goliath["backend_monitoring_endpoints"][0]
    assert endpoint["host"] == "192.168.3.20"
    assert endpoint["public_port"] == 18080
    assert endpoint["endpoint_role"] == "backend_monitoring"
    assert "url" not in endpoint and "scheme" not in endpoint

    unscoped = await executor._inventory({"base_url": "https://192.168.3.5:9443"})
    restored = next(
        item for item in unscoped["workloads"]
        if item["identity"] == "compose:turnberry:media:app"
    )
    assert restored["discovery_actionable"] is True
    assert restored["environment_selected"] is True


def _accept_suggestions(suggestions) -> None:
    endpoint = {
        "host": "192.168.3.20",
        "private_port": 8080,
        "public_port": 3579,
        "protocol": "tcp",
        "endpoint_role": "backend_monitoring",
    }
    workload = {
        "identity": "compose:goliath:ombi:ombi",
        "label": "ombi",
        "environment_key": "goliath",
        "environment_url": "tcp://192.168.3.20:9001",
        "deployment_kind": "compose",
        "compose_service": "ombi",
        "images": ["linuxserver/ombi:latest"],
        "discovery_actionable": True,
        "backend_monitoring_endpoints": [endpoint],
    }
    assert suggestions.connection_suggestions(workload) == (), (
        "TCP published-port evidence must not synthesize an HTTP(S) Connection"
    )
    evidence = suggestions.generic_workload_evidence([workload], authoritative=True)
    assert len(evidence) == 1
    assert evidence[0]["suggested_capabilities"] == [
        "docker_workload",
        "backend_transport",
    ]

    ambiguous = dict(workload)
    ambiguous["backend_monitoring_endpoints"] = [
        endpoint,
        {
            "host": "192.168.3.20",
            "private_port": 8081,
            "public_port": 18081,
            "protocol": "tcp",
            "endpoint_role": "backend_monitoring",
        },
    ]
    ambiguous_evidence = suggestions.generic_workload_evidence(
        [ambiguous], authoritative=True
    )
    assert ambiguous_evidence[0]["suggested_capabilities"] == ["docker_workload"]

    scrypted = dict(workload)
    scrypted["label"] = "scrypted"
    scrypted["compose_service"] = "scrypted"
    scrypted["images"] = ["koush/scrypted:latest"]
    result = suggestions.connection_suggestions(scrypted)
    assert len(result) == 1
    assert result[0]["adapter"] == "scrypted"
    assert result[0]["candidate_endpoint"] == "manual://scrypted"
    assert "http://" not in repr(result) and "https://" not in repr(result)

    ignored = dict(workload, discovery_actionable=False)
    assert suggestions.generic_workload_evidence([ignored], authoritative=True) == []


def _accept_recovery_contract() -> None:
    source = (BASE / "onboarding.py").read_text()
    required = {
        '"scheduler_jitter_seconds": 10',
        '"scheduler_failure_backoff_factor": 2',
        '"scheduler_failure_backoff_max_seconds": 300',
    }
    missing = sorted(item for item in required if item not in source)
    assert not missing, f"Portainer runtime intent lost generic recovery scheduling: {missing}"


def main() -> None:
    _install_endpoint_stub()
    endpoint_module = _load(
        "candidate.integrations.portainer.endpoint_provenance",
        DELTA / "endpoint_provenance.py",
    )
    suggestions = _load("portainer_phase2_suggestions", DELTA / "suggestions.py")
    asyncio.run(_accept_endpoint_provenance(endpoint_module))
    _accept_suggestions(suggestions)
    _accept_recovery_contract()
    print(
        "Portainer Phase-2 acceptance: PASS "
        "(raw inventory + environment disposition + LAN backend role + unambiguous backend ability + no TCP→HTTP guess + recovery intent)"
    )


if __name__ == "__main__":
    main()
