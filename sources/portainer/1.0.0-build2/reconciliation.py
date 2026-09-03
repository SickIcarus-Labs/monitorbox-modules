from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from ...canonical_config import CanonicalConfigError


@dataclass(frozen=True, slots=True)
class PortainerEnvironmentReconciliation:
    provider_id: int
    environment_key: str
    environment_name: str
    environment_url: str | None
    environment_host: str | None
    status: str
    matched_system_id: str | None
    candidate_system_ids: tuple[str, ...]
    evidence: str
    suggested_system: Mapping[str, str] | None = None

    @property
    def auto_associated(self) -> bool:
        return self.status == "matched" and self.matched_system_id is not None

    @property
    def needs_operator(self) -> bool:
        return self.status in {"needs_confirmation", "ambiguous", "unmatched"}

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider_id": self.provider_id,
            "environment_key": self.environment_key,
            "environment_name": self.environment_name,
            "environment_url": self.environment_url,
            "environment_host": self.environment_host,
            "status": self.status,
            "auto_associated": self.auto_associated,
            "candidate_system_ids": list(self.candidate_system_ids),
            "evidence": self.evidence,
        }
        if self.matched_system_id is not None:
            payload["matched_system_id"] = self.matched_system_id
        if self.suggested_system is not None:
            payload["suggested_system"] = dict(self.suggested_system)
        return payload


@dataclass(frozen=True, slots=True)
class PortainerReconciliationResult:
    environments: tuple[PortainerEnvironmentReconciliation, ...]

    @property
    def requires_operator(self) -> bool:
        return any(item.needs_operator for item in self.environments)

    def system_for_environment(self, environment_key: str) -> str | None:
        key = str(environment_key or "").strip().casefold()
        matches = [
            item.matched_system_id
            for item in self.environments
            if item.environment_key.casefold() == key and item.auto_associated
        ]
        return matches[0] if len(matches) == 1 else None

    def public(self) -> dict[str, Any]:
        return {
            "kind": "portainer_environments",
            "requires_operator": self.requires_operator,
            "environments": [item.public() for item in self.environments],
        }


def reconcile_portainer_environments(
    systems: Iterable[Mapping[str, Any]],
    observation: Mapping[str, Any],
    *,
    owning_system_id: str | None = None,
) -> PortainerReconciliationResult:
    declared = tuple(_declared_system(row) for row in systems)
    by_id = {item.id: item for item in declared}
    owner = by_id.get(str(owning_system_id or ""))

    metadata = observation.get("metadata")
    if not isinstance(metadata, Mapping) or str(metadata.get("provider") or "").casefold() != "portainer":
        raise CanonicalConfigError("Portainer reconciliation requires a Portainer validation observation")
    raw_environments = metadata.get("environments")
    if not isinstance(raw_environments, list):
        raise CanonicalConfigError("Portainer validation observation has no environment inventory")

    rows: list[PortainerEnvironmentReconciliation] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_environments, start=1):
        if not isinstance(raw, Mapping):
            raise CanonicalConfigError(f"Portainer environment {index} must be a mapping")
        provider_id = raw.get("provider_id")
        if isinstance(provider_id, bool) or not isinstance(provider_id, int):
            raise CanonicalConfigError(f"Portainer environment {index} has no numeric provider id")
        name = _required_text(raw.get("name"), f"Portainer environment {index} name")
        key = _required_text(raw.get("key"), f"Portainer environment {index} key")
        folded_key = key.casefold()
        if folded_key in seen_keys:
            raise CanonicalConfigError(f"Portainer environment key {key!r} is duplicated")
        seen_keys.add(folded_key)
        url = _optional_text(raw.get("url"))
        host = _endpoint_host(url) if url is not None else None
        rows.append(
            _reconcile_one(
                provider_id=provider_id,
                key=key,
                name=name,
                url=url,
                host=host,
                systems=declared,
                owner=owner,
            )
        )
    rows.sort(key=lambda item: (item.environment_name.casefold(), item.provider_id))
    return PortainerReconciliationResult(tuple(rows))


@dataclass(frozen=True, slots=True)
class _DeclaredSystem:
    id: str
    label: str
    address: str | None
    normalized_address: str | None
    resolved_addresses: frozenset[str]
    name_tokens: frozenset[str]


def _declared_system(row: Mapping[str, Any]) -> _DeclaredSystem:
    if not isinstance(row, Mapping):
        raise CanonicalConfigError("declared System reconciliation input must be a mapping")
    system_id = _required_text(row.get("id"), "declared System id")
    label = _required_text(row.get("label"), f"declared System {system_id} label")
    address = _optional_text(row.get("address"))
    tokens = frozenset(
        token
        for source in (system_id, label)
        for token in _name_tokens(source)
        if _useful_name_token(token)
    )
    return _DeclaredSystem(
        id=system_id,
        label=label,
        address=address,
        normalized_address=_normalize_host(address) if address else None,
        resolved_addresses=_resolved_addresses(address),
        name_tokens=tokens,
    )


def _reconcile_one(
    *,
    provider_id: int,
    key: str,
    name: str,
    url: str | None,
    host: str | None,
    systems: tuple[_DeclaredSystem, ...],
    owner: _DeclaredSystem | None,
) -> PortainerEnvironmentReconciliation:
    normalized_host = _normalize_host(host) if host else None
    host_addresses = _resolved_addresses(host)
    is_unix = _is_unix_url(url)
    address_matches = [
        item
        for item in systems
        if normalized_host is not None
        and (item.normalized_address == normalized_host or bool(host_addresses & item.resolved_addresses))
    ]
    env_tokens = frozenset(token for token in _name_tokens(name) if _useful_name_token(token))
    name_matches = [item for item in systems if env_tokens and bool(env_tokens & item.name_tokens)]
    owner_matches = [owner] if is_unix and owner is not None else []
    address_ids = {item.id for item in address_matches}
    name_ids = {item.id for item in name_matches}
    owner_ids = {item.id for item in owner_matches}
    candidates = tuple(sorted(address_ids | name_ids | owner_ids))

    if owner_matches:
        matched = owner_matches[0]
        conflicts = (address_ids | name_ids) - {matched.id}
        if not conflicts:
            return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "matched", matched.id, (matched.id,), f"Local Portainer Unix-socket environment belongs to the declared System {matched.label!r} that owns this Portainer controller.")
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "ambiguous", None, candidates, "Local Portainer controller ownership conflicts with other environment evidence; operator confirmation is required.")

    if len(address_matches) == 1:
        match = address_matches[0]
        conflicts = name_ids - {match.id}
        if not conflicts:
            evidence = (
                f"Portainer environment URL host {host!r} matches declared System {match.label!r}."
                if match.normalized_address == normalized_host
                else f"Portainer environment URL host {host!r} resolves to the same address as declared System {match.label!r}."
            )
            return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "matched", match.id, (match.id,), evidence)
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "ambiguous", None, candidates, "Portainer URL/address evidence and environment-name evidence point to different declared Systems; operator confirmation is required.")

    if len(address_matches) > 1:
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "ambiguous", None, candidates, f"Portainer environment URL host {host!r} maps to more than one declared System; operator confirmation is required.")

    if is_unix and len(name_matches) == 1:
        match = name_matches[0]
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "matched", match.id, (match.id,), f"Local Unix-socket environment name uniquely identifies declared System {match.label!r}.")
    if len(name_matches) == 1:
        match = name_matches[0]
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "needs_confirmation", None, (match.id,), f"Portainer environment name references declared System {match.label!r}, but endpoint evidence does not independently confirm it.")
    if len(name_matches) > 1:
        return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "ambiguous", None, candidates, "Portainer environment name references more than one declared System; operator confirmation is required.")
    suggestion = {"label": name, "address": host} if host else None
    return PortainerEnvironmentReconciliation(provider_id, key, name, url, host, "unmatched", None, (), "No declared System has trustworthy ownership, address/alias, or unique name evidence for this Portainer environment.", suggestion)


def _endpoint_host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    return parsed.hostname


def _is_unix_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        return urlsplit(value).scheme.casefold() == "unix"
    except ValueError:
        return False


def _normalize_host(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().strip("[]").rstrip(".").casefold()
    if not text:
        return None
    try:
        return ipaddress.ip_address(text).compressed.casefold()
    except ValueError:
        return text


def _resolved_addresses(value: str | None) -> frozenset[str]:
    normalized = _normalize_host(value)
    if not normalized:
        return frozenset()
    try:
        return frozenset({ipaddress.ip_address(normalized).compressed.casefold()})
    except ValueError:
        pass
    addresses: set[str] = set()
    try:
        rows = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return frozenset()
    for row in rows:
        sockaddr = row[4]
        if not sockaddr:
            continue
        try:
            addresses.add(ipaddress.ip_address(str(sockaddr[0])).compressed.casefold())
        except ValueError:
            continue
    return frozenset(addresses)


def _name_tokens(value: Any) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", str(value or "").casefold()) if token)


def _useful_name_token(value: str) -> bool:
    return len(value) >= 4 and value not in {"broad", "leaf", "testlab", "local", "docker", "environment", "server", "system", "host"}


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalConfigError(f"{field} must be non-empty text")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise CanonicalConfigError("Portainer environment URL must be text")
    return value.strip() or None
