from __future__ import annotations

import asyncio
import copy
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ...plugin_api import (
    AddObjectIntent,
    ConnectionPlan,
    ConnectionRequest,
    CredentialSecretWrite,
    DiscoveryConfidence,
    DiscoveryEvidence,
    DiscoveryRequest,
    FacetContext,
    IdentityKey,
    PresentationDescriptor,
    PresentationField,
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    RuntimeIntent,
    ValidationResult,
)
from .runtime import MODULE_ID, ScryptedRuntimeExecutor

_ID_CLEAN_RE = re.compile(r"[^a-z0-9_-]+")
_DEFAULT_PROGRAM = Path("/app/bridge/server.mjs")
_STARTUP_TIMEOUT_SECONDS = 5.0
_ACCEPTED_STATES = frozenset({"healthy", "degraded"})
_PROBES: tuple[tuple[str, int, str], ...] = (
    ("https", 10443, "HTTPS service (possible Scrypted)"),
    ("http", 11080, "HTTP service (possible Scrypted)"),
)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be non-empty text")
    return value.strip()


def _slug(value: Any) -> str:
    text = _ID_CLEAN_RE.sub("_", str(value or "scrypted").casefold()).strip("_")
    if not text:
        text = "scrypted"
    if not text[0].isalpha():
        text = f"scrypted_{text}"
    return text[:64]


def _unique_object_id(context: FacetContext, base: str = "scrypted") -> str:
    clean = _slug(base)
    site = next(
        (
            item
            for item in context.current_config.get("sites", [])
            if isinstance(item, Mapping) and item.get("id") == context.site_id
        ),
        None,
    )
    used = {
        str(item.get("id"))
        for item in (site.get("objects", []) if isinstance(site, Mapping) else [])
        if isinstance(item, Mapping)
    }
    if clean not in used:
        return clean
    index = 2
    while True:
        suffix = f"_{index}"
        candidate = f"{clean[:64-len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        index += 1


def _excluded(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError("Scrypted excluded camera names must be comma-separated text")


def _merged_values(request: ConnectionRequest) -> dict[str, Any]:
    values = dict(request.candidate.values)
    values.update(dict(request.values))
    return values


def _normalized(request: ConnectionRequest) -> dict[str, Any]:
    values = _merged_values(request)
    base_url = values.get("base_url")
    if not base_url and request.candidate.endpoint.casefold().startswith(("http://", "https://")):
        base_url = request.candidate.endpoint
    base_url = _text(base_url, "Scrypted server URL").rstrip("/")
    if not base_url.casefold().startswith(("http://", "https://")):
        raise ValueError("Scrypted server URL must use http:// or https://")
    return {
        "label": _text(values.get("label", "Scrypted cameras"), "Scrypted label"),
        "base_url": base_url,
        "username": _text(values.get("username"), "Scrypted username"),
        "password": _text(values.get("password"), "Scrypted password"),
        "excluded_camera_names": _excluded(values.get("excluded_camera_names", "")),
    }


def _worker_program() -> Path:
    override = os.environ.get("MONITORBOX_ONBOARDING_SCRYPTED_WORKER")
    return Path(override) if override else _DEFAULT_PROGRAM


async def _wait_ready(
    process: asyncio.subprocess.Process,
    socket_path: Path,
    *,
    timeout_seconds: float = _STARTUP_TIMEOUT_SECONDS,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        if process.returncode is not None:
            raise RuntimeError(
                f"Scrypted validation worker exited with status {process.returncode} before becoming ready"
            )
        if socket_path.exists():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("Scrypted validation worker did not become ready in time")


async def _stop(process: asyncio.subprocess.Process | None) -> None:
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3.0)
    except TimeoutError:
        process.kill()
        await process.wait()


def _scrub(value: Any, protected: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {str(key): _scrub(item, protected) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, protected) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, protected) for item in value)
    if isinstance(value, str):
        result = value
        for secret in protected:
            if secret:
                result = result.replace(secret, "[protected]")
        return result
    return value


def _valid_inventory_observation(public: Mapping[str, Any]) -> bool:
    metadata = public.get("metadata")
    return (
        isinstance(metadata, Mapping)
        and isinstance(metadata.get("cameras"), list)
        and isinstance(metadata.get("discovery_evidence"), list)
    )


class ScryptedIntegration:
    """Provider-local Scrypted discovery, onboarding, validation and runtime intent."""

    async def detect(
        self,
        request: DiscoveryRequest,
        context: FacetContext,
        probe,
    ) -> tuple[DiscoveryEvidence, ...]:
        del context
        host = request.address.strip()
        result: list[DiscoveryEvidence] = []
        for scheme, port, hint in _PROBES:
            if not await probe.tcp_open(host, port):
                continue
            endpoint = f"{scheme}://{host}:{port}"
            # 0540 intentionally treated an open common Scrypted port as only
            # generic HTTP evidence. Preserve that confidence boundary while
            # making the Scrypted module the owner of the detection policy.
            result.append(
                DiscoveryEvidence(
                    plugin_id="scrypted",
                    connection_plugin_id="http",
                    system_id=request.system_id,
                    kind="http",
                    label=hint,
                    endpoint=endpoint,
                    confidence=DiscoveryConfidence.POSSIBLE,
                    evidence=f"TCP/{port} is open; product identity requires validation",
                    default_selected=False,
                    values={"url": endpoint},
                )
            )
        return tuple(result)

    def plan(self, request: ConnectionRequest, context: FacetContext) -> ConnectionPlan:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = _text(
            local.get("agent_id") if isinstance(local, Mapping) else None,
            "local agent id",
        )
        username_env = "MONITORBOX_SCRYPTED_USERNAME"
        password_env = "MONITORBOX_SCRYPTED_PASSWORD"
        username_secret = _slug(f"{object_id}_username")
        password_secret = _slug(f"{object_id}_password")
        config: dict[str, Any] = {
            "socket": "/run/monitorbox-scrypted/bridge.sock",
            "operation": "inventory",
            "base_url": values["base_url"],
            "username_env": username_env,
            "password_env": password_env,
        }
        if values["excluded_camera_names"]:
            config["excluded_camera_names"] = list(values["excluded_camera_names"])
        obj = {
            "id": object_id,
            "label": values["label"],
            "kind": "integration",
            "depends_on": [request.candidate.system_id],
            "icon": "scrypted",
            "capabilities": [
                {
                    "id": "scrypted",
                    "kind": "cameras",
                    "label": "Scrypted camera inventory",
                    "enabled": True,
                    "providers": [
                        {
                            "id": "scrypted",
                            "label": "Scrypted camera inventory",
                            "adapter": "scrypted",
                            "agent_id": agent_id,
                            "check_id": f"{object_id}_inventory",
                            "enabled": True,
                            "interval_seconds": 60,
                            "timeout_seconds": 15,
                            "config": config,
                        }
                    ],
                }
            ],
        }
        return ConnectionPlan(
            plugin_id="scrypted",
            system_id=request.candidate.system_id,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            operations=(AddObjectIntent(site_id=context.site_id, object_data=obj),),
            secret_writes=(
                CredentialSecretWrite(
                    secret_id=username_secret,
                    value=values["username"],
                    env_name=username_env,
                ),
                CredentialSecretWrite(
                    secret_id=password_secret,
                    value=values["password"],
                    env_name=password_env,
                ),
            ),
            object_ids=(object_id,),
        )

    async def validate(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> ValidationResult:
        del context
        values = _normalized(request)
        protected = (values["username"], values["password"])
        process: asyncio.subprocess.Process | None = None
        with tempfile.TemporaryDirectory(prefix="monitorbox-onboarding-scrypted-", dir="/tmp") as raw_dir:
            temp = Path(raw_dir)
            socket_path = temp / "bridge.sock"
            environment = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": "/nonexistent",
                "SCRYPTED_URL": values["base_url"],
                "SCRYPTED_USERNAME": values["username"],
                "SCRYPTED_PASSWORD": values["password"],
                "SCRYPTED_EXCLUDED_CAMERA_NAMES": ",".join(values["excluded_camera_names"]),
                "SCRYPTED_BRIDGE_SOCKET": str(socket_path),
            }
            try:
                process = await asyncio.create_subprocess_exec(
                    "node",
                    str(_worker_program()),
                    env=environment,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await _wait_ready(process, socket_path)
                executor = ScryptedRuntimeExecutor()
                execution_context = RuntimeExecutionContext(
                    module_id=MODULE_ID,
                    package_root=str(temp / "package"),
                    state_root=str(temp / "state"),
                )
                await executor.start(execution_context)
                try:
                    execution = RuntimeExecutionRequest(
                        check_id="scrypted_validation",
                        object_id=request.candidate.system_id,
                        adapter="scrypted",
                        timeout_seconds=15,
                        options={
                            "socket": str(socket_path),
                            "operation": "inventory",
                        },
                    )
                    try:
                        async with asyncio.timeout(execution.timeout_seconds):
                            result = await executor.execute(execution, execution_context)
                    except TimeoutError:
                        public: dict[str, Any] = {
                            "state": "failed",
                            "summary": "Timed out after 15s",
                            "duration_ms": 15000,
                            "metrics": {},
                            "metadata": {},
                        }
                    else:
                        public = result.public()
                finally:
                    await executor.close(execution_context)
            except Exception as exc:
                public = {
                    "state": "failed",
                    "summary": (
                        "Scrypted validation worker unavailable: "
                        f"{type(exc).__name__}: {str(exc)[:200]}"
                    ),
                    "duration_ms": 0,
                    "metrics": {},
                    "metadata": {"failure_kind": "validation_worker"},
                }
            finally:
                await _stop(process)

        public = _scrub(copy.deepcopy(public), protected)
        state = str(public.get("state") or "failed")
        summary = str(public.get("summary") or "Scrypted validation completed")[:400]
        if state in _ACCEPTED_STATES and not _valid_inventory_observation(public):
            state = "failed"
            summary = "Scrypted validation returned no authenticated camera inventory"
            public["state"] = state
            public["summary"] = summary
            metadata = public.get("metadata")
            public["metadata"] = {
                **(dict(metadata) if isinstance(metadata, Mapping) else {}),
                "failure_kind": "provider_contract",
            }
        return ValidationResult(
            accepted=state in _ACCEPTED_STATES,
            state=state,
            summary=summary,
            observation=public,
            metadata={"transport": "scrypted", "validation_worker": "isolated"},
            values={
                "base_url": values["base_url"],
                "label": values["label"],
                "excluded_camera_names": list(values["excluded_camera_names"]),
            },
        )

    def identities(
        self,
        evidence,
        context: FacetContext,
    ) -> tuple[IdentityKey, ...]:
        del context
        if isinstance(evidence, DiscoveryEvidence):
            endpoint = str(
                evidence.values.get("base_url")
                or evidence.values.get("url")
                or evidence.endpoint
            ).rstrip("/")
            return (IdentityKey("scrypted-endpoint", endpoint.casefold(), 100),)
        return (evidence.identity,)

    def describe(self, context: FacetContext) -> PresentationDescriptor:
        del context
        return PresentationDescriptor(
            plugin_id="scrypted",
            title="Scrypted cameras",
            fields=(
                PresentationField(
                    key="base_url",
                    label="Scrypted server URL",
                    required=True,
                ),
                PresentationField(
                    key="username",
                    label="Username",
                    required=True,
                    secret=True,
                ),
                PresentationField(
                    key="password",
                    label="Password",
                    required=True,
                    secret=True,
                ),
                PresentationField(
                    key="excluded_camera_names",
                    label="Excluded camera names",
                ),
            ),
            provenance_keys=("transport", "validation_worker"),
        )

    def build_runtime_intent(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> RuntimeIntent:
        values = _normalized(request)
        object_id = _unique_object_id(context)
        local = context.current_config.get("runtime", {}).get("local_agent", {})
        agent_id = local.get("agent_id") if isinstance(local, Mapping) else None
        config: dict[str, Any] = {
            "socket": "/run/monitorbox-scrypted/bridge.sock",
            "operation": "inventory",
            "base_url": values["base_url"],
            "username_env": "MONITORBOX_SCRYPTED_USERNAME",
            "password_env": "MONITORBOX_SCRYPTED_PASSWORD",
        }
        if values["excluded_camera_names"]:
            config["excluded_camera_names"] = list(values["excluded_camera_names"])
        return RuntimeIntent(
            plugin_id="scrypted",
            checks=(
                {
                    "id": f"{object_id}_inventory",
                    "adapter": "scrypted",
                    "object_id": object_id,
                    "agent_id": agent_id,
                    "interval_seconds": 60,
                    "timeout_seconds": 15,
                    "config": config,
                },
            ),
        )
