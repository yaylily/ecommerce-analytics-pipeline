from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_delivery_review_deepening as analysis  # noqa: E402


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_TESTS") == "1",
    "set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests",
)
class DeliveryReviewDeepeningIntegrationTests(unittest.TestCase):
    def test_fixed_snapshot_reconciles_and_artifacts_round_trip(self) -> None:
        load_dotenv(ROOT / ".env")
        config = analysis.DatabaseConfig.from_environment()
        with analysis.connect_database(config) as connection:
            frame, baselines = analysis.load_analysis_snapshot(connection)

        validated = analysis.validate_analysis_frame(frame)
        summary = analysis.summarize_deepening(validated)
        analysis.reconcile_with_database(summary, baselines)
        analysis.validate_expected_snapshot(summary)

        self.assertEqual(summary.total_orders, 95_824)
        self.assertEqual(len(summary.monthly), 18)
        self.assertEqual(
            tuple(month.purchase_month for month in summary.monthly),
            analysis.APPROVED_MONTHS,
        )
        self.assertEqual(summary.late_delay_p25, 3.0)
        self.assertEqual(summary.late_delay_median, 7.0)
        self.assertEqual(summary.late_delay_p75, 13.0)
        self.assertEqual(summary.late_delay_max, 188)

        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            analysis.build_artifacts(summary, reports_dir)
            analysis.check_artifacts(summary, reports_dir)


if __name__ == "__main__":
    unittest.main()
