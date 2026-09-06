from __future__ import annotations

from typing import Any


LEGACY_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"
DEFAULT_SOCKET = "/run/monitorbox-modules/scrypted/bridge.sock"


def normalize_socket(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Scrypted socket must be non-empty text")
    socket = value.strip()
    if socket == LEGACY_DEFAULT_SOCKET:
        return DEFAULT_SOCKET
    return socket
