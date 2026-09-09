"""Configuration/Bootstrap Phase-3 local-control-plane projection.

The controller's in-container listener is not the operator-facing LAN identity:
Docker commonly binds a wildcard listener inside the container. Bootstrap instead
projects the already-canonical appliance identity from the controller self-object
and its monitored System address. No interface probing, Host-header inference,
or provider-specific heuristics are admitted.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

from aiohttp import web


_UNUSABLE_HOSTS = frozenset({"0.0.0.0", "::", "localhost"})


def _safe_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    host = value.strip()
    if not host:
        return None
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    folded = host.casefold().rstrip(".")
    if not folded or folded in _UNUSABLE_HOSTS:
        return None
    if any(token in host for token in ("/", "\\", "://", "@", "?", "#")):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = folded.split(".")
        if any(
            not label
            or len(label) > 63
            or label[0] == "-"
            or label[-1] == "-"
            or any(not (char.isalnum() or char == "-") for char in label)
            for label in labels
        ):
            return None
        return folded
    if address.is_unspecified or address.is_loopback:
        return None
    return address.compressed


def _port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _self_object_address(data: Mapping[str, Any], controller: Mapping[str, Any]) -> str | None:
    identity = controller.get("self_object")
    if not isinstance(identity, Mapping):
        return None
    site_id = identity.get("site_id")
    object_id = identity.get("object_id")
    if not isinstance(site_id, str) or not isinstance(object_id, str):
        return None
    sites = data.get("sites")
    if not isinstance(sites, list):
        return None
    for site in sites:
        if not isinstance(site, Mapping) or site.get("id") != site_id:
            continue
        objects = site.get("objects")
        if not isinstance(objects, list):
            return None
        for obj in objects:
            if isinstance(obj, Mapping) and obj.get("id") == object_id:
                return _safe_host(obj.get("address"))
        return None
    return None


def local_access(document: Any) -> dict[str, Any]:
    """Project explicit canonical local-access authority, or fail closed."""

    data = getattr(document, "data", document)
    if not isinstance(data, Mapping):
        data = {}
    runtime = data.get("runtime")
    controller = runtime.get("controller") if isinstance(runtime, Mapping) else None
    controller = controller if isinstance(controller, Mapping) else {}

    # Prefer the canonical self object's externally meaningful address. A
    # non-wildcard runtime listener is a bounded fallback for deployments that
    # explicitly bind the controller itself to a LAN address.
    host = _self_object_address(data, controller)
    source = "canonical-self-object"
    if host is None:
        host = _safe_host(controller.get("listen_address"))
        source = "canonical-controller-listener"
    port = _port(controller.get("listen_port"))
    if host is None or port is None:
        return {
            "available": False,
            "role": "local-control-plane",
            "reason": "canonical local controller address is not configured",
        }

    display_host = f"[{host}]" if ":" in host else host
    return {
        "available": True,
        "role": "local-control-plane",
        "scheme": "http",
        "host": host,
        "port": port,
        "local_url": f"http://{display_host}:{port}",
        "source": source,
    }


class LocalAccessUi:
    """Read-only Bootstrap-owned projection of canonical local access."""

    def __init__(self, platform: Any) -> None:
        self.platform = platform

    async def get(self, _request: web.Request) -> web.Response:
        return web.json_response(local_access(self.platform.store.load()))

    def install(self, app: web.Application) -> None:
        app.router.add_get("/api/v2/config/local-access", self.get)


__all__ = ["LocalAccessUi", "local_access"]
