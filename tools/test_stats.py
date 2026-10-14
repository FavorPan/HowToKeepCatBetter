import unittest

from stats import check, parse_section

SAMPLE = """# 6. 疫苗与驱虫

### 1. 幼猫打满猫三联
<!-- 成本标签: 钱=少 时间=中 毅力=否 收益=大 口径=猫健康 -->
- 成本：几百元。
- 说人话：能防住猫瘟。
- 收益：病死率 30 到 50%。
- 证据等级：A
- 来源：Day MJ et al. (2016). WSAVA vaccination guidelines for the dog and the cat. J Small Anim Pract. <https://doi.org/10.1111/jsap.12440>
- 备注：无。

### 2. 别买假疫苗
<!-- 成本标签: 钱=0 时间=少 毅力=否 收益=中 口径=金钱 -->
- 成本：零。
- 说人话：某队列研究说没用，直接拒绝。
- 收益：省一针钱。
- 证据等级：B
- 来源：<https://example.com>
- 备注：无。
"""


class ParseTest(unittest.TestCase):
    def test_counts_and_fields(self):
        es = parse_section(SAMPLE)
        self.assertEqual(len(es), 2)
        self.assertEqual(es[0]["grade"], "A")
        self.assertIn("钱=少", es[0]["tag"])
        # 标题 + 标签 + 6 栏 + 与下条之间的空行
        self.assertEqual(es[0]["lines"], 9)

    def test_grade_missing_detected(self):
        bad = SAMPLE.replace("- 证据等级：A\n", "")
        es = parse_section(bad)
        self.assertTrue(any("证据等级" in v for v in check(es)))


class CheckTest(unittest.TestCase):
    def test_forbidden_term_in_plain(self):
        es = parse_section(SAMPLE)
        self.assertTrue(any("说人话" in v and "队列" in v for v in check(es)))

    def test_naked_ref_flagged(self):
        es = parse_section(SAMPLE)
        es[0]["body"].append("- 备注：见第 7 条。")
        self.assertTrue(any("裸条号" in v for v in check(es)))

    def test_full_ref_not_flagged(self):
        es = parse_section(SAMPLE)
        es[0]["body"].append("- 备注：见第 6 节第 7 条（驱蛔虫）。")
        self.assertEqual([v for v in check(es) if "裸条号" in v], [])


if __name__ == "__main__":
    unittest.main()
