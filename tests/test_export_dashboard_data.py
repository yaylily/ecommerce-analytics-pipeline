from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_category_seller_trade as trade  # noqa: E402
import analyze_delivery_review_deepening as delivery  # noqa: E402
import export_dashboard_data as exporter  # noqa: E402
from dashboard.lib import CATEGORY_GROUPS, load_dashboard_data  # noqa: E402


D = Decimal


def synthetic_trade_result() -> trade.TradeAnalysisResult:
    months = trade.PRIMARY_MONTHS
    group_specs = tuple(
        (group_key, group_label)
        for group_key, group_label, _ in CATEGORY_GROUPS
    )
    monthly_rows = []
    category_rows = []
    concentration_rows = []
    for month_index, month in enumerate(months):
        gross = D("600") + D(month_index * 6)
        freight = D("60")
        monthly_rows.append(
            {
                "purchase_month": month,
                "gross_item_value": gross,
                "freight_amount": freight,
                "item_side_amount": gross + freight,
                "ordered_item_row_count": 120,
                "active_seller_count": 20,
            }
        )
        group_amount = gross / D("6")
        for rank, (group_key, group_label) in enumerate(group_specs, start=1):
            category_rows.append(
                {
                    "purchase_month": month,
                    "group_key": group_key,
                    "gross_item_value": group_amount,
                    "month_total_gross_item_value": gross,
                    "share": D("1") / D("6"),
                    "group_label": group_label,
                    "group_rank": rank,
                    "change_contribution": None,
                }
            )
        concentration_rows.append(
            {
                "purchase_month": month,
                "active_seller_count": 20,
                "total_gross_item_value": gross,
                "top1_seller_count": 1,
                "top10_seller_count": 10,
                "top10_percent_seller_count": 2,
                "top1_gross_item_value": gross * D("0.1"),
                "top10_gross_item_value": gross * D("0.7"),
                "top10_percent_gross_item_value": gross * D("0.2"),
                "top1_share": D("0.1"),
                "top10_share": D("0.7"),
                "top10_percent_share": D("0.2"),
            }
        )
    monthly = pd.DataFrame(monthly_rows)
    return trade.TradeAnalysisResult(
        monthly_overview=monthly,
        category_mix=pd.DataFrame(category_rows),
        seller_concentration=pd.DataFrame(concentration_rows),
        mapping_summary=pd.DataFrame(),
        top_categories=pd.DataFrame(),
        period_gross_item_value=sum(monthly["gross_item_value"], D("0")),
        period_freight_amount=sum(monthly["freight_amount"], D("0")),
        period_item_side_amount=sum(monthly["item_side_amount"], D("0")),
        period_ordered_item_row_count=int(monthly["ordered_item_row_count"].sum()),
        category_row_count=108,
        seller_row_count=360,
    )


def _group_metrics(
    name: str, count: int, score: str, low_count: int, total: int
) -> delivery.GroupMetrics:
    score_sum = D(score) * D(count)
    return delivery.GroupMetrics(
        name=name,
        order_count=count,
        order_share=count / total,
        review_row_count=count,
        review_score_sum=int(D(score) * D(count)),
        order_review_score_sum=score_sum,
        low_score_order_count=low_count,
        mean_review_score=float(D(score)),
        median_review_score=float(D(score)),
        low_score_rate=low_count / count,
    )


def _cohort_metrics(
    name: str, order_count: int, late_count: int
) -> delivery.CohortMetrics:
    not_late_count = order_count - late_count
    late_sum = D(late_count) * D("2")
    not_late_sum = D(not_late_count) * D("4")
    return delivery.CohortMetrics(
        name=name,
        order_count=order_count,
        late_order_count=late_count,
        not_late_order_count=not_late_count,
        review_row_count=order_count,
        review_score_sum=order_count * 4,
        late_order_review_score_sum=late_sum,
        not_late_order_review_score_sum=not_late_sum,
        late_rate=late_count / order_count,
        late_mean_review_score=2.0,
        not_late_mean_review_score=4.0,
        mean_score_gap=-2.0,
    )


def synthetic_delivery_summary() -> delivery.DeepeningSummary:
    counts = (88_163, 1_280, 1_852, 1_748, 1_446, 1_335)
    scores = ("4", "4", "2", "2", "2", "2")
    low_counts = (8_000, 150, 600, 1_100, 1_200, 1_050)
    groups = tuple(
        _group_metrics(name, count, score, low_count, exporter.EXPECTED_TOTAL_ORDERS)
        for name, count, score, low_count in zip(
            delivery.SEVERITY_ORDER, counts, scores, low_counts, strict=True
        )
    )
    monthly = tuple(
        delivery.MonthlyMetrics(
            purchase_month=month,
            order_count=1_000,
            late_order_count=100,
            not_late_order_count=900,
            review_row_count=1_000,
            review_score_sum=3_800,
            late_order_review_score_sum=D("200"),
            not_late_order_review_score_sum=D("3600"),
            late_rate=0.1,
            late_mean_review_score=2.0,
            not_late_mean_review_score=4.0,
            mean_score_gap=-2.0,
        )
        for month in delivery.APPROVED_MONTHS
    )
    sensitivity = (
        _cohort_metrics("all_orders", 95_824, 6_381),
        _cohort_metrics("without_chronology_inversions", 94_458, 6_250),
    )
    return delivery.DeepeningSummary(
        total_orders=95_824,
        review_row_count=95_824,
        review_score_sum=380_000,
        order_review_score_sum=sum(
            (group.order_review_score_sum for group in groups), D("0")
        ),
        low_score_order_count=sum(group.low_score_order_count for group in groups),
        overall_mean_review_score=4.0,
        overall_median_review_score=5.0,
        overall_low_score_rate=0.1,
        chronology_inversion_order_count=1_366,
        inversion_flag_null_counts=tuple(
            (flag, 0) for flag in delivery.INVERSION_FLAGS
        ),
        late_delay_p25=3.0,
        late_delay_median=7.0,
        late_delay_p75=13.0,
        late_delay_max=188,
        severity=groups,
        monthly=monthly,
        sensitivity=sensitivity,
    )


class DashboardExporterUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = exporter.public_rows(
            synthetic_trade_result(), synthetic_delivery_summary()
        )

    def test_public_rows_use_contract_names_and_exclude_identifiers(self) -> None:
        self.assertEqual(tuple(self.rows), exporter.CSV_FILE_ORDER)
        all_columns = {
            column
            for rows in self.rows.values()
            for row in rows
            for column in row
        }
        self.assertTrue(
            {
                "order_id",
                "seller_id",
                "customer_id",
                "product_id",
                "review_comment_message",
            }.isdisjoint(all_columns)
        )
        timing = self.rows["delivery_timing_summary.csv"]
        self.assertEqual(timing[0]["delivery_timing_group"], "early")
        self.assertEqual(timing[-1]["group_label"], "15일 이상 지연")

    def test_decimal_serialization_is_plain_and_not_float_rounded(self) -> None:
        self.assertEqual(exporter._canonical_decimal(D("100.2300")), "100.23")
        self.assertEqual(exporter._canonical_decimal(D("1E-12")), "0.000000000001")
        self.assertEqual(exporter._canonical_decimal(D("-0.0")), "0")
        self.assertEqual(
            exporter._canonical_decimal(None, nullable=True),
            "",
        )

    def test_write_bundle_is_deterministic_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first"
            second = Path(temporary_directory) / "second"
            exporter.write_bundle(self.rows, first)
            exporter.write_bundle(self.rows, second)
            for filename in exporter.ARTIFACT_FILES:
                self.assertEqual(
                    (first / filename).read_bytes(),
                    (second / filename).read_bytes(),
                )
            data = load_dashboard_data(first)
            self.assertEqual(len(data.category_mix), 108)
            self.assertEqual(len(data.delivery_timing_summary), 6)
            manifest = json.loads((first / "manifest.json").read_text())
            self.assertNotIn("generated_at", manifest)
            self.assertEqual(manifest["schema_version"], 1)

    def test_check_does_not_modify_committed_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            exporter.build_bundle(self.rows, data_dir)
            before = {
                filename: (data_dir / filename).read_bytes()
                for filename in exporter.ARTIFACT_FILES
            }
            exporter.check_bundle(self.rows, data_dir)
            after = {
                filename: (data_dir / filename).read_bytes()
                for filename in exporter.ARTIFACT_FILES
            }
            self.assertEqual(before, after)

    def test_check_rejects_stale_artifact_without_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            exporter.build_bundle(self.rows, data_dir)
            target = data_dir / "trade_monthly_overview.csv"
            target.write_bytes(target.read_bytes() + b"\n")
            corrupted = target.read_bytes()
            with self.assertRaises(exporter.DashboardExportError):
                exporter.check_bundle(self.rows, data_dir)
            self.assertEqual(target.read_bytes(), corrupted)

    def test_build_rolls_back_all_artifacts_if_a_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            exporter.build_bundle(self.rows, data_dir)
            original_bytes = {
                filename: (data_dir / filename).read_bytes()
                for filename in exporter.ARTIFACT_FILES
            }

            original_replace = Path.replace
            staged_replace_count = 0

            def fail_third_staged_replace(source: Path, target: Path) -> Path:
                nonlocal staged_replace_count
                if source.parent.name == "staged":
                    staged_replace_count += 1
                    if staged_replace_count == 3:
                        raise OSError("synthetic dashboard replace failure")
                return original_replace(source, target)

            with mock.patch.object(
                Path, "replace", new=fail_third_staged_replace
            ):
                with self.assertRaises(OSError):
                    exporter.build_bundle(self.rows, data_dir)

            self.assertEqual(staged_replace_count, 3)
            self.assertEqual(
                {
                    filename: (data_dir / filename).read_bytes()
                    for filename in exporter.ARTIFACT_FILES
                },
                original_bytes,
            )


if __name__ == "__main__":
    unittest.main()
