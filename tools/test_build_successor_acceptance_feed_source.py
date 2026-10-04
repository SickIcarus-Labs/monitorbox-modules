from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_successor_acceptance_feed_source import (
    AGENT,
    APP_IDS,
    CORE,
    MANAGER,
    NODE,
    PYTHON,
    REQUIRED_ARCH_IDS,
    WHEELS,
    FeedSourceError,
    build_source,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "platform" / "modules" / "first-party-successor-v1.json"
CORE_SOURCE_SHA = "a" * 40


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(entries.items()):
            archive.writestr(name, payload)
    return out.getvalue()


def manifest_zip(manifest: dict) -> bytes:
    return zip_bytes({
        "package.json": (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    })


class SuccessorAcceptanceFeedSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="successor-feed-source-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.packages = self.root / "packages"
        self.packages.mkdir()
        self.authority = json.loads(AUTHORITY.read_text("utf-8"))
        self.by_app = {
            item["artifact_id"]: item for item in self.authority["modules"]
        }
        self._build_complete_fixture()

    def write(self, name: str, payload: bytes) -> Path:
        path = self.packages / name
        path.write_bytes(payload)
        return path

    def _build_complete_fixture(self) -> None:
        for app_id in sorted(APP_IDS):
            item = self.by_app[app_id]
            self.write(
                app_id + ".zip",
                manifest_zip({
                    "schema": 1,
                    "artifact_id": app_id,
                    "kind": "module",
                    "version": item["version"],
                    "build": item["build"],
                    "release_eligible": True,
                    "packaging_stage": "successor-module-requalification",
                }),
            )

        for arch in ("amd64", "arm64"):
            runtime_packages: dict[str, tuple[Path, dict]] = {}
            for artifact_id, version in (
                (PYTHON, "3.13.15"),
                (NODE, "24.21.0"),
            ):
                manifest = {
                    "schema": 1,
                    "artifact_id": artifact_id,
                    "kind": "runtime",
                    "version": version,
                    "build": 1,
                    "release_eligible": True,
                    "packaging_stage": "qualified-native-runtime",
                    "platform": {"os": "linux", "arch": arch, "abi": "glibc"},
                }
                path = self.write(
                    f"{artifact_id}-{arch}.zip",
                    manifest_zip(manifest),
                )
                runtime_packages[artifact_id] = (path, manifest)

            wheel_manifest = {
                "schema": 1,
                "artifact_id": WHEELS,
                "packaging_stage": "qualified-wheel-closure",
                "release_eligible": True,
                "platform": {"os": "linux", "arch": arch, "python": "cp313"},
                "direct_requirements": ["example==1.0.0"],
                "wheels": [],
            }
            wheel_path = self.write(
                f"{WHEELS}-{arch}.zip",
                zip_bytes({
                    "wheelhouse.json": (
                        json.dumps(wheel_manifest, sort_keys=True) + "\n"
                    ).encode(),
                    "requirements.lock": b"synthetic\n",
                }),
            )

            manager_manifest = {
                "schema": 1,
                "artifact_id": MANAGER,
                "kind": "scaffold-manager",
                "version": "1.0.0",
                "build": 1,
                "release_eligible": True,
                "packaging_stage": "successor-scaffold-manager",
                "git_sha": CORE_SOURCE_SHA,
                "platform": {"os": "linux", "arch": arch, "abi": "static"},
                "entrypoint": "bin/monitorbox-scaffold",
            }
            self.write(
                f"{MANAGER}-{arch}.zip",
                manifest_zip(manager_manifest),
            )

            runtime_path, runtime_manifest = runtime_packages[PYTHON]
            runtime_digest = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
            wheel_digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
            runtime_ref = {
                "artifact_id": PYTHON,
                "version": runtime_manifest["version"],
                "build": runtime_manifest["build"],
                "sha256": runtime_digest,
            }
            wheel_ref = {
                "artifact_id": WHEELS,
                "version": "1.0.0",
                "build": 1,
                "sha256": wheel_digest,
            }
            for artifact_id in (CORE, AGENT):
                self.write(
                    f"{artifact_id}-{arch}.zip",
                    manifest_zip({
                        "schema": 1,
                        "artifact_id": artifact_id,
                        "kind": "module",
                        "version": "3.0.0",
                        "build": 1,
                        "release_eligible": True,
                        "packaging_stage": "qualified-interpreted",
                        "git_sha": CORE_SOURCE_SHA,
                        "runtime": runtime_ref,
                        "wheelhouse": wheel_ref,
                    }),
                )

    def test_exact_twenty_two_artifact_closure_is_derived(self) -> None:
        source = build_source(
            self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
        )
        artifacts = source["artifacts"]
        self.assertEqual("official-platform", source["repository_id"])
        self.assertEqual(22, len(artifacts))
        identities = {
            (item["artifact_id"], item["platform"]["arch"])
            for item in artifacts
        }
        expected = {
            (artifact_id, arch)
            for artifact_id in REQUIRED_ARCH_IDS
            for arch in ("amd64", "arm64")
        } | {(artifact_id, "any") for artifact_id in APP_IDS}
        self.assertEqual(expected, identities)

        for role in (CORE, AGENT):
            records = [
                item for item in artifacts if item["artifact_id"] == role
            ]
            self.assertEqual(2, len(records))
            for item in records:
                self.assertEqual("pure", item["platform"]["abi"])
                dependencies = {
                    dep["artifact_id"]: dep["version_range"]
                    for dep in item["dependencies"]
                }
                self.assertEqual("==3.13.15", dependencies[PYTHON])
                self.assertEqual("==1.0.0", dependencies[WHEELS])

        scrypted = next(
            item for item in artifacts
            if item["artifact_id"] == "com.sickicarus.monitorbox.scrypted"
        )
        self.assertEqual(
            {CORE, NODE},
            {dep["artifact_id"] for dep in scrypted["dependencies"]},
        )

    def test_core_source_identity_is_exact_for_roles_and_manager(self) -> None:
        core = self.packages / f"{CORE}-amd64.zip"
        with zipfile.ZipFile(core) as archive:
            manifest = json.loads(archive.read("package.json"))
        manifest["git_sha"] = "b" * 40
        core.write_bytes(manifest_zip(manifest))
        with self.assertRaisesRegex(
            FeedSourceError, "source-unbound"
        ):
            build_source(
                self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
            )

        self._build_complete_fixture()
        manager = self.packages / f"{MANAGER}-arm64.zip"
        with zipfile.ZipFile(manager) as archive:
            manifest = json.loads(archive.read("package.json"))
        manifest["git_sha"] = "b" * 40
        manager.write_bytes(manifest_zip(manifest))
        with self.assertRaisesRegex(
            FeedSourceError, "exact Core source"
        ):
            build_source(
                self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
            )

    def test_missing_architecture_fails_closed(self) -> None:
        (self.packages / f"{MANAGER}-arm64.zip").unlink()
        with self.assertRaisesRegex(FeedSourceError, "incomplete successor feed closure"):
            build_source(
            self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
        )

    def test_core_exact_runtime_digest_must_resolve_to_package_bytes(self) -> None:
        core = self.packages / f"{CORE}-amd64.zip"
        with zipfile.ZipFile(core) as archive:
            manifest = json.loads(archive.read("package.json"))
        manifest["runtime"]["sha256"] = "0" * 64
        core.write_bytes(manifest_zip(manifest))
        with self.assertRaisesRegex(
            FeedSourceError, "exact dependency package is absent"
        ):
            build_source(
            self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
        )

    def test_first_party_release_identity_must_match_reviewed_authority(self) -> None:
        ui = self.packages / "com.sickicarus.monitorbox.ui.zip"
        with zipfile.ZipFile(ui) as archive:
            manifest = json.loads(archive.read("package.json"))
        manifest["build"] += 1
        ui.write_bytes(manifest_zip(manifest))
        with self.assertRaisesRegex(
            FeedSourceError, "disagrees with successor authority"
        ):
            build_source(
            self.packages, AUTHORITY, core_source_sha=CORE_SOURCE_SHA
        )


if __name__ == "__main__":
    unittest.main()
