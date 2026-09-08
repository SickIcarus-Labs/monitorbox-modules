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
    """Normalize direct backend transport evidence from authenticated Portainer.

    These rows prove only a site-local published TCP transport. They deliberately
    do not claim HTTP, HTTPS, or any presentation URL. Product/application
    semantics must come from separate evidence before a web Connection can be
    proposed.
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
                "endpoint_role": "backend_monitoring",
            }
        )
    return sorted(
        result,
        key=lambda item: (item["private_port"], item["public_port"]),
    )


def _configured_environment_ids(options: Mapping[str, Any]) -> frozenset[int]:
    raw = options.get("environment_ids", [])
    if raw in (None, ""):
        return frozenset()
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        item
        for item in raw
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    )


class PortainerEndpointRuntimeExecutor(_BasePortainerRuntimeExecutor):
    """Enrich inventory with endpoint roles and durable environment disposition.

    Inventory intentionally remains complete across every authenticated
    environment. When the canonical Portainer provider is scoped to explicit
    environment IDs, descendants outside that scope stay in raw provenance but
    are not actionable discovery candidates. Removing the scope restores those
    descendants without losing identity/history.
    """

    async def _inventory(self, options: dict[str, Any]) -> dict[str, Any]:
        inventory = await super()._inventory(options)
        controller_base_url = str(options.get("base_url") or "").rstrip("/")
        selected_ids = _configured_environment_ids(options)

        environments = inventory.get("environments")
        if isinstance(environments, list):
            for environment in environments:
                if not isinstance(environment, dict):
                    continue
                provider_id = environment.get("provider_id")
                environment["discovery_selected"] = (
                    not selected_ids or provider_id in selected_ids
                )

        workloads = inventory.get("workloads")
        if not isinstance(workloads, list):
            return inventory
        for workload in workloads:
            if not isinstance(workload, dict):
                continue
            endpoints = _service_endpoints(
                environment_url=workload.get("environment_url"),
                controller_base_url=controller_base_url,
                published_ports=workload.get("published_ports"),
            )
            workload["service_endpoints"] = endpoints
            workload["backend_monitoring_endpoints"] = [dict(item) for item in endpoints]

            # Preserve stronger provider-local suppression (for example the
            # authenticated Portainer controller itself). Environment scope is a
            # second, independent disposition layer.
            if workload.get("discovery_actionable") is False:
                continue
            provider_id = workload.get("environment_provider_id")
            if selected_ids and provider_id not in selected_ids:
                workload["discovery_actionable"] = False
                workload["discovery_suppression_reason"] = "environment_not_selected"
                workload["environment_selected"] = False
            else:
                workload["discovery_actionable"] = True
                workload["environment_selected"] = True
                if workload.get("discovery_suppression_reason") == "environment_not_selected":
                    workload.pop("discovery_suppression_reason", None)
        return inventory
