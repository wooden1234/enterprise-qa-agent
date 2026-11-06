import unittest

from src.harness.knowledge.index import SectionIndex
from src.tools import content_terms


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.index = SectionIndex.load()

    def test_terms_keep_policy_words(self):
        self.assertEqual(content_terms("年假有多少天？"), ["年假"])
        self.assertEqual(content_terms("那病假呢？"), ["病假"])
        self.assertIn("班车", content_terms("公司班车早上几点发车？"))

    def test_annual_leave_hits_both_versions(self):
        result = self.index.search("年假")
        annual = [item for item in result["results"] if "年假" in item["heading"]]
        self.assertEqual({item["doc_id"] for item in annual}, {"D03", "D04"})
        self.assertTrue(result["version_conflicts"])
        self.assertNotIn("text", annual[0])

    def test_sections_keep_different_day_counts(self):
        result = self.index.search("年假")
        texts = []
        for item in result["results"]:
            if "八、年假" not in item["heading"]:
                continue
            texts.append(self.index.read(item["section_id"])["text"])
        joined = "\n".join(texts)
        self.assertIn("年休假 5 个工作日", joined)
        self.assertIn("年休假 10 个工作日", joined)

    def test_out_of_corpus(self):
        result = self.index.search("班车")
        self.assertEqual(result["match_count"], 0)

    def test_missing_section(self):
        result = self.index.read("D99:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "section_not_found")


if __name__ == "__main__":
    unittest.main()
