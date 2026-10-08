"""Existing signed stable-pair CLI and privileged read-only CI boundary."""
import base64
import json
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives import serialization

import successor_existing_stable_readonly as cli
from successor_registry_extract import FULL_REPO, SUPERVISOR_REPO
from test_successor_registry_extract import registry_candidate
from test_successor_release_manifest import candidate


def _configure_fake(monkeypatch, registry_candidate, tmp_path):
    registry, manifest, fixture = registry_candidate
    stable = {
        FULL_REPO: manifest["images"]["full"]["digest"],
        SUPERVISOR_REPO: manifest["images"]["supervisor"]["digest"],
    }
    provider_calls = []
    def resolve(repository):
        provider_calls.append(repository)
        return stable[repository]
    registry.resolve_stable_digest = resolve
    monkeypatch.setattr(cli, "read_only_ghcr_client_from_environment", lambda: registry)
    pub = fixture["keys"]["official-ed25519-1"].public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trust = tmp_path / "public.pub"
    trust.write_text(base64.b64encode(pub).decode() + "\n")
    monkeypatch.setattr(sys, "argv", ["stable-readonly", "--trust-root", str(trust)])
    return registry, stable, provider_calls


def test_cli_reads_real_style_historical_pair_with_no_candidate_or_write(
    registry_candidate, tmp_path, monkeypatch, capsys,
):
    provider, stable, calls = _configure_fake(monkeypatch, registry_candidate, tmp_path)
    assert cli.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "historical-stable-validated-read-only"
    assert data["full_digest"] == stable[FULL_REPO]
    assert data["supervisor_digest"] == stable[SUPERVISOR_REPO]
    assert data["publication_authorized"] is False
    assert data["candidate_release_verified"] is False
    assert data["channel_changed"] is False
    assert data["source_ci_verified"] is False
    assert calls == [FULL_REPO, SUPERVISOR_REPO, FULL_REPO, SUPERVISOR_REPO]
    assert all(request[0] in ("GET_MANIFEST", "GET_BLOB") for request in provider.calls)


def test_cli_fails_closed_on_current_pointer_drift(
    registry_candidate, tmp_path, monkeypatch, capsys,
):
    provider, stable, calls = _configure_fake(monkeypatch, registry_candidate, tmp_path)
    def drifting(repo):
        calls.append(repo)
        return "sha256:" + "f" * 64 if len(calls) == 3 else stable[repo]
    provider.resolve_stable_digest = drifting
    assert cli.main() == 1
    output = capsys.readouterr()
    assert not output.out.strip()
    assert "stable pointers changed" in output.err


def test_live_workflow_is_trusted_main_and_packages_read_only():
    workflow = (Path(__file__).parent.parent /
                ".github/workflows/successor-live-stable-readonly.yml").read_text("utf-8")
    assert "branches: [main]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "packages: read" in workflow
    assert "contents: read" in workflow
    assert "packages: write" not in workflow
    assert "persist-credentials: false" in workflow
    assert "ref: main" in workflow
    assert "github.token" in workflow
    assert "secrets." not in workflow
    assert "docker buildx imagetools create" not in workflow
    assert "docker/login-action" not in workflow
    assert "docker/build-push-action" not in workflow


def test_stable_cli_has_no_signing_or_mutation_entry_point():
    code = (Path(__file__).parent / "successor_existing_stable_readonly.py").read_text("utf-8")
    for forbidden in ("docker push", "imagetools create", "subprocess",
                      "MONITORBOX_MODULE_SIGNING_KEY", "promote-stable"):
        assert forbidden not in code
    assert '"publication_authorized": False' in code
    assert '"channel_changed": False' in code
