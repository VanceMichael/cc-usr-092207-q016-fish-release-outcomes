import unittest
from pathlib import Path
from src.domain import load_domain

class DomainTest(unittest.TestCase):
    def setUp(self):
        self.value = load_domain(Path("fixtures/domain.json"))

    def test_fixture_matches_domain(self):
        self.assertEqual(self.value["domain"], "fish-release-outcomes")
        self.assertGreaterEqual(self.value["version"], 2)

    def test_lineage_chain_is_continuous(self):
        text = "".join(self.value["constraints"])
        for link in ("亲本", "繁育检疫", "标记", "运输容器", "现场计数", "河段水文", "后续采样"):
            self.assertIn(link, text)

    def test_probabilistic_identification_carries_confidence(self):
        text = "".join(self.value["constraints"])
        self.assertIn("混合样本", text)
        self.assertIn("置信度", text)

    def test_raw_observations_are_append_only(self):
        text = "".join(self.value["constraints"])
        for event in ("标签脱落", "重复捕获", "计数纠正", "异常死亡", "监测方案换版"):
            self.assertIn(event, text)
        self.assertIn("不得回改原始记录", text)

    def test_responsibility_split_and_recomputation(self):
        text = "".join(self.value["constraints"])
        self.assertIn("繁育单位", text)
        self.assertIn("第三方监测", text)
        self.assertIn("复算", text)

    def test_natural_spawning_has_evidence_boundary(self):
        text = "".join(self.value["facts"]) + "".join(self.value["constraints"])
        self.assertIn("自然繁殖", text)
        self.assertIn("证据边界", text)

if __name__ == "__main__":
    unittest.main()
