from __future__ import annotations

import asyncio
import copy
import os
import secrets
from typing import Any, Mapping

from ...operator_ontology import SYSTEM_KINDS
from ...plugin_api import (
    ConnectionRequest,
    FacetContext,
    RuntimeExecutionContext,
    RuntimeExecutionRequest,
    ValidationResult,
)
from .endpoint_provenance import PortainerEndpointRuntimeExecutor
from .onboarding import _normalized
from .reconciliation import reconcile_portainer_environments
from .suggestions import recursive_suggestions

_PORTAINER_MODULE_ID = "com.sickicarus.monitorbox.portainer"
_VALIDATION_ENV_LOCK = asyncio.Lock()
_ACCEPTED_STATES = frozenset({"healthy", "degraded"})
_TLS_TRUST_MARKERS = (
    "self-signed certificate",
    "self signed certificate",
    "unable to get local issuer certificate",
    "unable to verify the first certificate",
    "certificate chain too long",
    "unknown ca",
    "certificate verify failed",
)


class PortainerValidation:
    """Provider-owned Portainer credential/inventory validation."""

    async def validate(
        self,
        request: ConnectionRequest,
        context: FacetContext,
    ) -> ValidationResult:
        values = _normalized(request)
        strict = await self._execute(
            values,
            context,
            verify_tls=values["verify_tls"],
        )
        result = strict
        fallback = False
        if (
            values["verify_tls"]
            and strict["state"] not in _ACCEPTED_STATES
            and _is_trust_chain_failure(strict)
        ):
            result = await self._execute(values, context, verify_tls=False)
            fallback = result["state"] in _ACCEPTED_STATES

        public = copy.deepcopy(result)
        metadata = public.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            public["metadata"] = metadata
        metadata.setdefault("provider", "portainer")
        if fallback:
            metadata["tls_trust_fallback"] = True

        state = str(public.get("state") or "failed")
        accepted = state in _ACCEPTED_STATES
        if accepted:
            reconciliation = await asyncio.to_thread(
                reconcile_portainer_environments,
                _systems(context),
                public,
                owning_system_id=request.candidate.system_id,
            )
            recursive = recursive_suggestions(public)
            metadata["authenticated_discovery"] = {
                "system_id": request.candidate.system_id,
                "kind": "portainer",
                "endpoint": request.candidate.endpoint,
                "requires_operator": reconciliation.requires_operator,
                "reconciliation": reconciliation.public(),
                "recursive_connection_suggestions": [
                    dict(item) for item in recursive
                ],
            }

        summary = str(
            public.get("summary") or "Portainer validation completed"
        )[:400]
        if fallback:
            summary = (
                "Validated after accepting the provider's untrusted local TLS certificate: "
                + summary
            )[:400]
        return ValidationResult(
            accepted=accepted,
            state=state,
            summary=summary,
            observation=public,
            metadata={
                "transport": "portainer",
                "tls_trust_fallback": fallback,
            },
            values={
                "base_url": values["base_url"],
                "label": values["label"],
                "verify_tls": False if fallback else values["verify_tls"],
                "environment_ids": list(values["environment_ids"]),
            },
        )

    async def _execute(
        self,
        values: dict[str, Any],
        context: FacetContext,
        *,
        verify_tls: bool,
    ) -> dict[str, Any]:
        env_name = (
            "MONITORBOX_ONBOARDING_PORTAINER_"
            f"{secrets.token_hex(12).upper()}"
        )
        executor = PortainerEndpointRuntimeExecutor()
        execution_context = RuntimeExecutionContext(
            module_id=_PORTAINER_MODULE_ID,
            package_root="",
            state_root="",
        )
        execution = RuntimeExecutionRequest(
            check_id="portainer_validation",
            object_id=context.site_id,
            adapter="portainer",
            timeout_seconds=15,
            options={
                "base_url": values["base_url"],
                "api_key_env": env_name,
                "operation": "inventory",
                "verify_tls": verify_tls,
                **(
                    {"environment_ids": list(values["environment_ids"])}
                    if values["environment_ids"]
                    else {}
                ),
            },
        )
        async with _VALIDATION_ENV_LOCK:
            previous = os.environ.get(env_name)
            try:
                os.environ[env_name] = values["api_key"]
                await executor.start(execution_context)
                try:
                    async with asyncio.timeout(execution.timeout_seconds):
                        result = await executor.execute(
                            execution,
                            execution_context,
                        )
                except TimeoutError:
                    return {
                        "state": "failed",
                        "summary": "Timed out after 15s",
                        "duration_ms": 15000,
                        "metrics": {},
                        "metadata": {
                            "provider": "portainer",
                            "authoritative": False,
                        },
                    }
                finally:
                    await executor.close(execution_context)
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous
        return result.public()


def _systems(context: FacetContext) -> list[dict[str, Any]]:
    site = next(
        (
            item
            for item in context.current_config.get("sites", [])
            if isinstance(item, Mapping) and item.get("id") == context.site_id
        ),
        None,
    )
    if not isinstance(site, Mapping):
        return []
    return [
        dict(item)
        for item in site.get("objects", [])
        if isinstance(item, Mapping)
        and str(item.get("kind") or "").casefold() in SYSTEM_KINDS
    ]


def _is_trust_chain_failure(result: dict[str, Any]) -> bool:
    summary = str(result.get("summary") or "").casefold()
    if (
        "certificate" not in summary
        and "ssl" not in summary
        and "tls" not in summary
    ):
        return False
    hard = (
        "hostname mismatch",
        "doesn't match",
        "does not match",
        "expired",
        "not yet valid",
    )
    if any(marker in summary for marker in hard):
        return False
    return any(marker in summary for marker in _TLS_TRUST_MARKERS)
