#!/usr/bin/env python3
"""Regression acceptance for UniFi Network 1.0.2 build 3 auth backoff."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import time
from pathlib import Path
from typing import Any

from accept_http_behavior import install_core_contract_stubs
from accept_unifi_runtime import _install_unifi_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.2-build3.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b3"
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
    def __init__(self, *, login_status: int, retry_after: str | None = None) -> None:
        self.login_status = login_status
        self.retry_after = retry_after
        self.login_count = 0
        self.get_count = 0
        self.valid_cookie = "TOKEN=fresh"

    def post(self, url: str, *, json=None, headers=None, ssl=None):
        del headers, ssl
        if url != BASE_URL + "/api/auth/login":
            raise AssertionError(f"unexpected POST {url}")
        self.login_count += 1
        if json != {
            "username": "monitorbox",
            "password": "acceptance-secret",
            "remember": False,
        }:
            return FakeResponse(403)
        if self.login_status != 200:
            headers = {"Retry-After": self.retry_after} if self.retry_after else {}
            return FakeResponse(self.login_status, headers=headers)
        return FakeResponse(
            200,
            headers={
                "Set-Cookie": self.valid_cookie + "; Path=/; HttpOnly",
                "X-Csrf-Token": "fresh-csrf",
            },
        )

    def get(self, url: str, *, headers=None, ssl=None):
        del ssl
        self.get_count += 1
        if (headers or {}).get("Cookie") != self.valid_cookie:
            return FakeResponse(403)
        if url.endswith("/stat/sta"):
            return FakeResponse(200, payload={"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]})
        raise AssertionError(f"unexpected GET {url}")


def _expire(executor, base: str) -> None:
    record = executor._auth_cooldown[base]
    executor._auth_cooldown[base] = (time.monotonic() - 1.0, record[1], record[2])


async def _fanout(executor, options: dict[str, Any], expected_login_count: int) -> None:
    results = await asyncio.gather(
        *(executor._login(options) for _ in range(4)),
        return_exceptions=True,
    )
    if not all(isinstance(item, RuntimeError) for item in results):
        raise AssertionError(f"concurrent denied logins did not all fail locally: {results!r}")
    if executor.session.login_count != expected_login_count:
        raise AssertionError(
            "concurrent login fan-out reached UniFi more than once: "
            f"expected {expected_login_count}, got {executor.session.login_count}"
        )


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed UniFi backoff package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_unifi_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)

    if managed.MODULE_ID != "com.sickicarus.monitorbox.unifi":
        raise AssertionError("UniFi durable module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.2", 3):
        raise AssertionError("UniFi auth-backoff release identity changed")

    os.environ["UNIFI_USER"] = "monitorbox"
    os.environ["UNIFI_PASSWORD"] = "acceptance-secret"
    options = {
        "base_url": BASE_URL,
        "site": "default",
        "username_env": "UNIFI_USER",
        "password_env": "UNIFI_PASSWORD",
        "verify_tls": False,
        "runtime_operation": "clients",
    }
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
        options=options,
    )

    # A provider 429 with Retry-After must collapse four waiting consumers into
    # one network login and hold subsequent checks locally during the cooldown.
    limited = managed.UniFiRuntimeExecutor()
    limited.session = FakeSession(login_status=429, retry_after="120")
    await _fanout(limited, options, 1)
    remaining, reason = limited._cooldown_remaining(BASE_URL) or (0.0, "")
    if remaining < 119.0 or reason != "HTTP 429":
        raise AssertionError(f"Retry-After was not honored: remaining={remaining}, reason={reason!r}")

    during_cooldown = await limited.execute(request, context)
    if during_cooldown.state != "unknown":
        raise AssertionError(f"rate-limited UniFi provider became target failure: {during_cooldown!r}")
    if limited.session.login_count != 1:
        raise AssertionError("monitoring cadence bypassed the provider cooldown")

    # Once the provider window expires, the same executor must be able to log in
    # and return healthy evidence without restart/reload/credential mutation.
    _expire(limited, BASE_URL)
    limited.session.login_status = 200
    recovered = await limited.execute(request, context)
    if recovered.state != "healthy":
        raise AssertionError(f"UniFi did not recover after rate-limit expiry: {recovered!r}")
    if limited.session.login_count != 2:
        raise AssertionError(f"recovery did not perform exactly one fresh login: {limited.session.login_count}")
    if BASE_URL in limited._auth_cooldown:
        raise AssertionError("successful UniFi login did not clear auth cooldown state")

    # 401/403 account denial must also collapse concurrent inventory fan-out so
    # disabling a service account cannot itself drive the controller into 429.
    denied = managed.UniFiRuntimeExecutor()
    denied.session = FakeSession(login_status=403)
    await _fanout(denied, options, 1)
    denied_remaining, denied_reason = denied._cooldown_remaining(BASE_URL) or (0.0, "")
    if denied_remaining < 29.0 or denied_reason != "HTTP 403":
        raise AssertionError(
            f"auth-denial cooldown was not established: {denied_remaining}, {denied_reason!r}"
        )
    _expire(denied, BASE_URL)
    denied.session.login_status = 200
    headers = await denied._login(options)
    if headers.get("Cookie") != denied.session.valid_cookie or denied.session.login_count != 2:
        raise AssertionError("same-executor recovery after auth-denial cooldown failed")

    # Without Retry-After, repeated 429s must back off exponentially rather than
    # retrying at monitoring cadence.
    exponential = managed.UniFiRuntimeExecutor()
    exponential.session = FakeSession(login_status=429)
    first = await asyncio.gather(exponential._login(options), return_exceptions=True)
    if not isinstance(first[0], RuntimeError) or exponential.session.login_count != 1:
        raise AssertionError("first 429 was not captured")
    first_remaining, _ = exponential._cooldown_remaining(BASE_URL) or (0.0, "")
    if first_remaining < 59.0:
        raise AssertionError(f"default first 429 cooldown too short: {first_remaining}")
    _expire(exponential, BASE_URL)
    second = await asyncio.gather(exponential._login(options), return_exceptions=True)
    if not isinstance(second[0], RuntimeError) or exponential.session.login_count != 2:
        raise AssertionError("second 429 was not captured")
    second_remaining, _ = exponential._cooldown_remaining(BASE_URL) or (0.0, "")
    if second_remaining < 119.0:
        raise AssertionError(f"429 backoff did not increase exponentially: {second_remaining}")

    print(
        "Managed UniFi Network 1.0.2 build 3: 429 Retry-After + concurrent login collapse + "
        "auth-denial cooldown + same-executor recovery + exponential fallback backoff: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
