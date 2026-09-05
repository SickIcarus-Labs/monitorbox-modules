from __future__ import annotations

import asyncio
import re
import socket
import time
from typing import Any, Mapping

from ...plugin_api.action_execution import ActionExecutionContext, ActionExecutionRequest
from ...plugin_api.contracts import PluginMetadata
from ...plugin_api.module_runtime import ModuleManifest
from ...plugin_api.registry import IntegrationDefinition

MODULE_ID = "com.sickicarus.monitorbox.wol"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1


async def _ping_once(host: str, timeout_seconds: float = 2) -> dict[str, Any]:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "ping", "-n", "-c", "1", "-W", str(max(1, int(timeout_seconds))), host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds + 1
        )
    except TimeoutError:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        return {"reachable": False, "latency_ms": None, "error": "timeout"}
    text = stdout.decode(errors="replace")
    if proc.returncode:
        error = stderr.decode(errors="replace").strip() or text.strip() or "no reply"
        return {"reachable": False, "latency_ms": None, "error": error[-160:]}
    match = re.search(r"time[=<]([0-9.]+)\s*ms", text)
    latency = float(match.group(1)) if match else (time.monotonic() - started) * 1000
    return {"reachable": True, "latency_ms": round(latency, 3), "error": None}


async def _send_magic_packets(request: ActionExecutionRequest) -> int:
    options = request.options
    broadcast = str(options.get("broadcast_address", "255.255.255.255"))
    port = int(options.get("port", 9))
    sent = 0
    loop = asyncio.get_running_loop()
    for address in options["mac_addresses"]:
        normalized = str(address).replace(":", "").replace("-", "")
        if len(normalized) != 12 or any(
            ch not in "0123456789abcdefABCDEF" for ch in normalized
        ):
            raise ValueError(f"invalid configured MAC address for action {request.action_id}")
        packet = bytes.fromhex("ff" * 6 + normalized * 16)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            await loop.sock_sendto(sock, packet, (broadcast, port))
            sent += 1
        finally:
            sock.close()
    return sent


async def _wake(request: ActionExecutionRequest) -> dict[str, Any]:
    options = request.options
    host = str(options.get("host", "")).strip()
    timeout = max(1.0, min(float(options.get("timeout_seconds", 300)), 1800.0))
    retry = max(1.0, min(float(options.get("retry_seconds", 30)), 300.0))
    probe_timeout = max(1.0, min(float(options.get("probe_timeout_seconds", 2)), 10.0))
    packets = 0
    batches = 0

    if host:
        initial = await _ping_once(host, probe_timeout)
        if initial["reachable"]:
            return {
                "host": host,
                "already_reachable": True,
                "reachable": True,
                "packets_sent": 0,
                "batches_sent": 0,
            }

    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        packets += await _send_magic_packets(request)
        batches += 1
        if not host:
            return {
                "reachable": None,
                "packets_sent": packets,
                "batches_sent": batches,
                "broadcast_address": str(
                    options.get("broadcast_address", "255.255.255.255")
                ),
            }
        # Give firmware/NIC wake handling a brief chance before the first probe.
        await asyncio.sleep(min(2.0, retry))
        result = await _ping_once(host, probe_timeout)
        if result["reachable"]:
            return {
                "host": host,
                "already_reachable": False,
                "reachable": True,
                "packets_sent": packets,
                "batches_sent": batches,
                "latency_ms": result["latency_ms"],
            }
        now = asyncio.get_running_loop().time()
        if now >= deadline:
            raise TimeoutError(
                f"{request.action_id} sent {batches} WOL batch(es) but {host} "
                f"did not become reachable within {timeout:g}s"
            )
        await asyncio.sleep(min(retry, max(0.0, deadline - now)))


def _validate_action_options(options: Mapping[str, Any]) -> None:
    addresses = options.get("mac_addresses")
    if (
        not isinstance(addresses, list)
        or not addresses
        or any(not isinstance(item, str) for item in addresses)
    ):
        raise ValueError("mac_addresses must be a non-empty string list")
    broadcast = options.get("broadcast_address", "255.255.255.255")
    if not isinstance(broadcast, str) or not broadcast.strip():
        raise ValueError("broadcast_address must be a non-empty string")


def _command_timeout_seconds(
    options: Mapping[str, Any], default_seconds: float
) -> float:
    wake_timeout = float(options.get("timeout_seconds", 300))
    return min(max(wake_timeout + 30.0, float(default_seconds)), 1830.0)


class WolActionExecutor:
    async def execute(
        self,
        request: ActionExecutionRequest,
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        del context
        if request.kind != "wol":
            raise ValueError(f"unsupported WOL action kind: {request.kind}")
        _validate_action_options(request.options)
        return await _wake(request)


_WOL = WolActionExecutor()
PLUGIN = IntegrationDefinition(
    metadata=PluginMetadata(plugin_id="wol", display_name="Wake-on-LAN"),
    action_kinds=("wol",),
    action_executor=_WOL,
    validate_action_options=_validate_action_options,
    resolve_action_command_timeout=_command_timeout_seconds,
)

MODULE_MANIFEST = ModuleManifest(
    module_id=MODULE_ID,
    display_name="Wake-on-LAN Action",
    version=MODULE_VERSION,
    build=MODULE_BUILD,
    module_type="integration",
    entrypoints={"integration": "monitorbox.v2.integrations.wol:PLUGIN"},
    requires_core=">=2.2.2 <3.0.0",
    requires_runtime_api=">=1 <2",
    state_schema=1,
    publisher_id="com.sickicarus",
)

__all__ = [
    "MODULE_BUILD",
    "MODULE_ID",
    "MODULE_MANIFEST",
    "MODULE_VERSION",
    "PLUGIN",
    "WolActionExecutor",
]
