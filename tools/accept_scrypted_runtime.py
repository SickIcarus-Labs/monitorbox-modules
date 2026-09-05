#!/usr/bin/env python3
"""Behavioral/runtime acceptance for managed Scrypted v1.0.0 build 1."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from aiohttp import web

from accept_http_behavior import install_core_contract_stubs

PACKAGE_NAME = "com.sickicarus.monitorbox.scrypted-1.0.0-build1.zip"
IMPORT_PACKAGE = "monitorbox_scrypted_b1"


def _install_scrypted_contracts(plugin_api) -> None:
    @dataclass(frozen=True)
    class RuntimeExecutionContext:
        module_id: str
        package_root: str
        state_root: str

    @dataclass(frozen=True)
    class RuntimeExecutionRequest:
        check_id: str
        object_id: str
        adapter: str
        timeout_seconds: float
        options: Mapping[str, Any] = field(default_factory=dict)
        agent_id: str | None = None
        capability_id: str | None = None
        capability_kind: str | None = None

    @dataclass(frozen=True)
    class RuntimeExecutionResult:
        state: str
        summary: str
        duration_ms: float
        metrics: Mapping[str, float] = field(default_factory=dict)
        metadata: Mapping[str, Any] = field(default_factory=dict)

        def public(self) -> dict[str, Any]:
            return {
                "state": self.state,
                "summary": self.summary,
                "duration_ms": self.duration_ms,
                "metrics": dict(self.metrics),
                "metadata": dict(self.metadata),
            }

    @dataclass(frozen=True)
    class IntegrationDefinition:
        metadata: Any
        connection_kinds: tuple[str, ...] = ()
        runtime_adapter_kinds: tuple[str, ...] = ()
        discovery: Any = None
        connection: Any = None
        validation: Any = None
        identity: Any = None
        inventory: Any = None
        presentation: Any = None
        runtime: Any = None
        runtime_executor: Any = None
        adoption: Any = None
        candidate_adoption: Any = None
        candidate_review: Any = None

    for value in (
        RuntimeExecutionContext,
        RuntimeExecutionRequest,
        RuntimeExecutionResult,
        IntegrationDefinition,
    ):
        setattr(plugin_api, value.__name__, value)


def _context(plugin_api):
    return plugin_api.FacetContext(
        site_id="lab",
        current_config={
            "sites": [{"id": "lab", "objects": []}],
            "runtime": {"local_agent": {"agent_id": "monitor"}},
        },
        current_revision=23,
        current_hash="scrypted-acceptance-hash",
    )


def _execution_context(plugin_api, managed, temp: Path):
    return plugin_api.RuntimeExecutionContext(
        module_id=managed.MODULE_ID,
        package_root=str(temp / "package"),
        state_root=str(temp / "state"),
    )


def _request(plugin_api, socket: Path, *, operation: str, camera_id: str = ""):
    options: dict[str, Any] = {"socket": str(socket), "operation": operation}
    if camera_id:
        options["camera_id"] = camera_id
    if operation == "inventory":
        options["expected_camera_ids"] = ["front-door", "driveway"]
    return plugin_api.RuntimeExecutionRequest(
        check_id=f"scrypted_{operation}",
        object_id=camera_id or "scrypted",
        adapter="scrypted",
        timeout_seconds=2.0,
        options=options,
    )


async def _serve(socket: Path):
    async def inventory(request):
        del request
        return web.json_response(
            {
                "serverVersion": "acceptance-1",
                "cameras": [
                    {
                        "id": "front-door",
                        "name": "Front Door",
                        "type": "doorbell",
                        "online": True,
                        "interfaces": ["Camera", "VideoCamera"],
                    },
                    {
                        "id": "driveway",
                        "name": "Driveway",
                        "type": "camera",
                        "online": True,
                        "interfaces": ["Camera", "VideoCamera"],
                    },
                    {
                        "id": "front-door-package",
                        "name": "Front Door Package Camera",
                        "type": "camera",
                        "online": True,
                        "interfaces": ["Camera"],
                    },
                ],
            }
        )

    async def state(request):
        camera_id = request.match_info["camera_id"]
        if camera_id == "front-door":
            return web.json_response(
                {
                    "id": camera_id,
                    "online": True,
                    "interfaces": ["Camera", "VideoCamera"],
                    "profiles": [],
                }
            )
        return web.json_response({}, status=404)

    app = web.Application()
    app.router.add_get("/v1/state", inventory)
    app.router.add_get("/v1/cameras/{camera_id}/state", state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.UnixSite(runner, str(socket))
    await site.start()
    return runner


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed Scrypted package is missing: {package}")

    plugin_api = install_core_contract_stubs()
    _install_scrypted_contracts(plugin_api)
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)

    if managed.MODULE_ID != "com.sickicarus.monitorbox.scrypted":
        raise AssertionError("managed Scrypted durable module id changed")
    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("1.0.0", 1):
        raise AssertionError("managed Scrypted release identity changed")
    manifest = managed.MODULE_MANIFEST
    if manifest.display_name != "Scrypted Integration":
        raise AssertionError("managed Scrypted product identity changed")
    if manifest.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("managed Scrypted manifest entrypoint is not generation-safe")
    if manifest.requires_core != ">=2.3.0 <3.0.0":
        raise AssertionError("managed Scrypted Core compatibility changed")
    if managed.PLUGIN.metadata.plugin_id != "scrypted":
        raise AssertionError("managed Scrypted provider identity changed")
    if managed.PLUGIN.runtime_adapter_kinds != ("scrypted",):
        raise AssertionError("managed Scrypted stopped claiming only the scrypted adapter")
    if managed.PLUGIN.candidate_adoption is None:
        raise AssertionError("managed Scrypted lost provider-owned camera adoption")

    candidate = plugin_api.DiscoveryEvidence(
        plugin_id="scrypted",
        connection_plugin_id="scrypted",
        system_id="arr2",
        kind="scrypted",
        label="Scrypted",
        endpoint="https://scrypted.example.test:10443",
        confidence=plugin_api.DiscoveryConfidence.DETECTED,
        evidence="synthetic authenticated Scrypted fixture",
        default_selected=True,
        values={"base_url": "https://scrypted.example.test:10443"},
    )
    connection = plugin_api.ConnectionRequest(
        candidate=candidate,
        values={
            "label": "Scrypted cameras",
            "username": "monitorbox",
            "password": "acceptance-secret",
            "excluded_camera_names": "Package Camera",
        },
    )
    plan = managed.ScryptedIntegration().plan(connection, _context(plugin_api))
    if plan.expected_revision != 23 or plan.expected_config_hash != "scrypted-acceptance-hash":
        raise AssertionError("Scrypted connection plan lost optimistic transaction guards")
    if len(plan.operations) != 1 or len(plan.secret_writes) != 2:
        raise AssertionError("Scrypted connection plan stopped brokering both credentials")
    provider = plan.operations[0].object_data["capabilities"][0]["providers"][0]
    if provider["adapter"] != "scrypted" or provider["config"]["operation"] != "inventory":
        raise AssertionError("Scrypted canonical inventory provider identity changed")
    if "acceptance-secret" in json.dumps(plan.public(), sort_keys=True):
        raise AssertionError("Scrypted public connection plan leaked protected credentials")

    camera_evidence = SimpleNamespace(
        source="scrypted",
        source_id="front-door",
    )
    camera_candidate = SimpleNamespace(
        candidate_id="camera:front-door",
        kind="camera",
        evidence=(camera_evidence,),
        addresses=(),
        mac=None,
        suggested_capabilities=("camera_state", "snapshot", "live_view"),
    )
    working = {
        "sites": [
            {
                "id": "lab",
                "objects": [
                    {
                        "id": "scrypted",
                        "capabilities": [
                            {
                                "providers": [
                                    {
                                        "adapter": "scrypted",
                                        "agent_id": "monitor",
                                        "config": {
                                            "operation": "inventory",
                                            "socket": "/run/monitorbox-scrypted/bridge.sock",
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ]
    }
    adopted_id, adopted = managed.ScryptedCandidateAdoption().adopt_candidate(
        working,
        site_id="lab",
        candidate=camera_candidate,
        label="Front Door",
        capabilities=("camera_state", "snapshot", "live_view"),
    )
    child = next(item for item in adopted["sites"][0]["objects"] if item["id"] == adopted_id)
    adapters = {
        p["adapter"]
        for capability in child["capabilities"]
        for p in capability["providers"]
    }
    if adapters != {"scrypted"} or len(child["capabilities"]) != 3:
        raise AssertionError("Scrypted camera adoption stopped reusing the managed provider")

    with tempfile.TemporaryDirectory(prefix="monitorbox-scrypted-accept-") as raw:
        temp = Path(raw)
        socket = temp / "bridge.sock"
        context = _execution_context(plugin_api, managed, temp)
        executor = managed.ScryptedRuntimeExecutor()

        lost_inventory = await executor.execute(
            _request(plugin_api, socket, operation="inventory"), context
        )
        if lost_inventory.state != "failed" or lost_inventory.metadata.get("failure_kind") != "monitor_dependency":
            raise AssertionError(f"Scrypted inventory provider-loss truth changed: {lost_inventory!r}")
        lost_camera = await executor.execute(
            _request(plugin_api, socket, operation="camera_state", camera_id="front-door"), context
        )
        if lost_camera.state != "unknown" or lost_camera.metadata.get("failure_kind") != "parent_unavailable":
            raise AssertionError(f"Scrypted child provider-loss truth changed: {lost_camera!r}")

        runner = await _serve(socket)
        try:
            recovered = await managed.ScryptedRuntimeExecutor().execute(
                _request(plugin_api, socket, operation="inventory"), context
            )
            if recovered.state != "healthy":
                raise AssertionError(f"Scrypted did not recover after delayed provider availability: {recovered!r}")
            evidence = recovered.metadata.get("discovery_evidence", [])
            by_id = {row.get("source_id"): row for row in evidence if isinstance(row, dict)}
            if set(by_id) != {"front-door", "driveway", "front-door-package"}:
                raise AssertionError(f"Scrypted camera inventory evidence changed: {by_id!r}")
            if not by_id["front-door-package"].get("metadata", {}).get("auxiliary"):
                raise AssertionError("Scrypted package/parcel auxiliary-camera classification changed")
            camera = await managed.ScryptedRuntimeExecutor().execute(
                _request(plugin_api, socket, operation="camera_state", camera_id="front-door"), context
            )
            if camera.state != "healthy" or camera.metadata.get("camera_status") != "online":
                raise AssertionError(f"Scrypted camera-state runtime changed: {camera!r}")
        finally:
            await runner.cleanup()

    print(
        "Managed Scrypted 1.0.0 build 1: connection + camera adoption + inventory + "
        "provider-loss/recovery truth: PASS",
        flush=True,
    )


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
