from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_delivery_review_deepening as analysis  # noqa: E402


BOUNDARY_DAYS = (-1, 0, 1, 3, 4, 7, 8, 14, 15)


def synthetic_frame(
    days: tuple[int, ...] = BOUNDARY_DAYS,
    *,
    true_inversion_index: int | None = 2,
) -> pd.DataFrame:
    rows = []
    for index, day in enumerate(days):
        score = (index % 5) + 1
        row = {
            "order_id": f"synthetic-{index}",
            "order_status": "delivered",
            "order_purchase_timestamp": pd.Timestamp("2017-02-15"),
            "delivery_days_vs_estimate": day,
            "delivery_timing_status": (
                "early" if day < 0 else "promised_date" if day == 0 else "late"
            ),
            "is_late": day > 0,
            "review_count": 1,
            "review_score_sum": score,
            "order_avg_review_score": Decimal(score),
            "is_approval_date_missing": False,
            "is_carrier_date_missing": False,
        }
        for flag in analysis.INVERSION_FLAGS:
            row[flag] = None
        if index == true_inversion_index:
            row["is_customer_before_carrier"] = True
        rows.append(row)
    return pd.DataFrame(rows)


def baselines_from_summary(
    summary: analysis.DeepeningSummary,
) -> analysis.DatabaseBaselines:
    overall = {
        "total_orders": summary.total_orders,
        "distinct_orders": summary.total_orders,
        "review_row_count": summary.review_row_count,
        "review_score_sum": summary.review_score_sum,
        "order_review_score_sum": summary.order_review_score_sum,
        "low_score_order_count": summary.low_score_order_count,
        "chronology_inversion_order_count": summary.chronology_inversion_order_count,
        "overall_median_review_score": summary.overall_median_review_score,
        "late_delay_p25": summary.late_delay_p25,
        "late_delay_median": summary.late_delay_median,
        "late_delay_p75": summary.late_delay_p75,
        "late_delay_max": summary.late_delay_max,
    }
    for flag, count in summary.inversion_flag_null_counts:
        overall[f"{flag}_null_count"] = count

    severity = pd.DataFrame(
        [
            {
                "severity_group": group.name,
                "order_count": group.order_count,
                "review_row_count": group.review_row_count,
                "review_score_sum": group.review_score_sum,
                "order_review_score_sum": group.order_review_score_sum,
                "low_score_order_count": group.low_score_order_count,
                "median_review_score": group.median_review_score,
            }
            for group in summary.severity
        ]
    )
    monthly = pd.DataFrame(
        [
            {
                "purchase_month": month.purchase_month,
                "order_count": month.order_count,
                "distinct_orders": month.order_count,
                "late_order_count": month.late_order_count,
                "not_late_order_count": month.not_late_order_count,
                "review_row_count": month.review_row_count,
                "review_score_sum": month.review_score_sum,
                "late_order_review_score_sum": month.late_order_review_score_sum,
                "not_late_order_review_score_sum": month.not_late_order_review_score_sum,
            }
            for month in summary.monthly
        ]
    )
    sensitivity = pd.DataFrame(
        [
            {
                "cohort_name": cohort.name,
                "order_count": cohort.order_count,
                "distinct_orders": cohort.order_count,
                "late_order_count": cohort.late_order_count,
                "not_late_order_count": cohort.not_late_order_count,
                "review_row_count": cohort.review_row_count,
                "review_score_sum": cohort.review_score_sum,
                "late_order_review_score_sum": cohort.late_order_review_score_sum,
                "not_late_order_review_score_sum": cohort.not_late_order_review_score_sum,
            }
            for cohort in summary.sensitivity
        ]
    )
    return analysis.DatabaseBaselines(
        overall=overall,
        severity=severity,
        monthly=monthly,
        sensitivity=sensitivity,
    )


class DeliveryReviewDeepeningUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validated = analysis.validate_analysis_frame(synthetic_frame())
        self.summary = analysis.summarize_deepening(self.validated)

    def test_boundary_values_are_mutually_exclusive_and_exhaustive(self) -> None:
        actual = analysis.assign_severity_group(self.validated).tolist()
        self.assertEqual(
            actual,
            [
                "early",
                "promised_date",
                "late_1_3",
                "late_1_3",
                "late_4_7",
                "late_4_7",
                "late_8_14",
                "late_8_14",
                "late_15_plus",
            ],
        )
        late_group_count = sum(
            group.order_count
            for group in self.summary.severity
            if group.name.startswith("late_")
        )
        self.assertEqual(late_group_count, int(self.validated["is_late"].sum()))

    def test_summary_keeps_exact_18_month_keys_and_empty_months_as_na(self) -> None:
        self.assertEqual(
            tuple(month.purchase_month for month in self.summary.monthly),
            analysis.APPROVED_MONTHS,
        )
        self.assertEqual(len(self.summary.monthly), 18)
        empty_month = self.summary.monthly[1]
        self.assertEqual(empty_month.order_count, 0)
        self.assertEqual(empty_month.late_order_count, 0)
        self.assertIsNone(empty_month.late_rate)
        self.assertIsNone(empty_month.mean_score_gap)

    def test_empty_severity_groups_are_zero_and_na(self) -> None:
        validated = analysis.validate_analysis_frame(
            synthetic_frame(days=(-1, 0, 1), true_inversion_index=None)
        )
        summary = analysis.summarize_deepening(validated)
        empty_group = summary.severity_group("late_15_plus")
        self.assertEqual(empty_group.order_count, 0)
        self.assertEqual(empty_group.order_share, 0.0)
        self.assertEqual(empty_group.order_review_score_sum, Decimal(0))
        self.assertIsNone(empty_group.mean_review_score)
        self.assertIsNone(empty_group.median_review_score)
        self.assertIsNone(empty_group.low_score_rate)
        self.assertIn("N/A", analysis.render_report(summary))

    def test_only_explicit_true_inversion_is_excluded(self) -> None:
        self.assertEqual(self.summary.chronology_inversion_order_count, 1)
        without = self.summary.sensitivity_cohort(
            "without_chronology_inversions"
        )
        self.assertEqual(without.order_count, self.summary.total_orders - 1)
        null_counts = dict(self.summary.inversion_flag_null_counts)
        self.assertEqual(
            null_counts["is_approval_before_purchase"],
            self.summary.total_orders,
        )
        self.assertEqual(
            null_counts["is_customer_before_carrier"],
            self.summary.total_orders - 1,
        )

    def test_report_is_aggregate_only_noncausal_and_contract_scoped(self) -> None:
        report = analysis.render_report(self.summary)
        self.assertIn("엄격하게 단조 악화한 형태는 아니었다", report)
        self.assertIn("인과 효과가 아니다", report)
        self.assertIn("late 주문", report)
        self.assertNotIn("평균 2점 이하 비율 |\n|---", report.split("## 3.")[1])
        self.assertNotIn("synthetic-", report)
        self.assertNotIn("/Users/", report)
        self.assertNotIn("PGPASSWORD", report)

    def test_severity_shape_wording_follows_the_values(self) -> None:
        changed = synthetic_frame()
        changed.loc[changed["delivery_days_vs_estimate"].between(8, 14), [
            "review_score_sum",
            "order_avg_review_score",
        ]] = 5
        changed.loc[changed["delivery_days_vs_estimate"].ge(15), [
            "review_score_sum",
            "order_avg_review_score",
        ]] = 1
        summary = analysis.summarize_deepening(
            analysis.validate_analysis_frame(changed)
        )
        note = analysis._severity_shape_note(summary)
        self.assertIn("마지막 구간 평균은 더 낮았지만", note)
        self.assertNotIn("8–14일 평균이 조금 더 낮아", note)

        equal_tail = synthetic_frame()
        equal_tail.loc[
            equal_tail["delivery_days_vs_estimate"].ge(8),
            ["review_score_sum", "order_avg_review_score"],
        ] = 2
        equal_summary = analysis.summarize_deepening(
            analysis.validate_analysis_frame(equal_tail)
        )
        self.assertIn("plateau", analysis._severity_shape_note(equal_summary))

    def test_decimal_sum_is_exact_and_not_truncated(self) -> None:
        analysis._assert_exact_decimal("score_sum", Decimal("1.10"), Decimal("1.10"))
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis._assert_exact_decimal(
                "score_sum", Decimal("1.10"), Decimal("1.90")
            )

    def test_sql_reconciliation_detects_count_decimal_and_month_key_drift(self) -> None:
        baselines = baselines_from_summary(self.summary)
        analysis.reconcile_with_database(self.summary, baselines)

        count_drift = copy.deepcopy(baselines)
        count_drift.severity.loc[0, "order_count"] += 1
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.reconcile_with_database(self.summary, count_drift)

        decimal_drift = copy.deepcopy(baselines)
        decimal_drift.severity.loc[0, "order_review_score_sum"] += Decimal(
            "0.01"
        )
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.reconcile_with_database(self.summary, decimal_drift)

        month_key_drift = copy.deepcopy(baselines)
        month_key_drift.monthly.loc[0, "purchase_month"] = pd.Timestamp(
            "2017-01-01"
        )
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.reconcile_with_database(self.summary, month_key_drift)

    def test_sql_reconciliation_accepts_empty_severity_group_nulls(self) -> None:
        summary = analysis.summarize_deepening(
            analysis.validate_analysis_frame(
                synthetic_frame(days=(-1, 0, 1), true_inversion_index=None)
            )
        )
        baselines = baselines_from_summary(summary)
        empty_median = baselines.severity.set_index("severity_group").loc[
            "late_4_7", "median_review_score"
        ]
        # A SQL NULL becomes NaN alongside non-empty float medians in pandas.
        self.assertTrue(pd.isna(empty_median))
        self.assertIsNone(summary.severity_group("late_4_7").median_review_score)
        analysis.reconcile_with_database(summary, baselines)

    def test_derived_metric_nulls_do_not_hide_observed_value_mismatches(self) -> None:
        for actual, expected in ((None, float("nan")), (float("nan"), None)):
            with self.subTest(actual=actual, expected=expected):
                analysis._assert_derived_float("empty_median", actual, expected)

        for actual, expected in (
            (None, 2.0),
            (float("nan"), 2.0),
            (2.0, None),
            (2.0, float("nan")),
            (None, 0.0),
            (0.0, float("nan")),
            (1.0, 2.0),
        ):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaises(analysis.DeliveryReviewDeepeningError):
                    analysis._assert_derived_float("median", actual, expected)

    def test_artifacts_are_deterministic_and_check_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            analysis.build_artifacts(self.summary, reports_dir)
            first = {
                path: (reports_dir / path).read_bytes()
                for path in analysis.ARTIFACT_FILES
            }
            analysis.check_artifacts(self.summary, reports_dir)
            second = {
                path: (reports_dir / path).read_bytes()
                for path in analysis.ARTIFACT_FILES
            }
            self.assertEqual(first, second)
            self.assertEqual(len(analysis.ARTIFACT_FILES), 3)
            self.assertTrue(
                first[analysis.SEVERITY_FIGURE].startswith(b"\x89PNG")
            )
            self.assertTrue(
                first[analysis.MONTHLY_FIGURE].startswith(b"\x89PNG")
            )

    def test_artifact_set_rolls_back_if_a_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            original_bytes = {}
            for index, relative_path in enumerate(analysis.ARTIFACT_FILES):
                target = reports_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                original_bytes[relative_path] = f"old-{index}".encode()
                target.write_bytes(original_bytes[relative_path])

            original_replace = Path.replace
            replace_count = 0

            def fail_second_replace(source: Path, target: Path) -> Path:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("synthetic replace failure")
                return original_replace(source, target)

            with mock.patch.object(Path, "replace", new=fail_second_replace):
                with self.assertRaises(OSError):
                    analysis.build_artifacts(self.summary, reports_dir)

            self.assertEqual(
                {
                    path: (reports_dir / path).read_bytes()
                    for path in analysis.ARTIFACT_FILES
                },
                original_bytes,
            )

    def test_invalid_contract_values_fail_closed(self) -> None:
        duplicate = pd.concat([synthetic_frame(), synthetic_frame().iloc[[0]]])
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.validate_analysis_frame(duplicate)

        wrong_late = synthetic_frame()
        wrong_late.loc[0, "is_late"] = True
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.validate_analysis_frame(wrong_late)

        nat_timestamp = synthetic_frame()
        nat_timestamp.loc[0, "order_purchase_timestamp"] = "NaT"
        with self.assertRaises(analysis.DeliveryReviewDeepeningError):
            analysis.validate_analysis_frame(nat_timestamp)


if __name__ == "__main__":
    unittest.main()
