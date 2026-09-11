#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 UI v1.1.14 build 27 brand correction."""
from __future__ import annotations

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

import build_first_party_ui_build27 as candidate

EXPECTED_RASTERS = {
    "monitorbox-192.png": (192, 192),
    "monitorbox-512.png": (512, 512),
    "monitorbox-apple-180.png": (180, 180),
    "monitorbox-maskable-512.png": (512, 512),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def rendered_raster_stats(page, payload: bytes) -> dict[str, int]:
    """Have Chromium decode the production PNG and inspect its rendered pixels.

    Candidate reproducibility is already proven by the first-party staging pass.
    This assertion deliberately targets browser-visible semantics instead of PNG
    encoder byte identity: correct dimensions, dark MonitorBox field present, and
    the bright health/status token absent from application-icon artwork.
    """
    source = "data:image/png;base64," + base64.b64encode(payload).decode("ascii")
    page.set_content(f'<img id="icon" src="{source}" alt="">')
    return page.evaluate(
        """async () => {
          const image = document.getElementById('icon');
          await image.decode();
          const canvas = document.createElement('canvas');
          canvas.width = image.naturalWidth;
          canvas.height = image.naturalHeight;
          const context = canvas.getContext('2d', {willReadFrequently: true});
          context.drawImage(image, 0, 0);
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
          let dark = 0;
          let health = 0;
          for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i] === 0x17 && pixels[i + 1] === 0x40 && pixels[i + 2] === 0x41 && pixels[i + 3] === 0xff) dark += 1;
            if (pixels[i] === 0x75 && pixels[i + 1] === 0xd6 && pixels[i + 2] === 0x9a && pixels[i + 3] === 0xff) health += 1;
          }
          return {width: canvas.width, height: canvas.height, dark, health};
        }"""
    )


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

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for name, expected_size in EXPECTED_RASTERS.items():
                stats = rendered_raster_stats(page, assets[name])
                size = (stats["width"], stats["height"])
                require(size == expected_size, f"{name} dimensions drifted: {size} != {expected_size}")
                require(
                    stats["dark"] >= (size[0] * size[1]) // 4,
                    f"{name} does not visibly carry the dark MonitorBox field",
                )
                require(stats["health"] == 0, f"{name} retained the bright health/status green")
        finally:
            browser.close()

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
