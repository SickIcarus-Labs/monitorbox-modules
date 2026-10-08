"""Synthetic fail-closed tests for the reviewed multi-package ICMP/ABI closure."""
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
        self.lock = json.loads(
            (self.checked_in / f"lock-{self.native}.json").read_text()
        )
        self.path = self.root / f"lock-{self.native}.json"
        self.path.write_text(json.dumps(self.lock, sort_keys=True) + "\n")

    def test_reviewed_native_lock_exact_approved_icmp_closure(self):
        approved = freeze.load_lock(self.checked_in)
        self.assertEqual(approved["base_image"], freeze.PYTHON_IMAGE)
        self.assertFalse(approved["release_eligible"])
        self.assertEqual(approved["base_ca_sha256"], freeze.BASE_CA)
        self.assertEqual(
            approved["requested"],
            ["libstdc++6", "libgcc-s1", "libatomic1", "iputils-ping"],
        )
        self.assertEqual(
            [item["package"] for item in approved["changed_packages"]],
            ["iputils-ping", "libatomic1", "libcap2-bin"],
        )
        self.assertEqual(
            approved["changed_packages"],
            list(freeze.APPROVED_CHANGED[self.native]),
        )
        self.assertIsNone(approved["baseline_abi_versions"]["iputils-ping"])
        self.assertIsNone(approved["baseline_abi_versions"]["libatomic1"])
        self.assertEqual(
            approved["installed_abi_versions"]["iputils-ping"],
            freeze.PING_VERSION,
        )
        self.assertEqual(
            approved["installed_abi_versions"]["libstdc++6"],
            freeze.GCC_VERSION,
        )

    def test_lock_schema_integrity_and_no_release_flag_forgery(self):
        cases = (
            ("wrong-base", lambda d: d.update(base_image="python:3.13-slim-bookworm")),
            (
                "wrong-native-arch",
                lambda d: d.update(
                    arch="arm64" if self.native == "amd64" else "amd64"
                ),
            ),
            ("release-forgery", lambda d: d.update(release_eligible=True)),
            ("bool-schema", lambda d: d.update(schema=True)),
            ("unknown-field", lambda d: d.update(extra="unauthorized")),
            ("missing-ca", lambda d: d.update(base_ca_sha256="0" * 64)),
            (
                "unapproved-baseline",
                lambda d: d["baseline_abi_versions"].update({"libstdc++6": "0"}),
            ),
            ("changed-package-count", lambda d: d.update(changed_packages=[])),
            (
                "wrong-ping-sha",
                lambda d: d["changed_packages"][0].update(sha256="0" * 64),
            ),
            (
                "wrong-libatomic-size",
                lambda d: d["changed_packages"][1].update(size=1),
            ),
            (
                "wrong-libcap-pool-path",
                lambda d: d["changed_packages"][2].update(
                    source_path="../../escape.deb"
                ),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                candidate = json.loads(json.dumps(self.lock))
                mutate(candidate)
                self.path.write_text(json.dumps(candidate))
                with self.assertRaises(freeze.FrozenDebianError):
                    freeze.load_lock(self.root)

        self.path.write_text(
            json.dumps(self.lock).replace(
                '"schema": 1', '"schema": 1, "schema": 1', 1
            )
        )
        with self.assertRaisesRegex(freeze.FrozenDebianError, "duplicate"):
            freeze.load_lock(self.root)

    def test_archive_set_is_exact_and_rejects_links_tampering_and_extras(self):
        approved = freeze.load_lock(self.root)
        archives = self.root / "debs"
        with self.assertRaisesRegex(freeze.FrozenDebianError, "missing"):
            freeze.verify_archives(approved, archives)

        archives.mkdir()
        (archives / "unexpected.deb").write_bytes(b"unapproved")
        with self.assertRaisesRegex(freeze.FrozenDebianError, "unexpected"):
            freeze.verify_archives(approved, archives)
        (archives / "unexpected.deb").unlink()

        records = approved["changed_packages"]
        for record in records:
            (archives / record["filename"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(freeze.FrozenDebianError, "differ"):
            freeze.verify_archives(approved, archives)

        for item in archives.iterdir():
            item.unlink()
        first = records[0]["filename"]
        (archives / first).symlink_to(self.path)
        with self.assertRaisesRegex(freeze.FrozenDebianError, "unexpected"):
            freeze.verify_archives(approved, archives)

        (archives / first).unlink()
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
