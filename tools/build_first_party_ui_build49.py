#!/usr/bin/env python3
"""UI49: #104 natural-height spatial dashboard and #103 header convergence.

Builds an immutable 1.13.0 successor over qualified UI48. No Core changes.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build48 as previous
from build_first_party_ui_build43 import _replace_once

UI_VERSION = "1.13.0"
UI_BUILD = 49
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b49"
RELEASE49 = stable.Release(
    build=UI_BUILD, certified_sha="feature-104-spatial-103-header",
    version=UI_VERSION,
)
SOURCE_BLOBS = {
    "card-composer-renderer.js": "fa725068ba4d9648633f343944c2772d220441b6",
    "card-composer.css": "8ff904118690c65621cc785ad990b11d01a57dc4",
    "card-item-registry.js": "7209fac13f543ad390f28d8a61f484539dac10f3",
    "card-layout-editor.html": "a7d25b9b2a6cff726dd8b35cb9484c29ce7bb472",
    "card-layout-editor.js": "ac4ee8352c3285d53a9df67b7fca2163f2a7890f",
    "card-layout-policy.js": "58d46f9b056217ec67fd7926c752f10fd4ee3a94",
    "card-layout.css": "c6b3d748868a6c667832e68e5a62d03f41db2dd6",
    "card-layout.js": "6676cc4b55faa9c590518b766c4728db79842085",
    "live-telemetry.js": "24d723db90cf6dddc8aa4ea241a11ae465e64c4e",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def _sources(root: Path) -> dict[str, bytes]:
    folder = root / "sources" / "ui" / "1.13.0-build49"
    if {p.name for p in folder.iterdir() if p.is_file()} != set(SOURCE_BLOBS):
        raise SystemExit("UI49 source inventory drift")
    source = {}
    for name, expected in SOURCE_BLOBS.items():
        blob = (folder / name).read_bytes()
        if _git_blob_sha(blob) != expected:
            raise SystemExit(f"UI49 unreviewed source fingerprint: {name}")
        source[name] = blob
    for name in ("card-layout-policy.js", "card-layout.js", "card-layout-editor.js"):
        for provider in (b"unifi", b"scrypted", b"portainer", b"meraki", b"eero"):
            if provider in source[name].lower():
                raise SystemExit(f"UI49 shared layout contains provider logic: {name}")
    return source


def _header_dividend(shell: bytes, dashboard: bytes) -> tuple[bytes, bytes]:
    """Join the existing canonical homepage state refresh to shared shell health.

    The shell's separate initial request is a one-shot hydration; late failures
    and responses must not overwrite newer canonical state from the dashboard.
    """
    shell = _replace_once(
        shell,
        b"    return HEALTH.has(state) ? state : 'unknown';",
        b"    return state === 'failed' ? 'critical' : HEALTH.has(state) ? state : 'unknown';",
        "failed site-health normalization",
    )
    shell = _replace_once(
        shell, b"  async function hydrate(shell) {\n",
        b"  let siteEpoch = 0;\n"
        b"  async function hydrate(shell) {\n"
        b"    const startedEpoch = siteEpoch;\n",
        "header state response order",
    )
    shell = _replace_once(
        shell, b"    if (stateResult.status === 'fulfilled') {\n",
        b"    if (stateResult.status === 'fulfilled' && siteEpoch === startedEpoch) {\n",
        "stale initial header response",
    )
    shell = _replace_once(
        shell, b"    } else if (!readShellCache()?.site) {\n",
        b"    } else if (stateResult.status !== 'fulfilled' && siteEpoch === startedEpoch && !readShellCache()?.site) {\n",
        "stale initial header failure",
    )
    shell = _replace_once(
        shell,
        b"    scheduleHydration(shell);\n",
        b"    document.addEventListener('monitorbox:state', event => {\n"
        b"      if (!event.detail || !Array.isArray(event.detail.sites)) return;\n"
        b"      ++siteEpoch;\n"
        b"      const summary = siteSummary(event.detail);\n"
        b"      applySite(shell, summary);\n"
        b"      writeShellCache({site:summary, site_at:Date.now()});\n"
        b"    });\n"
        b"    scheduleHydration(shell);\n",
        "canonical dashboard refresh to shared shell bridge",
    )
    dashboard = _replace_once(
        dashboard, b"async function loadState({quiet=false}={}){let error;",
        b"let _mbStateSequence=0,_mbStateApplied=0;\n"
        b"async function loadState({quiet=false}={}){const _mbRequest=++_mbStateSequence;let error;",
        "canonical refresh sequence",
    )
    dashboard = _replace_once(
        dashboard, b"app.state=data;app.stateRefreshFailures=0;",
        b"if(_mbRequest<_mbStateApplied)return app.state;"
        b"_mbStateApplied=_mbRequest;app.state=data;"
        b"document.dispatchEvent(new CustomEvent('monitorbox:state',{detail:data}));"
        b"app.stateRefreshFailures=0;",
        "canonical state event",
    )
    dashboard = _replace_once(
        dashboard, b"}app.stateRefreshFailures+=1;if(app.state&&app.stateRefreshFailures<2)",
        b"}if(_mbRequest<_mbStateApplied)return app.state;"
        b"app.stateRefreshFailures+=1;if(app.state&&app.stateRefreshFailures<2)",
        "stale canonical refresh failure",
    )
    return shell, dashboard


def _package_files(root: Path) -> dict[str, bytes]:
    inherited = previous._package_files(root)
    prefix = PARENT_IMPORT_PACKAGE + "/"
    parent = {}
    for path, content in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit(f"Foreign inherited UI48 member: {path}")
        parent[path[len(prefix):]] = content
    parent["__init__.py"] = _replace_once(
        parent["__init__.py"],
        b"Standalone managed MonitorBox UI 1.12.0 build 48.",
        b"Standalone managed MonitorBox UI 1.13.0 build 49.",
        "UI49 module identity",
    )
    for name, content in list(parent.items()):
        parent[name] = content.replace(
            PARENT_GENERATION.encode(), UI_GENERATION.encode()
        ).replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
    # Schema v4 is still UI-owned opaque state. Keep Core's accepted provider
    # reconciling unarranged automatic layouts and preserving explicit rows.
    parent["__init__.py"] = _replace_once(
        parent["__init__.py"],
        b'if current.get("schema_version") not in (1, 2, 3):',
        b'if current.get("schema_version") not in (1, 2, 3, 4):',
        "UI49 automatic snapshot admission",
    )
    shell, dashboard = _header_dividend(
        parent["assets/app-shell.js"], parent["assets/dashboard.js"],
    )
    parent["assets/app-shell.js"] = shell
    parent["assets/dashboard.js"] = dashboard
    for name, blob in _sources(root).items():
        parent["assets/" + name] = blob
    html = parent["assets/dashboard.html"]
    required = [
        b"/static/card-item-registry.js?v=" + UI_GENERATION.encode(),
        b"/static/card-layout-policy.js?v=" + UI_GENERATION.encode(),
        b"/static/card-layout.js?v=" + UI_GENERATION.encode(),
        b"/static/card-composer-renderer.js?v=" + UI_GENERATION.encode(),
        b"/static/live-telemetry.js?v=" + UI_GENERATION.encode(),
    ]
    if any(html.count(path) != 1 for path in required):
        raise SystemExit("UI49 homepage script dependencies changed")
    if html.count(b"/static/card-composer.css?v=" + UI_GENERATION.encode()) != 1:
        raise SystemExit("UI49 homepage lacks natural-height card CSS")
    if parent["assets/card-layout-editor.html"].count(b"arrangePanel") != 1:
        raise SystemExit("UI49 spatial editor is absent")
    if inherited[prefix + "assets/card-projection.js"] != parent["assets/card-projection.js"]:
        raise SystemExit("UI49 changed accepted canonical Core projection")
    if any(PARENT_GENERATION.encode() in blob for blob in parent.values()):
        raise SystemExit("UI49 inherited stale UI48 script identity")
    return {TARGET_IMPORT_PACKAGE + "/" + name: blob
            for name, blob in parent.items()}


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE49.filename
    target.write_bytes(data)
    print(f"UI49 development candidate {target}: sha256={hashlib.sha256(data).hexdigest()}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "packages")
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent, args.output_dir)


if __name__ == "__main__":
    main()
