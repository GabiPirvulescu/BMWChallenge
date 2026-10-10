"""Opt-in end-to-end checks against a disposable, loopback Neo4j instance."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlparse

from services.evidence import EvidenceScope, Neo4jEvidenceProvider
from services.ingestion import convert_sources, write_bundle


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA_DIR = Path(os.environ.get("BMW_DATA_DIR", REPO_ROOT / "BMW-Data")).resolve()
NEO4J_URI = os.environ.get("BMW_NEO4J_TEST_URI")


class LiveNeo4jTests(unittest.TestCase):
    """Import the real source set and prove scoped evidence reads with Neo4j."""

    @classmethod
    def setUpClass(cls) -> None:
        if not NEO4J_URI:
            raise unittest.SkipTest("set BMW_NEO4J_TEST_URI to run live Neo4j integration checks")
        host = urlparse(NEO4J_URI).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("Live integration tests only write to a loopback Neo4j instance")
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Install the Neo4j Python driver from pipeline/requirements-data.txt") from exc

        if os.environ.get("BMW_NEO4J_TEST_AUTH_DISABLED") == "1":
            auth = None
        else:
            user = os.environ.get("BMW_NEO4J_TEST_USER")
            password = os.environ.get("BMW_NEO4J_TEST_PASSWORD")
            if not user or not password:
                raise RuntimeError(
                    "Set BMW_NEO4J_TEST_USER and BMW_NEO4J_TEST_PASSWORD, or use a loopback test DB "
                    "with BMW_NEO4J_TEST_AUTH_DISABLED=1"
                )
            auth = (user, password)
        cls.driver = GraphDatabase.driver(NEO4J_URI, auth=auth)
        cls.driver.verify_connectivity()

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "driver", None) is not None:
            cls.driver.close()

    def test_real_import_is_idempotent_and_citations_resolve(self) -> None:
        self.assertTrue(REAL_DATA_DIR.is_dir(), f"BMW data directory not found: {REAL_DATA_DIR}")
        bundle = convert_sources(REAL_DATA_DIR, check_known_feedback_counts=True)
        self.assertEqual(bundle.manifest["status"], "succeeded", bundle.manifest.get("issues"))
        self.assertIn("corporate_report", {
            source.get("document_kind") for source in bundle.source_files
        })

        from importlib.util import spec_from_file_location, module_from_spec

        loader_path = REPO_ROOT / "pipeline" / "01_load_neo4j.py"
        spec = spec_from_file_location("bmw_data_loader", loader_path)
        self.assertIsNotNone(spec)
        loader = module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(loader)

        scratch_dir = REPO_ROOT / "scratch"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="neo4j-integration-", dir=scratch_dir) as temp_dir:
            processed_dir = Path(temp_dir) / "processed"
            write_bundle(bundle, processed_dir, REAL_DATA_DIR)
            first = loader.load_processed_bundle(self.driver, processed_dir)
            second = loader.load_processed_bundle(self.driver, processed_dir)

        self.assertEqual(first, second)
        self.assertEqual(first["counts"]["feedback_comments"], 10_128)
        self.assertEqual(first["counts"]["feedback_annotations"], 13_371)
        self.assertGreater(first["counts"]["document_chunks"], 78)

        with self.driver.session() as session:
            graph_counts = session.run("""
                MATCH (feedback:CustomerFeedback)
                WITH count(feedback) AS feedback_count
                MATCH (chunk:DocumentChunk {document_kind: 'corporate_report'})
                WITH feedback_count, count(chunk) AS strategy_chunk_count
                RETURN feedback_count, strategy_chunk_count
            """).single()
        self.assertEqual(graph_counts["feedback_count"], 10_128)
        self.assertGreater(graph_counts["strategy_chunk_count"], 0)
        with self.driver.session() as session:
            current_import_runs = session.run(
                "MATCH (run:ImportRun {id: $id}) RETURN count(run) AS count",
                id=first["import_run_id"],
            ).single()["count"]
        self.assertEqual(current_import_runs, 1)

        provider = Neo4jEvidenceProvider(self.driver)
        sample = next(comment for comment in bundle.feedback_comments
                      if comment.get("model") == "G70" and comment.get("region") == "US"
                      and comment.get("original_text", "").strip())
        searchable_words = re.findall(r"[A-Za-z0-9_'-]{6,}", sample["original_text"])
        self.assertTrue(searchable_words, "Chosen feedback sample has no searchable word")
        g70_us_texts = [comment.get("original_text", "").casefold()
                        for comment in bundle.feedback_comments
                        if comment.get("model") == "G70" and comment.get("region") == "US"]
        query = min(searchable_words,
                    key=lambda word: sum(word.casefold() in text for text in g70_us_texts))
        matches = provider.search_feedback(query, EvidenceScope(model="G70", region="US"), limit=100)
        sample_match = next((match for match in matches if match["id"] == sample["id"]), None)
        self.assertIsNotNone(sample_match)
        self.assertTrue(any(annotation.get("vfc2_original") for annotation in sample_match["annotations"]))
        source_record_id = sample_match["source_records"][0]["id"]
        source_record = provider.get_source_record(source_record_id)
        self.assertIsNotNone(source_record)
        self.assertTrue(source_record["locator"].get("row"))
        self.assertIn(sample["original_text"], source_record["raw_payload"]["values_by_header"].values())

        report_chunks = provider.search_document_chunks(
            "BMW", document_kind="corporate_report", limit=3
        )
        self.assertTrue(report_chunks)
        self.assertTrue(all(chunk["source_locator"].get("page") for chunk in report_chunks))
        self.assertTrue(all(chunk["source_locator"]["filename"].lower().endswith(".pdf")
                            for chunk in report_chunks))
        report_source = provider.get_source_record(report_chunks[0]["source_record_id"])
        page_text = report_source["raw_payload"]["text"]
        cited_chunk = report_chunks[0]
        self.assertEqual(
            page_text[cited_chunk["start_offset"]:cited_chunk["end_offset"]],
            cited_chunk["original_text"],
        )
        with self.driver.session() as session:
            taxonomy_counts = session.run("""
                MATCH (topic:VFCTag)
                WITH count(topic) AS topic_count
                MATCH (issue:VFCTag3)
                RETURN topic_count, count(issue) AS issue_count
            """).single()
        self.assertGreater(taxonomy_counts["topic_count"], 0)
        self.assertGreater(taxonomy_counts["issue_count"], 0)


if __name__ == "__main__":
    unittest.main()
