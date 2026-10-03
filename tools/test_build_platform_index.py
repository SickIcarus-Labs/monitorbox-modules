"""Publisher acceptance uses throwaway Ed25519 keys and non-executable fake ZIPs."""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_platform_index import (
    PublicationError,
    _load_key_from_env,
    sign_candidate,
    write_candidate,
)
from verify_platform_index import VerificationError, verify_index, verify_package
from portable_contracts import materialize_contract


ESSENTIALS = (
    ("com.sickicarus.monitorbox.core", "module"),
    ("com.sickicarus.monitorbox.agent", "module"),
    ("com.sickicarus.monitorbox.ui", "module"),
    ("com.sickicarus.monitorbox.configuration-bootstrap", "module"),
    ("com.sickicarus.monitorbox.backup-restore", "module"),
    ("com.sickicarus.monitorbox.scaffold-manager", "scaffold-manager"),
    ("com.sickicarus.monitorbox.runtime.python", "runtime"),
    ("com.sickicarus.monitorbox.runtime.node", "runtime"),
)


class BuildPlatformIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="synthetic-platform-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.packages = self.root / "platform" / "packages"
        self.packages.mkdir(parents=True)
        self.key = Ed25519PrivateKey.generate()
        self.keys = {"ephemeral-test-key": self.key.public_key()}
        self.clock = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
        self.source = {"schema": 1, "repository_id": "official-platform", "artifacts": []}
        for n, (identity, kind) in enumerate(ESSENTIALS):
            filename = f"synthetic-{n}.zip"
            version = (
                "3.13.0" if identity.endswith(".runtime.python")
                else "24.0.0" if identity.endswith(".runtime.node")
                else "3.0.0"
            )
            if kind == "module":
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                    if identity in {
                        "com.sickicarus.monitorbox.core",
                        "com.sickicarus.monitorbox.agent",
                    }:
                        z.writestr(
                            "package.json",
                            json.dumps({
                                "artifact_id": identity,
                                "version": version,
                                "build": 1,
                                "release_eligible": True,
                                "fixture_only": True,
                                "entrypoints": {"synthetic": "never-run"},
                            }),
                        )
                    else:
                        module_type = {
                            "com.sickicarus.monitorbox.ui": "ui",
                            "com.sickicarus.monitorbox.configuration-bootstrap": "configuration",
                            "com.sickicarus.monitorbox.backup-restore": "recovery",
                        }[identity]
                        z.writestr(
                            "package.json",
                            json.dumps({
                                "schema": 1,
                                "artifact_id": identity,
                                "kind": "module",
                                "version": version,
                                "build": 1,
                                "release_eligible": True,
                                "packaging_stage": "successor-module-requalification",
                                "module_runtime": {
                                    "module_id": identity,
                                    "display_name": "Synthetic first-party module",
                                    "version": version,
                                    "build": 1,
                                    "schema": 1,
                                    "state_schema": 1,
                                    "module_type": module_type,
                                    "entrypoints": {
                                        "synthetic": "synthetic_module:entry"
                                    },
                                    "requires_core": ">=3.0.0 <4.0.0",
                                    "requires_runtime_api": ">=1 <2",
                                    "dependencies": [],
                                    "publisher_id": "com.sickicarus",
                                    "permissions": [],
                                    "lifecycle_policy": "required",
                                },
                                "provenance": {
                                    "source": "immutable-signed-2.x-package",
                                    "predecessor_filename": "synthetic-predecessor.zip",
                                    "predecessor_sha256": "0" * 64,
                                },
                            }),
                        )
                    z.writestr(
                        "portable-config.json",
                        materialize_contract(identity, version, 1),
                    )
                    z.writestr("app/SYNTHETIC.txt", "NONEXECUTABLE TEST PACKAGE")
                (self.packages / filename).write_bytes(buffer.getvalue())
            elif kind in {"runtime", "scaffold-manager"}:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                    manifest = {
                        "schema": 1,
                        "artifact_id": identity,
                        "version": version,
                        "build": 1,
                        "kind": kind,
                        "release_eligible": True,
                    }
                    if kind == "runtime":
                        manifest.update({
                            "entrypoint": "runtime/usr/local/bin/interpreter",
                            "dynamic_loader": "runtime/loader/ld-linux-aarch64.so.1",
                        })
                        z.writestr(
                            "runtime/usr/local/bin/interpreter",
                            b"\x7fELF" + bytes(80),
                        )
                        z.writestr(
                            "runtime/loader/ld-linux-aarch64.so.1",
                            b"\x7fELF" + bytes(80),
                        )
                    z.writestr("package.json", json.dumps(manifest))
                (self.packages / filename).write_bytes(buffer.getvalue())

            arch = "any" if kind == "module" else "arm64"
            abi = "pure" if arch == "any" else "static"
            dependencies = []
            if identity.endswith(".core"):
                dependencies = [{
                    "artifact_id": "com.sickicarus.monitorbox.runtime.python",
                    "version_range": ">=3.13.0 <3.14.0",
                }]
            self.source["artifacts"].append({
                "artifact_id": identity,
                "kind": kind,
                "version": version,
                "build": 1,
                "platform": {"os": "linux", "arch": arch, "abi": abi},
                "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
                "dependencies": dependencies,
                "package_file": filename,
            })

    def candidate(self, **overrides) -> bytes:
        arguments = dict(
            package_root=self.root, key=self.key, key_id="ephemeral-test-key",
            channel="dev", sequence=17, generated_at=self.clock,
        )
        arguments.update(overrides)
        return sign_candidate(json.dumps(self.source).encode(), **arguments)

    def test_full_essential_and_runtime_set_signs_and_verifies(self) -> None:
        raw = self.candidate()
        signed = verify_index(raw, keys=self.keys, channel="dev", now=self.clock,
                              min_sequence=17)
        self.assertEqual(len(ESSENTIALS), len(signed["artifacts"]))
        self.assertEqual(sorted(x[0] for x in ESSENTIALS),
                         [a["artifact_id"] for a in signed["artifacts"]])
        for artifact in signed["artifacts"]:
            verify_package(artifact, self.root, self.keys)
            if artifact["kind"] == "module":
                self.assertEqual(1, artifact["portable_config"]["protocol"])
                self.assertEqual([], artifact["portable_config"]["accepted_source_schemas"])
            else:
                self.assertNotIn("portable_config", artifact)
        self.assertEqual(raw, self.candidate(), "fixed timestamp and key must sign deterministically")
        with self.assertRaisesRegex(VerificationError, "regressed"):
            verify_index(raw, keys=self.keys, channel="dev", now=self.clock, min_sequence=18)
        with self.assertRaisesRegex(VerificationError, "channel"):
            verify_index(raw, keys=self.keys, channel="stable", now=self.clock)

    def test_output_is_atomic_and_never_overwrites_published_index(self) -> None:
        target = self.root / "candidate" / "index.json"
        candidate = self.candidate()
        write_candidate(target, candidate)
        self.assertEqual(target.read_bytes(), candidate)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(PublicationError, "overwrite"):
            write_candidate(target, self.candidate(sequence=18))
        self.assertEqual(target.read_bytes(), candidate)

    def test_missing_or_symlinked_package_fails_before_output(self) -> None:
        output = self.root / "not-written.json"
        victim = self.packages / "synthetic-0.zip"
        victim.unlink()
        with self.assertRaisesRegex(PublicationError, "missing"):
            write_candidate(output, self.candidate())
        self.assertFalse(output.exists())
        victim.symlink_to(self.root / "outside")
        with self.assertRaisesRegex(PublicationError, "linked"):
            self.candidate()

    def test_source_traversal_duplicate_and_unknown_fields_rejected(self) -> None:
        self.source["artifacts"][0]["package_file"] = "../outside.zip"
        with self.assertRaisesRegex(PublicationError, "safe filename"):
            self.candidate()
        self.source["artifacts"][0]["package_file"] = "synthetic-0.zip"
        self.source["artifacts"].append(dict(self.source["artifacts"][0]))
        with self.assertRaisesRegex(PublicationError, "duplicate"):
            self.candidate()
        self.source["artifacts"].pop()
        self.source["artifacts"][0]["portable_config"] = {"protocol": 1}
        with self.assertRaisesRegex(PublicationError, "source inventory"):
            self.candidate()
        self.source["artifacts"][0].pop("portable_config")
        self.source["unexpected"] = "unsafe"
        with self.assertRaisesRegex(PublicationError, "only"):
            self.candidate()
        source = json.dumps(self.source).replace('"schema": 1', '"schema": 1, "schema": 1', 1)
        with self.assertRaisesRegex(PublicationError, "duplicate"):
            sign_candidate(source.encode(), package_root=self.root, key=self.key,
                           key_id="ephemeral-test-key", channel="dev", sequence=17,
                           generated_at=self.clock)

    def test_invalid_package_identity_and_platform_fail_closed(self) -> None:
        self.source["artifacts"][0]["platform"]["abi"] = "glibc"
        with self.assertRaisesRegex(PublicationError, "architecture-neutral"):
            self.candidate()
        self.source["artifacts"][0]["platform"]["abi"] = "pure"
        self.source["artifacts"][0]["artifact_id"] = "UPPERCASE!"
        with self.assertRaisesRegex(PublicationError, "identity"):
            self.candidate()

    def test_tampered_bytes_cannot_restore_or_verify(self) -> None:
        raw = self.candidate()
        signed = verify_index(raw, keys=self.keys, channel="dev", now=self.clock)
        a = signed["artifacts"][0]
        path = self.root / a["package"]["url"]
        path.write_bytes(path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(VerificationError, "digest"):
            verify_package(a, self.root, self.keys)

    def test_unreleaseable_core_source_and_false_identity_rejected(self) -> None:
        core = self.source["artifacts"][0]
        path = self.packages / core["package_file"]
        original = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            portable = source.read("portable-config.json")
        for release_eligible, artifact_id, error in (
            (False, core["artifact_id"], "unreleasable"),
            (None, core["artifact_id"], "unreleasable"),
            (True, "com.sickicarus.monitorbox.other", "identity"),
        ):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                z.writestr("package.json", json.dumps({
                    "artifact_id": artifact_id,
                    "version": core["version"],
                    "build": core["build"],
                    "release_eligible": release_eligible,
                }))
                z.writestr("portable-config.json", portable)
            path.write_bytes(buffer.getvalue())
            with self.assertRaisesRegex(PublicationError, error):
                self.candidate()
        path.write_bytes(original)
        self.assertTrue(self.candidate())

    def test_module_contract_missing_duplicate_or_identity_mismatch_rejected(self) -> None:
        core = self.source["artifacts"][0]
        path = self.packages / core["package_file"]
        original = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            package_manifest = source.read("package.json")
            portable = source.read("portable-config.json")

        with io.BytesIO() as out:
            with zipfile.ZipFile(out, "w") as z:
                z.writestr("package.json", package_manifest)
            path.write_bytes(out.getvalue())
        with self.assertRaisesRegex(PublicationError, "exactly one"):
            self.candidate()

        with io.BytesIO() as out:
            with zipfile.ZipFile(out, "w") as z:
                z.writestr("package.json", package_manifest)
                z.writestr("portable-config.json", portable)
                z.writestr("portable-config.json", portable)
            path.write_bytes(out.getvalue())
        with self.assertRaisesRegex(PublicationError, "exactly one"):
            self.candidate()

        altered = json.loads(portable)
        altered["version"] = "3.0.1"
        with io.BytesIO() as out:
            with zipfile.ZipFile(out, "w") as z:
                z.writestr("package.json", package_manifest)
                z.writestr("portable-config.json", json.dumps(altered))
            path.write_bytes(out.getvalue())
        with self.assertRaisesRegex(PublicationError, "package identity"):
            self.candidate()

        path.write_bytes(original)
        self.assertTrue(self.candidate())

    def test_first_party_application_module_requires_qualified_runtime_manifest(self) -> None:
        record = next(
            item for item in self.source["artifacts"]
            if item["artifact_id"] == "com.sickicarus.monitorbox.ui"
        )
        path = self.packages / record["package_file"]
        original = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            portable = source.read("portable-config.json")
            manifest = json.loads(source.read("package.json"))

        cases = [
            ("unqualified", {"release_eligible": False}, "unreleasable"),
            ("wrong-core", {
                "module_runtime": dict(
                    manifest["module_runtime"],
                    requires_core=">=2.7.0 <3.0.0",
                )
            }, "identity/API"),
            ("wrong-identity", {
                "module_runtime": dict(
                    manifest["module_runtime"],
                    module_id="com.sickicarus.monitorbox.other",
                )
            }, "identity/API"),
        ]
        for _, delta, error in cases:
            altered = dict(manifest)
            altered.update(delta)
            with io.BytesIO() as out:
                with zipfile.ZipFile(out, "w") as z:
                    z.writestr("package.json", json.dumps(altered))
                    z.writestr("portable-config.json", portable)
                    z.writestr("app/SYNTHETIC.txt", "NONEXECUTABLE TEST PACKAGE")
                path.write_bytes(out.getvalue())
            with self.assertRaisesRegex(PublicationError, error):
                self.candidate()

        path.write_bytes(original)
        self.assertTrue(self.candidate())

    def test_core_wheelhouse_signs_only_with_complete_hash_locked_closure(self) -> None:
        filename = "core-wheels-1.0.0-1.zip"
        payload = b"synthetic-wheel-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "schema": 1,
            "artifact_id": "com.sickicarus.monitorbox.core.wheels",
            "packaging_stage": "qualified-wheel-closure",
            "release_eligible": True,
            "platform": {"os": "linux", "arch": "arm64", "python": "cp313"},
            "direct_requirements": ["example==1.0.0"],
            "wheels": [{
                "filename": "example-1.0.0-py3-none-any.whl",
                "name": "example",
                "version": "1.0.0",
                "sha256": digest,
                "size": len(payload),
            }],
        }
        path = self.packages / filename
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("wheelhouse.json", json.dumps(manifest))
            archive.writestr("requirements.lock", "synthetic-lock")
            archive.writestr("wheels/example-1.0.0-py3-none-any.whl", payload)
        self.source["artifacts"].append({
            "artifact_id": "com.sickicarus.monitorbox.core.wheels",
            "kind": "runtime",
            "version": "1.0.0",
            "build": 1,
            "platform": {"os": "linux", "arch": "arm64", "abi": "glibc"},
            "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
            "dependencies": [],
            "package_file": filename,
        })
        self.assertTrue(self.candidate())

        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("wheelhouse.json", json.dumps(manifest))
            archive.writestr("requirements.lock", "synthetic-lock")
            archive.writestr("wheels/example-1.0.0-py3-none-any.whl", payload + b"tamper")
        with self.assertRaisesRegex(PublicationError, "differ"):
            self.candidate()

    def test_runtime_and_manager_require_explicit_approval_and_matching_identity(self) -> None:
        for position in (5, 6, 7):
            record = self.source["artifacts"][position]
            artifact = self.packages / record["package_file"]
            original = artifact.read_bytes()
            with zipfile.ZipFile(io.BytesIO(original)) as z:
                base = json.loads(z.read("package.json"))
            for delta, expected_error in (
                ({"release_eligible": False}, "unreleasable"),
                ({"release_eligible": None}, "unreleasable"),
                ({"artifact_id": "com.sickicarus.monitorbox.other"}, "identity"),
            ):
                altered = dict(base, **delta)
                with zipfile.ZipFile(io.BytesIO(original)) as src, io.BytesIO() as out:
                    with zipfile.ZipFile(out, "w") as dst:
                        for name in src.namelist():
                            dst.writestr(name, json.dumps(altered) if name == "package.json" else src.read(name))
                    artifact.write_bytes(out.getvalue())
                with self.assertRaisesRegex(PublicationError, expected_error):
                    self.candidate()
            artifact.write_bytes(original)
        self.assertTrue(self.candidate())

    def test_runtime_missing_loader_and_forged_elf_fail_before_signing(self) -> None:
        record = self.source["artifacts"][6]
        artifact = self.packages / record["package_file"]
        original = artifact.read_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as src:
            manifest = json.loads(src.read("package.json"))
            with io.BytesIO() as out:
                with zipfile.ZipFile(out, "w") as dst:
                    dst.writestr("package.json", json.dumps(manifest))
                    dst.writestr(manifest["entrypoint"], b"ELF-pretend")
                artifact.write_bytes(out.getvalue())
        # The first candidate is doubly invalid: forged executable bytes
        # and an omitted ELF loader. The independent ELF check rejects it.
        with self.assertRaisesRegex(PublicationError, "ELF data"):
            self.candidate()
        # Now include a genuine ELF-marked entrypoint, retaining the missing
        # loader to prove that *both* required files are enforced.
        with io.BytesIO() as out:
            with zipfile.ZipFile(out, "w") as dst:
                dst.writestr("package.json", json.dumps(manifest))
                dst.writestr(manifest["entrypoint"], b"\x7fELF" + bytes(80))
            artifact.write_bytes(out.getvalue())
        with self.assertRaisesRegex(PublicationError, "missing safe"):
            self.candidate()
        artifact.write_bytes(original)

    def test_expiry_and_future_or_invalid_key_rejected(self) -> None:
        raw = self.candidate()
        with self.assertRaisesRegex(VerificationError, "expired"):
            verify_index(raw, keys=self.keys, channel="dev", now=self.clock + timedelta(hours=49))
        with self.assertRaisesRegex(PublicationError, "expiry"):
            self.candidate(valid_hours=999)
        with self.assertRaisesRegex(PublicationError, "timezone"):
            self.candidate(generated_at=datetime(2026, 9, 27))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PublicationError, "missing private"):
                _load_key_from_env("MONITORBOX_PLATFORM_SIGNING_KEY")
        with patch.dict(os.environ, {"SYNTHETIC_KEY": base64.b64encode(b"short").decode()}):
            with self.assertRaisesRegex(PublicationError, "32 bytes"):
                _load_key_from_env("SYNTHETIC_KEY")


if __name__ == "__main__":
    unittest.main()
