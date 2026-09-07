#!/usr/bin/env python3
"""Prove UI 1.1.3 build 11 loads without the retired Core UI package."""

from __future__ import annotations

import importlib
import sys
import tempfile
import zipfile
from pathlib import Path

from aiohttp import web

PACKAGE = "com.sickicarus.monitorbox.ui-1.1.3-build11.zip"
IMPORT_PACKAGE = "monitorbox_ui_b11"


def _write_core_stub(root: Path) -> None:
    monitorbox = root / "monitorbox"
    v2 = monitorbox / "v2"
    icons = monitorbox / "static" / "icons"
    icons.mkdir(parents=True)
    (monitorbox / "__init__.py").write_text('__version__ = "2.3.1"\n', encoding="utf-8")
    (v2 / "__init__.py").write_text("", encoding="utf-8")
    stub = (
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class BuildIdentity:\n"
        "    version: str = '2.3.1'\n"
        "    build: str = '0000'\n"
        "    channel: str = 'acceptance'\n"
        "    git_sha: str = 'stub'\n"
        "    @property\n"
        "    def display(self):\n"
        "        return f'v{self.version} · build {self.build} · {self.channel}'\n"
        "    def as_dict(self):\n"
        "        return {'version': self.version, 'build': self.build, 'channel': self.channel, 'git_sha': self.git_sha, 'short_git_sha': self.git_sha, 'display': self.display}\n\n"
        "def current_build_identity():\n"
        "    return BuildIdentity()\n"
    )
    (v2 / "build_info.py").write_text(stub, encoding="utf-8")
    (icons / "acceptance.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>\n',
        encoding="utf-8",
    )


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    package = repo / "packages" / PACKAGE
    if not package.is_file():
        raise SystemExit(f"missing generated package: {package}")

    with tempfile.TemporaryDirectory(prefix="monitorbox-ui11-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(package) as archive:
            archive.extractall(root)
        _write_core_stub(root)

        # The stub deliberately contains no monitorbox.v2.modules package. Successful
        # import therefore proves build 11 is not relying on retired factory UI code.
        sys.path.insert(0, str(root))
        try:
            module = importlib.import_module(IMPORT_PACKAGE)
            app = web.Application()
            module.install(app)
        finally:
            sys.path.remove(str(root))

        route_paths = {route.resource.canonical for route in app.router.routes()}
        expected_paths = {
            "/",
            "/modules",
            "/api/v2/build",
            "/static/icons/{name}",
            "/static/{name}",
        }
        missing = expected_paths - route_paths
        if missing:
            raise SystemExit(f"standalone UI build 11 omitted routes: {sorted(missing)}")
        middleware_names = [getattr(item, "__name__", "") for item in app.middlewares]
        if middleware_names != ["managed_ui_presentation", "v22_settings_presentation"]:
            raise SystemExit(
                f"standalone UI build 11 middleware order changed: {middleware_names!r}"
            )

        if "monitorbox.v2.modules.ui" in sys.modules:
            raise SystemExit("retired Core UI package was imported during standalone acceptance")

    print("standalone UI build 11 loads and installs against Core substrate without factory UI")


if __name__ == "__main__":
    main()
