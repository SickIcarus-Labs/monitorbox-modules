"""Synthetic fail-closed tests: OCI-bound Debian .deb/CA hash lock, no network."""
from __future__ import annotations
import importlib.util
import json
import platform
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("freeze_runtime_debian_closure.py")
spec = importlib.util.spec_from_file_location("freeze_runtime_debian_closure_test", SOURCE)
assert spec and spec.loader
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)


class FrozenRuntimeDebianTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mb-test-debian-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
        if self.native is None:
            self.skipTest("requires native AMD64 or ARM64")
        self.checked_in = SOURCE.parents[1] / "platform/runtime/debian"
        self.lock = json.loads((self.checked_in / f"lock-{self.native}.json").read_text())
        self.path = self.root / f"lock-{self.native}.json"
        self.path.write_text(json.dumps(self.lock, sort_keys=True) + "\n")

    def test_reviewed_native_lock_exact_approved_base_and_one_package(self):
        approved = freeze.load_lock(self.checked_in)
        self.assertEqual(approved["base_image"], freeze.PYTHON_IMAGE)
        self.assertFalse(approved["release_eligible"])
        self.assertEqual(approved["base_ca_sha256"], freeze.BASE_CA)
        self.assertEqual(len(approved["changed_packages"]), 1)
        package = approved["changed_packages"][0]
        self.assertEqual(package["package"], "libatomic1")
        self.assertEqual(package["arch"], self.native)
        self.assertEqual(package["version"], freeze.VERSION)
        self.assertEqual(approved["baseline_abi_versions"]["libatomic1"], None)
        self.assertEqual(approved["installed_abi_versions"]["libstdc++6"], freeze.VERSION)

    def test_lock_schema_integrity_and_no_release_flag_forgery(self):
        cases = (
            ("wrong-base", lambda d: d.update(base_image="python:3.13-slim-bookworm")),
            ("wrong-native-arch", lambda d: d.update(arch="arm64" if self.native=="amd64" else "amd64")),
            ("release-forgery", lambda d: d.update(release_eligible=True)),
            ("bool-schema", lambda d: d.update(schema=True)),
            ("unknown-field", lambda d: d.update(extra="unauthorized")),
            ("missing-ca", lambda d: d.update(base_ca_sha256="0"*64)),
            ("unapproved-baseline", lambda d: d["baseline_abi_versions"].update({"libstdc++6": "0"})),
            ("changed-package-count", lambda d: d.update(changed_packages=[])),
            ("wrong-deb-sha", lambda d: d["changed_packages"][0].update(sha256="0"*64)),
            ("wrong-deb-size", lambda d: d["changed_packages"][0].update(size=1)),
            ("wrong-pool-path", lambda d: d["changed_packages"][0].update(source_path="../../escape.deb")),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                candidate = json.loads(json.dumps(self.lock))
                mutate(candidate)
                self.path.write_text(json.dumps(candidate))
                with self.assertRaises(freeze.FrozenDebianError):
                    freeze.load_lock(self.root)
        self.path.write_text(json.dumps(self.lock).replace('"schema": 1', '"schema": 1, "schema": 1', 1))
        with self.assertRaisesRegex(freeze.FrozenDebianError, "duplicate"):
            freeze.load_lock(self.root)

    def test_symlinked_or_unexpected_archive_fails_before_dpkg(self):
        self.path.write_text(json.dumps(self.lock))
        approved = freeze.load_lock(self.root)
        archives = self.root / "debs"
        with self.assertRaisesRegex(freeze.FrozenDebianError, "missing"):
            freeze.verify_archives(approved, archives)
        archives.mkdir()
        (archives / "unexpected.deb").write_bytes(b"unapproved")
        with self.assertRaisesRegex(freeze.FrozenDebianError, "unexpected"):
            freeze.verify_archives(approved, archives)
        (archives / "unexpected.deb").unlink()
        filename = approved["changed_packages"][0]["filename"]
        (archives / filename).symlink_to(self.path)
        with self.assertRaisesRegex(freeze.FrozenDebianError, "unexpected"):
            freeze.verify_archives(approved, archives)
        (archives / filename).unlink()
        (archives / filename).write_bytes(b"tampered")
        with self.assertRaisesRegex(freeze.FrozenDebianError, "differ"):
            freeze.verify_archives(approved, archives)
        archives.rename(self.root / "owned")
        archives.symlink_to(self.root / "owned", target_is_directory=True)
        with self.assertRaisesRegex(freeze.FrozenDebianError, "linked"):
            freeze.verify_archives(approved, archives)

    def test_symlinked_lock_and_duplicate_file_are_rejected(self):
        self.path.unlink()
        self.path.symlink_to(self.checked_in / self.path.name)
        with self.assertRaisesRegex(freeze.FrozenDebianError, "unsafe"):
            freeze.load_lock(self.root)


if __name__ == "__main__":
    unittest.main()
