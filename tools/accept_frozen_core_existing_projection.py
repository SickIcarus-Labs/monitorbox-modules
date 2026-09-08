#!/usr/bin/env python3
"""Prove #158 against frozen Core using Broad Leaf's migration-era authority shape.

Broad Leaf physical acceptance rejected Bootstrap build 3 because migrated SNMP
providers retain ``host`` but omit the provider-default port. Frozen Core's generic
existing-authority extractor therefore cannot form a socket and re-presents SNMP
as new intent. Bootstrap build 4 must recover only an unambiguous provider-blind
System + adapter + host -> observed socket match while preserving selected-System
scope and frozen Core behavior for complete authority.
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
    / "1.0.3-build4"
    / "monitorbox_configuration_bootstrap_b4.py"
)


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("phase2_bootstrap_b4", BOOTSTRAP_SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load Configuration/Bootstrap build 4 source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_capability(
    *,
    capability_id: str,
    label: str,
    adapter: str,
    config: dict,
) -> dict:
    return {
        "id": capability_id,
        "kind": f"{adapter}_connection",
        "label": label,
        "enabled": True,
        "providers": [{
            "id": f"{capability_id}_provider",
            "label": label,
            "adapter": adapter,
            "agent_id": "monitor",
            "check_id": capability_id,
            "enabled": True,
            "interval_seconds": 60,
            "timeout_seconds": 15,
            "config": dict(config),
        }],
    }


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
        "capabilities": [
            _provider_capability(
                capability_id=f"{object_id}_{adapter}",
                label=label,
                adapter=adapter,
                config=config,
            )
        ],
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
        address="192.168.3.13",
    )
    generated.add_system(
        system_id="turnberry",
        label="Turnberry",
        address="192.168.30.20",
    )
    config = generated.validated_config()
    objects = config["sites"][0]["objects"]
    systems = {
        str(item["id"]): item
        for item in objects
        if str(item.get("id") or "") in {"goliath", "turnberry"}
    }

    # Reproduce the real migration-era Broad Leaf shape: multiple managed SNMPv3
    # providers attached to Goliath carry host + secret references but no port.
    # Port 161 was historically a provider default, so frozen Core cannot derive
    # the canonical Connection socket from these rows.
    for suffix, label in (
        ("resources", "Goliath SNMP resources"),
        ("network", "Goliath SNMP network"),
        ("storage", "Goliath SNMP storage"),
    ):
        systems["goliath"].setdefault("capabilities", []).append(
            _provider_capability(
                capability_id=f"goliath_snmp_{suffix}",
                label=label,
                adapter="snmp",
                config={
                    "host": "192.168.3.13",
                    "version": "3",
                    "username_env": "GOLIATH_SNMPV3_USERNAME",
                    "auth_key_env": "GOLIATH_SNMPV3_AUTH_KEY",
                    "priv_key_env": "GOLIATH_SNMPV3_PRIV_KEY",
                },
            )
        )

    systems["turnberry"].setdefault("capabilities", []).append(
        _provider_capability(
            capability_id="turnberry_snmp",
            label="Turnberry SNMP",
            adapter="snmp",
            config={
                "host": "192.168.30.20",
                "version": "3",
                "username_env": "TURNBERRY_SNMPV3_USERNAME",
                "auth_key_env": "TURNBERRY_SNMPV3_AUTH_KEY",
                "priv_key_env": "TURNBERRY_SNMPV3_PRIV_KEY",
            },
        )
    )

    objects.extend([
        _provider_object(
            object_id="goliath_portainer",
            label="Goliath Portainer",
            owner="goliath",
            adapter="portainer",
            config={
                "base_url": "https://192.168.3.13:9443",
                "api_key_env": "GOLIATH_PORTAINER_API_KEY",
                "verify_tls": False,
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


def _candidate(
    *,
    kind: str,
    endpoint: str,
    label: str,
    confidence: DetectionConfidence = DetectionConfidence.DETECTED,
) -> ConnectionCandidate:
    return ConnectionCandidate(
        system_id="goliath",
        kind=kind,
        label=label,
        confidence=confidence,
        endpoint=endpoint,
        evidence="bounded provider discovery",
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
    assert len(rows) == 2, rows
    by_kind = {str(row.get("kind")): row for row in rows}
    assert set(by_kind) == {"snmp", "portainer"}, rows

    snmp = by_kind["snmp"]
    assert snmp["system_id"] == "goliath"
    assert snmp["endpoint"] == "udp://192.168.3.13:161"
    assert snmp["confidence"] == "possible"
    assert snmp["already_configured"] is True
    assert snmp["configured_object_id"] == "goliath"
    assert "credential_reuse" in snmp

    portainer = by_kind["portainer"]
    assert portainer["system_id"] == "goliath"
    assert portainer["already_configured"] is True
    assert portainer["configured_object_id"] == "goliath_portainer"

    assert all(row.get("system_id") != "turnberry" for row in rows)


def main() -> None:
    module = _load_bootstrap()
    with tempfile.TemporaryDirectory(prefix="monitorbox-phase2-") as raw_root:
        root = Path(raw_root)
        api = ExistingAuthorityOnboardingApi(root, auth=ConfigAdminAuth(root))

        session = api.sessions.start_quick_add(_baseline())
        session.detection_system_ids = ["goliath"]
        session.connection_candidates = [
            _candidate(
                kind="snmp",
                endpoint="udp://192.168.3.13:161",
                label="SNMP",
                confidence=DetectionConfidence.POSSIBLE,
            ),
            _candidate(
                kind="portainer",
                endpoint="https://192.168.3.13:9443",
                label="Goliath Portainer",
            ),
        ]

        # Exact frozen-Core reproducer from physical Broad Leaf: complete
        # Portainer authority matches, migrated host-only SNMP does not, and the
        # compatibility projector also leaks unselected Turnberry Portainer.
        frozen_rows = [
            row for row in api._summary(session)["connections"] if isinstance(row, dict)
        ]
        frozen_goliath_snmp = [
            row
            for row in frozen_rows
            if row.get("system_id") == "goliath" and row.get("kind") == "snmp"
        ]
        assert len(frozen_goliath_snmp) == 1, frozen_rows
        assert frozen_goliath_snmp[0].get("already_configured") is False, frozen_rows
        assert any(row.get("system_id") == "turnberry" for row in frozen_rows), frozen_rows

        original_validate = api.connections.validate_and_stage
        original_resolve = api.connections.resolve_authenticated_discovery
        quick_add = SimpleNamespace(onboarding=api)
        module._wire_scoped_connection_projection(quick_add)
        assert api.connections.validate_and_stage is not original_validate
        assert api.connections.resolve_authenticated_discovery is not original_resolve

        scoped_rows = [
            row for row in api._summary(session)["connections"] if isinstance(row, dict)
        ]
        _assert_selected_goliath(scoped_rows)

        payload = asyncio.run(_exercise_response_projection(module, api, session))
        rows = [row for row in payload["session"]["connections"] if isinstance(row, dict)]
        _assert_selected_goliath(rows)
        assert "TURNBERRY" not in repr(payload)
        assert "GOLIATH_SNMPV3_AUTH_KEY" not in repr(payload)
        assert "GOLIATH_SNMPV3_PRIV_KEY" not in repr(payload)
        assert "GOLIATH_PORTAINER_API_KEY" not in repr(payload)

        # Fail closed: canonical adapter+host cannot choose between two observed
        # sockets. Neither SNMP candidate may be silently adopted.
        ambiguous = api.sessions.start_quick_add(_baseline())
        ambiguous.detection_system_ids = ["goliath"]
        ambiguous.connection_candidates = [
            _candidate(
                kind="snmp",
                endpoint="udp://192.168.3.13:161",
                label="SNMP standard socket",
                confidence=DetectionConfidence.POSSIBLE,
            ),
            _candidate(
                kind="snmp",
                endpoint="udp://192.168.3.13:1161",
                label="SNMP alternate socket",
                confidence=DetectionConfidence.POSSIBLE,
            ),
        ]
        ambiguous_rows = [
            row
            for row in api._summary(ambiguous)["connections"]
            if isinstance(row, dict)
            and row.get("system_id") == "goliath"
            and row.get("kind") == "snmp"
        ]
        assert len(ambiguous_rows) == 2, ambiguous_rows
        assert all(row.get("already_configured") is False for row in ambiguous_rows)

    print(
        "Frozen-Core + Bootstrap #158 proof: PASS "
        "(Broad Leaf host-only SNMP authority is uniquely reconciled; "
        "unselected authority excluded; ambiguous sockets fail closed)"
    )


if __name__ == "__main__":
    main()
