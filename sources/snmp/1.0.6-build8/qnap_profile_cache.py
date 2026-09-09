from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

CACHE_SCHEMA = 1
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_CACHE_DIRECTORY = "qnap-platform-profiles"
_SALT_FILENAME = ".identity-salt"
_RECOGNIZED_PROFILES = frozenset({"quts_hero", "qts"})


def classify_qnap_firmware(value: str) -> str:
    """Return a conservative platform profile from authoritative firmware text."""
    text = str(value or "").strip().strip('"')
    if not text:
        return "unknown"
    lowered = text.casefold()
    if lowered.startswith("h") and len(lowered) > 2 and lowered[1].isdigit() and "." in lowered:
        return "quts_hero"
    if lowered[0].isdigit() and "." in lowered:
        return "qts"
    return "unknown"


def _environment_value(options: Mapping[str, Any], key: str) -> tuple[str, str]:
    name = str(options.get(key) or "").strip()
    if not name:
        return "", ""
    return name, os.environ.get(name, "")


def _security_material(options: Mapping[str, Any]) -> dict[str, Any]:
    version = str(options.get("version", "3")).strip().casefold()
    if version in {"1", "2", "2c"}:
        name, value = _environment_value(options, "community_env")
        return {
            "version": version,
            "community_env": name,
            "community": value,
        }

    username_name, username = _environment_value(options, "username_env")
    auth_name, auth_password = _environment_value(options, "auth_password_env")
    privacy_name, privacy_password = _environment_value(options, "privacy_password_env")
    return {
        "version": version,
        "username_env": username_name,
        "username": username,
        "auth_password_env": auth_name,
        "auth_password": auth_password,
        "auth_protocol": str(options.get("auth_protocol", "SHA")).strip().upper(),
        "privacy_password_env": privacy_name,
        "privacy_password": privacy_password,
        "privacy_protocol": str(options.get("privacy_protocol", "AES")).strip().upper(),
    }


class QnapPlatformProfileCache:
    """Durable fallback evidence for QNAP platform identity.

    Cache files contain only an HMAC identity token plus non-secret provider
    evidence. Resolved credentials participate in the token so a credential
    change cannot inherit a prior classification, but credential material is
    never persisted.
    """

    def __init__(self, state_root: str, *, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.root = Path(state_root) / _CACHE_DIRECTORY
        self.ttl_seconds = max(1.0, float(ttl_seconds))

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _salt(self) -> bytes:
        self._ensure_root()
        path = self.root / _SALT_FILENAME
        try:
            payload = path.read_bytes()
            if len(payload) == 32:
                return payload
        except FileNotFoundError:
            pass

        payload = os.urandom(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            existing = path.read_bytes()
            if len(existing) != 32:
                raise OSError("SNMP QNAP profile identity salt is invalid")
            return existing
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return payload

    def identity_key(
        self,
        *,
        host: str,
        port: int,
        options: Mapping[str, Any],
    ) -> str:
        material = {
            "host": str(host).strip().casefold(),
            "port": int(port),
            "security": _security_material(options),
        }
        canonical = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(self._salt(), canonical, hashlib.sha256).hexdigest()

    def _path(self, identity_key: str) -> Path:
        if len(identity_key) != 64 or any(ch not in "0123456789abcdef" for ch in identity_key):
            raise ValueError("invalid QNAP profile cache identity")
        return self.root / f"{identity_key}.json"

    def recall(self, identity_key: str, *, now: float | None = None) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._path(identity_key).read_text(encoding="utf-8"))
            observed_at = float(payload.get("observed_at"))
            current = time.time() if now is None else float(now)
            age = current - observed_at
            profile = str(payload.get("profile") or "")
            firmware = str(payload.get("firmware_version") or "")
            if payload.get("schema") != CACHE_SCHEMA:
                return None
            if payload.get("identity_key") != identity_key:
                return None
            if profile not in _RECOGNIZED_PROFILES or not firmware:
                return None
            if age < -300 or age > self.ttl_seconds:
                self.forget(identity_key)
                return None
            return {
                "profile": profile,
                "firmware_version": firmware,
                "observed_at": observed_at,
            }
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def remember(
        self,
        identity_key: str,
        *,
        profile: str,
        firmware_version: str,
        now: float | None = None,
    ) -> bool:
        profile = str(profile).strip()
        firmware = str(firmware_version).strip().strip('"')[:200]
        if profile not in _RECOGNIZED_PROFILES or not firmware:
            return False
        try:
            self._ensure_root()
            target = self._path(identity_key)
            payload = {
                "schema": CACHE_SCHEMA,
                "identity_key": identity_key,
                "profile": profile,
                "firmware_version": firmware,
                "observed_at": time.time() if now is None else float(now),
            }
            fd, raw = tempfile.mkstemp(prefix=".qnap-profile-", suffix=".tmp", dir=self.root)
            temp = Path(raw)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.chmod(temp, 0o600)
                except OSError:
                    pass
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def forget(self, identity_key: str) -> None:
        try:
            self._path(identity_key).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


__all__ = [
    "CACHE_TTL_SECONDS",
    "QnapPlatformProfileCache",
    "classify_qnap_firmware",
]
