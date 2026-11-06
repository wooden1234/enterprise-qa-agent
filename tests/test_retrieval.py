import unittest

from src.retrieval.bm25 import BM25Okapi, tokenize
from src.retrieval.chunks import build_chunks, validate_unique_chunk_ids
from src.retrieval.store import attach_ingest_time
from src.harness.tracing import trace_run
from src.retrieval.retriever import _rrf_fuse, search_policy
from src.retrieval.retriever import RetrievalHit


class RetrievalTests(unittest.TestCase):
    def test_tracing_is_off_without_langsmith_flag(self):
        seen = {}

        def _call():
            seen["ok"] = True
            return "done"

        self.assertEqual(trace_run("agent.turn", "chain", _call, {"question": "你好"}), "done")
        self.assertTrue(seen["ok"])

    def test_chunk_ids_are_unique(self):
        chunks = build_chunks()
        self.assertGreater(len(chunks), 10)
        validate_unique_chunk_ids(chunks)
        self.assertTrue(all(item["metadata"]["chunk_kind"] == "policy_section" for item in chunks))
        self.assertTrue(all(item["metadata"]["document_name"] and item["metadata"]["source"] for item in chunks))
        self.assertEqual(chunks[0]["metadata"]["document_name"], "财务报销制度及报销流程")
        self.assertEqual(chunks[0]["metadata"]["source"], "报销管理制度.md")
        self.assertTrue(all(item["text"] and item["metadata"]["section_id"] for item in chunks))

    def test_ingest_time_is_shared_metadata(self):
        chunks = build_chunks()[:2]
        stamped = attach_ingest_time(chunks, "2026-11-06T16:00:00+08:00")
        self.assertEqual(stamped, "2026-11-06T16:00:00+08:00")
        self.assertEqual(chunks[0]["metadata"]["ingested_at"], stamped)
        self.assertEqual(chunks[1]["metadata"]["ingested_at"], stamped)
        self.assertNotIn("document_name", chunks[0])

    def test_duplicate_chunk_id_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_unique_chunk_ids(
                [{"chunk_id": "D03:policy:000001"}, {"chunk_id": "D03:policy:000001"}]
            )

    def test_search_without_embedding_uses_bm25_and_rrf(self):
        result = search_policy("年假")
        annual = [item for item in result["results"] if "年假" in item["heading"]]
        self.assertEqual({item["doc_id"] for item in annual}, {"D03", "D04"})
        self.assertNotIn("text", annual[0])
        self.assertEqual(result["retrieval"]["mode"], "vector_bm25_rrf_rerank")
        self.assertGreater(result["retrieval"]["bm25_hits"], 0)
        self.assertEqual(result["retrieval"]["rerank_status"], "disabled")
        self.assertTrue(all(item["score_type"] == "rrf" for item in annual))
        self.assertIn("bm25_rank", annual[0])

    def test_rrf_adds_reciprocal_ranks(self):
        def hit(chunk_id):
            return RetrievalHit(
                text=chunk_id,
                score=1.0,
                metadata={"chunk_id": chunk_id, "section_id": chunk_id, "doc_id": "D03", "title": "", "version_date": "", "section": chunk_id},
                node_id=chunk_id,
            )

        fused = _rrf_fuse([("vector", [hit("a")]), ("bm25", [hit("b"), hit("a")])], top_k=2, rrf_k=60)
        self.assertEqual(fused[0].node_id, "a")
        self.assertAlmostEqual(fused[0].score, 1.0 / 61 + 1.0 / 62)
        self.assertAlmostEqual(fused[1].score, 1.0 / 61)

    def test_bm25_ignores_terms_missing_from_corpus(self):
        corpus = [tokenize("第五章 年假 年休假 5 个工作日"), tokenize("办公设备 更换周期 36 个月")]
        model = BM25Okapi(corpus)
        scores = model.scores(tokenize("公司班车早上几点发车"))
        self.assertEqual(scores, [0.0, 0.0])
        generic = [
            tokenize("每年共计十一个休假日"),
            tokenize("年假 年休假 5 个工作日"),
            tokenize("办公设备 更换周期"),
        ]
        model = BM25Okapi(generic)
        self.assertEqual(model.scores(tokenize("带薪休假 每年")), [0.0, 0.0, 0.0])
        self.assertGreater(model.scores(tokenize("年假"))[1], 0)

    def test_bus_schedule_abstains(self):
        result = search_policy("公司班车早上几点发车")
        self.assertEqual(result["match_count"], 0)
        self.assertTrue(result["retrieval"]["abstained"])


if __name__ == "__main__":
    unittest.main()
