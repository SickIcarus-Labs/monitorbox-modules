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
DARK_BRAND_RGBA = [0x17, 0x40, 0x41, 0xFF]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def rendered_raster_stats(page, payload: bytes) -> dict[str, object]:
    """Have Chromium decode the production PNG and inspect rendered semantics.

    Candidate reproducibility is already proven by the first-party staging pass.
    This check therefore targets browser-visible behavior rather than encoder-byte
    identity: correct dimensions, known field samples at the canonical dark brand
    color, visible white lighthouse artwork, and no health/status green in the icon.
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
          let white = 0;
          for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i] === 0x17 && pixels[i + 1] === 0x40 && pixels[i + 2] === 0x41 && pixels[i + 3] === 0xff) dark += 1;
            if (pixels[i] === 0x75 && pixels[i + 1] === 0xd6 && pixels[i + 2] === 0x9a && pixels[i + 3] === 0xff) health += 1;
            if (pixels[i] === 0xff && pixels[i + 1] === 0xff && pixels[i + 2] === 0xff && pixels[i + 3] === 0xff) white += 1;
          }
          const rgbaAt = (xn, yn) => {
            const x = Math.min(canvas.width - 1, Math.max(0, Math.floor(canvas.width * xn)));
            const y = Math.min(canvas.height - 1, Math.max(0, Math.floor(canvas.height * yn)));
            return Array.from(context.getImageData(x, y, 1, 1).data);
          };
          return {
            width: canvas.width,
            height: canvas.height,
            dark,
            health,
            white,
            fieldSamples: [rgbaAt(0.50, 0.10), rgbaAt(0.10, 0.50), rgbaAt(0.90, 0.50), rgbaAt(0.50, 0.90)],
          };
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
                require(stats["dark"] > 0, f"{name} has no canonical dark-brand pixels")
                require(stats["white"] > 0, f"{name} has no visible white lighthouse artwork")
                require(stats["health"] == 0, f"{name} retained the bright health/status green")
                for index, sample in enumerate(stats["fieldSamples"], start=1):
                    require(
                        sample == DARK_BRAND_RGBA,
                        f"{name} field sample {index} drifted: {sample} != {DARK_BRAND_RGBA}",
                    )
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
