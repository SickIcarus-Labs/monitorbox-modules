#!/usr/bin/env python3
"""Acceptance for Configuration/Bootstrap 1.0.4 build 5 local access."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
PACKAGE = f"{MODULE_ID}-1.0.4-build5.zip"
HELPER = "monitorbox_configuration_bootstrap_local_access_b5"
EXPECTED_FILES = {
    "monitorbox_configuration_bootstrap_b4.py",
    "monitorbox_configuration_bootstrap_b5.py",
    f"{HELPER}.py",
}


def document(
    *,
    address: str | None = "192.168.3.5",
    listen_address: str = "0.0.0.0",
    port: object = 8080,
):
    objects = [] if address is None else [{"id": "monitor", "address": address}]
    return SimpleNamespace(
        data={
            "runtime": {
                "controller": {
                    "listen_address": listen_address,
                    "listen_port": port,
                    "self_object": {"site_id": "broadleaf", "object_id": "monitor"},
                }
            },
            "sites": [{"id": "broadleaf", "objects": objects}],
        }
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE
    if not package.is_file():
        raise AssertionError(f"build Bootstrap candidate first: {package}")
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        if names != EXPECTED_FILES:
            raise AssertionError(f"unexpected Bootstrap build-5 package shape: {sorted(names)}")
        for name in names:
            compile(archive.read(name), name, "exec")
        wrapper = archive.read("monitorbox_configuration_bootstrap_b5.py").decode("utf-8")
        if "monitorbox_configuration_bootstrap_b4" not in wrapper:
            raise AssertionError("build 5 must compose the accepted build-4 workflow")
        if "monitorbox_configuration_bootstrap_local_access_b5" not in wrapper:
            raise AssertionError("build 5 wrapper omitted its generation-safe local-access helper")

    sys.path.insert(0, str(package))
    try:
        helper = __import__(HELPER)
    finally:
        sys.path.pop(0)

    resolved = helper.local_access(document())
    assert resolved == {
        "available": True,
        "role": "local-control-plane",
        "scheme": "http",
        "host": "192.168.3.5",
        "port": 8080,
        "local_url": "http://192.168.3.5:8080",
        "source": "canonical-self-object",
    }, resolved

    # A container wildcard is never presented as an operator address.
    unavailable = helper.local_access(document(address=None, listen_address="0.0.0.0"))
    assert unavailable["available"] is False, unavailable
    assert "local_url" not in unavailable, unavailable

    # Explicit non-wildcard controller binds remain a bounded fallback.
    listener = helper.local_access(
        document(address=None, listen_address="192.168.50.10", port="8081")
    )
    assert listener["local_url"] == "http://192.168.50.10:8081", listener
    assert listener["source"] == "canonical-controller-listener", listener

    # Loopback, CIDRs and invalid ports fail closed rather than manufacturing a URL.
    assert helper.local_access(document(address="127.0.0.1"))["available"] is False
    assert helper.local_access(document(address="192.168.3.0/24"))["available"] is False
    assert helper.local_access(document(port=0))["available"] is False

    ipv6 = helper.local_access(document(address="2001:db8::5"))
    assert ipv6["local_url"] == "http://[2001:db8::5]:8080", ipv6

    class Store:
        def load(self):
            return document()

    ui = helper.LocalAccessUi(SimpleNamespace(store=Store()))
    response = __import__("asyncio").run(ui.get(None))
    payload = json.loads(response.text)
    assert payload["local_url"] == "http://192.168.3.5:8080", payload
    assert response.status == 200

    print(
        "Configuration/Bootstrap Phase-3 build-5 acceptance: PASS "
        "(canonical self-object authority + wildcard fail-closed + route projection)"
    )


if __name__ == "__main__":
    main()
