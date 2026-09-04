#!/usr/bin/env python3
"""Offline acceptance for the public MonitorBox module repository publication contract."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_repository import build as build_repository, canonical

UI_ID = "com.sickicarus.monitorbox.ui"
PORTAINER_ID = "com.sickicarus.monitorbox.portainer"
EXPECTED_RELEASES = {
    (UI_ID, "1.0.0", 2),
    (UI_ID, "1.0.0", 3),
    (UI_ID, "1.0.0", 4),
    (UI_ID, "1.0.0", 5),
    (UI_ID, "1.0.1", 6),
    (PORTAINER_ID, "1.0.0", 2),
    (PORTAINER_ID, "1.0.0", 3),
    (PORTAINER_ID, "1.0.0", 4),
    (PORTAINER_ID, "1.0.0", 5),
}
SIGNATURE_IDENTITY = "acceptance-ephemeral-ed25519"
PORTAINER_SOURCE_FILES = {
    "__init__.py",
    "adoption.py",
    "deployment_transition.py",
    "endpoint_provenance.py",
    "expected_state_diagnostics.py",
    "lifecycle_diagnostics.py",
    "lifecycle_truth.py",
    "onboarding.py",
    "reconciliation.py",
    "review.py",
    "runtime.py",
    "suggestions.py",
    "validation.py",
}


def _release_identity(item: dict) -> tuple[str, str, int]:
    manifest = item["manifest"]
    return manifest["module_id"], manifest["version"], manifest["build"]


def _assert_python_syntax(archive: zipfile.ZipFile, names: set[str], package_root: str) -> None:
    for name in sorted(names):
        if not name.startswith(package_root) or not name.endswith(".py"):
            continue
        compile(archive.read(name), name, "exec")


def _ui_package_shape(archive: zipfile.ZipFile, names: set[str], build: int) -> None:
    package_root = f"monitorbox_ui_b{build}/"
    if f"{package_root}__init__.py" not in names:
        raise AssertionError(f"UI build {build} has no importable package root")
    if any(name.startswith("monitorbox/") for name in names):
        raise AssertionError("managed package may not shadow frozen Core's monitorbox namespace")
    expected_delta = build in {3, 4, 5, 6}
    for asset in ("discovery-v22.js", "endpoint-prefill-v22.js"):
        present = f"{package_root}assets/{asset}" in names
        if present != expected_delta:
            raise AssertionError(
                f"UI build {build} certified delta shape is wrong for {asset}"
            )
    hierarchy_assets = ("service-presentation.js", "service-presentation.css")
    for asset in hierarchy_assets:
        present = f"{package_root}assets/{asset}" in names
        if present != (build in {5, 6}):
            raise AssertionError(
                f"UI build {build} Compose hierarchy delta shape is wrong for {asset}"
            )
    _assert_python_syntax(archive, names, package_root)

    if build in {4, 5, 6}:
        discovery = archive.read(f"{package_root}assets/discovery-v22.js").decode("utf-8")
        required = (
            "function providerProvenance(item)",
            "metadata.environment_name||metadata.environment",
            "metadata.stack_name||metadata.compose_project",
            "metadata.compose_service",
            "metadata.deployment_kind",
            "Environment/System · ${environment}",
            "Stack · ${stack}",
            "Service · ${service}",
            "Deployment · ${deployment}",
            "renderProviderProvenance(row,item);",
            "line.textContent=text",
        )
        missing = [marker for marker in required if marker not in discovery]
        if missing:
            raise AssertionError(
                f"UI build {build} omitted provenance contract markers: {missing}"
            )
        forbidden = ("environment_url", "provider_id", "JSON.stringify(metadata)")
        present = [marker for marker in forbidden if marker in discovery]
        if present:
            raise AssertionError(
                f"UI build {build} leaks forbidden provider metadata: {present}"
            )

    if build in {5, 6}:
        hierarchy = archive.read(
            f"{package_root}assets/service-presentation.js"
        ).decode("utf-8")
        required_hierarchy = (
            "function serviceComposeProvenance(service)",
            "function servicePresentationEntries(services)",
            "function serviceStackRow(site,entry,parent)",
            "data-compose-stack=",
            "group.services.length<2",
            "stateRank(entry.state)>0",
            "data-service-object=",
            "health_participant:false",
            "environmentKey",
            "compose_project",
        )
        missing = [marker for marker in required_hierarchy if marker not in hierarchy]
        if missing:
            raise AssertionError(
                f"UI build {build} omitted Compose hierarchy contract markers: {missing}"
            )
        css = archive.read(
            f"{package_root}assets/service-presentation.css"
        ).decode("utf-8")
        required_css = (
            ".service-compose-group",
            ".service-compose-summary",
            ".service-compose-members",
            ".service-compose-group[open]",
        )
        missing_css = [marker for marker in required_css if marker not in css]
        if missing_css:
            raise AssertionError(
                f"UI build {build} omitted Compose hierarchy CSS markers: {missing_css}"
            )

    if build == 6:
        hierarchy = archive.read(
            f"{package_root}assets/service-presentation.js"
        ).decode("utf-8")
        required_provider_backing = (
            "function portainerInventoryWorkloads(site)",
            "function providerEnvironmentOwners(site,workloads)",
            "function providerPresentationModel(site)",
            "authenticated_portainer_controller",
            "['host','appliance']",
            "kind:'provider_workload'",
            "expected-state intent is not configured",
            "function renderProviderWorkloadDrawer(site,object)",
        )
        missing = [marker for marker in required_provider_backing if marker not in hierarchy]
        if missing:
            raise AssertionError(
                f"UI 1.0.1 build 6 omitted provider-backed hierarchy markers: {missing}"
            )
        forbidden_provider_backing = (
            "turnberry_-_apollo",
            "broad_leaf_-_goliath",
            "broad_leaf_-_arrrrr2",
            "192.168.3.13",
            "192.168.3.9",
        )
        present = [marker for marker in forbidden_provider_backing if marker in hierarchy]
        if present:
            raise AssertionError(
                f"UI build 6 embedded deployment-specific provider ownership: {present}"
            )


def _portainer_package_shape(
    archive: zipfile.ZipFile,
    names: set[str],
    build: int,
) -> None:
    package = f"monitorbox_portainer_b{build}"
    package_root = f"{package}/"
    expected_names = {f"{package_root}{name}" for name in PORTAINER_SOURCE_FILES}
    if names != expected_names:
        raise AssertionError(
            f"Portainer build {build} package shape changed: "
            f"missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
        )
    if any(name.startswith("monitorbox/") for name in names):
        raise AssertionError("managed Portainer package may not shadow Core's monitorbox namespace")
    _assert_python_syntax(archive, names, package_root)

    source = archive.read(f"{package_root}__init__.py").decode("utf-8")
    if build == 2:
        guard_marker = "managed Portainer build 2 requires MonitorBox Core build 0545 provider authority"
    else:
        guard_marker = f"managed Portainer build {build} requires MonitorBox Core build 0545+ provider authority"
    required_markers = (
        "monitorbox.v2.plugin_api.provider_authority",
        guard_marker,
        f'entrypoints={{"integration": "{package}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
    )
    for marker in required_markers:
        if marker not in source:
            raise AssertionError(f"Portainer managed package root omitted {marker!r}")

    forbidden = (
        "from ...plugin_api",
        "from ...canonical_config",
        "from ...operator_ontology",
        "monitorbox.v2.integrations.portainer:PLUGIN",
    )
    for path in sorted(expected_names):
        text = archive.read(path).decode("utf-8")
        present = [marker for marker in forbidden if marker in text]
        if present:
            raise AssertionError(f"Portainer managed namespace rewrite incomplete in {path}: {present}")

    if build in {4, 5}:
        validation = archive.read(f"{package_root}validation.py").decode("utf-8")
        if "from .runtime import MODULE_ID" in validation:
            raise AssertionError(
                f"Portainer build {build} reintroduced validation's activation-breaking runtime identity import"
            )
        required_validation = (
            '_PORTAINER_MODULE_ID = "com.sickicarus.monitorbox.portainer"',
            "module_id=_PORTAINER_MODULE_ID",
        )
        missing = [marker for marker in required_validation if marker not in validation]
        if missing:
            raise AssertionError(
                f"Portainer build {build} validation identity contract is incomplete: {missing}"
            )


def _package_shape(root: Path, source: dict) -> None:
    modules = source.get("modules")
    if not isinstance(modules, list):
        raise AssertionError("catalog modules must be an array")
    identities = {_release_identity(item) for item in modules}
    if identities != EXPECTED_RELEASES or len(modules) != len(EXPECTED_RELEASES):
        raise AssertionError(
            f"expected repository releases {sorted(EXPECTED_RELEASES)}, got {sorted(identities)}"
        )

    ui_versions = {2: "1.0.0", 3: "1.0.0", 4: "1.0.0", 5: "1.0.0", 6: "1.0.1"}
    for item in modules:
        manifest = item["manifest"]
        module_id, version, build = _release_identity(item)
        if module_id == UI_ID:
            if ui_versions.get(build) != version:
                raise AssertionError(f"unexpected UI release {(version, build)}")
            expected_entrypoint = {"webui": f"monitorbox_ui_b{build}:install"}
            if manifest["entrypoints"] != expected_entrypoint:
                raise AssertionError(
                    f"UI build {build} does not use its generation-specific entrypoint"
                )
            if manifest.get("module_type") != "ui" or manifest.get("lifecycle_policy") != "required":
                raise AssertionError(f"UI build {build} lifecycle/type contract changed")
            if manifest.get("requires_core") != ">=2.2.2 <3.0.0":
                raise AssertionError(f"UI build {build} Core SemVer floor changed")
        elif module_id == PORTAINER_ID:
            if version != "1.0.0" or build not in {2, 3, 4, 5}:
                raise AssertionError(f"unexpected Portainer release {(version, build)}")
            package = f"monitorbox_portainer_b{build}"
            if manifest["entrypoints"] != {"integration": f"{package}:PLUGIN"}:
                raise AssertionError(
                    f"Portainer build {build} does not use its generation-specific entrypoint"
                )
            if manifest.get("module_type") != "integration":
                raise AssertionError(f"Portainer build {build} is not an integration module")
            if manifest.get("lifecycle_policy") != "optional":
                raise AssertionError(
                    f"Portainer build {build} must remain ordinarily removable/disableable"
                )
            if manifest.get("requires_core") != ">=2.3.0 <3.0.0":
                raise AssertionError(f"Portainer build {build} Core SemVer floor changed")
        else:
            raise AssertionError(f"unexpected module id {module_id!r}")

        package_path = root / "packages" / item["package"]
        if not package_path.is_file():
            raise AssertionError(f"generated package is missing: {package_path.name}")
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            if module_id == UI_ID:
                _ui_package_shape(archive, names, build)
            else:
                _portainer_package_shape(archive, names, build)


def _signed_repository(root: Path, source: dict) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    with tempfile.TemporaryDirectory(prefix="monitorbox-public-repository-") as directory:
        output = Path(directory) / "index.json"
        build_repository(
            root / "catalog.source.json",
            output,
            private_key,
            SIGNATURE_IDENTITY,
        )
        envelope = json.loads(output.read_text(encoding="utf-8"))

    if envelope.get("schema") != 1:
        raise AssertionError("repository envelope schema changed")
    signed = envelope.get("signed")
    signature = envelope.get("signature")
    if not isinstance(signed, dict) or not isinstance(signature, dict):
        raise AssertionError("repository envelope is missing signed/signature objects")
    if signed.get("repository_id") != "official" or signed.get("display_name") != "MonitorBox Official":
        raise AssertionError("signed repository identity changed")
    if signature.get("algorithm") != "ed25519" or signature.get("identity") != SIGNATURE_IDENTITY:
        raise AssertionError("repository signature metadata changed")
    public_key.verify(base64.b64decode(signature["value"], validate=True), canonical(signed))

    releases = signed.get("modules")
    if not isinstance(releases, list):
        raise AssertionError("signed repository modules are missing")
    signed_identities = {_release_identity(item) for item in releases}
    if signed_identities != EXPECTED_RELEASES or len(releases) != len(EXPECTED_RELEASES):
        raise AssertionError("signed repository release set changed")

    source_by_identity = {_release_identity(item): item for item in source["modules"]}
    for release in releases:
        identity = _release_identity(release)
        package = release["package"]
        expected_name = source_by_identity[identity]["package"]
        if package["filename"] != expected_name or package["url"] != f"packages/{expected_name}":
            raise AssertionError(f"signed package location changed for {identity}")
        payload = (root / "packages" / expected_name).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if package["sha256"] != digest:
            raise AssertionError(f"signed package digest is wrong for {identity}")
        if package["signature_identity"] != SIGNATURE_IDENTITY:
            raise AssertionError(f"signed package identity is wrong for {identity}")
        public_key.verify(base64.b64decode(package["signature"], validate=True), payload)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    _package_shape(root, source)
    _signed_repository(root, source)
    print(
        "public module repository acceptance: PASS "
        "(reproducible UI builds 2/3/4/5 + UI v1.0.1 build 6 + immutable Portainer "
        "builds 2/3/4 + Portainer build 5 lifecycle-certified release + signed repository)"
    )


if __name__ == "__main__":
    main()
