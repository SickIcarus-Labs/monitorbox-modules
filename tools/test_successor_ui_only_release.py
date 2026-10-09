"""Fail-closed release-delta contract; pure unit tests, no GHCR or signer."""
import copy
import unittest

from successor_ui_only_release import (
    UI, EXPECTED_BUILD, EXPECTED_VERSION, DeltaRefused, assert_exact_delta,
)


def index(sequence, *, ui_version="1.17.1", ui_build=57, ui_digest="a" * 64):
    records = []
    for ident, arch, version, build, digest in (
        (UI, "any", ui_version, ui_build, ui_digest),
        ("com.sickicarus.monitorbox.core", "amd64", "3.0.0", 3, "c" * 64),
        ("com.sickicarus.monitorbox.scaffold-manager", "amd64", "1.0.0", 4, "d" * 64),
    ):
        records.append({
            "artifact_id": ident, "kind": "module",
            "version": version, "build": build,
            "platform": {"arch": arch, "abi": "pure", "os": "linux"},
            "dependencies": [], "portable_config": {"schema": 1},
            "package": {"sha256": digest, "url": "platform/packages/" + ident + ".zip"},
        })
    # Pure function checks the complete expected catalog census, not fixture size:
    for n in range(19):
        records.append({
            "artifact_id": f"com.sickicarus.monitorbox.example{n}",
            "kind": "module", "version": "1.0.0", "build": 1,
            "platform": {"arch": "any", "abi": "pure", "os": "linux"},
            "dependencies": [], "portable_config": {},
            "package": {"sha256": f"{n:064x}", "url": f"platform/packages/example{n}.zip"},
        })
    assert len(records) == 22
    return {"schema": 1,
            "signed": {"repository_id": "official-platform",
                       "channel": "stable", "sequence": sequence, "artifacts": records},
            "signature": {"identity": "official-ed25519-1"}}


class SuccessorUIOnlyDeltaTests(unittest.TestCase):
    def setUp(self):
        self.old = index(9)
        self.new = index(10, ui_version=EXPECTED_VERSION, ui_build=EXPECTED_BUILD,
                         ui_digest="b" * 64)

    def test_strict_single_package_delta_passes(self):
        assert_exact_delta(self.old, self.new, old_sequence=9)

    def _refuses(self, mutate):
        candidate = copy.deepcopy(self.new)
        mutate(candidate)
        with self.assertRaises(DeltaRefused):
            assert_exact_delta(self.old, candidate, old_sequence=9)

    def test_denies_same_sequence_alternate(self):
        self._refuses(lambda x: x["signed"].__setitem__("sequence", 9))

    def test_denies_sequence_jump(self):
        self._refuses(lambda x: x["signed"].__setitem__("sequence", 11))

    def test_denies_unrelated_core_digest(self):
        self._refuses(lambda x: x["signed"]["artifacts"][1]["package"].__setitem__("sha256", "f" * 64))

    def test_denies_unrelated_supervisor_version(self):
        self._refuses(lambda x: x["signed"]["artifacts"][2].__setitem__("version", "1.1.0"))

    def test_denies_missing_module(self):
        self._refuses(lambda x: x["signed"]["artifacts"].pop())

    def test_denies_same_ui_digest(self):
        self._refuses(lambda x: x["signed"]["artifacts"][0]["package"].__setitem__("sha256", "a" * 64))

    def test_denies_wrong_ui_build(self):
        self._refuses(lambda x: x["signed"]["artifacts"][0].__setitem__("build", 59))

    def test_denies_unexpected_predecessor(self):
        self.old["signed"]["artifacts"][0]["build"] = 56
        with self.assertRaises(DeltaRefused):
            assert_exact_delta(self.old, self.new, old_sequence=9)

    def test_denies_nonofficial_catalog(self):
        self._refuses(lambda x: x["signed"].__setitem__("repository_id", "arbitrary"))


if __name__ == "__main__":
    unittest.main()
