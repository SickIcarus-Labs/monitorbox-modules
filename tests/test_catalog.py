import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import catalog  # noqa: E402
import pointer  # noqa: E402

D1, D2 = "1" * 64, "2" * 64


def entry(v, sha, channels):
    return {"version": v, "url": f"https://example.test/{v}.tgz", "sha256": sha, "signature": None,
            "published": "2026-10-14T00:00:00Z", "channels": channels}


def cat():
    return {"schema": 1,
            "app": [entry("0.2.0", D2, ["dev"]), entry("0.1.0", D1, ["dev", "beta", "stable"])],
            "modules": {"hello": [entry("0.1.0", D1, ["dev", "beta"])]}}


class CatalogTests(unittest.TestCase):
    def test_committed_catalog_is_valid_and_matches_pointers(self):
        c = catalog.load(ROOT / "catalog.json")
        self.assertEqual(catalog.validate(c), [])
        ptrs = {n: pointer.load(ROOT / "channels" / f"{n}.json") for n in pointer.CHANNELS}
        self.assertEqual(catalog.cross_check(c, ptrs), [])

    def test_channels_must_be_in_order(self):
        c = cat()
        c["app"][0]["channels"] = ["stable"]
        self.assertTrue(any("prefix" in e for e in catalog.validate(c)))

    def test_version_listed_twice_refused(self):
        c = cat()
        c["app"].append(copy.deepcopy(c["app"][0]))
        self.assertTrue(any("twice" in e for e in catalog.validate(c)))

    def test_pointer_to_unreleased_or_unpromoted_version_flagged(self):
        c = cat()
        ptr = {"app": {"version": "0.2.0", "sha256": D2}, "modules": {}}
        errs = catalog.cross_check(c, {"beta": ptr})
        self.assertTrue(any("has not reached beta" in e for e in errs))
        ptr["app"]["version"] = "7.7.7"
        self.assertTrue(any("not in the catalog" in e for e in catalog.cross_check(c, {"dev": ptr})))
        ptr = {"app": {"version": "0.2.0", "sha256": D1}, "modules": {}}
        self.assertTrue(any("sha256 differs" in e for e in catalog.cross_check(c, {"dev": ptr})))

    def test_mark_reached_cannot_skip_a_stage(self):
        c = cat()
        ptr = {"app": {"version": "0.2.0"}, "modules": {}}
        with self.assertRaises(ValueError):
            catalog.mark_reached(c, ptr, "stable")
        catalog.mark_reached(c, ptr, "beta")
        catalog.mark_reached(c, ptr, "stable")
        self.assertEqual(c["app"][0]["channels"], ["dev", "beta", "stable"])


if __name__ == "__main__":
    unittest.main()
