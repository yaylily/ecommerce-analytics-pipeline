from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_delivery_reviews as analysis  # noqa: E402


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_TESTS") == "1",
    "set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests",
)
class DeliveryReviewAnalysisIntegrationTests(unittest.TestCase):
    def test_pandas_summary_reconciles_to_database_and_fixed_snapshot(self) -> None:
        load_dotenv(ROOT / ".env")
        config = analysis.DatabaseConfig.from_environment()
        with analysis.connect_database(config) as connection:
            frame, database_summary = analysis.load_analysis_snapshot(connection)

        validated = analysis.validate_analysis_frame(frame)
        summary = analysis.summarize_delivery_reviews(validated)
        analysis.reconcile_with_database(summary, database_summary)
        analysis.validate_expected_snapshot(summary)

        self.assertEqual(summary.total_orders, 95824)
        self.assertEqual(summary.not_late.order_count, 89443)
        self.assertEqual(summary.late.order_count, 6381)


if __name__ == "__main__":
    unittest.main()
