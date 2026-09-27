import copy
import json
import unittest
from pathlib import Path

from src.domain import load_domain, validate_domain

FIXTURE = Path("fixtures/domain.json")


def fixture_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class DomainTest(unittest.TestCase):
    def test_fixture_matches_domain(self):
        value = load_domain(FIXTURE)
        self.assertEqual(value["domain"], "fish-release-outcomes")
        self.assertGreaterEqual(value["version"], 2)
        self.assertGreaterEqual(len(value["constraints"]), 2)

    def test_seven_stage_custody_chain_is_continuous(self):
        value = fixture_data()
        stages = [step["stage"] for step in value["custody_chain"]]
        self.assertEqual(
            stages,
            [
                "broodstock",
                "breeding_quarantine",
                "tagging",
                "transport",
                "on_site_count",
                "release",
                "post_release_sampling",
            ],
        )

    def test_batch_lineage_reaches_broodstock(self):
        value = load_domain(FIXTURE)
        batch = value["batches"][0]
        broodstock = {b["id"] for b in value["broodstock"]}
        self.assertTrue(batch["quarantine_passed"])
        self.assertTrue(set(batch["parent_ids"]) <= broodstock)

    def test_breaking_chain_stage_is_rejected(self):
        value = fixture_data()
        value["custody_chain"][3], value["custody_chain"][4] = (
            value["custody_chain"][4],
            value["custody_chain"][3],
        )
        with self.assertRaisesRegex(ValueError, "血缘链"):
            validate_domain(value)

    def test_correction_must_append_not_overwrite(self):
        value = fixture_data()
        # 直接删掉原始现场计数，再保留纠正记录，等于改写历史。
        value["observations"] = [
            o for o in value["observations"] if o["id"] != "OBS-C-2025-0509"
        ]
        with self.assertRaisesRegex(ValueError, "原始观察"):
            validate_domain(value)

    def test_correction_earlier_than_original_is_rejected(self):
        value = fixture_data()
        for obs in value["observations"]:
            if obs["id"] == "OBS-C-2025-0509-C1":
                obs["recorded_at"] = "2025-05-08T00:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "回溯改写"):
            validate_domain(value)

    def test_mixed_sample_requires_interval_and_probability(self):
        value = fixture_data()
        assignment = next(a for a in value["origin_assignments"] if a["id"] == "OA-MIX-11")
        del assignment["credible_interval"]
        with self.assertRaisesRegex(ValueError, "后验与置信区间"):
            validate_domain(value)

    def test_mixed_sample_cannot_be_individually_assigned(self):
        value = fixture_data()
        assignment = next(a for a in value["origin_assignments"] if a["id"] == "OA-MIX-11")
        assignment["assignment"] = "hatchery"
        assignment["batch_id"] = "B2025-01"
        with self.assertRaisesRegex(ValueError, "混合样本"):
            validate_domain(value)

    def test_recapture_requires_dedup_adjustment(self):
        value = fixture_data()
        current = next(a for a in value["analyses"] if a["status"] == "current")
        current["adjustments"] = [
            item for item in current["adjustments"] if item["type"] != "recapture_dedup"
        ]
        with self.assertRaisesRegex(ValueError, "recapture_dedup"):
            validate_domain(value)

    def test_metrics_must_be_recomputable_from_analysis_inputs(self):
        value = fixture_data()
        current = next(a for a in value["analyses"] if a["status"] == "current")
        current["metrics"][0]["inputs"] = ["OBS-NOT-IN-ANALYSIS"]
        with self.assertRaisesRegex(ValueError, "分析输入之外"):
            validate_domain(value)

    def test_decision_must_reference_current_analysis(self):
        value = fixture_data()
        value["decisions"][0]["based_on_analysis"] = "AN-2025-01"
        with self.assertRaisesRegex(ValueError, "current"):
            validate_domain(value)

    def test_protocol_change_between_versions_needs_reason(self):
        value = fixture_data()
        current = next(a for a in value["analyses"] if a["status"] == "current")
        del current["protocol_change_reason"]
        with self.assertRaisesRegex(ValueError, "换版必须说明原因"):
            validate_domain(value)

    def test_decision_covers_species_quantity_reach(self):
        value = fixture_data()
        value["decisions"][0]["adjustments"] = [
            item for item in value["decisions"][0]["adjustments"]
            if item["dimension"] != "reach"
        ]
        with self.assertRaisesRegex(ValueError, "河段"):
            validate_domain(value)

    def test_each_capture_has_origin_assignment(self):
        value = load_domain(FIXTURE)
        captured = {
            o["id"] for o in value["observations"] if o["type"] == "capture"
        }
        assigned = {a["observation_id"] for a in value["origin_assignments"]}
        self.assertTrue(captured <= assigned)

    def test_responsibilities_are_segregated_by_actor(self):
        value = load_domain(FIXTURE)
        by_name = {a["name"]: a for a in value["actors"]}
        self.assertIn("on_site_count", by_name["放流执行单位"]["responsibilities"])
        self.assertNotIn("annual_decision", by_name["第三方生态监测人员"]["responsibilities"])
        self.assertIn("independent_evidence", by_name["第三方生态监测人员"]["responsibilities"])

    def test_deep_copy_helper_is_independent(self):
        # 守护测试：反例构造必须基于深拷贝，避免污染其他用例。
        first = fixture_data()
        second = copy.deepcopy(first)
        second["version"] = 99
        self.assertEqual(first["version"], 2)


if __name__ == "__main__":
    unittest.main()
