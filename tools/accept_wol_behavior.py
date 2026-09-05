#!/usr/bin/env python3
"""Behavioral acceptance for managed Wake-on-LAN v1.0.0 build 1.

The immutable source blob is byte-identical to accepted MonitorBox Core 0547 and
remained unchanged through accepted Core 0556. This harness supplies only the
provider-blind Core interfaces needed to execute the managed artifact; it sends
no real network traffic.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

WOL_PACKAGE = "com.sickicarus.monitorbox.wol-1.0.0-build1.zip"


def install_core_contract_stubs() -> ModuleType:
    monitorbox = ModuleType("monitorbox")
    monitorbox.__path__ = []
    v2 = ModuleType("monitorbox.v2")
    v2.__path__ = []
    plugin_api = ModuleType("monitorbox.v2.plugin_api")
    plugin_api.__path__ = []
    action_execution = ModuleType("monitorbox.v2.plugin_api.action_execution")
    contracts = ModuleType("monitorbox.v2.plugin_api.contracts")
    module_runtime = ModuleType("monitorbox.v2.plugin_api.module_runtime")
    registry = ModuleType("monitorbox.v2.plugin_api.registry")

    @dataclass(frozen=True)
    class ActionExecutionRequest:
        action_id: str
        kind: str
        options: Mapping[str, Any]

    @dataclass(frozen=True)
    class ActionExecutionContext:
        site_id: str = "lab"

    @dataclass(frozen=True)
    class PluginMetadata:
        plugin_id: str
        display_name: str
        api_version: int = 1

    @dataclass(frozen=True)
    class ModuleManifest:
        module_id: str
        display_name: str
        version: str
        build: int
        module_type: str
        entrypoints: Mapping[str, str]
        requires_core: str
        requires_runtime_api: str
        state_schema: int
        publisher_id: str
        schema: int = 1
        dependencies: tuple[str, ...] = ()
        permissions: tuple[str, ...] = ()
        lifecycle_policy: str = "optional"

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: PluginMetadata
        action_kinds: tuple[str, ...] = ()
        action_executor: Any = None
        validate_action_options: Any = None
        resolve_action_command_timeout: Any = None

    action_execution.ActionExecutionRequest = ActionExecutionRequest
    action_execution.ActionExecutionContext = ActionExecutionContext
    contracts.PluginMetadata = PluginMetadata
    module_runtime.ModuleManifest = ModuleManifest
    registry.IntegrationDefinition = IntegrationDefinition

    sys.modules.update(
        {
            "monitorbox": monitorbox,
            "monitorbox.v2": v2,
            "monitorbox.v2.plugin_api": plugin_api,
            "monitorbox.v2.plugin_api.action_execution": action_execution,
            "monitorbox.v2.plugin_api.contracts": contracts,
            "monitorbox.v2.plugin_api.module_runtime": module_runtime,
            "monitorbox.v2.plugin_api.registry": registry,
        }
    )
    return action_execution


class FakeSocket:
    def __init__(self) -> None:
        self.broadcast_enabled = False
        self.blocking: bool | None = None
        self.closed = False

    def setsockopt(self, level: int, option: int, value: int) -> None:
        del level, option
        self.broadcast_enabled = value == 1

    def setblocking(self, value: bool) -> None:
        self.blocking = value

    def close(self) -> None:
        self.closed = True


class FakeLoop:
    def __init__(self) -> None:
        self.sent: list[tuple[FakeSocket, bytes, tuple[str, int]]] = []

    async def sock_sendto(
        self, sock: FakeSocket, payload: bytes, destination: tuple[str, int]
    ) -> None:
        self.sent.append((sock, payload, destination))

    def time(self) -> float:
        return 100.0


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / WOL_PACKAGE
    if not package.is_file():
        raise AssertionError(f"managed WOL package is missing: {package}")

    action_execution = install_core_contract_stubs()
    sys.path.insert(0, str(package))
    managed = importlib.import_module("monitorbox_wol_b1")

    if managed.MODULE_ID != "com.sickicarus.monitorbox.wol":
        raise AssertionError("managed WOL module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed WOL release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.entrypoints != {"integration": "monitorbox_wol_b1:PLUGIN"}:
        raise AssertionError("managed WOL manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed WOL Core compatibility changed")
    if managed.PLUGIN.metadata.plugin_id != "wol" or managed.PLUGIN.action_kinds != ("wol",):
        raise AssertionError("managed WOL plugin ownership/action kind changed")

    managed.PLUGIN.validate_action_options(
        {"mac_addresses": ["00:11:22:33:44:55"], "broadcast_address": "192.168.1.255"}
    )
    for invalid in (
        {},
        {"mac_addresses": []},
        {"mac_addresses": [123]},
        {"mac_addresses": ["00:11:22:33:44:55"], "broadcast_address": ""},
    ):
        try:
            managed.PLUGIN.validate_action_options(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"WOL validation accepted invalid options: {invalid!r}")

    timeout = managed.PLUGIN.resolve_action_command_timeout(
        {"timeout_seconds": 300}, 60
    )
    if timeout != 330.0:
        raise AssertionError(f"WOL command timeout derivation changed: {timeout}")
    if managed.PLUGIN.resolve_action_command_timeout({"timeout_seconds": 9999}, 60) != 1830.0:
        raise AssertionError("WOL command timeout upper bound changed")

    fake_loop = FakeLoop()
    sockets: list[FakeSocket] = []

    def fake_socket(*args: Any, **kwargs: Any) -> FakeSocket:
        del args, kwargs
        sock = FakeSocket()
        sockets.append(sock)
        return sock

    original_get_running_loop = managed.asyncio.get_running_loop
    original_socket = managed.socket.socket
    managed.asyncio.get_running_loop = lambda: fake_loop
    managed.socket.socket = fake_socket
    try:
        request = action_execution.ActionExecutionRequest(
            action_id="wake-lab-host",
            kind="wol",
            options={
                "mac_addresses": ["00:11:22:33:44:55"],
                "broadcast_address": "192.168.1.255",
                "port": 9,
            },
        )
        result = await managed.PLUGIN.action_executor.execute(
            request, action_execution.ActionExecutionContext()
        )
        if result != {
            "reachable": None,
            "packets_sent": 1,
            "batches_sent": 1,
            "broadcast_address": "192.168.1.255",
        }:
            raise AssertionError(f"WOL fire-and-forget result changed: {result!r}")
        if len(fake_loop.sent) != 1 or len(sockets) != 1:
            raise AssertionError("WOL emitted an unexpected number of magic packets")
        sock, payload, destination = fake_loop.sent[0]
        expected = bytes.fromhex("ff" * 6 + "001122334455" * 16)
        if payload != expected or destination != ("192.168.1.255", 9):
            raise AssertionError("WOL magic-packet bytes or destination changed")
        if not sock.broadcast_enabled or sock.blocking is not False or not sock.closed:
            raise AssertionError("WOL UDP socket safety/cleanup contract changed")

        bad_request = action_execution.ActionExecutionRequest(
            action_id="bad-mac",
            kind="wol",
            options={"mac_addresses": ["not-a-mac"]},
        )
        try:
            await managed.PLUGIN.action_executor.execute(
                bad_request, action_execution.ActionExecutionContext()
            )
        except ValueError as exc:
            if "invalid configured MAC address" not in str(exc):
                raise
        else:
            raise AssertionError("WOL execution accepted an invalid MAC address")
    finally:
        managed.asyncio.get_running_loop = original_get_running_loop
        managed.socket.socket = original_socket

    original_ping = managed._ping_once

    async def reachable(host: str, timeout_seconds: float = 2) -> dict[str, Any]:
        del timeout_seconds
        if host != "already-awake.example.test":
            raise AssertionError(f"unexpected WOL probe host {host!r}")
        return {"reachable": True, "latency_ms": 1.25, "error": None}

    managed._ping_once = reachable
    try:
        already_awake = action_execution.ActionExecutionRequest(
            action_id="already-awake",
            kind="wol",
            options={
                "mac_addresses": ["00:11:22:33:44:55"],
                "host": "already-awake.example.test",
            },
        )
        result = await managed.PLUGIN.action_executor.execute(
            already_awake, action_execution.ActionExecutionContext()
        )
        if result != {
            "host": "already-awake.example.test",
            "already_reachable": True,
            "reachable": True,
            "packets_sent": 0,
            "batches_sent": 0,
        }:
            raise AssertionError(f"WOL already-reachable short-circuit changed: {result!r}")
    finally:
        managed._ping_once = original_ping


def main() -> None:
    asyncio.run(accept())
    print("managed Wake-on-LAN behavioral acceptance: PASS")


if __name__ == "__main__":
    main()
