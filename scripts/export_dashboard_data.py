#!/usr/bin/env python3
"""Build or verify the public aggregate bundle used by the Streamlit dashboard."""

from __future__ import annotations

import argparse
import csv
import filecmp
import hashlib
import json
import shutil
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_category_seller_trade as trade_analysis  # noqa: E402
import analyze_delivery_review_deepening as delivery_analysis  # noqa: E402
from dashboard.lib import (  # noqa: E402
    DELIVERY_SENSITIVITY_COHORTS,
    DELIVERY_TIMING_GROUPS,
    DashboardDataError,
    FILE_SPECS,
    load_dashboard_data,
)


SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
CSV_FILE_ORDER = tuple(FILE_SPECS)
ARTIFACT_FILES = (*CSV_FILE_ORDER, MANIFEST_FILE)
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "dashboard" / "data"
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env"
SOURCE_CATEGORY_SENTINELS = frozenset(
    {"__missing_source__", "__unmapped_translation__"}
)
DELIVERY_TIMING_LABELS = {
    key: label for key, label, _ in DELIVERY_TIMING_GROUPS
}
SENSITIVITY_LABELS = dict(DELIVERY_SENSITIVITY_COHORTS)
EXPECTED_TOTAL_ORDERS = 95_824
EXPECTED_LATE_ORDERS = 6_381
EXPECTED_WITHOUT_INVERSION_ORDERS = 94_458


class DashboardExportError(RuntimeError):
    """Expected export failure that is safe to display."""


def _canonical_decimal(value: Any, *, nullable: bool = False) -> str:
    if value is None or value is pd.NA:
        if nullable:
            return ""
        raise DashboardExportError("required numeric value is missing")
    try:
        if bool(pd.isna(value)):
            if nullable:
                return ""
            raise DashboardExportError("required numeric value is missing")
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        raise DashboardExportError("boolean value cannot be serialized as a number")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DashboardExportError("numeric value is not a finite decimal") from None
    if not number.is_finite():
        raise DashboardExportError("numeric value is not a finite decimal")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _canonical_integer(value: Any) -> str:
    if isinstance(value, bool):
        raise DashboardExportError("boolean value cannot be serialized as an integer")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DashboardExportError("integer value is invalid") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise DashboardExportError("integer value is invalid")
    return str(int(number))


def _canonical_month(value: Any) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        raise DashboardExportError("purchase month is invalid") from None
    if pd.isna(timestamp) or timestamp.day != 1:
        raise DashboardExportError("purchase month must be a month-start date")
    return timestamp.strftime("%Y-%m")


def _ratio(numerator: int | Decimal, denominator: int | Decimal) -> Decimal | None:
    denominator_decimal = Decimal(denominator)
    if denominator_decimal == 0:
        return None
    return Decimal(numerator) / denominator_decimal


def _mean(total: Decimal, count: int) -> Decimal | None:
    return _ratio(total, count)


def _trade_rows(
    result: trade_analysis.TradeAnalysisResult,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    monthly = result.monthly_overview.sort_values("purchase_month").reset_index(
        drop=True
    )
    monthly_rows = [
        {
            "purchase_month": _canonical_month(row.purchase_month),
            "gross_item_value": _canonical_decimal(row.gross_item_value),
            "freight_amount": _canonical_decimal(row.freight_amount),
            "item_side_amount": _canonical_decimal(row.item_side_amount),
            "ordered_item_row_count": _canonical_integer(
                row.ordered_item_row_count
            ),
            "active_seller_count": _canonical_integer(row.active_seller_count),
        }
        for row in monthly.itertuples(index=False)
    ]

    category = result.category_mix.sort_values(
        ["purchase_month", "group_rank"], kind="mergesort"
    ).reset_index(drop=True)
    observed_keys = set(category["group_key"])
    leaked_sentinels = SOURCE_CATEGORY_SENTINELS.intersection(observed_keys)
    if leaked_sentinels:
        raise DashboardExportError(
            "source category sentinel leaked into the public category groups"
        )
    category_rows = [
        {
            "purchase_month": _canonical_month(row.purchase_month),
            "group_key": str(row.group_key),
            "group_label": str(row.group_label),
            "group_rank": _canonical_integer(row.group_rank),
            "gross_item_value": _canonical_decimal(row.gross_item_value),
            "month_total_gross_item_value": _canonical_decimal(
                row.month_total_gross_item_value
            ),
            "share": _canonical_decimal(row.share),
        }
        for row in category.itertuples(index=False)
    ]

    concentration = result.seller_concentration.sort_values(
        "purchase_month"
    ).reset_index(drop=True)
    concentration_rows = [
        {
            "purchase_month": _canonical_month(row.purchase_month),
            "active_seller_count": _canonical_integer(row.active_seller_count),
            "total_gross_item_value": _canonical_decimal(
                row.total_gross_item_value
            ),
            "top1_seller_count": _canonical_integer(row.top1_seller_count),
            "top1_gross_item_value": _canonical_decimal(
                row.top1_gross_item_value
            ),
            "top1_share": _canonical_decimal(row.top1_share),
            "top10_seller_count": _canonical_integer(row.top10_seller_count),
            "top10_gross_item_value": _canonical_decimal(
                row.top10_gross_item_value
            ),
            "top10_share": _canonical_decimal(row.top10_share),
            "top10_percent_seller_count": _canonical_integer(
                row.top10_percent_seller_count
            ),
            "top10_percent_gross_item_value": _canonical_decimal(
                row.top10_percent_gross_item_value
            ),
            "top10_percent_share": _canonical_decimal(
                row.top10_percent_share
            ),
        }
        for row in concentration.itertuples(index=False)
    ]
    return monthly_rows, category_rows, concentration_rows


def _delivery_rows(
    summary: delivery_analysis.DeepeningSummary,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    group_names = tuple(group.name for group in summary.severity)
    if group_names != delivery_analysis.SEVERITY_ORDER:
        raise DashboardExportError("delivery timing groups are incomplete or unordered")
    timing_rows: list[dict[str, Any]] = []
    for rank, group in enumerate(summary.severity, start=1):
        mean_score = _mean(group.order_review_score_sum, group.order_count)
        low_score_rate = _ratio(group.low_score_order_count, group.order_count)
        timing_rows.append(
            {
                "delivery_timing_group": group.name,
                "group_label": DELIVERY_TIMING_LABELS[group.name],
                "group_rank": _canonical_integer(rank),
                "order_count": _canonical_integer(group.order_count),
                "order_share": _canonical_decimal(
                    _ratio(group.order_count, summary.total_orders)
                ),
                "order_review_score_sum": _canonical_decimal(
                    group.order_review_score_sum
                ),
                "mean_order_review_score": _canonical_decimal(
                    mean_score, nullable=True
                ),
                "median_order_review_score": _canonical_decimal(
                    group.median_review_score, nullable=True
                ),
                "low_score_order_count": _canonical_integer(
                    group.low_score_order_count
                ),
                "low_score_order_rate": _canonical_decimal(
                    low_score_rate, nullable=True
                ),
            }
        )

    monthly_rows: list[dict[str, Any]] = []
    for month in summary.monthly:
        late_mean = _mean(
            month.late_order_review_score_sum, month.late_order_count
        )
        not_late_mean = _mean(
            month.not_late_order_review_score_sum, month.not_late_order_count
        )
        gap = (
            late_mean - not_late_mean
            if late_mean is not None and not_late_mean is not None
            else None
        )
        monthly_rows.append(
            {
                "purchase_month": _canonical_month(month.purchase_month),
                "order_count": _canonical_integer(month.order_count),
                "late_order_count": _canonical_integer(month.late_order_count),
                "not_late_order_count": _canonical_integer(
                    month.not_late_order_count
                ),
                "late_order_review_score_sum": _canonical_decimal(
                    month.late_order_review_score_sum
                ),
                "not_late_order_review_score_sum": _canonical_decimal(
                    month.not_late_order_review_score_sum
                ),
                "late_rate": _canonical_decimal(
                    _ratio(month.late_order_count, month.order_count),
                    nullable=True,
                ),
                "late_mean_order_review_score": _canonical_decimal(
                    late_mean, nullable=True
                ),
                "not_late_mean_order_review_score": _canonical_decimal(
                    not_late_mean, nullable=True
                ),
                "mean_score_gap": _canonical_decimal(gap, nullable=True),
            }
        )

    sensitivity_names = tuple(cohort.name for cohort in summary.sensitivity)
    if sensitivity_names != (
        "all_orders",
        "without_chronology_inversions",
    ):
        raise DashboardExportError("delivery sensitivity cohorts are incomplete")
    sensitivity_rows: list[dict[str, Any]] = []
    for cohort in summary.sensitivity:
        late_mean = _mean(
            cohort.late_order_review_score_sum, cohort.late_order_count
        )
        not_late_mean = _mean(
            cohort.not_late_order_review_score_sum, cohort.not_late_order_count
        )
        gap = (
            late_mean - not_late_mean
            if late_mean is not None and not_late_mean is not None
            else None
        )
        sensitivity_rows.append(
            {
                "cohort": cohort.name,
                "cohort_label": SENSITIVITY_LABELS[cohort.name],
                "order_count": _canonical_integer(cohort.order_count),
                "late_order_count": _canonical_integer(cohort.late_order_count),
                "not_late_order_count": _canonical_integer(
                    cohort.not_late_order_count
                ),
                "late_rate": _canonical_decimal(
                    _ratio(cohort.late_order_count, cohort.order_count),
                    nullable=True,
                ),
                "late_mean_order_review_score": _canonical_decimal(
                    late_mean, nullable=True
                ),
                "not_late_mean_order_review_score": _canonical_decimal(
                    not_late_mean, nullable=True
                ),
                "mean_score_gap": _canonical_decimal(gap, nullable=True),
            }
        )
    return timing_rows, monthly_rows, sensitivity_rows


def public_rows(
    trade_result: trade_analysis.TradeAnalysisResult,
    delivery_summary: delivery_analysis.DeepeningSummary,
) -> dict[str, list[dict[str, Any]]]:
    monthly, category, concentration = _trade_rows(trade_result)
    timing, delivery_monthly, sensitivity = _delivery_rows(delivery_summary)
    rows = {
        "trade_monthly_overview.csv": monthly,
        "category_mix.csv": category,
        "seller_concentration.csv": concentration,
        "delivery_timing_summary.csv": timing,
        "delivery_monthly.csv": delivery_monthly,
        "delivery_sensitivity.csv": sensitivity,
    }
    if tuple(rows) != CSV_FILE_ORDER:
        raise DashboardExportError("dashboard file order differs from the data contract")
    if len(monthly) != 18 or len(category) != 108 or len(concentration) != 18:
        raise DashboardExportError("trade dashboard rows differ from the approved shape")
    if len(timing) != 6 or len(delivery_monthly) != 18 or len(sensitivity) != 2:
        raise DashboardExportError(
            "delivery dashboard rows differ from the approved shape"
        )
    timing_counts = {
        row["delivery_timing_group"]: int(row["order_count"]) for row in timing
    }
    if sum(timing_counts.values()) != EXPECTED_TOTAL_ORDERS:
        raise DashboardExportError("delivery timing rows do not match the final cohort")
    if (
        sum(
            timing_counts[name]
            for name in delivery_analysis.SEVERITY_ORDER
            if name.startswith("late_")
        )
        != EXPECTED_LATE_ORDERS
    ):
        raise DashboardExportError("late delivery groups do not match the approved count")
    sensitivity_counts = {
        row["cohort"]: int(row["order_count"]) for row in sensitivity
    }
    if sensitivity_counts != {
        "all_orders": EXPECTED_TOTAL_ORDERS,
        "without_chronology_inversions": EXPECTED_WITHOUT_INVERSION_ORDERS,
    }:
        raise DashboardExportError(
            "delivery sensitivity rows do not match the approved cohorts"
        )
    return rows


def _write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_columns = set(columns)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            if set(row) != expected_columns:
                raise DashboardExportError(
                    f"{path.name} row columns differ from the contract"
                )
            writer.writerow(dict(row))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key_bound(
    rows: Sequence[Mapping[str, Any]], key_columns: Sequence[str], *, maximum: bool
) -> list[str]:
    keys = [tuple(str(row[column]) for column in key_columns) for row in rows]
    if not keys:
        raise DashboardExportError("dashboard artifact cannot be empty")
    selected = max(keys) if maximum else min(keys)
    return list(selected)


def _manifest(
    directory: Path, rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for filename in CSV_FILE_ORDER:
        path = directory / filename
        rows = rows_by_file[filename]
        spec = FILE_SPECS[filename]
        files[filename] = {
            "byte_count": path.stat().st_size,
            "key_max": _key_bound(rows, spec.key_columns, maximum=True),
            "key_min": _key_bound(rows, spec.key_columns, maximum=False),
            "row_count": len(rows),
            "sha256": _sha256(path),
        }
    return {"files": files, "schema_version": SCHEMA_VERSION}


def write_bundle(
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]], directory: Path
) -> None:
    if tuple(rows_by_file) != CSV_FILE_ORDER:
        raise DashboardExportError("dashboard bundle file set differs from the contract")
    directory.mkdir(parents=True, exist_ok=True)
    for filename in CSV_FILE_ORDER:
        spec = FILE_SPECS[filename]
        _write_csv(directory / filename, spec.columns, rows_by_file[filename])
    manifest = _manifest(directory, rows_by_file)
    manifest_path = directory / MANIFEST_FILE
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    try:
        load_dashboard_data(directory)
    except DashboardDataError as exc:
        raise DashboardExportError(f"generated dashboard bundle is invalid: {exc}") from None


def _existing_entries(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    if not directory.is_dir():
        raise DashboardExportError("dashboard data target is not a directory")
    entries = {path.name for path in directory.iterdir()}
    unexpected = entries.difference(ARTIFACT_FILES)
    if unexpected:
        raise DashboardExportError(
            "dashboard data directory contains unexpected entries: "
            + ", ".join(sorted(unexpected))
        )
    return entries


def build_bundle(
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]], data_dir: Path
) -> None:
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    _existing_entries(data_dir)
    with tempfile.TemporaryDirectory(
        prefix="dashboard-data-build-", dir=data_dir.parent
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        staged = temporary_root / "staged"
        backup = temporary_root / "backup"
        write_bundle(rows_by_file, staged)
        data_dir.mkdir(parents=True, exist_ok=True)
        backup.mkdir(parents=True, exist_ok=True)
        existing = _existing_entries(data_dir)
        for filename in ARTIFACT_FILES:
            if filename in existing:
                shutil.copy2(data_dir / filename, backup / filename)

        replaced: list[str] = []
        try:
            for filename in ARTIFACT_FILES:
                (staged / filename).replace(data_dir / filename)
                replaced.append(filename)
        except OSError:
            for filename in reversed(replaced):
                target = data_dir / filename
                saved = backup / filename
                if saved.is_file():
                    saved.replace(target)
                else:
                    target.unlink(missing_ok=True)
            raise

    try:
        load_dashboard_data(data_dir)
    except DashboardDataError as exc:
        raise DashboardExportError(
            f"committed dashboard bundle is invalid after build: {exc}"
        ) from None


def check_bundle(
    rows_by_file: Mapping[str, Sequence[Mapping[str, Any]]], data_dir: Path
) -> None:
    _existing_entries(data_dir)
    try:
        load_dashboard_data(data_dir)
    except DashboardDataError as exc:
        raise DashboardExportError(f"committed dashboard bundle is invalid: {exc}") from None
    with tempfile.TemporaryDirectory(
        prefix="dashboard-data-check-", dir=data_dir.parent
    ) as temporary_directory:
        staged = Path(temporary_directory) / "staged"
        write_bundle(rows_by_file, staged)
        mismatches = [
            filename
            for filename in ARTIFACT_FILES
            if not (data_dir / filename).is_file()
            or not filecmp.cmp(
                data_dir / filename, staged / filename, shallow=False
            )
        ]
        if mismatches:
            raise DashboardExportError(
                "committed dashboard artifacts are stale or missing: "
                + ", ".join(mismatches)
            )


def load_verified_results() -> tuple[
    trade_analysis.TradeAnalysisResult,
    delivery_analysis.DeepeningSummary,
]:
    trade_config = trade_analysis.DatabaseConfig.from_environment()
    with trade_analysis.connect_database(trade_config) as connection:
        category_frame, seller_frame, baselines = (
            trade_analysis.load_analysis_snapshot(connection)
        )
    category, seller = trade_analysis.validate_analysis_frames(
        category_frame, seller_frame
    )
    trade_result = trade_analysis.summarize_trades(category, seller)
    trade_analysis.reconcile_with_database(
        category, seller, trade_result, baselines
    )
    trade_analysis.validate_expected_snapshot(trade_result)

    delivery_config = delivery_analysis.DatabaseConfig.from_environment()
    with delivery_analysis.connect_database(delivery_config) as connection:
        delivery_frame, delivery_baselines = (
            delivery_analysis.load_analysis_snapshot(connection)
        )
    validated_delivery = delivery_analysis.validate_analysis_frame(delivery_frame)
    delivery_summary = delivery_analysis.summarize_deepening(validated_delivery)
    delivery_analysis.reconcile_with_database(
        delivery_summary, delivery_baselines
    )
    delivery_analysis.validate_expected_snapshot(delivery_summary)
    return trade_result, delivery_summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or check the validated dashboard aggregate bundle"
    )
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="dashboard artifact directory",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="local PostgreSQL environment file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv(args.env_file)
    try:
        trade_result, delivery_summary = load_verified_results()
        rows = public_rows(trade_result, delivery_summary)
        if args.command == "build":
            build_bundle(rows, args.data_dir)
        else:
            check_bundle(rows, args.data_dir)
    except (
        DashboardExportError,
        trade_analysis.CategorySellerAnalysisError,
        delivery_analysis.DeliveryReviewDeepeningError,
        OSError,
    ) as exc:
        print(f"dashboard data export failed: {exc}", file=sys.stderr)
        return 1

    print(
        "dashboard data export passed: "
        f"command={args.command}, files={len(CSV_FILE_ORDER)}, "
        f"months={len(rows['trade_monthly_overview.csv'])}, "
        f"orders={sum(int(row['order_count']) for row in rows['delivery_timing_summary.csv'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
