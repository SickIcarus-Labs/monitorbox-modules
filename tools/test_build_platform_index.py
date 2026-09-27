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
            if identity in {"com.sickicarus.monitorbox.core", "com.sickicarus.monitorbox.agent"}:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr("package.json", json.dumps({"artifact_id": identity, "version": "3.0.0", "build": 1, "release_eligible": True,
                                                            "fixture_only": True, "entrypoints": {"synthetic": "never-run"}}))
                    z.writestr("app/SYNTHETIC.txt", "NONEXECUTABLE TEST PACKAGE")
                (self.packages / filename).write_bytes(buffer.getvalue())
            else:
                (self.packages / filename).write_bytes((f"NONEXECUTABLE {identity}\n" * 16).encode())
            arch = "any" if kind == "module" else "arm64"
            abi = "pure" if arch == "any" else "static"
            dependencies = []
            if identity.endswith(".core"):
                dependencies = [{"artifact_id": "com.sickicarus.monitorbox.runtime.python", "version_range": ">=3.13.0 <3.14.0"}]
            self.source["artifacts"].append({
                "artifact_id": identity, "kind": kind,
                "version": "3.13.0" if identity.endswith(".runtime.python") else "24.0.0" if identity.endswith(".runtime.node") else "3.0.0",
                "build": 1, "platform": {"os": "linux", "arch": arch, "abi": abi},
                "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
                "dependencies": dependencies, "package_file": filename,
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
        with self.assertRaisesRegex(PublicationError, "schema"):
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
        for release_eligible, artifact_id, error in (
            (False, core["artifact_id"], "unreleasable"),
            (None, core["artifact_id"], "unreleasable"),
            (True, "com.sickicarus.monitorbox.other", "identity"),
        ):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                z.writestr("package.json", json.dumps({"artifact_id": artifact_id,
                    "version": core["version"], "build": core["build"],
                    "release_eligible": release_eligible}))
            path.write_bytes(buffer.getvalue())
            with self.assertRaisesRegex(PublicationError, error):
                self.candidate()
        path.write_bytes(original)
        self.assertTrue(self.candidate())

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
