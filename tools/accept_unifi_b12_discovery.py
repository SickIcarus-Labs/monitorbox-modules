#!/usr/bin/env python3
"""Acceptance for UniFi 1.1.1 build12 (#358/#359)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_unifi_b12 as candidate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    files = candidate._package_files(ROOT)
    prefix = candidate.IMPORT_PACKAGE + "/"
    onboarding = files[prefix + "onboarding.py"].decode("utf-8")
    runtime = files[prefix + "runtime.py"].decode("utf-8")
    root = files[prefix + "__init__.py"].decode("utf-8")

    required = (
        "confidence=DiscoveryConfidence.POSSIBLE",
        'evidence="TCP/443 is open; UniFi identity requires credential validation"',
        "default_selected=False",
        '"presentation_object": "network"',
        '"verify_tls": False',
    )
    missing = [marker for marker in required if marker not in onboarding]
    assert not missing, missing

    # Preserve stronger positive identification when the public status endpoint
    # is available.
    assert "confidence=DiscoveryConfidence.DETECTED" in onboarding
    assert "UniFi Network status endpoint identified the controller" in onboarding

    assert f'MODULE_VERSION = "{candidate.MODULE_VERSION}"' in runtime
    assert f"MODULE_BUILD = {candidate.MODULE_BUILD}" in runtime
    entrypoint = f'entrypoints={{"integration": "{candidate.IMPORT_PACKAGE}:PLUGIN"}}'
    assert entrypoint in runtime
    assert entrypoint in root

    with tempfile.TemporaryDirectory() as raw:
        one = candidate.build(ROOT, Path(raw) / "one").read_bytes()
        two = candidate.build(ROOT, Path(raw) / "two").read_bytes()
        assert one == two

    print("UniFi 1.1.1 build12 bounded discovery/card contribution acceptance passed")


if __name__ == "__main__":
    main()
