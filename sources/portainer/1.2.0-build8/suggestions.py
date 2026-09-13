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
_MAX_FACT_VALUES = 16
_MAX_FACT_TEXT = 512


def _bounded_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:_MAX_FACT_TEXT]


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
    """Compatibility shim: provider inventory no longer names downstream products."""
    del workload
    return ()


def recursive_suggestions(observation: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Compatibility shim retained while generic catalog matching replaces this seam."""
    del observation
    return ()


def _capability_facts(workload: Mapping[str, Any]) -> dict[str, Any]:
    """Project only bounded provider-neutral workload facts for catalog matching."""
    facts: dict[str, Any] = {}

    raw_images = workload.get("images", [])
    if isinstance(raw_images, list):
        images: list[str] = []
        for raw in raw_images:
            text = _bounded_text(raw)
            if text is None or text in images:
                continue
            images.append(text)
            if len(images) >= _MAX_FACT_VALUES:
                break
        if images:
            facts["workload.image"] = images

    compose_service = _bounded_text(workload.get("compose_service"))
    if compose_service is not None:
        facts["workload.compose_service"] = compose_service

    deployment_kind = _bounded_text(workload.get("deployment_kind"))
    if deployment_kind is not None:
        facts["workload.deployment_kind"] = deployment_kind

    containers = workload.get("containers", [])
    if isinstance(containers, list) and containers:
        states = [
            str(item.get("state") or "").strip().casefold()
            for item in containers
            if isinstance(item, Mapping)
        ]
        if states:
            facts["workload.running"] = all(state == "running" for state in states)

    raw_ports = workload.get("published_ports", [])
    if isinstance(raw_ports, list):
        ports: set[int] = set()
        for item in raw_ports:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("protocol") or "tcp").strip().casefold() != "tcp":
                continue
            for key in ("public_port", "private_port"):
                value = item.get(key)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 1 <= value <= 65535
                ):
                    ports.add(value)
        if ports:
            facts["network.port"] = sorted(ports)[:_MAX_FACT_VALUES]

    return facts


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
        suggested_capabilities = ["docker_workload"]
        if len(_backend_monitoring_endpoints(workload)) == 1:
            suggested_capabilities.append("backend_transport")
        evidence = {
            "source": "portainer",
            "source_id": identity,
            "kind": "workload",
            "label": label,
            "confidence": 95,
            "addresses": [],
            "suggested_capabilities": suggested_capabilities,
            "metadata": metadata,
        }
        capability_facts = _capability_facts(workload)
        if capability_facts:
            evidence["capability_facts"] = capability_facts
        result.append(evidence)
    return result
