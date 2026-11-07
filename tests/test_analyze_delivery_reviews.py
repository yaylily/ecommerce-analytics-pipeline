from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_delivery_reviews as analysis  # noqa: E402


def synthetic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order_id": "synthetic-early",
                "order_status": "delivered",
                "delivery_days_vs_estimate": -2,
                "delivery_timing_status": "early",
                "is_late": False,
                "review_count": 1,
                "review_score_sum": 5,
                "order_avg_review_score": 5.0,
            },
            {
                "order_id": "synthetic-promised",
                "order_status": "delivered",
                "delivery_days_vs_estimate": 0,
                "delivery_timing_status": "promised_date",
                "is_late": False,
                "review_count": 1,
                "review_score_sum": 4,
                "order_avg_review_score": 4.0,
            },
            {
                "order_id": "synthetic-late-multi",
                "order_status": "delivered",
                "delivery_days_vs_estimate": 1,
                "delivery_timing_status": "late",
                "is_late": True,
                "review_count": 2,
                "review_score_sum": 2,
                "order_avg_review_score": 1.0,
            },
            {
                "order_id": "synthetic-late-single",
                "order_status": "delivered",
                "delivery_days_vs_estimate": 3,
                "delivery_timing_status": "late",
                "is_late": True,
                "review_count": 1,
                "review_score_sum": 5,
                "order_avg_review_score": 5.0,
            },
        ]
    )


class DeliveryReviewAnalysisUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validated = analysis.validate_analysis_frame(synthetic_frame())
        self.summary = analysis.summarize_delivery_reviews(self.validated)

    def test_summary_uses_equal_order_weighting(self) -> None:
        self.assertEqual(self.summary.total_orders, 4)
        self.assertEqual(self.summary.not_late.order_count, 2)
        self.assertEqual(self.summary.late.order_count, 2)
        self.assertEqual(self.summary.review_row_count, 5)
        self.assertEqual(self.summary.review_score_sum, 16)
        self.assertEqual(self.summary.multi_review_order_count, 1)
        self.assertAlmostEqual(self.summary.not_late.avg_review_score, 4.5)
        self.assertAlmostEqual(self.summary.late.avg_review_score, 3.0)
        self.assertAlmostEqual(self.summary.avg_score_difference, -1.5)
        late_row_weighted_average = 7 / 3
        self.assertNotAlmostEqual(
            self.summary.late.avg_review_score, late_row_weighted_average
        )

    def test_report_is_deterministic_aggregate_only_and_noncausal(self) -> None:
        first = analysis.render_report(self.summary)
        second = analysis.render_report(self.summary)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.assertIn("관찰된 관계", first)
        self.assertIn("인과 효과가 아니다", first)
        self.assertNotIn("synthetic-", first)
        self.assertNotIn("PGPASSWORD", first)
        self.assertNotIn("/Users/", first)

    def test_figures_encode_fixed_group_order_and_honest_axis(self) -> None:
        share_figure = analysis.create_cohort_share_figure(self.summary)
        share_axis = share_figure.axes[0]
        self.assertEqual(tuple(round(patch.get_width(), 8) for patch in share_axis.patches), (50.0, 50.0))
        self.assertEqual(share_axis.get_xlim(), (0.0, 100.0))

        score_figure = analysis.create_average_score_figure(self.summary)
        score_axis = score_figure.axes[0]
        self.assertEqual(
            tuple(round(patch.get_height(), 8) for patch in score_axis.patches),
            (4.5, 3.0),
        )
        self.assertEqual(score_axis.get_ylim(), (0.0, 5.0))
        analysis.plt.close(share_figure)
        analysis.plt.close(score_figure)

    def test_artifacts_are_reproducible_in_the_same_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            analysis.write_artifacts(self.summary, reports_dir)
            first = {
                path: (reports_dir / path).read_bytes()
                for path in analysis.ARTIFACT_FILES
            }
            analysis.write_artifacts(self.summary, reports_dir)
            second = {
                path: (reports_dir / path).read_bytes()
                for path in analysis.ARTIFACT_FILES
            }
            self.assertEqual(first, second)
            self.assertTrue(first[analysis.SHARE_FIGURE].startswith(b"\x89PNG"))
            self.assertTrue(first[analysis.SCORE_FIGURE].startswith(b"\x89PNG"))

    def test_check_detects_stale_artifact_without_mutating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            analysis.write_artifacts(self.summary, reports_dir)
            analysis.check_artifacts(self.summary, reports_dir)

            report_path = reports_dir / analysis.REPORT_FILE
            report_path.write_text("stale report\n", encoding="utf-8")
            stale_bytes = report_path.read_bytes()
            with self.assertRaises(analysis.DeliveryReviewAnalysisError):
                analysis.check_artifacts(self.summary, reports_dir)
            self.assertEqual(report_path.read_bytes(), stale_bytes)

    def test_duplicate_or_null_input_fails_closed(self) -> None:
        duplicate = pd.concat([synthetic_frame(), synthetic_frame().iloc[[0]]])
        with self.assertRaises(analysis.DeliveryReviewAnalysisError):
            analysis.validate_analysis_frame(duplicate)

        null_value = synthetic_frame()
        null_value.loc[0, "review_count"] = None
        with self.assertRaises(analysis.DeliveryReviewAnalysisError):
            analysis.validate_analysis_frame(null_value)

    def test_delivery_contract_mismatch_fails_closed(self) -> None:
        mutations = []
        wrong_status = synthetic_frame()
        wrong_status.loc[0, "delivery_timing_status"] = "late"
        mutations.append(wrong_status)

        wrong_late_flag = synthetic_frame()
        wrong_late_flag.loc[0, "is_late"] = True
        mutations.append(wrong_late_flag)

        wrong_order_status = synthetic_frame()
        wrong_order_status.loc[0, "order_status"] = "shipped"
        mutations.append(wrong_order_status)

        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                with self.assertRaises(analysis.DeliveryReviewAnalysisError):
                    analysis.validate_analysis_frame(mutation)

    def test_review_contract_mismatch_fails_closed(self) -> None:
        mutations = []
        zero_count = synthetic_frame()
        zero_count.loc[0, "review_count"] = 0
        mutations.append(zero_count)

        impossible_sum = synthetic_frame()
        impossible_sum.loc[0, "review_score_sum"] = 6
        mutations.append(impossible_sum)

        wrong_average = synthetic_frame()
        wrong_average.loc[0, "order_avg_review_score"] = 4.0
        mutations.append(wrong_average)

        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                with self.assertRaises(analysis.DeliveryReviewAnalysisError):
                    analysis.validate_analysis_frame(mutation)

    def test_database_reconciliation_detects_count_and_average_drift(self) -> None:
        baseline = {
            "total_orders": 4,
            "distinct_orders": 4,
            "early_orders": 1,
            "promised_date_orders": 1,
            "late_orders": 2,
            "not_late_orders": 2,
            "review_row_count": 5,
            "review_score_sum": 16,
            "multi_review_order_count": 1,
            "overall_avg_review_score": 3.75,
            "not_late_avg_review_score": 4.5,
            "late_avg_review_score": 3.0,
        }
        analysis.reconcile_with_database(self.summary, baseline)

        count_drift = copy.deepcopy(baseline)
        count_drift["late_orders"] = 3
        with self.assertRaises(analysis.DeliveryReviewAnalysisError):
            analysis.reconcile_with_database(self.summary, count_drift)

        average_drift = copy.deepcopy(baseline)
        average_drift["late_avg_review_score"] = 3.1
        with self.assertRaises(analysis.DeliveryReviewAnalysisError):
            analysis.reconcile_with_database(self.summary, average_drift)


if __name__ == "__main__":
    unittest.main()
