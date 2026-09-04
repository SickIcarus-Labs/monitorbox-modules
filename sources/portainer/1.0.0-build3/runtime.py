from __future__ import annotations

import os
import re
import time
from collections import Counter
from typing import Any, Mapping
from urllib.parse import quote

import aiohttp

from ...plugin_api import RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult
from .suggestions import generic_workload_evidence, is_portainer_controller_self

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_CACHE_SECONDS = 10.0


def _elapsed(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _result(
    start: float,
    state: str,
    summary: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    metrics: Mapping[str, float] | None = None,
) -> RuntimeExecutionResult:
    return RuntimeExecutionResult(
        state=state,
        summary=summary,
        duration_ms=_elapsed(start),
        metrics=dict(metrics or {}),
        metadata=dict(metadata or {}),
    )


def _truth(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in _TRUE:
            return True
        if folded in _FALSE:
            return False
    return None


def _slug(value: Any) -> str:
    text = re.sub(
        r"[^a-z0-9_.-]+",
        "_",
        str(value or "docker").strip().casefold(),
    ).strip("_")
    return text or "docker"


def _container_name(container: Mapping[str, Any]) -> str:
    names = container.get("Names")
    if isinstance(names, list):
        for name in names:
            if isinstance(name, str) and name.strip("/"):
                return name.strip("/")
    return str(container.get("Id") or "container")[:12]


def _health(container: Mapping[str, Any]) -> str | None:
    status = str(container.get("Status") or "").casefold()
    if "(unhealthy)" in status:
        return "unhealthy"
    if "(healthy)" in status:
        return "healthy"
    if "health: starting" in status:
        return "starting"
    return None


def _published_ports(container: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = container.get("Ports", [])
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int | None, str]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        private = item.get("PrivatePort")
        public = item.get("PublicPort")
        if (
            isinstance(private, bool)
            or not isinstance(private, int)
            or not 1 <= private <= 65535
        ):
            continue
        if public is None:
            public_port = None
        elif (
            isinstance(public, bool)
            or not isinstance(public, int)
            or not 1 <= public <= 65535
        ):
            continue
        else:
            public_port = public
        protocol = str(item.get("Type") or "tcp").strip().casefold()
        if protocol not in {"tcp", "udp"}:
            continue
        identity = (private, public_port, protocol)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "private_port": private,
                "public_port": public_port,
                "protocol": protocol,
            }
        )
    return result


def _ignored_workload_identities(options: Mapping[str, Any]) -> frozenset[str]:
    raw = options.get("ignored_workload_identities", [])
    if raw in (None, ""):
        return frozenset()
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise RuntimeError(
            "Portainer ignored_workload_identities must be a string list"
        )
    return frozenset(item.strip() for item in raw)


def _environment_rows(
    endpoints: list[Any],
    selected_ids: tuple[int, ...],
) -> list[tuple[Mapping[str, Any], int, str, str, str]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            continue
        provider_id = endpoint.get("Id", endpoint.get("id"))
        if isinstance(provider_id, bool) or not isinstance(provider_id, int):
            continue
        if provider_id in seen:
            raise RuntimeError(
                f"Portainer returned duplicate environment id {provider_id}"
            )
        seen.add(provider_id)
        engine = str(
            endpoint.get("ContainerEngine")
            or endpoint.get("containerEngine")
            or "docker"
        ).casefold()
        if engine and engine != "docker":
            continue
        name = str(
            endpoint.get("Name")
            or endpoint.get("name")
            or f"environment-{provider_id}"
        ).strip()
        rows.append(
            {
                "endpoint": endpoint,
                "provider_id": provider_id,
                "name": name,
                "engine": engine or "docker",
                "base_key": _slug(name),
            }
        )
    counts = Counter(str(row["base_key"]) for row in rows)
    for row in rows:
        base_key = str(row["base_key"])
        row["key"] = (
            base_key
            if counts[base_key] == 1
            else f"{base_key}_{row['provider_id']}"
        )
    while True:
        key_counts = Counter(str(row["key"]) for row in rows)
        collisions = {key for key, count in key_counts.items() if count > 1}
        if not collisions:
            break
        changed = False
        for key in sorted(collisions):
            matches = [row for row in rows if str(row["key"]) == key]
            plain = [
                row
                for row in matches
                if str(row["key"]) == str(row["base_key"])
            ]
            preserve = plain[0] if len(plain) == 1 else None
            for row in matches:
                if row is preserve:
                    continue
                row["key"] = f"{row['key']}_{row['provider_id']}"
                changed = True
        if not changed:
            raise RuntimeError(
                "Portainer environment identities could not be disambiguated"
            )
    selected = set(selected_ids)
    return [
        (
            row["endpoint"],
            int(row["provider_id"]),
            str(row["name"]),
            str(row["engine"]),
            str(row["key"]),
        )
        for row in rows
        if not selected or int(row["provider_id"]) in selected
    ]


def _workload_discovery_evidence(
    workloads: Any,
    *,
    authoritative: bool,
) -> list[dict[str, Any]]:
    """Compatibility name for module-local generic evidence projection."""
    return generic_workload_evidence(workloads, authoritative=authoritative)


def _inventory_runtime_health(
    workloads: Any,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Summarize provider-native container truth without inventing operator intent.

    Explicit Docker health failures and active restart/dead states are actionable
    runtime anomalies. Merely non-running containers are counted but remain
    policy-neutral until configuration supplies expected-running intent.
    """
    counts = {
        "containers_total": 0,
        "running_containers": 0,
        "healthy_containers": 0,
        "unhealthy_containers": 0,
        "starting_containers": 0,
        "non_running_containers": 0,
    }
    anomalies: list[dict[str, Any]] = []
    if not isinstance(workloads, list):
        return counts, anomalies

    for workload in workloads:
        if not isinstance(workload, Mapping):
            continue
        workload_identity = str(workload.get("identity") or "")
        containers = workload.get("containers", [])
        if not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, Mapping):
                continue
            counts["containers_total"] += 1
            state = str(container.get("state") or "unknown").strip().casefold()
            health = str(container.get("health") or "").strip().casefold()
            if state == "running":
                counts["running_containers"] += 1
            else:
                counts["non_running_containers"] += 1
            if health == "healthy":
                counts["healthy_containers"] += 1
            elif health == "unhealthy":
                counts["unhealthy_containers"] += 1
                anomalies.append(
                    {
                        "kind": "unhealthy",
                        "workload_identity": workload_identity,
                        "container_provider_id": container.get("provider_id"),
                        "container_name": container.get("name"),
                        "state": state,
                        "health": health,
                    }
                )
            elif health == "starting":
                counts["starting_containers"] += 1

            if state in {"restarting", "dead"}:
                anomalies.append(
                    {
                        "kind": state,
                        "workload_identity": workload_identity,
                        "container_provider_id": container.get("provider_id"),
                        "container_name": container.get("name"),
                        "state": state,
                        "health": health or None,
                    }
                )

    return counts, anomalies


class PortainerRuntimeExecutor:
    """Read-only Portainer API executor owned by the Portainer module."""

    def __init__(self) -> None:
        self._inventory_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}

    async def start(self, context: RuntimeExecutionContext) -> None:
        del context

    async def close(self, context: RuntimeExecutionContext) -> None:
        del context

    async def execute(
        self,
        request: RuntimeExecutionRequest,
        context: RuntimeExecutionContext,
    ) -> RuntimeExecutionResult:
        del context
        if request.adapter != "portainer":
            raise ValueError(
                f"Portainer executor cannot run adapter {request.adapter!r}"
            )
        start = time.monotonic()
        options = dict(request.options)
        try:
            inventory = await self._inventory(options)
        except Exception as exc:
            return _result(
                start,
                "unknown",
                f"Portainer unavailable: {type(exc).__name__}: {exc}"[:400],
                metadata={"provider": "portainer", "authoritative": False},
            )

        operation = str(options.get("operation", "inventory"))
        if operation == "inventory":
            errors = inventory["errors"]
            runtime_health, runtime_anomalies = _inventory_runtime_health(
                inventory["workloads"]
            )
            if errors and not inventory["successful_environments"]:
                state, summary = "unknown", "Portainer inventory unavailable"
            elif errors:
                state = "degraded"
                summary = (
                    "Portainer inventory partial: "
                    f"{len(inventory['workloads'])} workloads, "
                    f"{len(errors)} environment error(s)"
                )
            elif runtime_anomalies:
                state = "degraded"
                unhealthy = runtime_health["unhealthy_containers"]
                summary = f"Portainer inventory: {len(inventory['workloads'])} workloads"
                if unhealthy:
                    summary += f"; {unhealthy} unhealthy container(s)"
                else:
                    summary += f"; {len(runtime_anomalies)} runtime anomaly/anomalies"
            else:
                state = "healthy"
                summary = f"Portainer inventory: {len(inventory['workloads'])} workloads"
            authoritative = not errors
            metadata = {
                "provider": "portainer",
                "authoritative": authoritative,
                "environments": inventory["environments"],
                "successful_environments": sorted(
                    inventory["successful_environments"]
                ),
                "errors": errors,
                "workloads": inventory["workloads"],
                "ignored_count": inventory["ignored_count"],
                "runtime_health": runtime_health,
                "runtime_anomalies": runtime_anomalies,
                "discovery_evidence": _workload_discovery_evidence(
                    inventory["workloads"], authoritative=authoritative
                ),
            }
            return _result(
                start,
                state,
                summary,
                metadata=metadata,
                metrics={
                    "environments": float(len(inventory["environments"])),
                    "workloads": float(len(inventory["workloads"])),
                    "containers": float(runtime_health["containers_total"]),
                    "unhealthy_containers": float(
                        runtime_health["unhealthy_containers"]
                    ),
                    "starting_containers": float(
                        runtime_health["starting_containers"]
                    ),
                    "non_running_containers": float(
                        runtime_health["non_running_containers"]
                    ),
                },
            )

        identity = str(options["workload_identity"])
        policy = str(options.get("policy", "optional"))
        workload = next(
            (
                item
                for item in inventory["workloads"]
                if item.get("identity") == identity
            ),
            None,
        )
        environment_key = str(
            options.get("environment_key")
            or self._identity_environment(identity)
        )
        authoritative = environment_key in inventory["successful_environments"]
        if workload is None:
            if not authoritative:
                return _result(
                    start,
                    "unknown",
                    "Docker workload presence unknown: Portainer environment inventory is unavailable",
                    metadata={
                        "provider": "portainer",
                        "authoritative": False,
                        "workload_identity": identity,
                        "policy": policy,
                        "errors": inventory["errors"],
                    },
                )
            if policy == "required":
                return _result(
                    start,
                    "failed",
                    "Required Docker workload is missing",
                    metadata={
                        "provider": "portainer",
                        "authoritative": True,
                        "workload_identity": identity,
                        "policy": policy,
                        "missing": True,
                    },
                )
            return _result(
                start,
                "healthy",
                "Optional Docker workload is not present",
                metadata={
                    "provider": "portainer",
                    "authoritative": True,
                    "workload_identity": identity,
                    "policy": policy,
                    "missing": True,
                    "retired": True,
                    "health_neutral": True,
                },
            )

        states = {
            str(item.get("state") or "unknown").casefold()
            for item in workload.get("containers", [])
            if isinstance(item, Mapping)
        }
        health = {
            str(item.get("health"))
            for item in workload.get("containers", [])
            if isinstance(item, Mapping) and item.get("health")
        }
        running = bool(states) and states <= {"running"}
        unhealthy = "unhealthy" in health
        if unhealthy:
            state, summary = "failed", "Docker workload unhealthy"
        elif running:
            state, summary = "healthy", "Docker workload running"
        elif policy == "required":
            state, summary = "failed", "Required Docker workload is stopped"
        else:
            state, summary = "healthy", "Docker workload stopped (optional)"
        return _result(
            start,
            state,
            summary,
            metadata={
                "provider": "portainer",
                "authoritative": True,
                "policy": policy,
                "health_neutral": policy == "optional" and not running,
                **workload,
            },
        )

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        base = str(options["base_url"]).rstrip("/")
        api_key_env = str(options["api_key_env"])
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Portainer API key environment {api_key_env} is not set"
            )
        operation = str(options.get("operation", "inventory")).strip().casefold()
        configured_ids = tuple(
            int(item) for item in options.get("environment_ids", [])
        )
        selected_ids = () if operation == "inventory" else configured_ids
        ignored_identities = _ignored_workload_identities(options)
        verify_tls = bool(options.get("verify_tls", True))
        cache_key = (
            base,
            api_key_env,
            operation,
            selected_ids,
            verify_tls,
            tuple(sorted(ignored_identities)),
        )
        now = time.monotonic()
        cached = self._inventory_cache.get(cache_key)
        if cached is not None and now - cached[0] < _CACHE_SECONDS:
            return cached[1]

        headers = {"X-API-Key": api_key, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            endpoints = await self._get(
                session,
                base + "/api/endpoints",
                headers,
                verify_tls,
            )
            if not isinstance(endpoints, list):
                raise RuntimeError(
                    "Portainer /api/endpoints returned an invalid payload"
                )
            environments: list[dict[str, Any]] = []
            workloads_by_identity: dict[str, dict[str, Any]] = {}
            successful: set[str] = set()
            errors: list[dict[str, Any]] = []
            ignored_count = 0
            for (
                endpoint,
                provider_id,
                name,
                engine,
                environment_key,
            ) in _environment_rows(endpoints, selected_ids):
                endpoint_url = endpoint.get("URL", endpoint.get("url"))
                environments.append(
                    {
                        "provider_id": provider_id,
                        "name": name,
                        "key": environment_key,
                        "status": endpoint.get(
                            "Status", endpoint.get("status")
                        ),
                        "url": endpoint_url,
                        "container_engine": engine,
                    }
                )
                try:
                    containers = await self._get(
                        session,
                        (
                            f"{base}/api/endpoints/{provider_id}/docker/"
                            "containers/json?all=true"
                        ),
                        headers,
                        verify_tls,
                    )
                    if not isinstance(containers, list):
                        raise RuntimeError("container inventory is not a list")
                    successful.add(environment_key)
                except Exception as exc:
                    errors.append(
                        {
                            "environment": name,
                            "environment_key": environment_key,
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                        }
                    )
                    continue

                for container in containers:
                    if not isinstance(container, Mapping):
                        continue
                    labels = container.get("Labels")
                    labels = labels if isinstance(labels, Mapping) else {}
                    if _truth(labels.get("monitorbox.ignore")) is True:
                        ignored_count += 1
                        continue
                    project = str(
                        labels.get("com.docker.compose.project") or ""
                    ).strip()
                    service = str(
                        labels.get("com.docker.compose.service") or ""
                    ).strip()
                    name_value = _container_name(container)
                    if project and service:
                        identity = (
                            f"compose:{environment_key}:"
                            f"{quote(project, safe='._-')}:"
                            f"{quote(service, safe='._-')}"
                        )
                        label, deployment_kind = service, "compose"
                    else:
                        identity = (
                            f"container:{environment_key}:"
                            f"{quote(_slug(name_value), safe='._-')}"
                        )
                        label, deployment_kind = name_value, "standalone"
                    if identity in ignored_identities:
                        ignored_count += 1
                        continue
                    required_hint = _truth(labels.get("monitorbox.required"))
                    record = workloads_by_identity.setdefault(
                        identity,
                        {
                            "identity": identity,
                            "label": label,
                            "environment": name,
                            "environment_key": environment_key,
                            "environment_provider_id": provider_id,
                            "environment_url": endpoint_url,
                            "deployment_kind": deployment_kind,
                            "compose_project": project or None,
                            "compose_service": service or None,
                            "required_hint": required_hint,
                            "containers": [],
                            "images": [],
                            "published_ports": [],
                        },
                    )
                    if (
                        record.get("required_hint") is None
                        and required_hint is not None
                    ):
                        record["required_hint"] = required_hint
                    image = str(container.get("Image") or "").strip()
                    if image and image not in record["images"]:
                        record["images"].append(image)
                    ports = _published_ports(container)
                    for port in ports:
                        if port not in record["published_ports"]:
                            record["published_ports"].append(port)
                    record["containers"].append(
                        {
                            "provider_id": container.get("Id"),
                            "name": name_value,
                            "image": image or None,
                            "image_id": container.get("ImageID"),
                            "state": container.get("State"),
                            "status": container.get("Status"),
                            "health": _health(container),
                            "ports": ports,
                        }
                    )

        workloads = sorted(
            workloads_by_identity.values(),
            key=lambda item: (
                str(item["environment"]).casefold(),
                str(item.get("compose_project") or "").casefold(),
                str(item["label"]).casefold(),
            ),
        )
        for workload in workloads:
            if is_portainer_controller_self(workload):
                workload["discovery_actionable"] = False
                workload["discovery_suppression_reason"] = (
                    "authenticated_portainer_controller"
                )
            else:
                workload["discovery_actionable"] = True

        result = {
            "environments": environments,
            "successful_environments": successful,
            "errors": errors,
            "workloads": workloads,
            "ignored_count": ignored_count,
        }
        self._inventory_cache[cache_key] = (now, result)
        return result

    @staticmethod
    async def _get(
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        verify_tls: bool,
    ) -> Any:
        async with session.get(
            url,
            headers=headers,
            ssl=None if verify_tls else False,
        ) as response:
            if response.status != 200:
                text = (await response.text())[:240]
                raise RuntimeError(
                    f"{url} returned HTTP {response.status}: {text}"
                )
            try:
                return await response.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"{url} returned invalid JSON") from exc

    @staticmethod
    def _identity_environment(identity: str) -> str:
        parts = identity.split(":", 2)
        return parts[1] if len(parts) >= 2 else ""
