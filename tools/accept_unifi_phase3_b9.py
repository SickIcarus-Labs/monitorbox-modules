#!/usr/bin/env python3
"""Phase-3 acceptance for UniFi 1.0.8 build 9 derived-child recovery truth."""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
from pathlib import Path

from accept_http_behavior import install_core_contract_stubs
from accept_unifi_runtime import _install_unifi_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.8-build9.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b9"
SOURCE_CHECK_ID = "broadleaf_unifi_inventory"


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed UniFi build-9 package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_unifi_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.8", 9):
        raise AssertionError("UniFi Phase-3 candidate release identity changed")

    status = {"value": "disconnected"}
    executor = managed.UniFiRuntimeExecutor()

    async def fixture_get(options, path):
        del options
        if path.endswith("stat/device"):
            return {
                "data": [
                    {
                        "mac": "aa:bb:cc:dd:ee:ff",
                        "name": "Aggregation",
                        "state": 1,
                        "adopted": True,
                        "port_table": [],
                        "radio_table": [],
                        "radio_table_stats": [],
                    }
                ]
            }
        if path.endswith("stat/health"):
            return {"data": [{"subsystem": "wan", "status": "ok"}]}
        if path.endswith("rest/networkconf"):
            return {
                "data": [
                    {
                        "_id": "vpn-turnberry",
                        "name": "Turnberry",
                        "purpose": "site-vpn",
                        "enabled": True,
                        "remote_vpn_subnets": ["192.168.40.0/24"],
                    }
                ]
            }
        if path.endswith("/vpn/connections"):
            return {
                "connections": [
                    {"network_id": "vpn-turnberry", "status": status["value"]}
                ]
            }
        raise AssertionError(f"unexpected UniFi fixture path: {path}")

    executor._get = fixture_get
    request = plugin_api.RuntimeExecutionRequest(
        check_id=SOURCE_CHECK_ID,
        object_id="unifi_controller",
        adapter="unifi",
        timeout_seconds=2.0,
        options={
            "base_url": "https://unifi.example.test",
            "site": "default",
            "username_env": "UNIFI_USER",
            "password_env": "UNIFI_PASSWORD",
            "verify_tls": False,
            "vpn_expectations": [
                {
                    "object_id": "turnberry_vpn",
                    "name": "Turnberry",
                    "label": "Turnberry VPN",
                }
            ],
        },
    )

    with tempfile.TemporaryDirectory(prefix="monitorbox-unifi-phase3-") as temp:
        context = plugin_api.RuntimeExecutionContext(
            module_id=managed.MODULE_ID,
            package_root="/tmp/unifi-b9",
            state_root=temp,
        )

        failed = await executor.execute(request, context)
        failed_child = failed.metadata["vpn_components"][0]
        if failed_child["state"] != "failed":
            raise AssertionError(f"disconnected VPN fixture did not fail: {failed_child!r}")

        status["value"] = "connected"
        recovered = await executor.execute(request, context)
        recovered_child = recovered.metadata["vpn_components"][0]
        if recovered_child["state"] != "healthy":
            raise AssertionError(
                "fresh connected provider evidence did not replace the prior child failure: "
                f"{recovered_child!r}"
            )

    if recovered.metadata.get("source_check_id") != SOURCE_CHECK_ID:
        raise AssertionError("source virtual component lost runnable collection-check provenance")
    device = recovered.metadata["devices"][0]
    if device.get("source_check_id") != SOURCE_CHECK_ID:
        raise AssertionError("derived UniFi device lost runnable collection-check provenance")
    if recovered_child.get("metadata", {}).get("source_check_id") != SOURCE_CHECK_ID:
        raise AssertionError("derived UniFi VPN child lost runnable collection-check provenance")
    if recovered_child["id"] == SOURCE_CHECK_ID:
        raise AssertionError("fixture stopped exercising a genuinely derived child identity")

    print(
        "UniFi Phase-3 build-9 acceptance: PASS "
        "(fresh failure→healthy child projection + explicit runnable-check provenance)"
    )


if __name__ == "__main__":
    asyncio.run(accept())
