from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_category_seller_trade as analysis  # noqa: E402


D = Decimal


def synthetic_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build 18 complete synthetic months at the two approved mart grains."""

    category_specs = (
        ("alpha", "Alpha", "mapped", D("30"), 2),
        ("beta", "Beta", "mapped", D("20"), 2),
        ("gamma", "Gamma", "mapped", D("20"), 2),
        ("delta", "Delta", "mapped", D("15"), 1),
        ("epsilon", "Epsilon", "mapped", D("10"), 1),
        ("zeta", "Zeta", "mapped", D("5"), 1),
        ("__missing_source__", "Unknown", "missing_source", D("40"), 1),
        (
            "__unmapped_translation__",
            "Unmapped",
            "unmapped_translation",
            D("25"),
            1,
        ),
    )
    seller_specs = (
        ("seller-secret-a", D("30")),
        ("seller-secret-b", D("30")),
        ("seller-secret-c", D("20")),
        ("seller-secret-d", D("18")),
        ("seller-secret-e", D("16")),
        ("seller-secret-f", D("14")),
        ("seller-secret-g", D("12")),
        ("seller-secret-h", D("10")),
        ("seller-secret-i", D("8")),
        ("seller-secret-j", D("6")),
        ("seller-secret-k", D("1")),
    )

    category_records: list[dict[str, object]] = []
    seller_records: list[dict[str, object]] = []
    for month_index, month in enumerate(analysis.PRIMARY_MONTHS):
        for key, label, status, base_gross, item_rows in category_specs:
            gross = base_gross + (D(month_index) if key == "alpha" else D("0"))
            freight = D(item_rows)
            category_records.append(
                {
                    "purchase_month": month,
                    "category_key": key,
                    "category_display_name": label,
                    "category_mapping_status": status,
                    "gross_item_value": gross,
                    "freight_amount": freight,
                    "item_side_amount": gross + freight,
                    "ordered_item_row_count": item_rows,
                }
            )

        # The first two sellers remain tied in every month. Splitting the monthly
        # increment equally preserves that tie while reconciling to category totals.
        tied_increment = D(month_index) / D("2")
        for seller_id, base_gross in seller_specs:
            gross = base_gross
            if seller_id in {"seller-secret-a", "seller-secret-b"}:
                gross += tied_increment
            seller_records.append(
                {
                    "purchase_month": month,
                    "seller_id": seller_id,
                    "gross_item_value": gross,
                    "freight_amount": D("1"),
                    "item_side_amount": gross + D("1"),
                    "ordered_item_row_count": 1,
                }
            )

    return pd.DataFrame(category_records), pd.DataFrame(seller_records)


def sql_baselines_from_result(
    category: pd.DataFrame,
    seller: pd.DataFrame,
    result: analysis.TradeAnalysisResult,
) -> analysis.SqlBaselines:
    """Create an independent-SQL-shaped baseline from a synthetic fixture."""

    category_monthly = analysis._aggregate_monthly(category)
    seller_monthly = analysis._aggregate_monthly(seller)
    category_rows = category.groupby("purchase_month", sort=True).size()
    seller_rows = seller.groupby("purchase_month", sort=True).size()
    monthly_records = []
    for row_index, month in enumerate(category_monthly["purchase_month"]):
        category_row = category_monthly.iloc[row_index]
        seller_row = seller_monthly.iloc[row_index]
        monthly_records.append(
            {
                "purchase_month": month,
                "category_row_count": int(category_rows.loc[month]),
                "seller_row_count": int(seller_rows.loc[month]),
                "active_seller_count": int(seller_rows.loc[month]),
                "category_gross_item_value": category_row["gross_item_value"],
                "seller_gross_item_value": seller_row["gross_item_value"],
                "category_freight_amount": category_row["freight_amount"],
                "seller_freight_amount": seller_row["freight_amount"],
                "category_item_side_amount": category_row["item_side_amount"],
                "seller_item_side_amount": seller_row["item_side_amount"],
                "category_item_row_count": int(
                    category_row["ordered_item_row_count"]
                ),
                "seller_item_row_count": int(seller_row["ordered_item_row_count"]),
            }
        )

    return analysis.SqlBaselines(
        monthly_totals=pd.DataFrame(monthly_records),
        top_categories=result.top_categories.loc[
            :, ("category_key", "category_display_name", "gross_item_value")
        ].copy(),
        category_mix=result.category_mix.loc[
            :, ("purchase_month", "group_key", "gross_item_value")
        ].copy(),
        seller_concentration=result.seller_concentration.loc[
            :,
            (
                "purchase_month",
                "active_seller_count",
                "total_gross_item_value",
                "top1_gross_item_value",
                "top10_gross_item_value",
                "top10_percent_seller_count",
                "top10_percent_gross_item_value",
            ),
        ].copy(),
        mapping_summary=result.mapping_summary.loc[
            :,
            (
                "category_mapping_status",
                "gross_item_value",
                "ordered_item_row_count",
            ),
        ].copy(),
    )


class CategorySellerTradeAnalysisUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        category_frame, seller_frame = synthetic_frames()
        self.category, self.seller = analysis.validate_analysis_frames(
            category_frame, seller_frame
        )
        self.result = analysis.summarize_trades(self.category, self.seller)

    def test_summary_calculations_and_share_invariants(self) -> None:
        self.assertEqual(tuple(self.result.monthly_overview["purchase_month"]), analysis.PRIMARY_MONTHS)
        self.assertEqual(self.result.category_row_count, 18 * 8)
        self.assertEqual(self.result.seller_row_count, 18 * 11)
        self.assertEqual(self.result.period_gross_item_value, D("3123"))
        self.assertEqual(self.result.period_freight_amount, D("198"))
        self.assertEqual(self.result.period_item_side_amount, D("3321"))
        self.assertEqual(self.result.period_ordered_item_row_count, 198)
        self.assertTrue(self.result.monthly_overview["active_seller_count"].eq(11).all())

        for _, month_rows in self.result.category_mix.groupby("purchase_month"):
            self.assertLessEqual(
                abs(sum(month_rows["share"], D("0")) - D("1")),
                analysis.SHARE_TOLERANCE,
            )
        self.assertLessEqual(
            abs(
                sum(
                    self.result.mapping_summary["gross_item_value_share"], D("0")
                )
                - D("1")
            ),
            analysis.SHARE_TOLERANCE,
        )
        self.assertLessEqual(
            abs(
                sum(
                    self.result.mapping_summary["ordered_item_row_share"], D("0")
                )
                - D("1")
            ),
            analysis.SHARE_TOLERANCE,
        )

        first_month = self.result.monthly_overview.iloc[0]
        last_month = self.result.monthly_overview.iloc[-1]
        self.assertEqual(first_month["gross_item_value"], D("165"))
        self.assertEqual(last_month["gross_item_value"], D("182"))

    def test_top_category_tie_and_exceptional_states_are_deterministic(self) -> None:
        self.assertEqual(
            tuple(self.result.top_categories["category_key"]),
            ("alpha", "beta", "gamma", "delta", "epsilon"),
        )
        self.assertEqual(
            tuple(self.result.top_categories["category_rank"]), (1, 2, 3, 4, 5)
        )
        self.assertNotIn(
            "__missing_source__", set(self.result.top_categories["category_key"])
        )
        self.assertNotIn(
            "__unmapped_translation__",
            set(self.result.top_categories["category_key"]),
        )

        first_month = analysis.PRIMARY_MONTHS[0]
        first_mix = self.result.category_mix.loc[
            self.result.category_mix["purchase_month"].eq(first_month)
        ]
        self.assertEqual(
            tuple(first_mix.sort_values("group_rank")["group_key"]),
            ("alpha", "beta", "gamma", "delta", "epsilon", "__other__"),
        )
        other = first_mix.loc[first_mix["group_key"].eq("__other__")].iloc[0]
        self.assertEqual(other["gross_item_value"], D("70"))
        self.assertEqual(other["group_label"], "Other")

    def test_absent_category_in_observed_month_is_zero_filled(self) -> None:
        missing_month = analysis.PRIMARY_MONTHS[1]
        reduced = self.category.loc[
            ~(
                self.category["purchase_month"].eq(missing_month)
                & self.category["category_key"].eq("epsilon")
            )
        ].copy()
        top_categories = analysis._select_top_categories(reduced)
        overview = analysis._aggregate_monthly(reduced)
        overview["active_seller_count"] = 11
        mix = analysis._build_category_mix(reduced, overview, top_categories)
        epsilon = mix.loc[
            mix["purchase_month"].eq(missing_month)
            & mix["group_key"].eq("epsilon")
        ].iloc[0]
        self.assertEqual(epsilon["gross_item_value"], D("0"))

    def test_seller_concentration_counts_bounds_and_tie_sort(self) -> None:
        first = self.result.seller_concentration.iloc[0]
        self.assertEqual(first["active_seller_count"], 11)
        self.assertEqual(first["top1_seller_count"], 1)
        self.assertEqual(first["top10_seller_count"], 10)
        self.assertEqual(first["top10_percent_seller_count"], 2)
        self.assertEqual(first["top1_gross_item_value"], D("30"))
        self.assertEqual(first["top10_gross_item_value"], D("164"))
        self.assertEqual(first["top10_percent_gross_item_value"], D("60"))
        self.assertLessEqual(first["top1_share"], first["top10_share"])
        self.assertLessEqual(first["top1_share"], first["top10_percent_share"])

        original_sort_values = pd.DataFrame.sort_values
        observed_sorts: list[tuple[object, object]] = []

        def recording_sort_values(frame: pd.DataFrame, by: object, *args: object, **kwargs: object) -> pd.DataFrame:
            observed_sorts.append((by, kwargs.get("ascending")))
            return original_sort_values(frame, by, *args, **kwargs)

        with patch.object(pd.DataFrame, "sort_values", new=recording_sort_values):
            analysis._build_seller_concentration(self.seller)
        self.assertIn(
            (["gross_item_value", "seller_id"], [False, True]), observed_sorts
        )

        small = pd.DataFrame(
            {
                "purchase_month": [analysis.PRIMARY_MONTHS[0]] * 3,
                "seller_id": ["seller-c", "seller-a", "seller-b"],
                "gross_item_value": [D("1"), D("3"), D("2")],
            }
        )
        small_result = analysis._build_seller_concentration(small).iloc[0]
        self.assertEqual(small_result["top10_seller_count"], 3)
        self.assertEqual(small_result["top10_share"], D("1"))
        self.assertEqual(small_result["top10_percent_seller_count"], 1)
        self.assertEqual(small_result["top10_percent_gross_item_value"], D("3"))

    def test_change_contribution_reconciles_and_detects_drift(self) -> None:
        first_contributions = self.result.category_mix.loc[
            self.result.category_mix["purchase_month"].eq(analysis.PRIMARY_MONTHS[0]),
            "change_contribution",
        ]
        self.assertTrue(first_contributions.isna().all())

        for month in analysis.PRIMARY_MONTHS[1:]:
            month_rows = self.result.category_mix.loc[
                self.result.category_mix["purchase_month"].eq(month)
            ]
            self.assertEqual(sum(month_rows["change_contribution"], D("0")), D("1"))
            alpha_change = month_rows.loc[
                month_rows["group_key"].eq("alpha"), "change_contribution"
            ].iloc[0]
            self.assertEqual(alpha_change, D("1"))

        drifted = self.result.category_mix.copy()
        drift_index = drifted.index[
            drifted["purchase_month"].eq(analysis.PRIMARY_MONTHS[1])
            & drifted["group_key"].eq("alpha")
        ][0]
        drifted.at[drift_index, "change_contribution"] += D("0.01")
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis._validate_change_decomposition(
                self.result.monthly_overview, drifted
            )

        gap = pd.DataFrame(
            {
                "purchase_month": pd.to_datetime(
                    ["2017-01-01", "2017-03-01", "2017-04-01"]
                ),
                "group_key": ["alpha", "alpha", "alpha"],
                "gross_item_value": [D("10"), D("30"), D("35")],
            }
        )
        with_changes = analysis.add_change_contributions(gap)
        self.assertTrue(pd.isna(with_changes.loc[0, "change_contribution"]))
        self.assertTrue(pd.isna(with_changes.loc[1, "change_contribution"]))
        self.assertEqual(with_changes.loc[2, "change_contribution"], D("5"))

    def test_sql_shaped_baselines_reconcile_exactly_and_detect_drift(self) -> None:
        baselines = sql_baselines_from_result(
            self.category, self.seller, self.result
        )
        analysis.reconcile_with_database(
            self.category, self.seller, self.result, baselines
        )

        drifted_monthly = copy.deepcopy(baselines.monthly_totals)
        drifted_monthly.loc[0, "category_gross_item_value"] += D("0.01")
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis.reconcile_with_database(
                self.category,
                self.seller,
                self.result,
                replace(baselines, monthly_totals=drifted_monthly),
            )

        shifted_months = copy.deepcopy(baselines.monthly_totals)
        shifted_months["purchase_month"] = (
            pd.to_datetime(shifted_months["purchase_month"])
            + pd.offsets.MonthBegin(1)
        )
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis.reconcile_with_database(
                self.category,
                self.seller,
                self.result,
                replace(baselines, monthly_totals=shifted_months),
            )

        drifted_seller = self.seller.copy()
        drifted_seller.loc[0, "gross_item_value"] += D("0.01")
        drifted_seller.loc[0, "item_side_amount"] += D("0.01")
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis.summarize_trades(self.category, drifted_seller)

    def test_share_tolerance_is_only_for_float_representation(self) -> None:
        analysis._assert_share_sum(
            [D("0.5"), D("0.5000000000001")], "within tolerance"
        )
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis._assert_share_sum(
                [D("0.5"), D("0.50000000001")], "outside tolerance"
            )

    def test_report_is_deterministic_private_aggregate_only_and_noncausal(self) -> None:
        first = analysis.render_report(self.result)
        second = analysis.render_report(self.result)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        for secret in (
            "seller-secret-",
            "__missing_source__",
            "__unmapped_translation__",
            "/Users/",
            "PGPASSWORD",
            "synthetic-order",
            "zip_code",
        ):
            self.assertNotIn(secret, first)
        self.assertIn("회사 매출·순매출·이익이 아니다", first)
        self.assertIn("변화의 원인을 증명하는 기여도가 아니라", first)
        self.assertIn("실제 사업 위험이나 개선 성과를 증명하지 않는다", first)
        self.assertIn("판매자 식별자와 상세 위치를 포함하지 않았다", first)

    def test_figures_use_contract_axes_series_and_group_order(self) -> None:
        overview = analysis.create_monthly_overview_figure(self.result)
        self.assertEqual(len(overview.axes), 2)
        self.assertEqual(overview.axes[0].get_ylim()[0], 0.0)
        self.assertEqual(overview.axes[1].get_ylim()[0], 0.0)
        self.assertEqual(len(overview.axes[0].patches), 18)
        self.assertEqual(len(overview.axes[1].lines[0].get_xdata()), 18)

        category_mix = analysis.create_category_mix_figure(self.result)
        category_axis = category_mix.axes[0]
        self.assertEqual(category_axis.get_ylim(), (0.0, 100.0))
        self.assertEqual(
            tuple(text.get_text() for text in category_axis.get_legend().get_texts()),
            ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Other"),
        )

        concentration = analysis.create_seller_concentration_figure(self.result)
        concentration_axis = concentration.axes[0]
        self.assertEqual(concentration_axis.get_ylim(), (0.0, 100.0))
        self.assertEqual(
            tuple(line.get_label() for line in concentration_axis.lines),
            ("Top 1", "Top 10", "Top 10%"),
        )
        for line in concentration_axis.lines:
            self.assertEqual(
                tuple(pd.to_datetime(line.get_xdata())), analysis.PRIMARY_MONTHS
            )

        analysis.plt.close(overview)
        analysis.plt.close(category_mix)
        analysis.plt.close(concentration)

    def test_artifacts_are_reproducible_and_stale_check_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reports_dir = Path(temporary_directory) / "reports"
            analysis.write_artifacts(self.result, reports_dir)
            first = {
                relative_path: (reports_dir / relative_path).read_bytes()
                for relative_path in analysis.ARTIFACT_FILES
            }
            analysis.write_artifacts(self.result, reports_dir)
            second = {
                relative_path: (reports_dir / relative_path).read_bytes()
                for relative_path in analysis.ARTIFACT_FILES
            }
            self.assertEqual(first, second)
            for figure_path in (
                analysis.OVERVIEW_FIGURE,
                analysis.CATEGORY_FIGURE,
                analysis.CONCENTRATION_FIGURE,
            ):
                self.assertTrue(first[figure_path].startswith(b"\x89PNG"))

            analysis.check_artifacts(self.result, reports_dir)
            report_path = reports_dir / analysis.REPORT_FILE
            report_path.write_text("stale report\n", encoding="utf-8")
            stale_bytes = report_path.read_bytes()
            with self.assertRaises(analysis.CategorySellerAnalysisError):
                analysis.check_artifacts(self.result, reports_dir)
            self.assertEqual(report_path.read_bytes(), stale_bytes)

    def test_invalid_input_contracts_fail_closed(self) -> None:
        raw_category, raw_seller = synthetic_frames()
        mutations: list[tuple[pd.DataFrame, pd.DataFrame]] = []

        missing_column = raw_category.drop(columns="gross_item_value")
        mutations.append((missing_column, raw_seller))

        null_value = raw_category.copy()
        null_value.loc[0, "category_display_name"] = None
        mutations.append((null_value, raw_seller))

        duplicate = pd.concat([raw_category, raw_category.iloc[[0]]], ignore_index=True)
        mutations.append((duplicate, raw_seller))

        invalid_status = raw_category.copy()
        invalid_status.loc[0, "category_mapping_status"] = "invented"
        mutations.append((invalid_status, raw_seller))

        missing_status = raw_category.loc[
            ~raw_category["category_mapping_status"].eq("unmapped_translation")
        ].copy()
        mutations.append((missing_status, raw_seller))

        inconsistent_identity = raw_category.copy()
        beta_rows = inconsistent_identity.index[
            inconsistent_identity["category_key"].eq("beta")
        ]
        inconsistent_identity.loc[beta_rows[1], "category_display_name"] = "Beta 2"
        mutations.append((inconsistent_identity, raw_seller))

        non_month_start = raw_category.copy()
        non_month_start.loc[0, "purchase_month"] = pd.Timestamp("2017-02-02")
        mutations.append((non_month_start, raw_seller))

        non_numeric = raw_category.copy()
        non_numeric.loc[0, "gross_item_value"] = "not-a-number"
        mutations.append((non_numeric, raw_seller))

        negative_freight = raw_category.copy()
        negative_freight.loc[0, "freight_amount"] = D("-1")
        mutations.append((negative_freight, raw_seller))

        bad_item_side = raw_category.copy()
        bad_item_side.loc[0, "item_side_amount"] += D("1")
        mutations.append((bad_item_side, raw_seller))

        zero_rows = raw_category.copy()
        zero_rows.loc[0, "ordered_item_row_count"] = 0
        mutations.append((zero_rows, raw_seller))

        different_months = raw_seller.loc[
            ~raw_seller["purchase_month"].eq(analysis.PRIMARY_MONTHS[-1])
        ].copy()
        mutations.append((raw_category, different_months))

        both_missing_month = (
            raw_category.loc[
                ~raw_category["purchase_month"].eq(analysis.PRIMARY_MONTHS[-1])
            ].copy(),
            raw_seller.loc[
                ~raw_seller["purchase_month"].eq(analysis.PRIMARY_MONTHS[-1])
            ].copy(),
        )
        mutations.append(both_missing_month)

        for mutation_index, (category, seller) in enumerate(mutations):
            with self.subTest(mutation=mutation_index):
                with self.assertRaises(analysis.CategorySellerAnalysisError):
                    analysis.validate_analysis_frames(category, seller)

    def test_invalid_analysis_states_fail_closed(self) -> None:
        four_categories = self.category.loc[
            self.category["category_key"].isin(
                ("alpha", "beta", "gamma", "delta")
            )
        ]
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis._select_top_categories(four_categories)

        zero_overview = self.result.monthly_overview.copy()
        zero_overview.loc[0, "gross_item_value"] = D("0")
        with self.assertRaises(analysis.CategorySellerAnalysisError):
            analysis._build_category_mix(
                analysis._primary_slice(self.category),
                zero_overview,
                self.result.top_categories,
            )


if __name__ == "__main__":
    unittest.main()
