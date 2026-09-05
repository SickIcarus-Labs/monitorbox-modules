#!/usr/bin/env python3
"""Regression acceptance for UniFi Network 1.0.3 build 4 auth backoff."""

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

PACKAGE_NAME = "com.sickicarus.monitorbox.unifi-1.0.3-build4.zip"
IMPORT_PACKAGE = "monitorbox_unifi_b4"
BASE_URL = "https://unifi.example.test"
EXPECTED_429_SCHEDULE = (60.0, 120.0, 240.0, 300.0, 600.0, 1200.0, 1800.0, 1800.0)


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
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.3", 4):
        raise AssertionError("UniFi long-backoff release identity changed")

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

    # Provider Retry-After remains authoritative and four waiting consumers must
    # still collapse into one network login.
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

    _expire(limited, BASE_URL)
    limited.session.login_status = 200
    limited.session.retry_after = None
    recovered = await limited.execute(request, context)
    if recovered.state != "healthy":
        raise AssertionError(f"UniFi did not recover after rate-limit expiry: {recovered!r}")
    if limited.session.login_count != 2:
        raise AssertionError(f"recovery did not perform exactly one fresh login: {limited.session.login_count}")
    if BASE_URL in limited._auth_cooldown:
        raise AssertionError("successful UniFi login did not clear auth cooldown state")

    # 401/403 account denial remains bounded separately and still collapses
    # concurrent inventory fan-out.
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

    # Without Retry-After, repeated provider 429s must follow the conservative
    # 60s -> 120s -> 240s -> 5m -> 10m -> 20m -> 30m schedule, then remain
    # capped at 30 minutes. This is the physical Broad Leaf regression from #224.
    exponential = managed.UniFiRuntimeExecutor()
    exponential.session = FakeSession(login_status=429)
    for attempt, expected in enumerate(EXPECTED_429_SCHEDULE, start=1):
        result = await asyncio.gather(exponential._login(options), return_exceptions=True)
        if not isinstance(result[0], RuntimeError):
            raise AssertionError(f"429 attempt {attempt} unexpectedly succeeded: {result!r}")
        if exponential.session.login_count != attempt:
            raise AssertionError(
                f"429 attempt count drifted: expected {attempt}, got {exponential.session.login_count}"
            )
        remaining, reason = exponential._cooldown_remaining(BASE_URL) or (0.0, "")
        if remaining < expected - 1.0 or reason != "HTTP 429":
            raise AssertionError(
                f"429 backoff schedule mismatch at attempt {attempt}: "
                f"expected~={expected}, remaining={remaining}, reason={reason!r}"
            )
        if attempt != len(EXPECTED_429_SCHEDULE):
            _expire(exponential, BASE_URL)

    print(
        "Managed UniFi Network 1.0.3 build 4: Retry-After + single-flight auth + "
        "UNKNOWN truth + same-executor recovery + 60/120/240/300/600/1200/1800s 429 backoff: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
