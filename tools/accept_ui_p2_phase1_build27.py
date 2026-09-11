#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 UI v1.1.14 build 27 brand correction."""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path

from PIL import Image

import build_first_party_ui_build27 as candidate

EXPECTED_RASTERS = {
    "monitorbox-192.png": (192, 192),
    "monitorbox-512.png": (512, 512),
    "monitorbox-apple-180.png": (180, 180),
    "monitorbox-maskable-512.png": (512, 512),
}
DARK_BRAND_RGBA = (0x17, 0x40, 0x41, 0xFF)
HEALTH_GREEN_RGBA = (0x75, 0xD6, 0x9A, 0xFF)
WHITE_RGBA = (0xFF, 0xFF, 0xFF, 0xFF)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def raster_stats(payload: bytes) -> dict[str, object]:
    """Decode the committed production PNG and inspect rendered RGBA semantics."""
    with Image.open(BytesIO(payload)) as image:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        pixels = list(rgba.getdata())
        counts = Counter(pixels)
        samples = (
            rgba.getpixel((width // 2, height // 10)),
            rgba.getpixel((width // 10, height // 2)),
            rgba.getpixel((width * 9 // 10, height // 2)),
            rgba.getpixel((width // 2, height * 9 // 10)),
        )
        return {
            "size": (width, height),
            "dark": counts[DARK_BRAND_RGBA],
            "health": counts[HEALTH_GREEN_RGBA],
            "white": counts[WHITE_RGBA],
            "samples": samples,
            "alpha_extrema": rgba.getchannel("A").getextrema(),
            "top_colors": counts.most_common(8),
        }


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

    for name, expected_size in EXPECTED_RASTERS.items():
        stats = raster_stats(assets[name])
        print(f"{name} raster stats: {stats}", flush=True)
        require(stats["size"] == expected_size, f"{name} dimensions drifted: {stats['size']} != {expected_size}")
        require(stats["alpha_extrema"] == (255, 255), f"{name} unexpectedly contains transparent pixels")
        require(stats["white"] > 0, f"{name} has no visible white lighthouse artwork")
        require(stats["health"] == 0, f"{name} retained the bright health/status green")
        require(stats["dark"] > 0, f"{name} has no canonical dark-brand pixels")
        for index, sample in enumerate(stats["samples"], start=1):
            require(sample == DARK_BRAND_RGBA, f"{name} field sample {index} drifted: {sample} != {DARK_BRAND_RGBA}")

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
