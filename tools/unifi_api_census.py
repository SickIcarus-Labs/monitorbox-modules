#!/usr/bin/env python3
"""Bounded, read-only UniFi API census collector for #170/#228.

The migration authority lives in monitorbox/docs/UNIFI-API-MIGRATION.md.
This tool deliberately does not encode a provider migration. It records
controller-local API evidence so migration/topology decisions can be made from
the actual Broad Leaf controller rather than assumptions.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
SENSITIVE_KEY_PARTS = (
    "authorization", "cookie", "password", "passwd", "secret", "apikey",
    "csrf", "token", "privatekey",
)
NAME_KEYS = {"name", "hostname", "host_name", "display_name", "device_name", "site_name", "ssid"}
SERIAL_KEYS = {"serial", "serial_number"}
IP_KEY_RE = re.compile(r"(^|_)(ip|ipv4|ipv6|ip_address|ipaddr)($|_)")


class CensusError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _sensitive_key(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(part in compact for part in SENSITIVE_KEY_PARTS)


@dataclass(frozen=True)
class Controller:
    base_url: str
    verify_tls: bool
    timeout_seconds: float
    max_bytes: int

    @property
    def origin(self) -> tuple[str, str, int | None]:
        parsed = urllib.parse.urlsplit(self.base_url)
        return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port


@dataclass(frozen=True)
class LeakGuardValue:
    """Protected material checked before sanitized census output is written.

    High-value secrets use substring matching so they cannot survive embedded in
    another serialized string. Low-entropy identifiers such as usernames use
    exact-only matching to avoid false positives against harmless schema/static
    text while still refusing an actual raw identifier value or object key.
    """

    value: str
    exact_only: bool = False


class Sanitizer:
    def __init__(self, aliases: Mapping[str, str] | None = None) -> None:
        self._aliases = {str(k): str(v) for k, v in dict(aliases or {}).items() if str(k)}

    @staticmethod
    def _digest(kind: str, value: str) -> str:
        return hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()[:12]

    def _scalar(self, key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if value in self._aliases:
            return f"<alias:{self._aliases[value]}>"
        folded = key.casefold()
        if _sensitive_key(folded):
            return "<redacted>"
        if "mac" in folded:
            return f"<mac:{self._digest('mac', value.casefold())}>"
        if IP_KEY_RE.search(folded):
            return f"<ip:{self._digest('ip', value.casefold())}>"
        if folded in SERIAL_KEYS:
            return f"<serial:{self._digest('serial', value)}>"
        if folded == "id" or folded.endswith("_id") or folded.endswith("-id"):
            return f"<id:{self._digest('id', value)}>"
        if folded in NAME_KEYS:
            return f"<name:{self._digest('name', value)}>"
        return value

    def sanitize(self, value: Any, *, key: str = "") -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                item_key = str(raw_key)
                if _sensitive_key(item_key):
                    result[item_key] = "<redacted>"
                else:
                    result[item_key] = self.sanitize(raw_value, key=item_key)
            return result
        if isinstance(value, list):
            return [self.sanitize(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self.sanitize(item, key=key) for item in value]
        return self._scalar(key, value)


class BackendClient:
    def __init__(self, controller: Controller, headers: Mapping[str, str] | None = None) -> None:
        self.controller = controller
        self.headers = dict(headers or {})
        cookie_jar = http.cookiejar.CookieJar()
        handlers: list[Any] = [_NoRedirect(), urllib.request.HTTPCookieProcessor(cookie_jar)]
        if controller.origin[0] == "https":
            context = ssl.create_default_context()
            if not controller.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self.opener = urllib.request.build_opener(*handlers)

    def _url(self, path: str) -> str:
        if not isinstance(path, str) or not path.startswith("/"):
            raise CensusError(f"probe path must be absolute-path only: {path!r}")
        parsed_path = urllib.parse.urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc or parsed_path.fragment:
            raise CensusError(f"probe path may not contain scheme/origin/fragment: {path!r}")
        base = self.controller.base_url.rstrip("/") + "/"
        url = urllib.parse.urljoin(base, path.lstrip("/"))
        parsed = urllib.parse.urlsplit(url)
        origin = parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port
        if origin != self.controller.origin:
            raise CensusError(f"cross-origin request refused: {url!r}")
        return url

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise CensusError(f"HTTP method refused: {method}")
        if method == "POST" and (path != "/api/auth/login" or body is None):
            raise CensusError("POST is restricted to the explicit /api/auth/login legacy handshake")
        if method == "GET" and body is not None:
            raise CensusError("GET request body refused")
        request_headers = {**self.headers, **dict(headers or {})}
        req = urllib.request.Request(
            self._url(path), data=body, headers=request_headers, method=method
        )
        started = time.monotonic()
        try:
            response = self.opener.open(req, timeout=self.controller.timeout_seconds)
        except urllib.error.HTTPError as exc:
            response = exc
        elapsed_ms = (time.monotonic() - started) * 1000.0
        with response:
            raw = response.read(self.controller.max_bytes + 1)
            truncated = len(raw) > self.controller.max_bytes
            if truncated:
                raw = raw[: self.controller.max_bytes]
            response_headers = dict(response.headers.items())
            return {
                "status": int(response.status),
                "elapsed_ms": round(elapsed_ms, 3),
                "content_type": response.headers.get("Content-Type", ""),
                "headers": response_headers,
                "body": raw,
                "truncated": truncated,
            }


def _controller(raw: Mapping[str, Any]) -> Controller:
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CensusError("controller.base_url must be an origin such as https://controller.example")
    timeout = float(raw.get("timeout_seconds", DEFAULT_TIMEOUT))
    max_bytes = int(raw.get("max_bytes", DEFAULT_MAX_BYTES))
    if timeout <= 0 or timeout > 120:
        raise CensusError("controller.timeout_seconds must be >0 and <=120")
    if max_bytes < 1024 or max_bytes > 32 * 1024 * 1024:
        raise CensusError("controller.max_bytes must be between 1 KiB and 32 MiB")
    return Controller(base_url, bool(raw.get("verify_tls", True)), timeout, max_bytes)


def _secret(
    env_name: str,
    collected: list[LeakGuardValue],
    *,
    exact_only: bool = False,
) -> str:
    name = str(env_name or "").strip()
    if not name:
        raise CensusError("credential environment variable name is required")
    try:
        value = os.environ[name]
    except KeyError as exc:
        raise CensusError(f"credential environment variable is missing: {name}") from exc
    if not value:
        raise CensusError(f"credential environment variable is empty: {name}")
    collected.append(LeakGuardValue(value=value, exact_only=exact_only))
    return value


def _client_for_backend(
    controller: Controller,
    backend: Mapping[str, Any],
    secrets: list[LeakGuardValue],
) -> BackendClient:
    auth = backend.get("auth")
    if not isinstance(auth, Mapping):
        raise CensusError("backend.auth must be an object")
    mode = str(auth.get("mode") or "").strip()
    if mode == "api_key":
        header = str(auth.get("header") or "").strip()
        if not header or "\n" in header or "\r" in header:
            raise CensusError("api_key auth requires a valid auth.header")
        key = _secret(str(auth.get("env") or ""), secrets)
        return BackendClient(controller, {header: key, "Accept": "application/json"})
    if mode == "username_password":
        username = _secret(
            str(auth.get("username_env") or ""), secrets, exact_only=True
        )
        password = _secret(str(auth.get("password_env") or ""), secrets)
        client = BackendClient(controller, {"Accept": "application/json"})
        login_path = str(auth.get("login_path") or "/api/auth/login")
        if login_path != "/api/auth/login":
            raise CensusError("legacy login POST is restricted to /api/auth/login")
        body = json.dumps(
            {"username": username, "password": password, "remember": False},
            separators=(",", ":"),
        ).encode()
        result = client.request(
            login_path,
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        if result["status"] != 200:
            raise CensusError(f"legacy authentication returned HTTP {result['status']}")
        csrf = result["headers"].get("X-Csrf-Token") or result["headers"].get("X-CSRF-Token")
        if csrf:
            secrets.append(LeakGuardValue(value=csrf))
            client.headers["X-Csrf-Token"] = csrf
        return client
    raise CensusError(f"unsupported auth mode: {mode!r}")


def _probe(
    client: BackendClient,
    probe: Mapping[str, Any],
    sanitizer: Sanitizer,
) -> dict[str, Any]:
    capability = str(probe.get("capability") or "").strip()
    path = str(probe.get("path") or "").strip()
    if not capability or not path:
        raise CensusError("each probe requires capability and path")
    result = client.request(path, method="GET")
    content_type = str(result["content_type"]).casefold()
    raw: bytes = result.pop("body")
    payload: Any = None
    parse_error: str | None = None
    if not result["truncated"] and (
        "json" in content_type or raw.lstrip()[:1] in {b"{", b"["}
    ):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    record = {
        "capability": capability,
        "path": path,
        "status": result["status"],
        "elapsed_ms": result["elapsed_ms"],
        "content_type": result["content_type"],
        "bytes_captured": len(raw),
        "truncated": bool(result["truncated"]),
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "response_headers": sanitizer.sanitize(result["headers"]),
        "json": sanitizer.sanitize(payload) if payload is not None else None,
    }
    if parse_error:
        record["parse_error"] = parse_error
    return record


def _serialized_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _serialized_string_values(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _serialized_string_values(nested)
        return
    if isinstance(value, str):
        yield value


def _assert_no_secret_leak(
    serialized: str,
    secrets: Iterable[LeakGuardValue | str],
) -> None:
    normalized = [
        item if isinstance(item, LeakGuardValue) else LeakGuardValue(value=item)
        for item in secrets
        if (item.value if isinstance(item, LeakGuardValue) else item)
    ]
    exact_values = {item.value for item in normalized if item.exact_only}
    if exact_values:
        try:
            parsed = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise CensusError(
                "cannot validate exact-only protected values in non-JSON census output"
            ) from exc
        for candidate in _serialized_string_values(parsed):
            if candidate in exact_values:
                raise CensusError(
                    "sanitized census contains a raw credential/session secret; refusing to write output"
                )

    for item in normalized:
        if not item.exact_only and item.value in serialized:
            raise CensusError(
                "sanitized census contains a raw credential/session secret; refusing to write output"
            )


def collect(plan: Mapping[str, Any]) -> dict[str, Any]:
    controller_raw = plan.get("controller")
    if not isinstance(controller_raw, Mapping):
        raise CensusError("plan.controller must be an object")
    controller = _controller(controller_raw)
    aliases = plan.get("aliases")
    if aliases is not None and not isinstance(aliases, Mapping):
        raise CensusError("plan.aliases must be an object when provided")
    sanitizer = Sanitizer(aliases if isinstance(aliases, Mapping) else None)
    backends = plan.get("backends")
    if not isinstance(backends, list) or not backends:
        raise CensusError("plan.backends must be a non-empty list")

    secrets: list[LeakGuardValue] = []
    records: list[dict[str, Any]] = []
    for backend in backends:
        if not isinstance(backend, Mapping):
            raise CensusError("each backend must be an object")
        name = str(backend.get("name") or "").strip()
        if not name:
            raise CensusError("each backend requires name")
        probes = backend.get("probes")
        if not isinstance(probes, list) or not probes:
            raise CensusError(f"backend {name!r} requires at least one probe")
        try:
            client = _client_for_backend(controller, backend, secrets)
        except (OSError, urllib.error.URLError, TimeoutError, CensusError) as exc:
            records.append(
                {
                    "backend": name,
                    "capability": "authentication",
                    "path": "<auth-handshake>",
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                }
            )
            continue
        for probe in probes:
            if not isinstance(probe, Mapping):
                raise CensusError("each probe must be an object")
            try:
                record = _probe(client, probe, sanitizer)
                record["backend"] = name
            except (OSError, urllib.error.URLError, TimeoutError, CensusError) as exc:
                record = {
                    "backend": name,
                    "capability": str(probe.get("capability") or ""),
                    "path": str(probe.get("path") or ""),
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                }
            records.append(record)

    output = {
        "format": "monitorbox-unifi-census-v1",
        "controller": {
            "scheme": controller.origin[0],
            "verify_tls": controller.verify_tls,
        },
        "records": records,
    }
    serialized = json.dumps(output, sort_keys=True, separators=(",", ":"))
    _assert_no_secret_leak(serialized, secrets)
    return output


def _report(data: Mapping[str, Any]) -> str:
    lines = [
        "# UniFi API census capability observations",
        "",
        "This report records observation status only. Capability parity and #170 topology authority require review of the sanitized payloads.",
        "",
        "| Backend | Capability | HTTP/result | Path |",
        "| --- | --- | --- | --- |",
    ]
    for item in data.get("records", []):
        if not isinstance(item, Mapping):
            continue
        result = (
            f"HTTP {item['status']}"
            if "status" in item
            else str(item.get("error") or "error").replace("|", "\\|")
        )
        lines.append(
            f"| {item.get('backend', '')} | {item.get('capability', '')} | {result} | `{item.get('path', '')}` |"
        )
    lines.extend(["", "No parity/topology conclusion is implied by HTTP success alone.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Ephemeral JSON census plan (must not contain secret values)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory that will receive sanitized artifacts",
    )
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text())
        if not isinstance(plan, Mapping):
            raise CensusError("plan root must be an object")
        data = collect(plan)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        (args.output_dir / "census.json").write_text(json_text)
        (args.output_dir / "CAPABILITY-OBSERVATIONS.md").write_text(_report(data))
        print(f"wrote sanitized census to {args.output_dir}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError, CensusError) as exc:
        print(f"census failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
