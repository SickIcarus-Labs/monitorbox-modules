#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import unifi_api_census as module
import unifi_api_census_migration as migration

# Base transport/sanitization contract.
sanitizer = module.Sanitizer(
    {"Bonus Room": "fixture-edge", "Aggregation": "fixture-core"}
)
payload = {
    "mac": "aa:bb:cc:dd:ee:ff",
    "uplink_mac": "aa:bb:cc:dd:ee:ff",
    "ip": "192.0.2.10",
    "name": "Bonus Room",
    "parent_name": "Aggregation",
    "site_id": "site-real-id",
    "port_idx": 9,
    "up": True,
    "speed": 10000,
    "api_key": "NEVER",
    "nested": {"password": "NOPE", "client_id": "client-real-id"},
}
out = sanitizer.sanitize(payload)
assert out["mac"] == out["uplink_mac"], out
assert out["name"] == "<alias:fixture-edge>", out
assert out["parent_name"] == "<alias:fixture-core>", out
assert out["site_id"].startswith("<id:"), out
assert out["port_idx"] == 9 and out["up"] is True and out["speed"] == 10000, out
assert out["api_key"] == "<redacted>" and out["nested"]["password"] == "<redacted>", out
assert "192.0.2.10" not in json.dumps(out), out

controller = module._controller(
    {"base_url": "https://controller.example", "verify_tls": False}
)
client = module.BackendClient(controller)
assert client._url("/proxy/network/api/s/default/stat/device") == (
    "https://controller.example/proxy/network/api/s/default/stat/device"
)
for bad in [
    "https://evil.example/x",
    "//evil.example/x",
    "relative/path",
    "/x#fragment",
]:
    try:
        client._url(bad)
    except module.CensusError:
        pass
    else:
        raise AssertionError(f"unsafe path accepted: {bad}")

for method in ("DELETE", "PUT", "PATCH"):
    try:
        client.request("/x", method=method)
    except module.CensusError:
        pass
    else:
        raise AssertionError(f"mutating {method} was accepted")

try:
    client.request("/x", method="POST", body=b"{}")
except module.CensusError:
    pass
else:
    raise AssertionError("arbitrary POST was accepted")

try:
    module._assert_no_secret_leak('{"safe":true}', ["topsecret"])
except module.CensusError:
    raise AssertionError("false-positive secret leak")
try:
    module._assert_no_secret_leak('{"value":"topsecret"}', ["topsecret"])
except module.CensusError:
    pass
else:
    raise AssertionError("raw secret leak was not blocked")

os.environ["CENSUS_TEST_API_KEY"] = "test-key-must-never-persist"
backend_cfg = {
    "name": "official",
    "auth": {
        "mode": "api_key",
        "header": "X-API-Key",
        "env": "CENSUS_TEST_API_KEY",
    },
    "probes": [{"capability": "inventory", "path": "/integration/v1/example"}],
}
secrets: list[str] = []
backend = module._client_for_backend(controller, backend_cfg, secrets)
assert backend.headers["X-API-Key"] == os.environ["CENSUS_TEST_API_KEY"]
assert secrets == [os.environ["CENSUS_TEST_API_KEY"]]
sanitized_headers = sanitizer.sanitize(backend.headers)
assert sanitized_headers["X-API-Key"] == "<redacted>", sanitized_headers
assert os.environ["CENSUS_TEST_API_KEY"] not in json.dumps(sanitized_headers)

# Migration-specific default-deny sanitization and path pseudonymization.
strict = migration.StrictSanitizer(
    {"Bonus Room": "fixture-edge", "Aggregation": "fixture-core"}
)
migration_payload = {
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "uplinkMac": "aa:bb:cc:dd:ee:ff",
    "ipAddress": "192.0.2.10",
    "name": "Bonus Room",
    "parentName": "Aggregation",
    "siteId": "123e4567-e89b-12d3-a456-426614174000",
    "applicationVersion": "10.5.67",
    "state": "ONLINE",
    "manufacturer": "private-string",
}
mout = strict.sanitize(migration_payload)
assert mout["macAddress"] == mout["uplinkMac"], mout
assert mout["name"] == "<alias:fixture-edge>", mout
assert mout["parentName"] == "<alias:fixture-core>", mout
assert mout["applicationVersion"] == "10.5.67", mout
assert mout["state"] == "ONLINE", mout
assert mout["manufacturer"].startswith("<str:"), mout
assert "192.0.2.10" not in json.dumps(mout), mout

dynamic_path = (
    "/integration/v1/sites/123e4567-e89b-12d3-a456-426614174000/"
    "devices/123e4567-e89b-12d3-a456-426614174001"
)
safe_path = strict.text(dynamic_path)
assert "123e4567-e89b-12d3-a456-426614174000" not in safe_path
assert "123e4567-e89b-12d3-a456-426614174001" not in safe_path
assert safe_path.count("<id:") == 2, safe_path

assert migration.path_id("site/unsafe") == "site%2Funsafe"
assert migration.items({"data": [{"id": "a"}]}) == [{"id": "a"}]
assert migration.items({"items": [{"id": "b"}]}) == [{"id": "b"}]
assert migration.items({"data": "wrong"}) == []


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def request(self, path, *, method="GET", body=None, headers=None):
        status, body_obj = self.responses.get(path, (404, {"code": "missing"}))
        raw = json.dumps(body_obj).encode()
        return {
            "status": status,
            "elapsed_ms": 1.0,
            "content_type": "application/json",
            "headers": {},
            "body": raw,
            "truncated": False,
        }


fake = FakeClient(
    {
        "/integration/v1/info": (401, {"code": "unauthorized"}),
        "/proxy/network/integration/v1/info": (
            200,
            {"applicationVersion": "10.5.67"},
        ),
        "/proxy/network/integration/v1/sites?limit=200": (
            200,
            {
                "data": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "name": "Broad Leaf",
                    }
                ]
            },
        ),
        "/proxy/network/integration/v1/sites/123e4567-e89b-12d3-a456-426614174000/devices?limit=200": (
            200,
            {
                "data": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174001",
                        "name": "Bonus Room",
                    }
                ]
            },
        ),
    }
)
original_factory = module._client_for_backend
try:
    module._client_for_backend = lambda controller, cfg, secrets: fake
    records: list[dict] = []
    metadata = migration.official(
        controller,
        {
            "name": "official",
            "auth": {"mode": "api_key", "env": "IGNORED"},
        },
        strict,
        [],
        records,
    )
finally:
    module._client_for_backend = original_factory

assert metadata["selected_prefix"] == "/proxy/network/integration", metadata
assert metadata["site_count"] == 1 and metadata["device_count"] == 1, metadata
records_text = json.dumps(records)
assert "123e4567-e89b-12d3-a456-426614174000" not in records_text
assert "123e4567-e89b-12d3-a456-426614174001" not in records_text
assert "<alias:fixture-edge>" in records_text

try:
    migration.traffic_probe(
        [],
        fake,
        backend="legacy",
        path="/proxy/network/v2/api/site/default/cmd/devmgr",
        sanitizer=strict,
    )
except module.CensusError:
    pass
else:
    raise AssertionError("migration traffic helper accepted a mutating path")

del os.environ["CENSUS_TEST_API_KEY"]
print("UniFi API census safety/coverage acceptance: PASS")
