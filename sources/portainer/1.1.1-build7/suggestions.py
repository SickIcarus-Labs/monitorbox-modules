from __future__ import annotations

from typing import Any, Mapping

_PORTAINER_CONTROLLER_REPOSITORIES = frozenset(
    {
        "portainer/portainer-ce",
        "portainer/portainer-ee",
    }
)
_PROVIDER_MONITORING_COVERAGE = {
    "status": "covered",
    "kind": "provider_inventory",
    "source_label": "Portainer",
}


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
    """Recognize only this authenticated controller's local workload."""
    environment_url = str(workload.get("environment_url") or "").strip().casefold()
    if not environment_url.startswith("unix://"):
        return False
    return bool(_image_repositories(workload) & _PORTAINER_CONTROLLER_REPOSITORIES)


def _backend_monitoring_endpoints(workload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return transport-only backend evidence without inventing application protocol."""
    raw = workload.get("backend_monitoring_endpoints")
    if not isinstance(raw, list):
        raw = workload.get("service_endpoints", [])
    if not isinstance(raw, list):
        return ()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("endpoint_role") or "backend_monitoring") != "backend_monitoring":
            continue
        if str(item.get("protocol") or "tcp").strip().casefold() != "tcp":
            continue
        host = str(item.get("host") or "").strip()
        public_port = item.get("public_port")
        if (
            not host
            or isinstance(public_port, bool)
            or not isinstance(public_port, int)
            or not 1 <= public_port <= 65535
        ):
            continue
        result.append(dict(item))
    return tuple(
        sorted(
            result,
            key=lambda item: (
                str(item.get("host") or ""),
                int(item.get("public_port") or 0),
                int(item.get("private_port") or 0),
            ),
        )
    )


def connection_suggestions(workload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return bounded downstream Connection suggestions.

    Published Docker TCP ports are backend transport evidence only. Portainer
    does not know whether a TCP listener is HTTP, HTTPS, or another application
    protocol, so this module must never synthesize a web URL from a port number.
    Product-specific recognition may still propose that product, but its endpoint
    remains manual unless separate semantic evidence supplies a safe URL.
    """
    if workload.get("discovery_actionable") is False or is_portainer_controller_self(workload):
        return ()

    result: list[dict[str, Any]] = []
    repositories = _image_repositories(workload)
    image_match = any(repository.rsplit("/", 1)[-1] == "scrypted" for repository in repositories)
    compose_service = str(workload.get("compose_service") or "").strip().casefold()
    service_match = compose_service == "scrypted"

    if image_match or service_match:
        signal = "container image" if image_match else "Compose service identity"
        result.append({
            "adapter": "scrypted",
            "preset": "scrypted",
            "label": "Scrypted",
            "reason": f"Detected Scrypted from Portainer {signal}.",
            "candidate_kind": "scrypted",
            "candidate_endpoint": "manual://scrypted",
            "candidate_confidence": "detected",
            "candidate_default_selected": True,
            "candidate_label_prefix": "Scrypted",
            "suppress_if_adapter_present": "scrypted",
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
        metadata["monitoring_coverage"] = dict(_PROVIDER_MONITORING_COVERAGE)
        required_hint = workload.get("required_hint")
        if required_hint is True:
            metadata["policy_hint"] = "required"
        elif required_hint is False:
            metadata["policy_hint"] = "optional"
        suggestions = connection_suggestions(workload)
        if suggestions:
            metadata["connection_suggestions"] = [dict(item) for item in suggestions]
        suggested_capabilities = ["docker_workload"]
        if len(_backend_monitoring_endpoints(workload)) == 1:
            suggested_capabilities.append("backend_transport")
        result.append({
            "source": "portainer",
            "source_id": identity,
            "kind": "service",
            "label": label,
            "confidence": 95,
            "addresses": [],
            "suggested_capabilities": suggested_capabilities,
            "metadata": metadata,
        })
    return result


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
