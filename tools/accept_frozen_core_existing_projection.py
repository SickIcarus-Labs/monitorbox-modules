#!/usr/bin/env python3
"""Prove #158 recursive Quick Add projection on accepted frozen Core + Bootstrap.

Frozen Core owns canonical existing-Connection identity/reconciliation. Its
compatibility runtime also broadens Quick Add presentation to every configured
Connection in the Site. Configuration/Bootstrap 1.0.2 build 3 must preserve the
canonical projection while restoring the carried-forward selected-System scope
contract and routing legacy recursive response paths through that scoped owner
summary.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from monitorbox.v2.canonical_config import validate_document
from monitorbox.v2.config_auth import ConfigAdminAuth
from monitorbox.v2.onboarding_detection import ConnectionCandidate, DetectionConfidence
from monitorbox.v2.onboarding_existing_web import ExistingAuthorityOnboardingApi
from monitorbox.v2.onboarding_generator import GeneratedAuthority

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_SOURCE = (
    ROOT
    / "sources"
    / "configuration-bootstrap"
    / "1.0.2-build3"
    / "monitorbox_configuration_bootstrap_b3.py"
)


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("phase2_bootstrap_b3", BOOTSTRAP_SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load Configuration/Bootstrap build 3 source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_object(
    *,
    object_id: str,
    label: str,
    owner: str,
    adapter: str,
    config: dict,
) -> dict:
    return {
        "id": object_id,
        "label": label,
        "kind": "integration",
        "depends_on": [owner],
        "capabilities": [{
            "id": f"{adapter}_connection",
            "kind": f"{adapter}_connection",
            "label": f"{label} connection",
            "enabled": True,
            "providers": [{
                "id": adapter,
                "label": label,
                "adapter": adapter,
                "agent_id": "monitor",
                "check_id": f"{object_id}_check",
                "enabled": True,
                "interval_seconds": 60,
                "timeout_seconds": 15,
                "config": dict(config),
            }],
        }],
    }


def _baseline() -> dict:
    generated = GeneratedAuthority.fresh(
        site_label="Broad Leaf proof",
        local_address="192.168.3.5",
        token_factory=lambda: "agent-token",
        epoch_factory=lambda: "phase2-existing-projection",
    )
    generated.add_system(
        system_id="goliath",
        label="Goliath",
        address="192.168.3.20",
    )
    generated.add_system(
        system_id="turnberry",
        label="Turnberry",
        address="192.168.30.20",
    )
    config = generated.validated_config()
    objects = config["sites"][0]["objects"]
    objects.extend([
        _provider_object(
            object_id="goliath_snmp",
            label="Goliath SNMP",
            owner="goliath",
            adapter="snmp",
            config={
                "host": "192.168.3.20",
                "port": 161,
                "community_env": "GOLIATH_SNMP_COMMUNITY",
            },
        ),
        _provider_object(
            object_id="goliath_portainer",
            label="Goliath Portainer",
            owner="goliath",
            adapter="portainer",
            config={
                "base_url": "https://192.168.3.20:9443",
                "api_key_env": "GOLIATH_PORTAINER_API_KEY",
                "verify_tls": False,
            },
        ),
        _provider_object(
            object_id="turnberry_snmp",
            label="Turnberry SNMP",
            owner="turnberry",
            adapter="snmp",
            config={
                "host": "192.168.30.20",
                "port": 161,
                "community_env": "TURNBERRY_SNMP_COMMUNITY",
            },
        ),
        _provider_object(
            object_id="turnberry_portainer",
            label="Turnberry Portainer",
            owner="turnberry",
            adapter="portainer",
            config={
                "base_url": "https://192.168.30.20:9443",
                "api_key_env": "TURNBERRY_PORTAINER_API_KEY",
                "verify_tls": False,
            },
        ),
    ])
    return validate_document(config).data


def _candidate(*, kind: str, endpoint: str, label: str) -> ConnectionCandidate:
    return ConnectionCandidate(
        system_id="goliath",
        kind=kind,
        label=label,
        confidence=DetectionConfidence.DETECTED,
        endpoint=endpoint,
        evidence="authenticated recursive discovery",
        default_selected=True,
        values={},
    )


async def _exercise_response_projection(module, api, session) -> dict:
    raw_summary = session.summary()
    assert all("already_configured" not in row for row in raw_summary["connections"])

    async def frozen_core_response(_request) -> web.Response:
        return web.json_response(
            {
                "authenticated_discovery_resolution": {"accepted": []},
                "session": raw_summary,
            },
            headers={"Cache-Control": "no-store"},
        )

    wrapped = module._project_connection_response(api, frozen_core_response)
    request = SimpleNamespace(match_info={"session_id": session.id})
    response = await wrapped(request)
    assert response.status == 200
    assert response.headers.get("Cache-Control") == "no-store"
    return json.loads(response.text)


def _assert_selected_goliath(rows: list[dict]) -> None:
    configured = [row for row in rows if row.get("already_configured") is True]
    assert len(rows) == 2, rows
    assert {
        (row["system_id"], row["kind"], row["configured_object_id"])
        for row in configured
    } == {
        ("goliath", "snmp", "goliath_snmp"),
        ("goliath", "portainer", "goliath_portainer"),
    }
    assert all(row.get("system_label") == "Goliath" for row in configured)
    assert all(row.get("already_configured") is True for row in rows)
    assert all(row.get("system_id") != "turnberry" for row in rows)


def main() -> None:
    module = _load_bootstrap()
    with tempfile.TemporaryDirectory(prefix="monitorbox-phase2-") as raw_root:
        root = Path(raw_root)
        api = ExistingAuthorityOnboardingApi(root, auth=ConfigAdminAuth(root))

        # Deliberately do not write canonical.json. The validated Quick Add
        # transaction baseline must remain authoritative throughout recursion.
        session = api.sessions.start_quick_add(_baseline())
        session.detection_system_ids = ["goliath"]
        session.connection_candidates = [
            _candidate(
                kind="snmp",
                endpoint="192.168.3.20:161",
                label="Detected Goliath SNMP",
            ),
            _candidate(
                kind="portainer",
                endpoint="https://192.168.3.20:9443",
                label="Detected Goliath Portainer",
            ),
        ]

        # Reproduce accepted frozen Core before installing Bootstrap build 3:
        # canonical Goliath reconciliation is correct, but the compatibility
        # projector broadens presentation back to unselected Turnberry.
        frozen_rows = [
            row for row in api._summary(session)["connections"] if isinstance(row, dict)
        ]
        assert {row.get("system_id") for row in frozen_rows} == {"goliath", "turnberry"}

        original_validate = api.connections.validate_and_stage
        original_resolve = api.connections.resolve_authenticated_discovery
        quick_add = SimpleNamespace(onboarding=api)
        module._wire_scoped_connection_projection(quick_add)
        assert api.connections.validate_and_stage is not original_validate
        assert api.connections.resolve_authenticated_discovery is not original_resolve

        # All owning Bootstrap summaries now retain Core's existing-authority
        # reconciliation while enforcing the selected-System workflow scope.
        scoped_rows = [
            row for row in api._summary(session)["connections"] if isinstance(row, dict)
        ]
        _assert_selected_goliath(scoped_rows)

        # The two frozen-Core legacy response paths must also escape through the
        # now-scoped owner summary during recursive authenticated discovery.
        payload = asyncio.run(_exercise_response_projection(module, api, session))
        rows = [row for row in payload["session"]["connections"] if isinstance(row, dict)]
        _assert_selected_goliath(rows)
        assert "TURNBERRY" not in repr(payload)
        assert "GOLIATH_SNMP_COMMUNITY" not in repr(payload)
        assert "GOLIATH_PORTAINER_API_KEY" not in repr(payload)

        again = api._summary(session)
        again_rows = [row for row in again["connections"] if isinstance(row, dict)]
        assert [
            (row["system_id"], row["kind"], row.get("configured_object_id"))
            for row in again_rows
        ] == [
            (row["system_id"], row["kind"], row.get("configured_object_id"))
            for row in rows
        ]

    print(
        "Frozen-Core + Bootstrap #158 proof: PASS "
        "(recursive responses retain selected Goliath SNMP + Portainer authority; unselected authority excluded)"
    )


if __name__ == "__main__":
    main()
