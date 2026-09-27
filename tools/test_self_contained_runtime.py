"""Synthetic runtime-proof tests; never require a production signer or Docker."""
from __future__ import annotations
import importlib.util
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("package_self_contained_runtime.py")
spec = importlib.util.spec_from_file_location("package_self_contained_runtime", SCRIPT)
assert spec and spec.loader
pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pkg)


class SelfContainedRuntimeTests(unittest.TestCase):
    def test_ldd_parser_discards_vdso_and_detects_missing(self):
        listing = """
          linux-vdso.so.1 (0x00007f)
          libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x7f)
          libpython3.13.so.1.0 => /usr/local/lib/libpython3.13.so.1.0 (0x7f)
          /lib64/ld-linux-x86-64.so.2 (0x7f)
        """
        self.assertEqual({"libz.so.1", "libpython3.13.so.1.0", "ld-linux-x86-64.so.2"},
                         pkg.parse_ldd_for_test(listing))
        self.assertIn("libz.so.1", pkg.parse_ldd_for_test(
            "libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1.2.13 (0x7f)"))
        with self.assertRaisesRegex(pkg.RuntimePackagingError, "missing shared"):
            pkg.parse_ldd_for_test("libnotpresent.so => not found")

    def test_runtime_manifest_unreleaseable_and_zip_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "fake-upstream"
            executable = base / "bin/python3.13"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"\x7fELF FAKE PYTHON")
            executable.chmod(0o755)
            shared = base / "lib/libpython3.13.so.1.0"
            shared.parent.mkdir(parents=True)
            shared.write_bytes(b"\x7fELF FAKE LIBPYTHON")
            (base / "lib/python3.13").mkdir()
            (base / "lib/python3.13/__init__.py").write_text("FAKE = 1\n")
            (base / "lib/python3.13/__pycache__").mkdir()
            (base / "lib/python3.13/__pycache__/ignored.pyc").write_bytes(b"old")
            (base / "lib/python3.13/lib-dynload").mkdir()
            (base / "lib/python3.13/lib-dynload/_tkinter.so").write_bytes(b"\\x7fELF FAKE GUI")
            (base / "lib/python3.13/tkinter").mkdir()
            (base / "lib/python3.13/tkinter/__init__.py").write_text("GUI ONLY\\n")
            system_loader = Path("/lib64/ld-linux-x86-64.so.2")
            if not system_loader.exists():
                self.skipTest("x86-64 ELF loader not present in unit environment")
            for name in ("one", "two"):
                with patch.object(pkg, "host_arch", return_value="amd64"), \
                     patch.object(pkg, "_version", return_value="3.13.9"), \
                     patch.object(pkg, "_ldd_dependencies", return_value={system_loader.name: system_loader.resolve()}), \
                     patch.object(pkg, "_resolve_abi_library", return_value=system_loader.resolve()), \
                     patch.object(pkg, "verified_debian_abi", return_value={"proof": "synthetic-test-only"}):
                    result = pkg.build_runtime("python", root / f"{name}.zip", python_prefix=base)
                self.assertFalse(result["release_eligible"])
                self.assertEqual(result["packaging_stage"], "digest-pinned-upstream-runtime-proof")
                self.assertEqual(result["upstream"]["python_image"],
                                 pkg.load_upstream_lock()["python_image"])
                self.assertEqual(result["upstream"]["node_image"],
                                 pkg.load_upstream_lock()["node_image"])
                self.assertEqual(result["upstream"]["os_packages"],
                                 "sha256-locked-oci-base-abi-prototype")
                self.assertEqual(result["upstream"]["debian_abi"], {"proof": "synthetic-test-only"})
                self.assertEqual("com.sickicarus.monitorbox.runtime.python", result["artifact_id"])
                self.assertEqual("runtime/loader/ld-linux-x86-64.so.2", result["dynamic_loader"])
            self.assertEqual((root / "one.zip").read_bytes(), (root / "two.zip").read_bytes())
            with zipfile.ZipFile(root / "one.zip") as archive:
                self.assertIn("runtime/usr/local/bin/python3.13", archive.namelist())
                self.assertIn("runtime/usr/local/lib/python3.13/__init__.py", archive.namelist())
                for support in pkg.ABI_SUPPORT_LIBRARIES:
                    self.assertIn("runtime/lib/" + support, archive.namelist())
                self.assertNotIn("runtime/usr/local/lib/python3.13/__pycache__/ignored.pyc", archive.namelist())
                self.assertNotIn("runtime/usr/local/lib/python3.13/lib-dynload/_tkinter.so", archive.namelist())
                self.assertNotIn("runtime/usr/local/lib/python3.13/tkinter/__init__.py", archive.namelist())
                self.assertTrue(archive.getinfo("runtime/usr/local/bin/python3.13").external_attr >> 16 & stat.S_IXUSR)
                self.assertEqual(result, json.loads(archive.read("package.json")))
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "overwrite"):
                pkg.build_runtime("python", root / "one.zip", python_prefix=base)

    def test_exact_upstream_lock_rejects_floating_images_drift_and_override(self):
        source_lock = Path(__file__).resolve().parents[1] / "platform/runtime/upstream-lock.json"
        source_dockerfile = source_lock.parent / "Dockerfile"
        upstream = pkg.load_upstream_lock(source_lock)
        self.assertEqual(
            upstream["python_image"],
            "python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26",
        )
        self.assertEqual(
            upstream["node_image"],
            "node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6",
        )
        pkg.verify_locked_dockerfile(source_dockerfile, upstream)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            lock = directory / "lock.json"
            base = json.loads(source_lock.read_text())
            for label, value in (
                ("floating-tag", {**base, "python_image": "python:3.13-slim-bookworm"}),
                ("swapped-runtime", {**base, "node_image": base["python_image"]}),
                ("malformed-digest", {**base, "node_image": "node:24-bookworm-slim@sha256:" + "z" * 64}),
                ("missing-arch", {**base, "platforms": ["linux/amd64"]}),
                ("unexpected-release", {**base, "release_eligible": True}),
                ("bad-schema", {**base, "schema": True}),
            ):
                with self.subTest(label=label):
                    lock.write_text(json.dumps(value))
                    with self.assertRaises(pkg.RuntimePackagingError):
                        pkg.load_upstream_lock(lock)
            lock.write_text(source_lock.read_text().replace(
                '"schema": 1,', '"schema": 1, "schema": 1,', 1,
            ))
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "duplicate"):
                pkg.load_upstream_lock(lock)
            dockerfile = directory / "Dockerfile"
            dockerfile.write_text(source_dockerfile.read_text().replace(
                upstream["python_image"], "python:3.13-slim-bookworm",
            ))
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "differs"):
                pkg.verify_locked_dockerfile(dockerfile, upstream)
            dockerfile.write_text(source_dockerfile.read_text() + "\nARG PYTHON_IMAGE=unsafe\n")
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "differs"):
                pkg.verify_locked_dockerfile(dockerfile, upstream)
    def test_invalid_sources_and_unsupported_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.write_text("SYNTHETIC")
            stdlib = root / "stdlib"
            stdlib.mkdir()
            (stdlib / "escape.py").symlink_to(outside)
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "escaping symlink"):
                pkg._copy_tree(stdlib, root / "dest")
            with patch.object(pkg.platform, "machine", return_value="sparc"):
                with self.assertRaisesRegex(pkg.RuntimePackagingError, "unsupported build"):
                    pkg.host_arch()
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "unapproved runtime"):
                pkg._resolve_abi_library("amd64", "libadversary.so")
            with self.assertRaisesRegex(pkg.RuntimePackagingError, "unsupported runtime"):
                pkg.build_runtime("rust", root / "unrequested.zip")


if __name__ == "__main__":
    unittest.main()
