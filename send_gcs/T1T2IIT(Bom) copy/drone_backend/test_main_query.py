from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main


class RagQueryForceLookupTests(unittest.TestCase):
    def test_below_threshold_without_force_skips_rag(self) -> None:
        request = main.RagQueryRequest(
            signal_id="test-skip",
            score=0.319,
            vector=[0.0] * main.VECTOR_SIZE,
        )

        with patch.object(main, "get_qdrant") as get_qdrant:
            result = main.query_rag(request)

        get_qdrant.assert_not_called()
        self.assertFalse(result.is_anomaly)
        self.assertEqual(result.retrieved_medoids, [])
        self.assertIn("RAG_SKIP: Below anomaly threshold.", result.verbose_logs)

    def test_below_threshold_with_force_searches_rag(self) -> None:
        request = main.RagQueryRequest(
            signal_id="test-force",
            score=0.319,
            vector=[0.0] * main.VECTOR_SIZE,
            force_rag_lookup=True,
        )

        with (
            patch.object(main, "get_qdrant", return_value=object()),
            patch.object(main, "ensure_collection"),
            patch.object(main, "search_tier", return_value=[]),
        ):
            result = main.query_rag(request)

        self.assertFalse(result.is_anomaly)
        self.assertEqual(result.retrieved_medoids, [])
        self.assertIn(
            "RAG_FORCE: Frontend anomaly decision requested retrieval.",
            result.verbose_logs,
        )
        self.assertNotIn("RAG_SKIP: Below anomaly threshold.", result.verbose_logs)


if __name__ == "__main__":
    unittest.main()
