from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from monitorbox.v2.canonical_store import CanonicalConfigStore
from monitorbox.v2.secret_store import ProtectedSecretStore

_DEFAULT_CONFIG_ROOT = Path("/config")
_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"
_LEGACY_USERNAME_SECRET = "scrypted_username"
_LEGACY_PASSWORD_SECRET = "scrypted_password"


def _config_root() -> Path:
    raw = os.environ.get("MONITORBOX_CONFIG_ROOT")
    return Path(raw) if raw else _DEFAULT_CONFIG_ROOT


def _credential_value(store: ProtectedSecretStore, secret_id: str, label: str) -> str:
    value = store.read(secret_id).rstrip("\r\n")
    if not value:
        raise RuntimeError(f"Scrypted {label} credential is empty")
    return value


def _base_url(raw: Any, object_address: Any) -> str:
    if raw in (None, ""):
        if not isinstance(object_address, str) or not object_address.strip():
            raise RuntimeError("Scrypted legacy control has no base URL or object address")
        raw = f"https://{object_address.strip()}:10443"
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Scrypted base URL is invalid")
    value = raw.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Scrypted base URL must use http or https")
    return value


def _socket(raw: Any) -> str:
    value = str(raw or _DEFAULT_SOCKET).strip()
    if not value.startswith("/"):
        raise RuntimeError("Scrypted socket must be an absolute path")
    path = Path(value)
    runtime_root = Path("/run/monitorbox-scrypted")
    try:
        path.relative_to(runtime_root)
    except ValueError as exc:
        raise RuntimeError(f"Scrypted socket must live below {runtime_root}") from exc
    return str(path)


def _excluded(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return tuple(item.strip() for item in value if item.strip())
    raise RuntimeError("Scrypted excluded camera names must be strings")


def _inventory_candidates(document: Mapping[str, Any]):
    for site in document.get("sites", []):
        if not isinstance(site, Mapping):
            continue
        site_id = str(site.get("id") or "").strip()
        for obj in site.get("objects", []):
            if not isinstance(obj, Mapping):
                continue
            for capability in obj.get("capabilities", []):
                if not isinstance(capability, Mapping) or capability.get("enabled", True) is False:
                    continue
                for provider in capability.get("providers", []):
                    if not isinstance(provider, Mapping):
                        continue
                    if provider.get("enabled", True) is False or provider.get("adapter") != "scrypted":
                        continue
                    config = provider.get("config", {})
                    if isinstance(config, Mapping) and config.get("operation") == "inventory":
                        yield site_id, obj, config


def resolve_legacy_worker_config() -> dict[str, Any] | None:
    """Reconstruct stripped early-2.1 worker control from canonical authority.

    This is deliberately module-owned migration compatibility. Core exposes only
    generic canonical configuration and protected-secret storage; it contains no
    Scrypted provider policy or fallback implementation.
    """
    root = _config_root()
    store = CanonicalConfigStore(root)
    if not store.exists():
        return None
    document = store.load().data
    runtime = document.get("runtime")
    local_agent = runtime.get("local_agent") if isinstance(runtime, Mapping) else None
    credential_refs = (
        local_agent.get("credential_secret_refs", {})
        if isinstance(local_agent, Mapping)
        else {}
    )
    if not isinstance(credential_refs, Mapping):
        credential_refs = {}
    secrets = ProtectedSecretStore(root)

    candidates: list[dict[str, Any]] = []
    for site_id, obj, config in _inventory_candidates(document):
        username_env = config.get("username_env")
        password_env = config.get("password_env")
        if username_env is not None or password_env is not None:
            if not isinstance(username_env, str) or not username_env.strip():
                raise RuntimeError("Scrypted canonical username_env is incomplete")
            if not isinstance(password_env, str) or not password_env.strip():
                raise RuntimeError("Scrypted canonical password_env is incomplete")
            username_ref = credential_refs.get(username_env)
            password_ref = credential_refs.get(password_env)
            if not isinstance(username_ref, str) or not username_ref:
                raise RuntimeError("Scrypted canonical username secret reference is unavailable")
            if not isinstance(password_ref, str) or not password_ref:
                raise RuntimeError("Scrypted canonical password secret reference is unavailable")
            username_label = username_env.strip()
            password_label = password_env.strip()
        else:
            username_ref = _LEGACY_USERNAME_SECRET
            password_ref = _LEGACY_PASSWORD_SECRET
            if not secrets.exists(username_ref) or not secrets.exists(password_ref):
                raise RuntimeError("Scrypted legacy protected credentials are unavailable")
            username_label = f"secret:{username_ref}"
            password_label = f"secret:{password_ref}"

        candidate = {
            "site_id": site_id,
            "base_url": _base_url(config.get("base_url"), obj.get("address")),
            "socket": _socket(config.get("socket")),
            "excluded_camera_names": _excluded(config.get("excluded_camera_names")),
            "username_env": username_label,
            "username": _credential_value(secrets, username_ref, "username"),
            "password_env": password_label,
            "password": _credential_value(secrets, password_ref, "password"),
        }
        candidates.append(candidate)

    if not candidates:
        return None

    def identity(item: Mapping[str, Any]) -> str:
        comparable = {
            "base_url": item["base_url"],
            "socket": item["socket"],
            "excluded_camera_names": list(item["excluded_camera_names"]),
            "username_env": item["username_env"],
            "password_env": item["password_env"],
        }
        return json.dumps(comparable, sort_keys=True, separators=(",", ":"))

    if len({identity(item) for item in candidates}) != 1:
        raise RuntimeError("canonical authority contains divergent Scrypted worker configurations")
    result = dict(candidates[0])
    result.pop("site_id", None)
    return result


__all__ = ["resolve_legacy_worker_config"]
