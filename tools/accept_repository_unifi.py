#!/usr/bin/env python3
"""Extend first-party repository acceptance through UniFi Network v1.0.2 build 3."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_snmp as previous

UNIFI_ID = "com.sickicarus.monitorbox.unifi"
UNIFI_BUILD1 = (UNIFI_ID, "1.0.0", 1)
UNIFI_BUILD2 = (UNIFI_ID, "1.0.1", 2)
UNIFI_BUILD3 = (UNIFI_ID, "1.0.2", 3)
UNIFI_RELEASES = {UNIFI_BUILD1, UNIFI_BUILD2, UNIFI_BUILD3}
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | UNIFI_RELEASES
IMPORT_BUILD1 = "monitorbox_unifi_b1"
IMPORT_BUILD2 = "monitorbox_unifi_b2"
IMPORT_BUILD3 = "monitorbox_unifi_b3"


def _release(source: dict, identity: tuple[str, str, int]) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == identity
        ),
        None,
    )
    if item is None:
        raise AssertionError(f"UniFi Network release is missing: {identity!r}")
    return item


def _expected_manifest(version: str, build: int, import_package: str) -> dict:
    return {
        "module_id": UNIFI_ID,
        "display_name": "UniFi Network Integration",
        "version": version,
        "build": build,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": f"{import_package}:PLUGIN"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }


def _package_texts(
    root: Path,
    source: dict,
    identity: tuple[str, str, int],
    import_package: str,
) -> dict[str, str]:
    release = _release(source, identity)
    version, build = identity[1], identity[2]
    expected_manifest = _expected_manifest(version, build, import_package)
    if release.get("manifest") != expected_manifest:
        raise AssertionError(
            f"UniFi Network {version} build {build} manifest changed: {release.get('manifest')!r}"
        )

    expected_filename = f"{UNIFI_ID}-{version}-build{build}.zip"
    package_path = root / "packages" / release["package"]
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError(
            f"UniFi Network {version} build {build} package is missing or misnamed"
        )

    expected_files = {
        f"{import_package}/__init__.py",
        f"{import_package}/adoption.py",
        f"{import_package}/discovery.py",
        f"{import_package}/discovery_runtime.py",
        f"{import_package}/onboarding.py",
        f"{import_package}/runtime.py",
        f"{import_package}/vertical_runtime.py",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError(
                f"UniFi Network {version} build {build} package shape changed: "
                f"missing={sorted(expected_files - names)}, extra={sorted(names - expected_files)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed UniFi package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, f"{import_package}/")
        return {name: archive.read(name).decode("utf-8") for name in expected_files}


def _assert_common_contract(
    texts: dict[str, str],
    *,
    version: str,
    build: int,
    import_package: str,
) -> None:
    root_text = texts[f"{import_package}/__init__.py"]
    runtime_text = texts[f"{import_package}/runtime.py"]
    vertical_text = texts[f"{import_package}/vertical_runtime.py"]

    required = (
        'metadata=PluginMetadata(plugin_id="unifi", display_name="UniFi Network")',
        'runtime_adapter_kinds=("unifi",)',
        "candidate_adoption=_UNIFI_ADOPTION",
        f'entrypoints={{"integration": "{import_package}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
    )
    missing = [marker for marker in required if marker not in root_text]
    if missing:
        raise AssertionError(f"UniFi managed package root omitted contract markers: {missing}")

    runtime_required = (
        'MODULE_ID = "com.sickicarus.monitorbox.unifi"',
        f'MODULE_VERSION = "{version}"',
        f"MODULE_BUILD = {build}",
        '_STATE_FILE = "link-expectations.json"',
        '"failure_kind": "unsupported_runtime_operation"',
        f'entrypoints={{"integration": "{import_package}:PLUGIN"}}',
    )
    missing_runtime = [marker for marker in runtime_required if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"UniFi runtime omitted release/state markers: {missing_runtime}")

    vertical_required = (
        "_PERSISTENCE_VERSION = 2",
        'Path(context.state_root) / "link-expectations.json"',
        '"failure_kind": "monitor_dependency"',
        '"authoritative": False',
        'State.FAILED, "Switch port is enabled but has no link"',
    )
    missing_vertical = [marker for marker in vertical_required if marker not in vertical_text]
    if missing_vertical:
        raise AssertionError(f"UniFi vertical runtime omitted state/truth markers: {missing_vertical}")

    forbidden = (
        "from ...discovery",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.unifi:PLUGIN",
    )
    present = [
        marker
        for marker in forbidden
        if any(marker in text for text in texts.values())
    ]
    if present:
        raise AssertionError(f"UniFi managed namespace rewrite is incomplete: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    build1 = _package_texts(root, source, UNIFI_BUILD1, IMPORT_BUILD1)
    _assert_common_contract(build1, version="1.0.0", build=1, import_package=IMPORT_BUILD1)

    build2 = _package_texts(root, source, UNIFI_BUILD2, IMPORT_BUILD2)
    _assert_common_contract(build2, version="1.0.1", build=2, import_package=IMPORT_BUILD2)
    recovery_text = build2[f"{IMPORT_BUILD2}/discovery_runtime.py"]
    recovery_required = (
        "_AUTH_DENIAL_HTTP_STATUSES = {401, 403}",
        "self._invalidate_auth(options",
        '"failure_kind": "monitor_dependency"',
        '"authoritative": False',
        'state="unknown"',
    )
    missing_recovery = [marker for marker in recovery_required if marker not in recovery_text]
    if missing_recovery:
        raise AssertionError(
            f"UniFi 1.0.1 build 2 omitted auth-recovery truth markers: {missing_recovery}"
        )

    build3 = _package_texts(root, source, UNIFI_BUILD3, IMPORT_BUILD3)
    _assert_common_contract(build3, version="1.0.2", build=3, import_package=IMPORT_BUILD3)
    backoff_text = build3[f"{IMPORT_BUILD3}/discovery_runtime.py"]
    backoff_required = (
        "_AUTH_DENIAL_INITIAL_BACKOFF_SECONDS = 30.0",
        "_RATE_LIMIT_INITIAL_BACKOFF_SECONDS = 60.0",
        "_MAX_AUTH_BACKOFF_SECONDS = 300.0",
        "_auth_cooldown",
        "Retry-After",
        "response.status == 429",
        "UniFi authentication cooldown active",
        '"failure_kind": "monitor_dependency"',
        'state="unknown"',
    )
    missing_backoff = [marker for marker in backoff_required if marker not in backoff_text]
    if missing_backoff:
        raise AssertionError(
            f"UniFi 1.0.2 build 3 omitted auth-backoff markers: {missing_backoff}"
        )

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in UNIFI_RELEASES
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
