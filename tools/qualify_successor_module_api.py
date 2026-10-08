#!/usr/bin/env python3
"""Cross-repository Core3 API qualification for successor first-party modules.

The caller supplies an exact MonitorBox Core checkout. This script never edits
that checkout. It imports the newly wrapped package bytes against the Core3
module/plugin API contract and proves that the exact ten application modules:
- reject a 2.7 Core compatibility decision;
- admit under Core 3.0.0 / Module Runtime API v1;
- resolve every declared entrypoint from the package ZIP;
- register all seven integration modules together without ownership collisions.

This is an API/package qualification gate, not physical provider acceptance.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


def _entrypoint(target: str) -> object:
    module_name, attribute = target.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def _runtime_manifest(runtime_cls, raw: dict[str, Any]):
    return runtime_cls(
        module_id=raw["module_id"],
        display_name=raw["display_name"],
        description=raw.get("description"),
        version=raw["version"],
        build=raw["build"],
        schema=raw["schema"],
        state_schema=raw["state_schema"],
        module_type=raw["module_type"],
        entrypoints=dict(raw["entrypoints"]),
        requires_core=raw["requires_core"],
        requires_runtime_api=raw["requires_runtime_api"],
        dependencies=tuple(raw["dependencies"]),
        publisher_id=raw["publisher_id"],
        permissions=tuple(raw["permissions"]),
        lifecycle_policy=raw["lifecycle_policy"],
        capability_detection=raw.get("capability_detection"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-src", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True)
    args = parser.parse_args()

    core_src = args.core_src.resolve()
    if not (core_src / "monitorbox" / "v2" / "plugin_api").is_dir():
        raise SystemExit("Core source path does not contain the module/plugin API")
    sys.path.insert(0, str(core_src))

    import monitorbox
    from monitorbox.v2.plugin_api.contracts import PLUGIN_API_VERSION
    from monitorbox.v2.plugin_api.module_runtime import (
        MODULE_RUNTIME_API_VERSION,
        ModuleLoadError,
        ModuleLoader,
        ModulePackage,
        ModuleManifest,
        TestModuleSource,
    )
    from monitorbox.v2.plugin_api.registry import PluginRegistry

    if MODULE_RUNTIME_API_VERSION != 1 or PLUGIN_API_VERSION != 1:
        raise SystemExit("successor qualification expected Module/Plugin API v1")
    # The successor package version is intentionally independent from the
    # source checkout's historical application version. Module admission must
    # use the exact selected Core artifact version supplied by scaffold.
    monitorbox.__version__ = "3.0.0"

    package_paths = sorted(args.packages.glob("com.sickicarus.monitorbox.*.zip"))
    expected_ids = {
        "com.sickicarus.monitorbox.backup-restore",
        "com.sickicarus.monitorbox.configuration-bootstrap",
        "com.sickicarus.monitorbox.http",
        "com.sickicarus.monitorbox.nut",
        "com.sickicarus.monitorbox.portainer",
        "com.sickicarus.monitorbox.scrypted",
        "com.sickicarus.monitorbox.snmp",
        "com.sickicarus.monitorbox.ui",
        "com.sickicarus.monitorbox.unifi",
        "com.sickicarus.monitorbox.wol",
    }
    observed: dict[str, ModulePackage] = {}
    inserted: list[str] = []
    try:
        for path in package_paths:
            with zipfile.ZipFile(path, "r") as archive:
                manifest = json.loads(archive.read("package.json"))
            runtime_raw = manifest["module_runtime"]
            artifact_id = manifest["artifact_id"]
            if artifact_id not in expected_ids or artifact_id in observed:
                raise SystemExit("unexpected or duplicate successor module package")
            runtime = _runtime_manifest(ModuleManifest, runtime_raw)
            runtime.validate()

            target = str(path)
            sys.path.insert(0, target)
            inserted.append(target)
            resolved = {
                name: _entrypoint(entrypoint)
                for name, entrypoint in runtime.entrypoints.items()
            }
            if any(not callable(value) and name != "integration"
                   for name, value in resolved.items()):
                raise SystemExit(f"{artifact_id} exposed non-callable application entrypoint")

            package = ModulePackage(
                manifest=runtime,
                entrypoints=resolved,
                source_id="successor-qualification",
                artifact_identity=f"{artifact_id}@{runtime.version}+{runtime.build}",
            )
            # The same candidate must NOT be considered compatible with the
            # accepted 2.x Core. This proves the new build did not merely erase
            # the verified compatibility barrier from #114.
            try:
                ModuleLoader(
                    (TestModuleSource((package,)),),
                    core_version="2.7.0",
                    runtime_api_version=MODULE_RUNTIME_API_VERSION,
                ).load()
            except ModuleLoadError:
                pass
            else:
                raise SystemExit(f"{artifact_id} incorrectly admits Core 2.7.0")

            loaded = ModuleLoader(
                (TestModuleSource((package,)),),
                core_version="3.0.0",
                runtime_api_version=MODULE_RUNTIME_API_VERSION,
            ).load()
            if len(loaded) != 1 or loaded[0].manifest.module_id != artifact_id:
                raise SystemExit(f"{artifact_id} failed Core3 ModuleLoader admission")
            observed[artifact_id] = package

        if set(observed) != expected_ids:
            missing = sorted(expected_ids - set(observed))
            extra = sorted(set(observed) - expected_ids)
            raise SystemExit(f"successor package set mismatch: missing={missing} extra={extra}")

        integrations = tuple(
            package for package in observed.values()
            if package.manifest.module_type == "integration"
        )
        registry = PluginRegistry.from_module_packages(integrations)
        expected_plugins = {"http", "nut", "portainer", "scrypted", "snmp", "unifi", "wol"}
        if set(registry.ids()) != expected_plugins:
            raise SystemExit(
                "successor integration registry mismatch: "
                f"{registry.ids()} != {sorted(expected_plugins)}"
            )

        for artifact_id in (
            "com.sickicarus.monitorbox.ui",
            "com.sickicarus.monitorbox.configuration-bootstrap",
            "com.sickicarus.monitorbox.backup-restore",
        ):
            package = observed[artifact_id]
            if not all(callable(value) for value in package.entrypoints.values()):
                raise SystemExit(f"{artifact_id} has unresolved required callable entrypoint")
    finally:
        for target in inserted:
            while target in sys.path:
                sys.path.remove(target)

    print(
        "qualified 10 successor first-party packages against Core3 Module Runtime API v1 "
        "and Plugin API v1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
