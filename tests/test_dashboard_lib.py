from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from dashboard.lib import (
    APPROVED_MONTH_STRINGS,
    CATEGORY_GROUPS,
    DELIVERY_SENSITIVITY_COHORTS,
    DELIVERY_TIMING_GROUPS,
    FILE_SPECS,
    DashboardDataError,
    compute_delivery_kpis,
    compute_trade_kpis,
    filter_months,
    load_dashboard_data,
)


def _decimal_ratio(numerator: int, denominator: int) -> str:
    return str(Decimal(numerator) / Decimal(denominator))


def _fixture_tables() -> dict[str, list[dict[str, Any]]]:
    trade_rows: list[dict[str, Any]] = []
    category_rows: list[dict[str, Any]] = []
    seller_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []

    for month in APPROVED_MONTH_STRINGS:
        trade_rows.append(
            {
                "purchase_month": month,
                "gross_item_value": "600",
                "freight_amount": "60",
                "item_side_amount": "660",
                "ordered_item_row_count": "60",
                "active_seller_count": "20",
            }
        )
        for group_key, group_label, group_rank in CATEGORY_GROUPS:
            category_rows.append(
                {
                    "purchase_month": month,
                    "group_key": group_key,
                    "group_label": group_label,
                    "group_rank": str(group_rank),
                    "gross_item_value": "100",
                    "month_total_gross_item_value": "600",
                    "share": _decimal_ratio(1, 6),
                }
            )
        seller_rows.append(
            {
                "purchase_month": month,
                "active_seller_count": "20",
                "total_gross_item_value": "600",
                "top1_seller_count": "1",
                "top1_gross_item_value": "60",
                "top1_share": "0.1",
                "top10_seller_count": "10",
                "top10_gross_item_value": "400",
                "top10_share": _decimal_ratio(2, 3),
                "top10_percent_seller_count": "2",
                "top10_percent_gross_item_value": "120",
                "top10_percent_share": "0.2",
            }
        )
        order_count = 100
        late_count = 10
        not_late_count = order_count - late_count
        monthly_rows.append(
            {
                "purchase_month": month,
                "order_count": str(order_count),
                "late_order_count": str(late_count),
                "not_late_order_count": str(not_late_count),
                "late_order_review_score_sum": str(late_count * 2),
                "not_late_order_review_score_sum": str(not_late_count * 4),
                "late_rate": _decimal_ratio(late_count, order_count),
                "late_mean_order_review_score": "2",
                "not_late_mean_order_review_score": "4",
                "mean_score_gap": "-2",
            }
        )

    timing_counts = (80_000, 9_443, 2_000, 1_600, 1_500, 1_281)
    timing_means = (4, 4, 3, 2, 2, 1)
    timing_rows: list[dict[str, Any]] = []
    for (group_key, group_label, group_rank), count, mean in zip(
        DELIVERY_TIMING_GROUPS, timing_counts, timing_means, strict=True
    ):
        low_count = count // 10
        timing_rows.append(
            {
                "delivery_timing_group": group_key,
                "group_label": group_label,
                "group_rank": str(group_rank),
                "order_count": str(count),
                "order_share": _decimal_ratio(count, 95_824),
                "order_review_score_sum": str(count * mean),
                "mean_order_review_score": str(mean),
                "median_order_review_score": str(mean),
                "low_score_order_count": str(low_count),
                "low_score_order_rate": _decimal_ratio(low_count, count),
            }
        )

    late_score_sum = sum(
        count * mean for count, mean in zip(timing_counts[2:], timing_means[2:])
    )
    not_late_score_sum = sum(
        count * mean for count, mean in zip(timing_counts[:2], timing_means[:2])
    )
    all_late_mean = Decimal(late_score_sum) / Decimal(6_381)
    all_not_late_mean = Decimal(not_late_score_sum) / Decimal(89_443)
    sensitivity_rows = [
        {
            "cohort": DELIVERY_SENSITIVITY_COHORTS[0][0],
            "cohort_label": DELIVERY_SENSITIVITY_COHORTS[0][1],
            "order_count": "95824",
            "late_order_count": "6381",
            "not_late_order_count": "89443",
            "late_rate": _decimal_ratio(6_381, 95_824),
            "late_mean_order_review_score": str(all_late_mean),
            "not_late_mean_order_review_score": str(all_not_late_mean),
            "mean_score_gap": str(all_late_mean - all_not_late_mean),
        },
        {
            "cohort": DELIVERY_SENSITIVITY_COHORTS[1][0],
            "cohort_label": DELIVERY_SENSITIVITY_COHORTS[1][1],
            "order_count": "94458",
            "late_order_count": "6357",
            "not_late_order_count": "88101",
            "late_rate": _decimal_ratio(6_357, 94_458),
            "late_mean_order_review_score": "2.2",
            "not_late_mean_order_review_score": "4.0",
            "mean_score_gap": "-1.8",
        },
    ]

    return {
        "trade_monthly_overview.csv": trade_rows,
        "category_mix.csv": category_rows,
        "seller_concentration.csv": seller_rows,
        "delivery_timing_summary.csv": timing_rows,
        "delivery_monthly.csv": monthly_rows,
        "delivery_sensitivity.csv": sensitivity_rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    spec = FILE_SPECS[path.name]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=spec.columns, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _raw_key_range(
    rows: list[dict[str, Any]], filename: str
) -> tuple[list[str], list[str]]:
    keys = [
        tuple(str(row[column]) for column in FILE_SPECS[filename].key_columns)
        for row in rows
    ]
    return list(min(keys)), list(max(keys))


def _write_manifest(
    data_dir: Path, tables: dict[str, list[dict[str, Any]]]
) -> None:
    files: dict[str, Any] = {}
    for filename, rows in tables.items():
        raw = (data_dir / filename).read_bytes()
        key_min, key_max = _raw_key_range(rows, filename)
        files[filename] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "row_count": len(rows),
            "key_min": key_min,
            "key_max": key_max,
        }
    (data_dir / "manifest.json").write_text(
        json.dumps(
            {"schema_version": 1, "files": files},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _build_bundle(tmp_path: Path) -> tuple[Path, dict[str, list[dict[str, Any]]]]:
    data_dir = tmp_path / "dashboard-data"
    data_dir.mkdir()
    tables = _fixture_tables()
    for filename, rows in tables.items():
        _write_csv(data_dir / filename, rows)
    _write_manifest(data_dir, tables)
    return data_dir, tables


def _rewrite_table(
    data_dir: Path,
    tables: dict[str, list[dict[str, Any]]],
    filename: str,
) -> None:
    _write_csv(data_dir / filename, tables[filename])
    _write_manifest(data_dir, tables)


class DashboardLibTest(unittest.TestCase):
    def _build_bundle(
        self,
    ) -> tuple[Path, dict[str, list[dict[str, Any]]]]:
        tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        return _build_bundle(tmp_path)

    def test_load_dashboard_data_validates_and_types_all_six_files(self) -> None:
        data_dir, _ = self._build_bundle()

        data = load_dashboard_data(data_dir)

        self.assertEqual(len(data.trade_monthly_overview), 18)
        self.assertEqual(len(data.category_mix), 108)
        self.assertEqual(len(data.seller_concentration), 18)
        self.assertEqual(len(data.delivery_timing_summary), 6)
        self.assertEqual(len(data.delivery_monthly), 18)
        self.assertEqual(len(data.delivery_sensitivity), 2)
        self.assertTrue(
            pd.api.types.is_datetime64_any_dtype(
                data.trade_monthly_overview["purchase_month"]
            )
        )
        self.assertIsInstance(
            data.trade_monthly_overview.at[0, "gross_item_value"], Decimal
        )
        self.assertEqual(data.manifest["schema_version"], 1)

    def test_loader_fails_closed_when_required_file_is_missing(self) -> None:
        for filename in (
            "trade_monthly_overview.csv",
            "delivery_sensitivity.csv",
        ):
            with self.subTest(filename=filename):
                data_dir, _ = self._build_bundle()
                (data_dir / filename).unlink()

                with self.assertRaisesRegex(DashboardDataError, "missing"):
                    load_dashboard_data(data_dir)

    def test_loader_rejects_checksum_drift_before_parsing(self) -> None:
        data_dir, _ = self._build_bundle()
        path = data_dir / "trade_monthly_overview.csv"
        path.write_bytes(path.read_bytes() + b"\n")

        with self.assertRaisesRegex(
            DashboardDataError, "byte-count|checksum"
        ):
            load_dashboard_data(data_dir)

    def test_loader_rejects_unexpected_manifest_fields(self) -> None:
        data_dir, _ = self._build_bundle()
        path = data_dir / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["generated_at"] = "synthetic-time"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(DashboardDataError, "top-level schema"):
            load_dashboard_data(data_dir)

    def test_loader_rejects_schema_and_duplicate_keys(self) -> None:
        data_dir, tables = self._build_bundle()
        tables["trade_monthly_overview.csv"][1]["purchase_month"] = (
            tables["trade_monthly_overview.csv"][0]["purchase_month"]
        )
        _rewrite_table(data_dir, tables, "trade_monthly_overview.csv")

        with self.assertRaisesRegex(DashboardDataError, "duplicate key"):
            load_dashboard_data(data_dir)

    def test_loader_rejects_unapproved_month_even_with_matching_manifest(
        self,
    ) -> None:
        data_dir, tables = self._build_bundle()
        tables["delivery_monthly.csv"][0]["purchase_month"] = "2017-01"
        _rewrite_table(data_dir, tables, "delivery_monthly.csv")

        with self.assertRaisesRegex(
            DashboardDataError, "approved 18 months"
        ):
            load_dashboard_data(data_dir)

    def test_loader_rejects_category_share_that_changes_the_full_month_denominator(
        self,
    ) -> None:
        data_dir, tables = self._build_bundle()
        tables["category_mix.csv"][0]["share"] = "0.2"
        _rewrite_table(data_dir, tables, "category_mix.csv")

        with self.assertRaisesRegex(
            DashboardDataError, "full-month denominator"
        ):
            load_dashboard_data(data_dir)

    def test_loader_rejects_cross_file_trade_mismatch(self) -> None:
        data_dir, tables = self._build_bundle()
        row = tables["trade_monthly_overview.csv"][0]
        row["gross_item_value"] = "601"
        row["item_side_amount"] = "661"
        _rewrite_table(data_dir, tables, "trade_monthly_overview.csv")

        with self.assertRaisesRegex(DashboardDataError, "category and trade"):
            load_dashboard_data(data_dir)

    def test_filter_months_is_inclusive_sorted_and_does_not_mutate_input(
        self,
    ) -> None:
        frame = pd.DataFrame(
            {
                "purchase_month": pd.to_datetime(
                    ["2017-04-01", "2017-02-01", "2017-03-01"]
                ),
                "value": [3, 1, 2],
            }
        )
        original = frame.copy(deep=True)

        result = filter_months(frame, "2017-02", "2017-03")

        self.assertEqual(
            result["purchase_month"].dt.strftime("%Y-%m").tolist(),
            ["2017-02", "2017-03"],
        )
        self.assertEqual(result["value"].tolist(), [1, 2])
        pd.testing.assert_frame_equal(frame, original)

    def test_filter_months_rejects_reverse_or_unapproved_periods(self) -> None:
        frame = pd.DataFrame(
            {"purchase_month": pd.to_datetime(["2017-02-01"]), "value": [1]}
        )
        with self.assertRaisesRegex(DashboardDataError, "start month"):
            filter_months(frame, "2017-03", "2017-02")
        with self.assertRaisesRegex(DashboardDataError, "outside"):
            filter_months(frame, "2017-01", "2017-02")

    def test_compute_trade_kpis_sums_additive_values_and_uses_last_month_sellers(
        self,
    ) -> None:
        frame = pd.DataFrame(
            {
                "purchase_month": pd.to_datetime(
                    ["2017-02-01", "2017-03-01"]
                ),
                "gross_item_value": [Decimal("10.5"), Decimal("20.5")],
                "freight_amount": [Decimal("1"), Decimal("2")],
                "ordered_item_row_count": [2, 3],
                "active_seller_count": [7, 9],
            }
        )

        result = compute_trade_kpis(frame)

        self.assertEqual(result.gross_item_value, Decimal("31.0"))
        self.assertEqual(result.freight_amount, Decimal("3"))
        self.assertEqual(result.ordered_item_row_count, 5)
        self.assertEqual(result.active_seller_count, 9)

    def test_compute_delivery_kpis_recomputes_weighted_results_from_raw_sums(
        self,
    ) -> None:
        frame = pd.DataFrame(
            {
                "order_count": [20, 100],
                "late_order_count": [10, 20],
                "not_late_order_count": [10, 80],
                "late_order_review_score_sum": [
                    Decimal("10"),
                    Decimal("100"),
                ],
                "not_late_order_review_score_sum": [
                    Decimal("50"),
                    Decimal("240"),
                ],
                # Deliberately wrong display means: the helper must not average them.
                "late_mean_order_review_score": [
                    Decimal("5"),
                    Decimal("5"),
                ],
                "not_late_mean_order_review_score": [
                    Decimal("1"),
                    Decimal("1"),
                ],
            }
        )

        result = compute_delivery_kpis(frame)

        self.assertEqual(result.order_count, 120)
        self.assertEqual(result.late_rate, Decimal(30) / Decimal(120))
        self.assertEqual(
            result.late_mean_order_review_score,
            Decimal(110) / Decimal(30),
        )
        self.assertEqual(
            result.not_late_mean_order_review_score,
            Decimal(290) / Decimal(90),
        )
        self.assertEqual(
            result.mean_score_gap,
            Decimal(110) / Decimal(30) - Decimal(290) / Decimal(90),
        )

    def test_compute_delivery_kpis_returns_none_for_undefined_denominators(
        self,
    ) -> None:
        cases = (
            (10, 0, 10, Decimal("0")),
            (0, 0, 0, None),
        )
        for order_count, late_count, not_late_count, expected_rate in cases:
            with self.subTest(
                order_count=order_count,
                late_count=late_count,
                not_late_count=not_late_count,
            ):
                frame = pd.DataFrame(
                    {
                        "order_count": [order_count],
                        "late_order_count": [late_count],
                        "not_late_order_count": [not_late_count],
                        "late_order_review_score_sum": [Decimal("0")],
                        "not_late_order_review_score_sum": [
                            Decimal(not_late_count * 4)
                        ],
                    }
                )

                result = compute_delivery_kpis(frame)

                self.assertEqual(result.late_rate, expected_rate)
                self.assertIsNone(result.late_mean_order_review_score)
                self.assertIsNone(result.mean_score_gap)
                if not_late_count:
                    self.assertEqual(
                        result.not_late_mean_order_review_score,
                        Decimal("4"),
                    )
                else:
                    self.assertIsNone(result.not_late_mean_order_review_score)


if __name__ == "__main__":
    unittest.main()
