from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

from ...canonical_config import content_digest
from ...plugin_api import (
    CandidateDispositionChoice,
    CandidatePolicyChoice,
    CandidateReviewDescriptor,
    CandidateReviewPlan,
    FacetContext,
    ReplaceProviderConfigIntent,
)


class PortainerCandidateReview:
    """Provider-local review semantics for discovered Portainer workloads.

    Core supplies only detached canonical authority through ``FacetContext``.
    This facet describes review choices and emits bounded provider-config
    replacement intent; it never receives or commits a canonical store handle.
    """

    def describe_candidate(
        self,
        candidate: Any,
        context: FacetContext,
    ) -> CandidateReviewDescriptor | None:
        del context
        evidence = _candidate_source(candidate)
        if evidence is None or getattr(candidate, "kind", None) != "service":
            return None
        suggested = set(getattr(candidate, "suggested_capabilities", ()) or ())
        if "docker_workload" not in suggested:
            return None
        default_policy = _policy_hint(evidence) or "optional"
        return CandidateReviewDescriptor(
            plugin_id="portainer",
            group_label="Docker workload",
            policy_label="Availability policy",
            policy_choices=(
                CandidatePolicyChoice(value="optional", label="Optional"),
                CandidatePolicyChoice(value="required", label="Required"),
            ),
            default_policy=default_policy,
            durable_dispositions=(
                CandidateDispositionChoice(
                    value="ignore",
                    label="Ignore future discovery",
                ),
                CandidateDispositionChoice(
                    value="allow",
                    label="Allow future discovery",
                ),
            ),
        )

    def current_policy(
        self,
        obj: Mapping[str, Any],
        candidate: Any,
        context: FacetContext,
    ) -> str | None:
        del context
        evidence = _candidate_source(candidate)
        if evidence is None:
            return None
        matches = []
        for _capability_id, _provider_id, provider in _providers(obj):
            config = provider.get("config")
            if (
                provider.get("adapter") == "portainer"
                and isinstance(config, Mapping)
                and config.get("operation") == "workload"
                and config.get("workload_identity") == evidence.source_id
                and config.get("policy") in {"optional", "required"}
            ):
                matches.append(str(config["policy"]))
        return matches[0] if len(matches) == 1 else None

    def current_disposition(
        self,
        candidate: Any,
        context: FacetContext,
    ) -> str | None:
        evidence = _candidate_source(candidate)
        if evidence is None:
            return None
        try:
            _object_id, _capability_id, _provider_id, provider = _inventory_provider(
                context.current_config,
                context.site_id,
            )
        except ValueError:
            # Review descriptors can be rendered before a canonical inventory
            # provider exists (for example during staged onboarding). There is
            # no durable disposition to report in that state.
            return None
        current = provider.get("config")
        if not isinstance(current, Mapping):
            return None
        raw = current.get("ignored_workload_identities", [])
        if raw in (None, ""):
            raw = []
        if not isinstance(raw, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            raise ValueError("Portainer inventory ignored workload identities are invalid")
        identities = {item.strip() for item in raw}
        return "ignore" if evidence.source_id in identities else "allow"

    def plan_existing_policy(
        self,
        candidate: Any,
        *,
        object_id: str,
        policy: str,
        context: FacetContext,
    ) -> CandidateReviewPlan:
        if policy not in {"optional", "required"}:
            raise ValueError("Portainer workload policy must be optional or required")
        evidence = _candidate_source(candidate)
        if evidence is None:
            raise ValueError("Portainer workload discovery evidence is missing")
        obj = _object(context.current_config, context.site_id, object_id)
        matches: list[tuple[str, str, dict[str, Any]]] = []
        for capability_id, provider_id, provider in _providers(obj):
            config = provider.get("config")
            if (
                provider.get("adapter") == "portainer"
                and isinstance(config, dict)
                and config.get("operation") == "workload"
                and config.get("workload_identity") == evidence.source_id
                and config.get("policy") in {"optional", "required"}
            ):
                matches.append((capability_id, provider_id, provider))
        if len(matches) != 1:
            raise ValueError(
                "Portainer workload policy requires exactly one matching workload provider"
            )
        capability_id, provider_id, provider = matches[0]
        current = provider["config"]
        assert isinstance(current, dict)
        replacement = copy.deepcopy(current)
        replacement["policy"] = policy
        operations = ()
        changed_object_ids = ()
        if replacement != current:
            operations = (
                ReplaceProviderConfigIntent(
                    site_id=context.site_id,
                    object_id=object_id,
                    capability_id=capability_id,
                    provider_id=provider_id,
                    provider_config=replacement,
                    expected_config_hash=content_digest(current),
                ),
            )
            changed_object_ids = (object_id,)
        return CandidateReviewPlan(
            plugin_id="portainer",
            operations=operations,
            changed_object_ids=changed_object_ids,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            summary=f"Set Docker workload policy to {policy}",
        )

    def plan_durable_disposition(
        self,
        candidate: Any,
        *,
        disposition: str,
        context: FacetContext,
    ) -> CandidateReviewPlan:
        if disposition not in {"ignore", "allow"}:
            raise ValueError("Portainer durable disposition must be ignore or allow")
        evidence = _candidate_source(candidate)
        if evidence is None:
            raise ValueError("Portainer workload discovery evidence is missing")
        object_id, capability_id, provider_id, provider = _inventory_provider(
            context.current_config,
            context.site_id,
        )
        current = provider.get("config")
        assert isinstance(current, dict)
        raw = current.get("ignored_workload_identities", [])
        if raw in (None, ""):
            raw = []
        if not isinstance(raw, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            raise ValueError("Portainer inventory ignored workload identities are invalid")
        identities = {item.strip() for item in raw}
        if disposition == "ignore":
            identities.add(evidence.source_id)
        else:
            identities.discard(evidence.source_id)
        replacement = copy.deepcopy(current)
        if identities:
            replacement["ignored_workload_identities"] = sorted(identities)
        else:
            replacement.pop("ignored_workload_identities", None)
        operations = ()
        changed_object_ids = ()
        if replacement != current:
            operations = (
                ReplaceProviderConfigIntent(
                    site_id=context.site_id,
                    object_id=object_id,
                    capability_id=capability_id,
                    provider_id=provider_id,
                    provider_config=replacement,
                    expected_config_hash=content_digest(current),
                ),
            )
            changed_object_ids = (object_id,)
        return CandidateReviewPlan(
            plugin_id="portainer",
            operations=operations,
            changed_object_ids=changed_object_ids,
            expected_revision=context.current_revision,
            expected_config_hash=context.current_hash,
            summary=(
                "Ignore Docker workload in future discovery"
                if disposition == "ignore"
                else "Allow Docker workload in future discovery"
            ),
        )


def _candidate_source(candidate: Any):
    return next(
        (
            item
            for item in getattr(candidate, "evidence", ())
            if getattr(item, "source", None) == "portainer"
        ),
        None,
    )


def _policy_hint(evidence: Any) -> str | None:
    metadata = getattr(evidence, "metadata", {})
    explicit = metadata.get("policy_hint")
    if explicit in {"optional", "required"}:
        return str(explicit)
    hint = metadata.get("required_hint")
    if hint is True:
        return "required"
    if hint is False:
        return "optional"
    return None


def _site(config: Mapping[str, Any], site_id: str) -> Mapping[str, Any]:
    site = next(
        (
            item
            for item in config.get("sites", [])
            if isinstance(item, Mapping) and item.get("id") == site_id
        ),
        None,
    )
    if not isinstance(site, Mapping):
        raise ValueError(f"unknown Portainer review site {site_id}")
    return site


def _object(config: Mapping[str, Any], site_id: str, object_id: str) -> Mapping[str, Any]:
    obj = next(
        (
            item
            for item in _site(config, site_id).get("objects", [])
            if isinstance(item, Mapping) and item.get("id") == object_id
        ),
        None,
    )
    if not isinstance(obj, Mapping):
        raise ValueError(f"unknown Portainer review Object {object_id}")
    return obj


def _providers(obj: Mapping[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    for capability in obj.get("capabilities", []):
        if not isinstance(capability, Mapping) or not isinstance(capability.get("id"), str):
            continue
        for provider in capability.get("providers", []):
            if isinstance(provider, dict) and isinstance(provider.get("id"), str):
                yield str(capability["id"]), str(provider["id"]), provider


def _inventory_provider(
    config: Mapping[str, Any],
    site_id: str,
) -> tuple[str, str, str, dict[str, Any]]:
    matches: list[tuple[str, str, str, dict[str, Any]]] = []
    for obj in _site(config, site_id).get("objects", []):
        if not isinstance(obj, Mapping) or not isinstance(obj.get("id"), str):
            continue
        for capability_id, provider_id, provider in _providers(obj):
            provider_config = provider.get("config")
            if (
                provider.get("adapter") == "portainer"
                and isinstance(provider_config, dict)
                and provider_config.get("operation", "inventory") == "inventory"
            ):
                matches.append((str(obj["id"]), capability_id, provider_id, provider))
    if len(matches) != 1:
        raise ValueError(
            "Portainer durable discovery policy requires exactly one inventory provider; "
            f"found {len(matches)}"
        )
    return matches[0]
