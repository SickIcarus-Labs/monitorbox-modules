from __future__ import annotations

from pathlib import Path
from typing import Any

LEGACY_SOCKET = "/run/monitorbox-scrypted/bridge.sock"


def resolve_managed_socket(requested: Any, state_root: str | None) -> str:
    """Resolve module-owned bridge IPC without requiring a host /run directory.

    Scrypted 2.0/2.1 persisted a fixed /run/monitorbox-scrypted socket path. That
    worked only while deployment-specific host setup happened to make the
    directory writable. Managed modules instead receive a Core-allocated writable
    state_root. Preserve explicitly supplied non-legacy absolute sockets (used by
    validation/tests), while transparently relocating the historical/default path
    into that state namespace.
    """

    raw = str(requested or "").strip()
    if raw and raw != LEGACY_SOCKET:
        if not raw.startswith("/"):
            raise ValueError("Scrypted socket must be an absolute path")
        return raw

    if not state_root:
        raise RuntimeError("Scrypted managed state root is unavailable")
    root = Path(state_root)
    if not root.is_absolute():
        raise ValueError("Scrypted managed state root must be an absolute path")
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        # The Core-owned namespace may already have a deployment-specific mode.
        # Writability, not mode rewriting, is the runtime requirement.
        pass
    return str(root / "bridge.sock")


__all__ = ["LEGACY_SOCKET", "resolve_managed_socket"]
