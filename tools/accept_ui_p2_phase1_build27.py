#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 UI v1.1.14 build 27 brand correction."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import build_first_party_ui_build27 as candidate

EXPECTED_RASTERS = {
    "monitorbox-192.png": ((192, 192), "2865e1e4c0691d3d0deab9f17edf3bbaa0b7e9c397d987c489dfb1b4c7b691a2"),
    "monitorbox-512.png": ((512, 512), "7af7f331e814fd88a5395fb7aa5bac184fad5bb9399f8e3b825c7f9974b32700"),
    "monitorbox-apple-180.png": ((180, 180), "f31c634f30b5816896b60bb1f3bfe271c7a6caa2c67c3dcc365b3a3e31507f7d"),
    "monitorbox-maskable-512.png": ((512, 512), "f3ab538a8505abf161b028f348f38de7a37a655fb9ff0d525bf5f7da7f209123"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def png_dimensions(payload: bytes) -> tuple[int, int]:
    require(payload.startswith(b"\x89PNG\r\n\x1a\n"), "brand raster is not PNG")
    require(payload[12:16] == b"IHDR", "brand raster has no leading IHDR")
    return struct.unpack(">II", payload[16:24])


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build27_assets(root)
    app = candidate._standalone_application()

    require(candidate.UI_VERSION == "1.1.14" and candidate.UI_BUILD == 27, "wrong build-27 identity")
    require(candidate.RELEASE27.version == "1.1.14", "build27 semantic version drift")
    require(candidate.accepted.RELEASE23.build == 23, "build27 accepted predecessor must remain build23")

    mark = assets["monitorbox-mark.svg"].decode("utf-8")
    require("#174041" in mark, "brand mark does not use the dark MonitorBox field")
    require("#75d69a" not in mark.lower(), "bright health green leaked into the brand mark")

    for name, (size, digest) in EXPECTED_RASTERS.items():
        payload = assets[name]
        require(png_dimensions(payload) == size, f"{name} dimensions drifted")
        require(hashlib.sha256(payload).hexdigest() == digest, f"{name} bytes drifted")

    # Brand and health are intentionally separate tokens: #174041 is the solid app/icon
    # field, while #75d69a remains the live healthy/status signal in the UI.
    shell_css = assets["app-shell.css"].decode("utf-8").lower()
    require("#75d69a" in shell_css, "bright healthy/status green was accidentally removed")
    require("#174041" not in shell_css, "dark brand field leaked into shell health-state styling")

    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        require(b"1.1.14-27" in assets[name], f"{name} did not advance to generation 27")
        require(b"1.1.14-26" not in assets[name], f"{name} retained stale generation 26")
    require(b'_UI_GENERATION = "1.1.14-27"' in app, "standalone generation did not advance")
    require(b"Standalone managed MonitorBox UI 1.1.14 build 27." in app, "standalone build27 identity missing")

    print("P2 Phase-1 UI build27 dark-brand icon acceptance: PASS")


if __name__ == "__main__":
    main()
