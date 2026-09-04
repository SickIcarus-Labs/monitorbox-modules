from __future__ import annotations

from typing import Any, Mapping

_HTTPISH_TCP_PORTS = frozenset(
    {80, 443, 3000, 5000, 5055, 8000, 8080, 8443, 9000, 9443, 10443, 11080}
)
_TLS_HTTPISH_TCP_PORTS = frozenset({443, 8443, 9443, 10443})
_PORTAINER_CONTROLLER_REPOSITORIES = frozenset(
    {
        "portainer/portainer-ce",
        "portainer/portainer-ee",
    }
)


def _image_repository(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = text.split("@", 1)[0]
    slash = text.rfind("/")
    colon = text.rfind(":")
    if colon > slash:
        text = text[:colon]
    return text


def _image_repositories(workload: Mapping[str, Any]) -> set[str]:
    images = workload.get("images", [])
    if not isinstance(images, list):
        return set()
    return {
        repository
        for image in images
        if isinstance(image, str) and image.strip()
        if (repository := _image_repository(image))
    }


def is_portainer_controller_self(workload: Mapping[str, Any]) -> bool:
    """Recognize only this authenticated controller's local workload.

    A Portainer controller image in a remote Agent-backed environment can be a
    legitimate independent workload and must remain actionable. Portainer Agent
    images are likewise ordinary workloads. The self-dedup boundary therefore
    requires both provider-native local Unix-socket provenance and an exact
    official Portainer controller repository.
    """
    environment_url = str(workload.get("environment_url") or "").strip().casefold()
    if not environment_url.startswith("unix://"):
        return False
    return bool(_image_repositories(workload) & _PORTAINER_CONTROLLER_REPOSITORIES)


def _url_host(host: str) -> str:
    """Bracket IPv6 literals while preserving ordinary DNS/IPv4 hosts."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _http_service_endpoints(workload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = workload.get("service_endpoints", [])
    if not isinstance(raw, list):
        return ()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("protocol") or "tcp").strip().casefold() != "tcp":
            continue
        host = str(item.get("host") or "").strip()
        private_port = item.get("private_port")
        public_port = item.get("public_port")
        if (
            not host
            or isinstance(private_port, bool)
            or not isinstance(private_port, int)
            or private_port not in _HTTPISH_TCP_PORTS
            or isinstance(public_port, bool)
            or not isinstance(public_port, int)
            or not 1 <= public_port <= 65535
        ):
            continue
        scheme = "https" if private_port in _TLS_HTTPISH_TCP_PORTS else "http"
        result.append(
            {
                **dict(item),
                "scheme": scheme,
                "url": f"{scheme}://{_url_host(host)}:{public_port}",
            }
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                0 if item["scheme"] == "https" else 1,
                item["private_port"],
                item["public_port"],
                item["host"],
            ),
        )
    )


def connection_suggestions(workload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return bounded declarative downstream Connection suggestions.

    The provider owns product recognition and candidate semantics. Generic Core
    only materializes these descriptors after environment/System review.
    """
    if workload.get("discovery_actionable") is False or is_portainer_controller_self(workload):
        return ()

    result: list[dict[str, Any]] = []
    repositories = _image_repositories(workload)
    image_match = any(repository.rsplit("/", 1)[-1] == "scrypted" for repository in repositories)
    compose_service = str(workload.get("compose_service") or "").strip().casefold()
    service_match = compose_service == "scrypted"
    http_endpoints = _http_service_endpoints(workload)
    preferred_endpoint = http_endpoints[0]["url"] if http_endpoints else None

    if image_match or service_match:
        signal = "container image" if image_match else "Compose service identity"
        result.append({
            "adapter": "scrypted",
            "preset": "scrypted",
            "label": "Scrypted",
            "reason": f"Detected Scrypted from Portainer {signal}.",
            "candidate_kind": "scrypted",
            "candidate_endpoint": preferred_endpoint or "manual://scrypted",
            "candidate_confidence": "detected",
            "candidate_default_selected": True,
            "candidate_label_prefix": "Scrypted",
            "suppress_if_adapter_present": "scrypted",
        })

    if http_endpoints:
        display = ", ".join(item["url"] for item in http_endpoints[:4])
        result.append({
            "adapter": "http",
            "preset": "http_service",
            "label": "HTTP(S)",
            "reason": (
                "Portainer reports externally published TCP service endpoint(s) "
                f"whose container port is commonly used for HTTP(S): {display}."
            ),
            "candidate_kind": "http",
            "candidate_endpoint": preferred_endpoint,
            "candidate_endpoints": [item["url"] for item in http_endpoints],
            "candidate_confidence": "possible",
            "candidate_default_selected": False,
            "candidate_label_prefix": "HTTP(S)",
        })
    return tuple(result)


def recursive_suggestions(observation: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    metadata = observation.get("metadata")
    if not isinstance(metadata, Mapping):
        return ()
    workloads = metadata.get("workloads")
    if not isinstance(workloads, list):
        return ()
    output: list[dict[str, Any]] = []
    for workload in workloads:
        if not isinstance(workload, Mapping):
            continue
        environment_key = _optional_text(workload.get("environment_key"))
        workload_identity = _optional_text(workload.get("identity"))
        workload_label = _optional_text(workload.get("label"))
        if not environment_key or not workload_identity or not workload_label:
            continue
        for suggestion in connection_suggestions(workload):
            output.append({
                "environment_key": environment_key,
                "workload_identity": workload_identity,
                "workload_label": workload_label,
                **suggestion,
            })
    return tuple(output)


def generic_workload_evidence(workloads: Any, *, authoritative: bool) -> list[dict[str, Any]]:
    """Project authenticated Portainer workload rows into generic discovery evidence."""
    if not isinstance(workloads, list):
        return []
    result: list[dict[str, Any]] = []
    for workload in workloads:
        if not isinstance(workload, Mapping):
            continue
        if workload.get("discovery_actionable") is False or is_portainer_controller_self(workload):
            continue
        identity = workload.get("identity")
        label = workload.get("label")
        if not isinstance(identity, str) or not identity or not isinstance(label, str) or not label:
            continue
        metadata = dict(workload)
        metadata["authoritative"] = authoritative
        required_hint = workload.get("required_hint")
        if required_hint is True:
            metadata["policy_hint"] = "required"
        elif required_hint is False:
            metadata["policy_hint"] = "optional"
        suggestions = connection_suggestions(workload)
        if suggestions:
            metadata["connection_suggestions"] = [dict(item) for item in suggestions]
        result.append({
            "source": "portainer",
            "source_id": identity,
            "kind": "service",
            "label": label,
            "confidence": 95,
            "addresses": [],
            "suggested_capabilities": ["docker_workload"],
            "metadata": metadata,
        })
    return result


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
