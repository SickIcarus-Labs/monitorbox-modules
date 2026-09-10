#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("unifi_api_census", ROOT / "unifi_api_census.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

sanitizer = module.Sanitizer({"Bonus Room": "fixture-edge", "Aggregation": "fixture-core"})
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

controller = module._controller({"base_url": "https://controller.example", "verify_tls": False})
client = module.BackendClient(controller)
assert client._url("/proxy/network/api/s/default/stat/device") == (
    "https://controller.example/proxy/network/api/s/default/stat/device"
)
for bad in ["https://evil.example/x", "//evil.example/x", "relative/path", "/x#fragment"]:
    try:
        client._url(bad)
    except module.CensusError:
        pass
    else:
        raise AssertionError(f"unsafe path accepted: {bad}")

try:
    client.request("/x", method="DELETE")
except module.CensusError:
    pass
else:
    raise AssertionError("mutating DELETE was accepted")

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
plan = {
    "controller": {"base_url": "https://controller.example"},
    "backends": [
        {
            "name": "official",
            "auth": {
                "mode": "api_key",
                "header": "X-API-Key",
                "env": "CENSUS_TEST_API_KEY",
            },
            "probes": [{"capability": "inventory", "path": "/integration/v1/example"}],
        }
    ],
}
secrets: list[str] = []
backend = module._client_for_backend(
    module._controller(plan["controller"]), plan["backends"][0], secrets
)
assert backend.headers["X-API-Key"] == os.environ["CENSUS_TEST_API_KEY"]
assert secrets == [os.environ["CENSUS_TEST_API_KEY"]]
sanitized_headers = sanitizer.sanitize(backend.headers)
assert sanitized_headers["X-API-Key"] == "<redacted>", sanitized_headers
assert os.environ["CENSUS_TEST_API_KEY"] not in json.dumps(sanitized_headers)

del os.environ["CENSUS_TEST_API_KEY"]
print("UniFi API census safety acceptance: PASS")
