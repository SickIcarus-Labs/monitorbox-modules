#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 UI v1.1.14 build 27 brand correction."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import build_first_party_ui_build27 as candidate

EXPECTED_RASTERS = {
    "monitorbox-192.png": (192, 192),
    "monitorbox-512.png": (512, 512),
    "monitorbox-apple-180.png": (180, 180),
    "monitorbox-maskable-512.png": (512, 512),
}
DARK_BRAND_RGBA = bytes((0x17, 0x40, 0x41, 0xFF))
HEALTH_GREEN_RGBA = bytes((0x75, 0xD6, 0x9A, 0xFF))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def png_rgba(payload: bytes) -> tuple[tuple[int, int], bytes]:
    """Decode the constrained RGBA PNGs used for the MonitorBox brand assets.

    Acceptance cares about rendered pixels, not encoder-specific byte identity. The
    repository candidate is already proven reproducible by the first-party staging
    pass; this check independently proves that every raster carries the dark brand
    field rather than the bright health/status token.
    """
    require(payload.startswith(b"\x89PNG\r\n\x1a\n"), "brand raster is not PNG")
    offset = 8
    width = height = 0
    idat = bytearray()
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk = payload[offset + 8 : offset + 8 + length]
        require(offset + 12 + length <= len(payload), "truncated PNG chunk")
        offset += 12 + length
        if chunk_type == b"IHDR":
            require(len(chunk) == 13, "invalid PNG IHDR")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            require(bit_depth == 8 and color_type == 6, "brand PNG must remain 8-bit RGBA")
            require(compression == 0 and filter_method == 0 and interlace == 0, "unsupported brand PNG encoding")
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break

    require(width > 0 and height > 0 and idat, "brand PNG is missing image data")
    raw = zlib.decompress(bytes(idat))
    bpp = 4
    stride = width * bpp
    require(len(raw) == height * (stride + 1), "brand PNG scanline size drifted")

    pixels = bytearray(height * stride)
    previous = bytearray(stride)
    src = 0
    for row_index in range(height):
        filter_type = raw[src]
        src += 1
        scan = raw[src : src + stride]
        src += stride
        recon = bytearray(stride)
        for x, value in enumerate(scan):
            left = recon[x - bpp] if x >= bpp else 0
            up = previous[x]
            upper_left = previous[x - bpp] if x >= bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = _paeth(left, up, upper_left)
            else:
                raise SystemExit(f"unsupported PNG filter {filter_type}")
            recon[x] = (value + predictor) & 0xFF
        start = row_index * stride
        pixels[start : start + stride] = recon
        previous = recon

    return (width, height), bytes(pixels)


def pixel_count(pixels: bytes, rgba: bytes) -> int:
    return sum(1 for index in range(0, len(pixels), 4) if pixels[index : index + 4] == rgba)


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
        size, pixels = png_rgba(assets[name])
        require(size == expected_size, f"{name} dimensions drifted")
        dark_pixels = pixel_count(pixels, DARK_BRAND_RGBA)
        require(dark_pixels >= (size[0] * size[1]) // 4, f"{name} does not visibly carry the dark MonitorBox field")
        require(pixel_count(pixels, HEALTH_GREEN_RGBA) == 0, f"{name} retained the bright health/status green")

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
