"""Filesystem destination adapter for managed Backup / Restore."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class BackupDestinationError(ValueError):
    """Raised when publishing a backup to a configured destination fails safely."""


@dataclass(frozen=True, slots=True)
class DestinationResult:
    destination_id: str
    locator: str
    bytes: int
    sha256: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


class BackupDestination(Protocol):
    destination_id: str

    def publish(self, source: Path, *, filename: str) -> DestinationResult: ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FilesystemBackupDestination:
    """Publish to a local or host-mounted filesystem/NAS directory."""

    destination_id = "filesystem"

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()

    def publish(self, source: Path, *, filename: str) -> DestinationResult:
        source = Path(source)
        if not source.is_file() or source.is_symlink():
            raise BackupDestinationError("backup source must be a regular file")
        if not filename or filename != Path(filename).name or filename in {".", ".."}:
            raise BackupDestinationError("destination filename must be a safe basename")

        try:
            self.path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupDestinationError(f"unable to create backup destination: {exc}") from exc
        if not self.path.is_dir() or self.path.is_symlink():
            raise BackupDestinationError("backup destination must be a real directory")

        destination = self.path / filename
        fd = -1
        try:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                fd = -1
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        except FileExistsError as exc:
            raise BackupDestinationError(
                f"destination already contains {filename}; refusing to overwrite"
            ) from exc
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise BackupDestinationError(f"unable to publish backup: {exc}") from exc
        finally:
            if fd >= 0:
                os.close(fd)

        source_digest = _sha256_file(source)
        copied_digest = _sha256_file(destination)
        if source.stat().st_size != destination.stat().st_size or source_digest != copied_digest:
            destination.unlink(missing_ok=True)
            raise BackupDestinationError("destination copy failed integrity verification")
        return DestinationResult(
            destination_id=self.destination_id,
            locator=str(destination),
            bytes=destination.stat().st_size,
            sha256=copied_digest,
        )
