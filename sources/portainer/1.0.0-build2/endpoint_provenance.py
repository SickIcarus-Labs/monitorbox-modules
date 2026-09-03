from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from .lifecycle_truth import (
    PortainerLifecycleTruthRuntimeExecutor as _BasePortainerRuntimeExecutor,
)


def _url_host(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None
    return host.strip() if isinstance(host, str) and host.strip() else None


def _service_host(
    *,
    environment_url: Any,
    controller_base_url: Any,
) -> tuple[str, str] | None:
    """Resolve the provider-owned host that receives published Docker ports.

    Remote Agent-backed environments advertise their own network address and
    therefore own the service host directly. A local Unix-socket environment has
    no network host; for that one bounded case, the authenticated Portainer
    controller host is the only provider-known host for the same Docker engine.
    We do not guess from human environment labels or unrelated addresses.
    """
    environment_text = str(environment_url or "").strip()
    environment_host = _url_host(environment_text)
    if environment_host:
        return environment_host, "environment_url"
    if environment_text.casefold().startswith("unix://"):
        controller_host = _url_host(controller_base_url)
        if controller_host:
            return controller_host, "controller_base_url"
    return None


def _service_endpoints(
    *,
    environment_url: Any,
    controller_base_url: Any,
    published_ports: Any,
) -> list[dict[str, Any]]:
    """Normalize externally reachable TCP service provenance from Portainer.

    Docker private-only ports are not reachable service candidates. UDP is not
    projected into the current Connection suggestion surface. The bind address
    is intentionally absent because the existing Portainer runtime already
    strips it from container port metadata.
    """
    resolved_host = _service_host(
        environment_url=environment_url,
        controller_base_url=controller_base_url,
    )
    if resolved_host is None or not isinstance(published_ports, list):
        return []
    host, host_source = resolved_host
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for item in published_ports:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("protocol") or "tcp").strip().casefold() != "tcp":
            continue
        private_port = item.get("private_port")
        public_port = item.get("public_port")
        if (
            isinstance(private_port, bool)
            or not isinstance(private_port, int)
            or not 1 <= private_port <= 65535
            or isinstance(public_port, bool)
            or not isinstance(public_port, int)
            or not 1 <= public_port <= 65535
        ):
            continue
        identity = (private_port, public_port)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "host": host,
                "private_port": private_port,
                "public_port": public_port,
                "protocol": "tcp",
                "host_source": host_source,
            }
        )
    return sorted(
        result,
        key=lambda item: (item["private_port"], item["public_port"]),
    )


class PortainerEndpointRuntimeExecutor(_BasePortainerRuntimeExecutor):
    """Enrich certified Portainer inventory with service endpoint provenance."""

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        inventory = await super()._inventory(options)
        controller_base_url = str(options.get("base_url") or "").rstrip("/")
        workloads = inventory.get("workloads")
        if not isinstance(workloads, list):
            return inventory
        for workload in workloads:
            if not isinstance(workload, dict):
                continue
            workload["service_endpoints"] = _service_endpoints(
                environment_url=workload.get("environment_url"),
                controller_base_url=controller_base_url,
                published_ports=workload.get("published_ports"),
            )
        return inventory
