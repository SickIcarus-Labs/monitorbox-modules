import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pointer  # noqa: E402

DIGEST = "a" * 64


def good(channel="dev"):
    return {
        "schema": 1,
        "channel": channel,
        "updated": "2026-10-14T00:00:00Z",
        "app": {"version": "0.1.0", "url": "https://example.test/app-0.1.0.tar.gz", "sha256": DIGEST, "signature": None},
        "modules": {
            "snmp": {"version": "0.1.0", "url": "https://example.test/snmp-0.1.0.tar.gz", "sha256": DIGEST},
        },
    }


def catalog_for_good():
    g = good()
    entry = lambda a: {**a, "signature": None, "published": "2026-10-14T00:00:00Z", "channels": ["dev"]}
    return {"schema": 1, "app": [entry(g["app"])], "modules": {"snmp": [entry(g["modules"]["snmp"])]}}


class ValidateTests(unittest.TestCase):
    def test_valid_pointer(self):
        self.assertEqual(pointer.validate(good(), "dev"), [])

    def test_the_optional_launcher_version_is_checked(self):
        ok = good("dev"); ok["launcher"] = {"version": "0.2.0"}
        self.assertEqual(pointer.validate(ok), [])
        for bad in ({"version": "two"}, {"version": "0.2.0", "extra": 1}, {}, "0.2.0", {"version": 2}):
            p = good("dev"); p["launcher"] = bad
            self.assertTrue(any("launcher" in e for e in pointer.validate(p)), bad)

    def test_empty_pointer_is_valid_before_first_release(self):
        empty = {"schema": 1, "channel": "dev", "updated": "x", "app": None, "modules": {}}
        self.assertEqual(pointer.validate(empty, "dev"), [])

    def test_committed_channel_files_are_valid(self):
        for name in pointer.CHANNELS:
            path = ROOT / "channels" / f"{name}.json"
            self.assertEqual(pointer.validate(pointer.load(path), name), [], name)

    def test_rejects_bad_digest_url_and_version(self):
        bad = good()
        bad["app"]["sha256"] = "XYZ"
        bad["app"]["url"] = "http://insecure.test/a"
        bad["modules"]["snmp"]["version"] = "latest"
        text = " ".join(pointer.validate(bad, "dev"))
        self.assertIn("app.sha256", text)
        self.assertIn("app.url", text)
        self.assertIn("modules.snmp.version", text)

    def test_rejects_unknown_keys_and_wrong_channel(self):
        bad = good("beta")
        bad["surprise"] = 1
        text = " ".join(pointer.validate(bad, "dev"))
        self.assertIn("surprise", text)
        self.assertIn("file is for 'dev'", text)


class PromoteTests(unittest.TestCase):
    def test_forward_promotion_copies_content(self):
        result = pointer.promote(good("dev"), "beta", "2026-10-15T00:00:00Z", "dev")
        self.assertEqual(result["channel"], "beta")
        self.assertEqual(result["promotedFrom"], "dev")
        self.assertEqual(result["app"], good()["app"])
        self.assertEqual(result["modules"], good()["modules"])

    def test_disallowed_directions_refused(self):
        for source, target in (("beta", "dev"), ("dev", "stable"), ("stable", "beta"), ("stable", "dev")):
            with self.assertRaises(ValueError, msg=f"{source}->{target}"):
                pointer.promote(good(source), target, "now", source)

    def test_nothing_to_promote_refused(self):
        empty = {"schema": 1, "channel": "dev", "updated": "x", "app": None, "modules": {}}
        with self.assertRaises(ValueError):
            pointer.promote(empty, "beta", "now", "dev")

    def test_invalid_source_refused(self):
        bad = good("dev")
        bad["app"]["sha256"] = "nope"
        with self.assertRaises(ValueError):
            pointer.promote(bad, "beta", "now", "dev")


class CliTests(unittest.TestCase):
    """Run the real promote command against a throwaway git repository."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tools", self.tmp / "tools")
        (self.tmp / "channels").mkdir()
        for name in pointer.CHANNELS:        # fixed, empty pointers: the tests must not depend on what the real channels hold today
            (self.tmp / "channels" / f"{name}.json").write_text(json.dumps(
                {"schema": 1, "channel": name, "updated": "2026-10-14T00:00:00Z", "app": None, "modules": {}}))
        (self.tmp / "catalog.json").write_text(json.dumps(catalog_for_good()))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "user.name", "test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.tmp, check=True, capture_output=True, text=True).stdout.strip()

    def promote(self, *args):
        return subprocess.run(
            [sys.executable, "-I", str(self.tmp / "tools" / "promote.py"), *args],
            cwd=self.tmp, capture_output=True, text=True,
        )

    def write(self, channel, data):
        (self.tmp / "channels" / f"{channel}.json").write_text(json.dumps(data))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"set {channel}")

    def read(self, channel):
        return json.loads((self.tmp / "channels" / f"{channel}.json").read_text())

    def test_dev_to_beta_changes_only_beta(self):
        self.write("dev", good("dev"))
        before_dev = (self.tmp / "channels" / "dev.json").read_text()
        before_stable = (self.tmp / "channels" / "stable.json").read_text()
        done = self.promote("--source", "dev", "--target", "beta")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.read("beta")["app"], good()["app"])
        self.assertEqual((self.tmp / "channels" / "dev.json").read_text(), before_dev)
        self.assertEqual((self.tmp / "channels" / "stable.json").read_text(), before_stable)

    def test_promotion_records_channel_in_catalog(self):
        self.write("dev", good("dev"))
        self.assertEqual(self.promote("--source", "dev", "--target", "beta").returncode, 0)
        cat = json.loads((self.tmp / "catalog.json").read_text())
        self.assertEqual(cat["app"][0]["channels"], ["dev", "beta"])
        self.assertEqual(cat["modules"]["snmp"][0]["channels"], ["dev", "beta"])
        self.git("add", "-A")  # the real workflow commits between promotions
        self.git("commit", "-q", "-m", "promoted to beta")
        self.assertEqual(self.promote("--source", "beta", "--target", "stable").returncode, 0)
        cat = json.loads((self.tmp / "catalog.json").read_text())
        self.assertEqual(cat["app"][0]["channels"], ["dev", "beta", "stable"])

    def test_promoting_a_version_missing_from_catalog_is_refused(self):
        d = good("dev")
        d["app"]["version"] = "9.9.9"
        self.write("dev", d)
        done = self.promote("--source", "dev", "--target", "beta")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not in the catalog", done.stderr)
        self.assertEqual(self.read("beta")["app"], None)  # and nothing was written

    def test_skipping_beta_is_refused(self):
        self.write("dev", good("dev"))
        done = self.promote("--source", "dev", "--target", "stable")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not allowed", done.stderr)

    def test_rollback_restores_earlier_pointer(self):
        old = good("stable")
        self.write("stable", old)
        old_ref = self.git("rev-parse", "HEAD")
        newer = good("stable")
        newer["app"]["version"] = "0.2.0"
        self.write("stable", newer)
        done = self.promote("--source", "stable", "--target", "stable", "--ref", old_ref)
        self.assertEqual(done.returncode, 0, done.stderr)
        restored = self.read("stable")
        self.assertEqual(restored["app"]["version"], "0.1.0")
        self.assertTrue(restored["promotedFrom"].startswith("rollback:"))

    def test_rollback_without_ref_is_refused(self):
        done = self.promote("--source", "stable", "--target", "stable")
        self.assertNotEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
