#!/usr/bin/env python3
"""UI55 deterministic package, signed predecessor, and channel-policy UI invariants."""
from __future__ import annotations

import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build54 as parent
import build_first_party_ui_build55 as candidate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    old = parent._package_files(ROOT)
    assert hashlib.sha256(stable._zip_bytes(old)).hexdigest() == candidate.SIGNED_UI54_SHA256
    files = candidate._package_files(ROOT)
    prefix = candidate.TARGET_IMPORT_PACKAGE + "/"
    assets = {name.removeprefix(prefix): body for name, body in files.items()}
    assert files and all(name.startswith(prefix) for name in files)
    assert b"1.18.0 build 55" in assets["__init__.py"]
    assert b"1.18.0-55" in assets["assets/app-shell.js"]
    assert b"release-channel" in assets["assets/modules.js"]
    assert b'const channels = ["stable", "beta", "dev"];' in assets["assets/modules.js"]
    assert b"option.disabled = !permitted.includes(channel)" in assets["assets/modules.js"]
    assert b"csrfToken" in assets["assets/modules.js"]
    assert b"window.confirm(warning)" in assets["assets/modules.js"]
    assert b"no Compose pull" in assets["assets/modules.js"]
    assert b"identity.channel" not in assets["assets/app-shell.js"]
    assert b"policy.preferred_channel" in assets["assets/app-shell.js"]
    assert b"policy.release_channels.includes(policy.preferred_channel)" in assets["assets/app-shell.js"]
    assert b"monitorbox.shell.cache.v2-channel-policy" in assets["assets/app-shell.js"]
    assert b"moduleResult" in assets["assets/app-shell.js"]
    assert assets["assets/card-projection.js"] == old[
        parent.TARGET_IMPORT_PACKAGE + "/assets/card-projection.js"
    ]
    ast.parse(assets["__init__.py"].decode())
    ast.parse(assets["bootstrap.py"].decode())
    with tempfile.TemporaryDirectory(prefix="mb-ui55-") as directory:
        root = Path(directory)
        for name in ("modules.js", "app-shell.js"):
            path = root / name
            path.write_bytes(assets["assets/" + name])
            subprocess.run(["node", "--check", str(path)], check=True)
        a = candidate.build(ROOT, root / "first").read_bytes()
        b = candidate.build(ROOT, root / "second").read_bytes()
        assert a == b
        assert a != stable._zip_bytes(old)
        print("UI55 exact UI54 parent, signed policy selector, header authority, "
              "JS syntax and deterministic candidate PASS. sha256="
              + hashlib.sha256(a).hexdigest())


if __name__ == "__main__":
    main()
