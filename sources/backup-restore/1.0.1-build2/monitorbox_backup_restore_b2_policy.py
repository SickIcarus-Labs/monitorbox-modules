"""Durable scheduling/retention policy for the managed Backup / Restore module."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
POLICY_SCHEMA = 1
DEFAULT_RETENTION_BYTES = 20 * 1024 * 1024 * 1024


class BackupPolicyError(ValueError):
    """Raised when module-owned backup policy is invalid or cannot be persisted."""


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    enabled: bool = False
    interval_hours: int = 24
    retention_count: int = 7
    retention_bytes: int = DEFAULT_RETENTION_BYTES
    destination_type: str | None = None
    destination_path: str | None = None

    def validate(self) -> None:
        if not isinstance(self.enabled, bool):
            raise BackupPolicyError("schedule enabled must be boolean")
        if isinstance(self.interval_hours, bool) or not isinstance(self.interval_hours, int):
            raise BackupPolicyError("schedule interval must be an integer number of hours")
        if not 1 <= self.interval_hours <= 24 * 7:
            raise BackupPolicyError("schedule interval must be between 1 and 168 hours")
        if isinstance(self.retention_count, bool) or not isinstance(self.retention_count, int):
            raise BackupPolicyError("retention count must be an integer")
        if not 1 <= self.retention_count <= 100:
            raise BackupPolicyError("retention count must be between 1 and 100")
        if isinstance(self.retention_bytes, bool) or not isinstance(self.retention_bytes, int):
            raise BackupPolicyError("retention byte limit must be an integer")
        if not 64 * 1024 * 1024 <= self.retention_bytes <= 1024 * 1024 * 1024 * 1024:
            raise BackupPolicyError("retention byte limit must be between 64 MiB and 1 TiB")
        if self.destination_type not in {None, "filesystem"}:
            raise BackupPolicyError("unsupported backup destination type")
        if self.destination_type is None:
            if self.destination_path not in {None, ""}:
                raise BackupPolicyError("destination path requires a destination type")
            return
        path = str(self.destination_path or "").strip()
        if not path:
            raise BackupPolicyError("filesystem destination requires a path")
        if len(path) > 4096 or any(ord(ch) < 32 for ch in path):
            raise BackupPolicyError("filesystem destination path is invalid")
        if not Path(path).expanduser().is_absolute():
            raise BackupPolicyError("filesystem destination path must be absolute")

    def public(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BackupPolicy":
        policy = cls(
            enabled=raw.get("enabled", False),
            interval_hours=raw.get("interval_hours", 24),
            retention_count=raw.get("retention_count", 7),
            retention_bytes=raw.get("retention_bytes", DEFAULT_RETENTION_BYTES),
            destination_type=raw.get("destination_type"),
            destination_path=raw.get("destination_path"),
        )
        policy.validate()
        return policy


class BackupPolicyStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.state_root = self.root / "module-state" / MODULE_ID
        self.path = self.state_root / "policy.json"

    def _validate_destination_scope(self, policy: BackupPolicy) -> None:
        if policy.destination_type != "filesystem" or not policy.destination_path:
            return
        try:
            appliance_root = self.root.resolve(strict=False)
            destination = Path(policy.destination_path).expanduser().resolve(strict=False)
        except OSError as exc:
            raise BackupPolicyError("filesystem destination path cannot be resolved safely") from exc
        if destination == appliance_root or appliance_root in destination.parents:
            raise BackupPolicyError(
                "filesystem destination must be outside the MonitorBox persistent root"
            )

    def load(self) -> BackupPolicy:
        if not self.path.exists():
            return BackupPolicy()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BackupPolicyError("backup policy state is unreadable") from exc
        if not isinstance(raw, dict) or raw.get("schema") != POLICY_SCHEMA:
            raise BackupPolicyError("backup policy state uses an unsupported schema")
        payload = raw.get("policy")
        if not isinstance(payload, dict):
            raise BackupPolicyError("backup policy state is malformed")
        policy = BackupPolicy.from_mapping(payload)
        self._validate_destination_scope(policy)
        return policy

    def save(self, policy: BackupPolicy) -> BackupPolicy:
        policy.validate()
        self._validate_destination_scope(policy)
        try:
            self.state_root.mkdir(parents=True, exist_ok=True)
            fd, raw = tempfile.mkstemp(prefix=".policy-", suffix=".tmp", dir=self.state_root)
        except OSError as exc:
            raise BackupPolicyError(f"unable to prepare backup policy state: {exc}") from exc
        temp = Path(raw)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"schema": POLICY_SCHEMA, "policy": policy.public()},
                    handle,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            os.replace(temp, self.path)
        except OSError as exc:
            raise BackupPolicyError(f"unable to persist backup policy: {exc}") from exc
        finally:
            temp.unlink(missing_ok=True)
        return policy
