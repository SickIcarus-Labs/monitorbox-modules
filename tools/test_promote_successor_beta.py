"""Pure protected-Beta promotion admission checks; no registry or secrets."""
import copy
import unittest

from promote_successor_beta import (
    REQUIRED_ROLES, BetaPromotionRefused, validate_cohort,
)


def cohort():
    names = sorted(REQUIRED_ROLES)
    artifacts = []
    for i, role in enumerate(names):
        arches = ("amd64", "arm64") if i < 9 else ("any",)
        for arch in arches:
            artifacts.append({
                "artifact_id": role,
                "platform": {"os": "linux", "arch": arch, "abi": "pure" if arch == "any" else "gnu"},
                "version": "3.0.0",
                "build": 10,
            })
    assert len(artifacts) == 22
    earlier = copy.deepcopy(artifacts)
    for item in earlier:
        item["build"] = 9
    return {"dev": {"artifacts": artifacts}, "beta": {"artifacts": earlier}}


class BetaCohortTest(unittest.TestCase):
    def test_full_13_role_22_record_snapshot(self):
        validate_cohort(cohort())

    def test_missing_role_rejected(self):
        c = cohort()
        c["dev"]["artifacts"][0]["artifact_id"] = "com.other.signed"
        with self.assertRaises(BetaPromotionRefused):
            validate_cohort(c)

    def test_missing_arch_rejected(self):
        c = cohort()
        c["beta"]["artifacts"][0]["platform"]["arch"] = "other"
        with self.assertRaises(BetaPromotionRefused):
            validate_cohort(c)

    def test_beta_downgrade_rejected(self):
        c = cohort()
        c["beta"]["artifacts"][0]["version"] = "4.0.0"
        with self.assertRaises(BetaPromotionRefused):
            validate_cohort(c)

    def test_duplicate_identity_rejected(self):
        c = cohort()
        c["dev"]["artifacts"][1]["platform"] = dict(c["dev"]["artifacts"][0]["platform"])
        c["dev"]["artifacts"][1]["artifact_id"] = c["dev"]["artifacts"][0]["artifact_id"]
        with self.assertRaises(BetaPromotionRefused):
            validate_cohort(c)


if __name__ == "__main__":
    unittest.main()
