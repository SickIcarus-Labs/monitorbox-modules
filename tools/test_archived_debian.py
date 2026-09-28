"""Offline and adversarial snapshot provenance tests, no network."""
from __future__ import annotations
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
source = HERE / "discover_archived_debian.py"
spec = importlib.util.spec_from_file_location("approved_debian_snapshot", source)
assert spec and spec.loader
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SignedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mb-signed-snapshot-test-")
        self.addCleanup(self.temp.cleanup)
        self.dir = pathlib.Path(self.temp.name)
        self.production = HERE.parent / "platform/runtime/debian"
        self.arch = "amd64"
        self.approved = snapshot.load_approved_snapshot(
            self.production / "snapshot-amd64.json", self.arch
        )
        self.candidate = self.dir / "reviewed.json"
        self.candidate.write_text(json.dumps(self.approved, sort_keys=True) + "\n")

    def test_reviewed_source_locks_both_architectures(self):
        for arch in ("amd64", "arm64"):
            approved = snapshot.load_approved_snapshot(
                self.production / f"snapshot-{arch}.json", arch
            )
            self.assertFalse(approved["release_eligible"])
            self.assertEqual(approved["source"], "debian")
            self.assertEqual(approved["suite"], "bookworm")
            self.assertEqual(approved["inrelease"]["sha256"], snapshot.APPROVED_RELEASE)
            self.assertEqual(approved["keyring_sha256"], snapshot.APPROVED_KEYRING)
            self.assertEqual(
                approved["packages"]["sha256"],
                snapshot.APPROVED_PACKAGE_INDEX[arch][0],
            )
            self.assertEqual(approved["deb"]["sha256"], snapshot.APPROVED[arch][0])

    def test_all_development_approval_forgery_and_snapshot_drift_fail_closed(self):
        cases = {
            "release-forgery": lambda m: m.update(release_eligible=True),
            "boolean-schema": lambda m: m.update(schema=True),
            "future-checkpoint": lambda m: m.update(checkpoint="20290101T000000Z"),
            "changed-archive": lambda m: m.update(source="debian-security"),
            "unapproved-suite": lambda m: m.update(suite="bookworm-updates"),
            "changed-trusted-keyring": lambda m: m.update(keyring_sha256="0"*64),
            "unsigned-inrelease": lambda m: m["inrelease"].update(sha256="0"*64),
            "wrong-index": lambda m: m["packages"].update(sha256="0"*64),
            "wrong-expanded-index": lambda m: m["packages"].update(uncompressed_sha256="0"*64),
            "wrong-signed-size": lambda m: m["packages"].update(size=1),
            "wrong-native-package": lambda m: m["deb"].update(sha256="0"*64),
            "wrong-archive-url": lambda m: m["inrelease"].update(url="http://debian.org/InRelease"),
            "injected-field": lambda m: m["inrelease"].update(unsafe=True),
            "extra-top-level": lambda m: m.update(eligible=True),
        }
        for name, mutation in cases.items():
            with self.subTest(case=name):
                candidate = json.loads(json.dumps(self.approved))
                mutation(candidate)
                self.candidate.write_text(json.dumps(candidate))
                with self.assertRaises(snapshot.SnapshotError):
                    snapshot.load_approved_snapshot(self.candidate, self.arch)
        self.candidate.write_text(json.dumps(self.approved).replace(
            '"schema": 1', '"schema": 1, "schema": 1', 1
        ))
        with self.assertRaisesRegex(snapshot.SnapshotError, "duplicate"):
            snapshot.load_approved_snapshot(self.candidate, self.arch)

    def test_symlinked_manifest_and_wrong_architecture_fail_before_network(self):
        self.candidate.unlink()
        self.candidate.symlink_to(self.production / "snapshot-amd64.json")
        with self.assertRaisesRegex(snapshot.SnapshotError, "unsafe"):
            snapshot.load_approved_snapshot(self.candidate, self.arch)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.load_approved_snapshot(
                self.production / "snapshot-amd64.json", "arm64"
            )

    def test_unsigned_or_invalid_gpgv_release_does_not_authorize_index(self):
        inrelease = self.dir / "InRelease"
        key = self.dir / "debian.gpg"
        key.write_bytes(b"SYNTHETIC WRONG KEY")
        content = (b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
                   b"Date: Fri, 25 Sep 2026 00:00:00 +0000\n"
                   b"SHA256:\n" + b"0"*64 + b" 1024 main/binary-amd64/Packages.xz\n"
                   b"\n-----BEGIN PGP SIGNATURE-----\nforged\n")
        with mock.patch.object(snapshot.subprocess, "run",
                               return_value=mock.Mock(returncode=1,stderr="BAD SIGNATURE")):
            with self.assertRaisesRegex(snapshot.SnapshotError, "signature FAILED"):
                snapshot.verified_release(content, key, inrelease)

    def test_bounded_immutable_snapshot_transport_rejects_cross_origin(self):
        class CrossOrigin:
            status = 200
            url = "https://evil.example/file/debian"
            headers = {"Content-Length": "15"}
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, *_):
                return b"untrusted"
        with mock.patch.object(snapshot.urllib.request, "urlopen",
                               return_value=CrossOrigin()):
            with self.assertRaisesRegex(snapshot.SnapshotError, "unsafe redirect"):
                snapshot.download(
                    "https://snapshot.debian.org/archive/debian/20260926T000000Z/dists/bookworm/InRelease",
                    snapshot.MAX_RELEASE
                )

    def test_native_signed_package_selection_rejects_duplicate_reviewed_record(self):
        paragraph = (
            "Package: libatomic1\n"
            "Version: 12.2.0-14+deb12u1\n"
            "Architecture: amd64\n"
            "Filename: pool/main/g/gcc-12/libatomic1_12.2.0-14+deb12u1_amd64.deb\n"
            f"SHA256: {snapshot.APPROVED['amd64'][0]}\n"
            "Size: 9376\n\n"
        )
        item = snapshot.selected_paragraph(paragraph.encode(), "amd64")
        self.assertEqual(item["SHA256"], snapshot.APPROVED["amd64"][0])
        with self.assertRaisesRegex(snapshot.SnapshotError, "ambiguous"):
            snapshot.selected_paragraph((paragraph + paragraph).encode(), "amd64")


if __name__ == "__main__":
    unittest.main()
