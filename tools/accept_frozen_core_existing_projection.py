#!/usr/bin/env python3
"""Prove #158 existing-Connection projection on the accepted frozen Core runtime.

This script intentionally depends only on installed, provider-blind Core APIs.
The managed Configuration/Bootstrap module composes these primitives; it does
not need a release when the accepted Core transaction/summary seam already
satisfies the provider-neutral contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from monitorbox.v2.canonical_config import validate_document
from monitorbox.v2.config_auth import ConfigAdminAuth
from monitorbox.v2.onboarding_detection import ConnectionCandidate, DetectionConfidence
from monitorbox.v2.onboarding_existing_web import ExistingAuthorityOnboardingApi
from monitorbox.v2.onboarding_generator import GeneratedAuthority


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


def main() -> None:
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

        payload = api._summary(session)
        rows = [row for row in payload["connections"] if isinstance(row, dict)]
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
        assert "TURNBERRY" not in repr(payload)
        assert "GOLIATH_SNMP_COMMUNITY" not in repr(payload)
        assert "GOLIATH_PORTAINER_API_KEY" not in repr(payload)

        # Recursive re-projection must remain idempotent: configured authority is
        # neither dropped nor duplicated after another authenticated-discovery pass.
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
        "Frozen-Core #158 proof: PASS "
        "(selected Goliath SNMP + Portainer retained, already-configured dedupe preserved, unselected authority excluded)"
    )


if __name__ == "__main__":
    main()
