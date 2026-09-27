"""Synthetic-key-only tests. No production package or signing keys are used."""
import base64
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from verify_platform_index import VerificationError, canonical, verify_index, verify_package


class PlatformContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.keys = {"ci-only": self.key.public_key()}
        self.data = b"CI SYNTHETIC PACKAGE; NOT EXECUTABLE"
        target = self.root / "platform/packages/test-package.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(self.data)
        self.pkg = {
            "url": "platform/packages/test-package.zip",
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size": len(self.data),
            "signature": self.sign(self.data),
        }
        self.artifact = {
            "artifact_id": "com.sickicarus.monitorbox.core", "kind": "module",
            "version": "3.0.0", "build": 1,
            "platform": {"os": "linux", "arch": "any", "abi": "pure"},
            "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
            "dependencies": [], "package": self.pkg,
        }
        self.now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        self.signed = {
            "repository_id": "official-platform", "channel": "stable", "sequence": 5,
            "generated_at": (self.now - timedelta(minutes=1)).isoformat(),
            "expires_at": (self.now + timedelta(days=1)).isoformat(),
            "artifacts": [self.artifact],
        }

    def sign(self, raw):
        return {"algorithm": "ed25519", "identity": "ci-only",
                "value": base64.b64encode(self.key.sign(raw)).decode("ascii")}

    def envelope(self):
        return json.dumps({"schema": 1, "signed": self.signed,
                           "signature": self.sign(canonical(self.signed))}).encode("utf-8")

    def verify(self, **kwargs):
        return verify_index(self.envelope(), keys=self.keys, channel="stable", now=self.now, **kwargs)

    def test_valid_signed_index_and_raw_package(self):
        result = self.verify(min_sequence=5)
        self.assertEqual(1, len(result["artifacts"]))
        verify_package(self.artifact, self.root, self.keys)

    def test_replay_and_wrong_channel(self):
        with self.assertRaisesRegex(VerificationError, "regressed"):
            self.verify(min_sequence=6)
        with self.assertRaisesRegex(VerificationError, "channel"):
            verify_index(self.envelope(), keys=self.keys, channel="dev", now=self.now)

    def test_signature_tamper(self):
        raw = self.envelope().replace(b'"sequence": 5', b'"sequence": 6')
        with self.assertRaisesRegex(VerificationError, "signature"):
            verify_index(raw, keys=self.keys, channel="stable", now=self.now)

    def test_expiry(self):
        with self.assertRaisesRegex(VerificationError, "expired"):
            verify_index(self.envelope(), keys=self.keys, channel="stable",
                         now=self.now + timedelta(days=2))

    def test_duplicate_json_key(self):
        raw = self.envelope().replace(b'"schema": 1', b'"schema": 1, "schema": 1', 1)
        with self.assertRaisesRegex(VerificationError, "duplicate"):
            verify_index(raw, keys=self.keys, channel="stable", now=self.now)

    def test_unsafe_package_path(self):
        self.artifact["package"]["url"] = "platform/packages/../secret.zip"
        with self.assertRaisesRegex(VerificationError, "unsafe"):
            self.verify()

    def test_symlink_escape_and_corruption(self):
        target = self.root / "platform/packages/test-package.zip"
        target.write_bytes(b"tampered")
        with self.assertRaisesRegex(VerificationError, "digest"):
            verify_package(self.artifact, self.root, self.keys)
        target.unlink()
        target.symlink_to(self.root / "other")
        with self.assertRaisesRegex(VerificationError, "symlink"):
            verify_package(self.artifact, self.root, self.keys)

    def test_missing_trust_root(self):
        with self.assertRaisesRegex(VerificationError, "unknown"):
            verify_index(self.envelope(), keys={}, channel="stable", now=self.now)

    def test_architecture_neutral_must_be_pure(self):
        self.artifact["platform"]["abi"] = "static"
        with self.assertRaisesRegex(VerificationError, "architecture-neutral"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
