#!/usr/bin/env python3
"""Regression acceptance for UniFi Network 1.0.1 build 2 auth-loss recovery."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Any

from accept_http_behavior import install_core_contract_stubs
from accept_unifi_runtime import _install_unifi_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.1-build2.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b2"
BASE_URL = "https://unifi.example.test"


class FakeResponse:
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str] | None = None,
        payload: Any = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def read(self) -> bytes:
        return b""

    async def json(self, *, content_type=None) -> Any:
        del content_type
        return self._payload


class FakeSession:
    """Tiny UniFi HTTP fixture with revocable account and session cookies."""

    def __init__(self) -> None:
        self.account_enabled = True
        self.login_count = 0
        self.get_count = 0
        self.flow_count = 0
        self.valid_cookie = "TOKEN=fresh"

    def _authorized(self, headers: dict[str, str] | None) -> bool:
        return self.account_enabled and (headers or {}).get("Cookie") == self.valid_cookie

    def post(self, url: str, *, json=None, headers=None, ssl=None):
        del ssl
        if url == BASE_URL + "/api/auth/login":
            self.login_count += 1
            if not self.account_enabled:
                return FakeResponse(403)
            if json != {
                "username": "monitorbox",
                "password": "acceptance-secret",
                "remember": False,
            }:
                return FakeResponse(403)
            return FakeResponse(
                200,
                headers={
                    "Set-Cookie": self.valid_cookie + "; Path=/; HttpOnly",
                    "X-Csrf-Token": "fresh-csrf",
                },
            )

        if "/traffic-flows" in url:
            self.flow_count += 1
            if not self._authorized(headers):
                return FakeResponse(403)
            return FakeResponse(200, payload={"data": [{"id": "flow-1"}]})

        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, *, headers=None, ssl=None):
        del ssl
        self.get_count += 1
        if not self._authorized(headers):
            return FakeResponse(403)
        if url.endswith("/stat/sta"):
            return FakeResponse(200, payload={"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]})
        raise AssertionError(f"unexpected GET {url}")


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed UniFi patch package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_unifi_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)

    if managed.MODULE_ID != "com.sickicarus.monitorbox.unifi":
        raise AssertionError("UniFi durable module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.1", 2):
        raise AssertionError("UniFi auth-recovery release identity changed")
    if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("UniFi auth-recovery entrypoint is not generation-safe")

    os.environ["UNIFI_USER"] = "monitorbox"
    os.environ["UNIFI_PASSWORD"] = "acceptance-secret"

    context = plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root="/tmp/unifi-package",
        state_root="/tmp/unifi-state",
    )
    request = plugin_api.RuntimeExecutionRequest(
        check_id="unifi_clients",
        object_id="monitor",
        adapter="unifi",
        timeout_seconds=2.0,
        options={
            "base_url": BASE_URL,
            "site": "default",
            "username_env": "UNIFI_USER",
            "password_env": "UNIFI_PASSWORD",
            "verify_tls": False,
            "runtime_operation": "clients",
        },
    )

    executor = managed.UniFiRuntimeExecutor()
    session = FakeSession()
    executor.session = session

    # A stale cached session must be discarded and refreshed inside the same check.
    executor._auth[BASE_URL] = {
        "Cookie": "TOKEN=stale",
        "X-Csrf-Token": "stale-csrf",
    }
    recovered_stale = await executor.execute(request, context)
    if recovered_stale.state != "healthy":
        raise AssertionError(f"UniFi did not recover a stale session in-check: {recovered_stale!r}")
    if session.login_count != 1:
        raise AssertionError(f"stale session did not force exactly one fresh login: {session.login_count}")
    if executor._auth.get(BASE_URL, {}).get("Cookie") != session.valid_cookie:
        raise AssertionError("fresh UniFi auth was not cached after stale-session recovery")

    # Revoke the account while the executor retains the previously valid session.
    session.account_enabled = False
    lost = await executor.execute(request, context)
    if lost.state != "unknown":
        raise AssertionError(f"UniFi auth loss was promoted to target failure: {lost!r}")
    if lost.metadata.get("failure_kind") != "monitor_dependency":
        raise AssertionError(f"UniFi auth loss lacks dependency truth: {lost.metadata!r}")
    if lost.metadata.get("authoritative") is not False:
        raise AssertionError(f"UniFi auth loss remained authoritative: {lost.metadata!r}")
    if BASE_URL in executor._auth:
        raise AssertionError("rejected UniFi auth remained cached after provider loss")

    # Restore the same account. No executor restart, module reload, or credential change.
    session.account_enabled = True
    restored = await executor.execute(request, context)
    if restored.state != "healthy":
        raise AssertionError(f"UniFi did not recover after account restoration: {restored!r}")
    if BASE_URL not in executor._auth:
        raise AssertionError("UniFi recovery did not establish a fresh session")

    # Traffic-flow calls use the same rejected-session recovery contract.
    executor._auth[BASE_URL] = {
        "Cookie": "TOKEN=stale-again",
        "X-Csrf-Token": "stale-csrf",
    }
    flow_request = plugin_api.RuntimeExecutionRequest(
        check_id="unifi_flows",
        object_id="monitor",
        adapter="unifi",
        timeout_seconds=2.0,
        options={
            "base_url": BASE_URL,
            "site": "default",
            "username_env": "UNIFI_USER",
            "password_env": "UNIFI_PASSWORD",
            "verify_tls": False,
            "runtime_operation": "traffic_flows",
        },
    )
    flows = await executor.execute(flow_request, context)
    if flows.state != "healthy" or len(flows.metadata.get("flows", [])) != 1:
        raise AssertionError(f"UniFi traffic-flow stale-session recovery failed: {flows!r}")

    print(
        "Managed UniFi Network 1.0.1 build 2: stale auth refresh + auth-loss UNKNOWN + "
        "same-executor account restoration + traffic-flow recovery: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
