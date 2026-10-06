from __future__ import annotations

import os
import shutil
from pathlib import Path


def node_launch_prefix() -> tuple[str, ...]:
    """Resolve the successor's signed Node ELF launch contract.

    A successor scaffold supplies all three values together. The legacy PATH
    fallback remains available only when no scaffold Node authority is present.
    """

    binary = os.environ.get("MONITORBOX_MODULE_NODE", "").strip()
    loader = os.environ.get("MONITORBOX_MODULE_NODE_LOADER", "").strip()
    library_path = os.environ.get("MONITORBOX_MODULE_NODE_LIBRARY_PATH", "").strip()

    if not any((binary, loader, library_path)):
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js runtime is unavailable for the Scrypted module")
        return (node,)

    if not all((binary, loader, library_path)):
        raise RuntimeError("incomplete scaffold-selected signed Node runtime")

    libraries = library_path.split(":")
    if (
        not Path(binary).is_absolute()
        or not Path(loader).is_absolute()
        or not libraries
        or any(not item or not Path(item).is_absolute() for item in libraries)
    ):
        raise RuntimeError("unsafe scaffold-selected signed Node runtime")

    if not Path(binary).is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("signed Node runtime executable is unavailable")
    if not Path(loader).is_file() or not os.access(loader, os.X_OK):
        raise RuntimeError("signed Node runtime loader is unavailable")
    if any(not Path(item).is_dir() for item in libraries):
        raise RuntimeError("signed Node runtime library path is unavailable")

    return loader, "--library-path", library_path, binary
