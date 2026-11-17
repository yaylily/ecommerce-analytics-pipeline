"""Validated, side-effect-free inputs and KPI calculations for the dashboard.

The dashboard deliberately consumes only aggregate CSV files.  This module owns
the boundary between those files and the presentation layer: no partial data is
returned unless the manifest, every file, and the cross-file reconciliations all
pass.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


SCHEMA_VERSION = 1
SHARE_TOLERANCE = Decimal("1e-12")
APPROVED_MONTHS = tuple(pd.date_range("2017-02-01", "2018-07-01", freq="MS"))
APPROVED_MONTH_STRINGS = tuple(month.strftime("%Y-%m") for month in APPROVED_MONTHS)

CATEGORY_GROUPS = (
    ("beleza_saude", "health_beauty", 1),
    ("relogios_presentes", "watches_gifts", 2),
    ("cama_mesa_banho", "bed_bath_table", 3),
    ("esporte_lazer", "sports_leisure", 4),
    ("informatica_acessorios", "computers_accessories", 5),
    ("__other__", "Other", 6),
)
FORBIDDEN_CATEGORY_KEYS = frozenset(
    {"__missing_source__", "__unmapped_translation__"}
)

DELIVERY_TIMING_GROUPS = (
    ("early", "예정일 이전", 1),
    ("promised_date", "예정일 당일", 2),
    ("late_1_3", "1~3일 지연", 3),
    ("late_4_7", "4~7일 지연", 4),
    ("late_8_14", "8~14일 지연", 5),
    ("late_15_plus", "15일 이상 지연", 6),
)
LATE_DELIVERY_GROUPS = frozenset(
    {"late_1_3", "late_4_7", "late_8_14", "late_15_plus"}
)

DELIVERY_SENSITIVITY_COHORTS = (
    ("all_orders", "전체 주문"),
    ("without_chronology_inversions", "시간 순서 역전 제외"),
)


class DashboardDataError(RuntimeError):
    """A safe, expected validation error suitable for fail-closed display."""


@dataclass(frozen=True)
class FileSpec:
    """One aggregate CSV's immutable public schema and validation metadata."""

    columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    row_count: int
    integer_columns: tuple[str, ...] = ()
    decimal_columns: tuple[str, ...] = ()
    month_columns: tuple[str, ...] = ()
    text_columns: tuple[str, ...] = ()


FILE_SPECS: dict[str, FileSpec] = {
    "trade_monthly_overview.csv": FileSpec(
        columns=(
            "purchase_month",
            "gross_item_value",
            "freight_amount",
            "item_side_amount",
            "ordered_item_row_count",
            "active_seller_count",
        ),
        key_columns=("purchase_month",),
        row_count=18,
        integer_columns=("ordered_item_row_count", "active_seller_count"),
        decimal_columns=(
            "gross_item_value",
            "freight_amount",
            "item_side_amount",
        ),
        month_columns=("purchase_month",),
    ),
    "category_mix.csv": FileSpec(
        columns=(
            "purchase_month",
            "group_key",
            "group_label",
            "group_rank",
            "gross_item_value",
            "month_total_gross_item_value",
            "share",
        ),
        key_columns=("purchase_month", "group_key"),
        row_count=108,
        integer_columns=("group_rank",),
        decimal_columns=(
            "gross_item_value",
            "month_total_gross_item_value",
            "share",
        ),
        month_columns=("purchase_month",),
        text_columns=("group_key", "group_label"),
    ),
    "seller_concentration.csv": FileSpec(
        columns=(
            "purchase_month",
            "active_seller_count",
            "total_gross_item_value",
            "top1_seller_count",
            "top1_gross_item_value",
            "top1_share",
            "top10_seller_count",
            "top10_gross_item_value",
            "top10_share",
            "top10_percent_seller_count",
            "top10_percent_gross_item_value",
            "top10_percent_share",
        ),
        key_columns=("purchase_month",),
        row_count=18,
        integer_columns=(
            "active_seller_count",
            "top1_seller_count",
            "top10_seller_count",
            "top10_percent_seller_count",
        ),
        decimal_columns=(
            "total_gross_item_value",
            "top1_gross_item_value",
            "top1_share",
            "top10_gross_item_value",
            "top10_share",
            "top10_percent_gross_item_value",
            "top10_percent_share",
        ),
        month_columns=("purchase_month",),
    ),
    "delivery_timing_summary.csv": FileSpec(
        columns=(
            "delivery_timing_group",
            "group_label",
            "group_rank",
            "order_count",
            "order_share",
            "order_review_score_sum",
            "mean_order_review_score",
            "median_order_review_score",
            "low_score_order_count",
            "low_score_order_rate",
        ),
        key_columns=("delivery_timing_group",),
        row_count=6,
        integer_columns=("group_rank", "order_count", "low_score_order_count"),
        decimal_columns=(
            "order_share",
            "order_review_score_sum",
            "mean_order_review_score",
            "median_order_review_score",
            "low_score_order_rate",
        ),
        text_columns=("delivery_timing_group", "group_label"),
    ),
    "delivery_monthly.csv": FileSpec(
        columns=(
            "purchase_month",
            "order_count",
            "late_order_count",
            "not_late_order_count",
            "late_order_review_score_sum",
            "not_late_order_review_score_sum",
            "late_rate",
            "late_mean_order_review_score",
            "not_late_mean_order_review_score",
            "mean_score_gap",
        ),
        key_columns=("purchase_month",),
        row_count=18,
        integer_columns=(
            "order_count",
            "late_order_count",
            "not_late_order_count",
        ),
        decimal_columns=(
            "late_order_review_score_sum",
            "not_late_order_review_score_sum",
            "late_rate",
            "late_mean_order_review_score",
            "not_late_mean_order_review_score",
            "mean_score_gap",
        ),
        month_columns=("purchase_month",),
    ),
    "delivery_sensitivity.csv": FileSpec(
        columns=(
            "cohort",
            "cohort_label",
            "order_count",
            "late_order_count",
            "not_late_order_count",
            "late_rate",
            "late_mean_order_review_score",
            "not_late_mean_order_review_score",
            "mean_score_gap",
        ),
        key_columns=("cohort",),
        row_count=2,
        integer_columns=(
            "order_count",
            "late_order_count",
            "not_late_order_count",
        ),
        decimal_columns=(
            "late_rate",
            "late_mean_order_review_score",
            "not_late_mean_order_review_score",
            "mean_score_gap",
        ),
        text_columns=("cohort", "cohort_label"),
    ),
}


@dataclass(frozen=True)
class DashboardData:
    trade_monthly_overview: pd.DataFrame
    category_mix: pd.DataFrame
    seller_concentration: pd.DataFrame
    delivery_timing_summary: pd.DataFrame
    delivery_monthly: pd.DataFrame
    delivery_sensitivity: pd.DataFrame
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class TradeKpis:
    gross_item_value: Decimal
    freight_amount: Decimal
    ordered_item_row_count: int
    active_seller_count: int


@dataclass(frozen=True)
class DeliveryKpis:
    order_count: int
    late_order_count: int
    not_late_order_count: int
    late_rate: Decimal | None
    late_mean_order_review_score: Decimal | None
    not_late_mean_order_review_score: Decimal | None
    mean_score_gap: Decimal | None


def _fail(message: str) -> None:
    raise DashboardDataError(message)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _decimal_close(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= SHARE_TOLERANCE


def _sum_decimal(values: pd.Series) -> Decimal:
    return sum(values, Decimal("0"))


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("manifest.json contains a duplicate JSON key")
        result[key] = value
    return result


def _load_manifest(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "manifest.json"
    if not path.is_file():
        _fail("manifest.json is missing")
    try:
        payload = path.read_text(encoding="utf-8")
        manifest = json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("manifest.json is unreadable or invalid JSON")

    if not isinstance(manifest, dict):
        _fail("manifest.json must contain one JSON object")
    if set(manifest) != {"schema_version", "files"}:
        _fail("manifest.json has an unexpected top-level schema")
    if not _is_int(manifest["schema_version"]) or manifest["schema_version"] != SCHEMA_VERSION:
        _fail("manifest.json has an unsupported schema version")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(FILE_SPECS):
        _fail("manifest.json does not list the exact required aggregate files")

    required_entry_fields = {
        "sha256",
        "byte_count",
        "row_count",
        "key_min",
        "key_max",
    }
    for filename, spec in FILE_SPECS.items():
        entry = files[filename]
        if not isinstance(entry, dict) or set(entry) != required_entry_fields:
            _fail(f"manifest entry for {filename} has an unexpected schema")
        digest = entry["sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            _fail(f"manifest entry for {filename} has an invalid SHA-256")
        if not _is_int(entry["byte_count"]) or entry["byte_count"] <= 0:
            _fail(f"manifest entry for {filename} has an invalid byte count")
        if not _is_int(entry["row_count"]) or entry["row_count"] != spec.row_count:
            _fail(f"manifest entry for {filename} has an invalid row count")
        for field in ("key_min", "key_max"):
            value = entry[field]
            if not isinstance(value, list) or len(value) != len(spec.key_columns):
                _fail(f"manifest entry for {filename} has an invalid key range")
            if any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in value):
                _fail(f"manifest entry for {filename} has an invalid key range")
    return manifest


def _parse_integer(value: str, filename: str) -> int:
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None:
        _fail(f"{filename} contains a non-integer value")
    return int(value)


def _parse_decimal(value: str, filename: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail(f"{filename} contains a non-numeric value")
    if not parsed.is_finite():
        _fail(f"{filename} contains a non-finite numeric value")
    return parsed


def _parse_csv_month(value: str, filename: str) -> pd.Timestamp:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
        _fail(f"{filename} contains an invalid purchase month")
    try:
        parsed = pd.Timestamp(f"{value}-01")
    except (TypeError, ValueError):
        _fail(f"{filename} contains an invalid purchase month")
    if parsed.strftime("%Y-%m") != value:
        _fail(f"{filename} contains an invalid purchase month")
    return parsed


def _manifest_scalar(value: object) -> str | int:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value)


def _manifest_key_range(
    frame: pd.DataFrame, spec: FileSpec
) -> tuple[list[str | int], list[str | int]]:
    keys = [
        tuple(_manifest_scalar(row[column]) for column in spec.key_columns)
        for row in frame.to_dict(orient="records")
    ]
    if not keys:
        _fail("an aggregate CSV unexpectedly has no rows")
    return list(min(keys)), list(max(keys))


def _read_csv(
    data_dir: Path, filename: str, spec: FileSpec, manifest_entry: Mapping[str, Any]
) -> pd.DataFrame:
    path = data_dir / filename
    if not path.is_file():
        _fail(f"required aggregate file is missing: {filename}")
    try:
        raw = path.read_bytes()
    except OSError:
        _fail(f"required aggregate file is unreadable: {filename}")
    if len(raw) != manifest_entry["byte_count"]:
        _fail(f"byte-count validation failed for {filename}")
    if hashlib.sha256(raw).hexdigest() != manifest_entry["sha256"]:
        _fail(f"checksum validation failed for {filename}")
    try:
        text = raw.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        rows = list(reader)
    except (UnicodeError, csv.Error, StopIteration):
        _fail(f"CSV parsing failed for {filename}")
    if tuple(header) != spec.columns:
        _fail(f"CSV schema validation failed for {filename}")
    if any(len(row) != len(spec.columns) for row in rows):
        _fail(f"CSV row width validation failed for {filename}")
    if len(rows) != spec.row_count or len(rows) != manifest_entry["row_count"]:
        _fail(f"CSV row-count validation failed for {filename}")

    frame = pd.DataFrame(rows, columns=spec.columns, dtype=object)
    if any(
        not isinstance(value, str) or value == "" or value != value.strip()
        for value in frame.to_numpy().ravel()
    ):
        _fail(f"{filename} contains a blank or non-canonical field")

    for column in spec.month_columns:
        frame[column] = frame[column].map(lambda value: _parse_csv_month(value, filename))
    for column in spec.integer_columns:
        frame[column] = frame[column].map(lambda value: _parse_integer(value, filename))
    for column in spec.decimal_columns:
        frame[column] = frame[column].map(lambda value: _parse_decimal(value, filename))
    for column in spec.text_columns:
        frame[column] = frame[column].astype(str)

    if frame.loc[:, list(spec.key_columns)].isna().any().any():
        _fail(f"{filename} contains a NULL key")
    if frame.duplicated(list(spec.key_columns), keep=False).any():
        _fail(f"{filename} contains a duplicate key")
    key_min, key_max = _manifest_key_range(frame, spec)
    if key_min != manifest_entry["key_min"] or key_max != manifest_entry["key_max"]:
        _fail(f"key-range validation failed for {filename}")
    return frame


def _validate_months(frame: pd.DataFrame, filename: str) -> None:
    months = tuple(frame["purchase_month"].drop_duplicates().sort_values())
    if months != APPROVED_MONTHS:
        _fail(f"{filename} does not contain the exact approved 18 months")


def _validate_trade(frame: pd.DataFrame) -> None:
    filename = "trade_monthly_overview.csv"
    _validate_months(frame, filename)
    if any(value <= 0 for value in frame["gross_item_value"]):
        _fail(f"{filename} contains a non-positive product trade value")
    if any(value < 0 for value in frame["freight_amount"]):
        _fail(f"{filename} contains a negative freight amount")
    if any(value <= 0 for value in frame["ordered_item_row_count"]):
        _fail(f"{filename} contains a non-positive item count")
    if any(value <= 0 for value in frame["active_seller_count"]):
        _fail(f"{filename} contains a non-positive active-seller count")
    if any(
        row.item_side_amount != row.gross_item_value + row.freight_amount
        for row in frame.itertuples(index=False)
    ):
        _fail(f"{filename} does not reconcile product value plus freight")


def _validate_category(frame: pd.DataFrame) -> None:
    filename = "category_mix.csv"
    _validate_months(frame, filename)
    expected = {
        key: (label, rank) for key, label, rank in CATEGORY_GROUPS
    }
    if set(frame["group_key"]) & FORBIDDEN_CATEGORY_KEYS:
        _fail(f"{filename} contains a forbidden source sentinel")
    if set(frame["group_key"]) != set(expected):
        _fail(f"{filename} does not contain the approved category groups")
    for row in frame.itertuples(index=False):
        if (row.group_label, row.group_rank) != expected[row.group_key]:
            _fail(f"{filename} has an invalid category label or rank")
        if row.gross_item_value < 0 or row.month_total_gross_item_value <= 0:
            _fail(f"{filename} contains an invalid monetary range")
        if not Decimal("0") <= row.share <= Decimal("1"):
            _fail(f"{filename} contains an invalid share")
        expected_share = row.gross_item_value / row.month_total_gross_item_value
        if not _decimal_close(row.share, expected_share):
            _fail(f"{filename} contains a share that does not match its full-month denominator")

    for _, group in frame.groupby("purchase_month", sort=True):
        if len(group) != len(CATEGORY_GROUPS):
            _fail(f"{filename} does not contain six groups in every month")
        totals = set(group["month_total_gross_item_value"])
        if len(totals) != 1:
            _fail(f"{filename} has inconsistent full-month denominators")
        total = next(iter(totals))
        if _sum_decimal(group["gross_item_value"]) != total:
            _fail(f"{filename} group values do not reconcile to the full-month total")
        if not _decimal_close(_sum_decimal(group["share"]), Decimal("1")):
            _fail(f"{filename} monthly shares do not sum to one")


def _validate_seller(frame: pd.DataFrame) -> None:
    filename = "seller_concentration.csv"
    _validate_months(frame, filename)
    zero = Decimal("0")
    one = Decimal("1")
    for row in frame.itertuples(index=False):
        if row.active_seller_count <= 0 or row.total_gross_item_value <= 0:
            _fail(f"{filename} contains an invalid monthly denominator")
        if row.top1_seller_count != 1:
            _fail(f"{filename} has an invalid Top 1 seller count")
        if row.top10_seller_count != min(10, row.active_seller_count):
            _fail(f"{filename} has an invalid Top 10 seller count")
        if row.top10_percent_seller_count != max(
            1, (row.active_seller_count + 9) // 10
        ):
            _fail(f"{filename} has an invalid Top 10% seller count")
        series = (
            (row.top1_gross_item_value, row.top1_share),
            (row.top10_gross_item_value, row.top10_share),
            (row.top10_percent_gross_item_value, row.top10_percent_share),
        )
        for amount, share in series:
            if not zero <= amount <= row.total_gross_item_value:
                _fail(f"{filename} contains an invalid concentration amount")
            if not zero <= share <= one:
                _fail(f"{filename} contains an invalid concentration share")
            if not _decimal_close(share, amount / row.total_gross_item_value):
                _fail(f"{filename} contains a concentration share mismatch")
        if not (
            row.top1_gross_item_value <= row.top10_gross_item_value
            and row.top1_gross_item_value <= row.top10_percent_gross_item_value
            and row.top1_share <= row.top10_share
            and row.top1_share <= row.top10_percent_share
        ):
            _fail(f"{filename} concentration series are not monotonic")


def _validate_delivery_timing(frame: pd.DataFrame) -> None:
    filename = "delivery_timing_summary.csv"
    expected = {
        key: (label, rank) for key, label, rank in DELIVERY_TIMING_GROUPS
    }
    if set(frame["delivery_timing_group"]) != set(expected):
        _fail(f"{filename} does not contain the approved delivery groups")
    total_orders = int(frame["order_count"].sum())
    if total_orders != 95_824:
        _fail(f"{filename} does not reconcile to the approved final cohort")
    late_orders = int(
        frame.loc[
            frame["delivery_timing_group"].isin(LATE_DELIVERY_GROUPS), "order_count"
        ].sum()
    )
    if late_orders != 6_381:
        _fail(f"{filename} does not reconcile to the approved late cohort")

    for row in frame.itertuples(index=False):
        if (row.group_label, row.group_rank) != expected[row.delivery_timing_group]:
            _fail(f"{filename} has an invalid delivery label or rank")
        if row.order_count <= 0:
            _fail(f"{filename} contains a non-positive order count")
        if not Decimal("0") <= row.order_share <= Decimal("1"):
            _fail(f"{filename} contains an invalid order share")
        if not _decimal_close(row.order_share, Decimal(row.order_count) / Decimal(total_orders)):
            _fail(f"{filename} contains an order-share mismatch")
        lower = Decimal(row.order_count)
        upper = lower * Decimal("5")
        if not lower <= row.order_review_score_sum <= upper:
            _fail(f"{filename} contains an invalid review-score sum")
        expected_mean = row.order_review_score_sum / Decimal(row.order_count)
        if not Decimal("1") <= row.mean_order_review_score <= Decimal("5"):
            _fail(f"{filename} contains an invalid mean review score")
        if not _decimal_close(row.mean_order_review_score, expected_mean):
            _fail(f"{filename} contains a mean review-score mismatch")
        if not Decimal("1") <= row.median_order_review_score <= Decimal("5"):
            _fail(f"{filename} contains an invalid median review score")
        if not 0 <= row.low_score_order_count <= row.order_count:
            _fail(f"{filename} contains an invalid low-score count")
        expected_rate = Decimal(row.low_score_order_count) / Decimal(row.order_count)
        if not Decimal("0") <= row.low_score_order_rate <= Decimal("1"):
            _fail(f"{filename} contains an invalid low-score rate")
        if not _decimal_close(row.low_score_order_rate, expected_rate):
            _fail(f"{filename} contains a low-score-rate mismatch")
    if not _decimal_close(_sum_decimal(frame["order_share"]), Decimal("1")):
        _fail(f"{filename} order shares do not sum to one")


def _validate_delivery_monthly(frame: pd.DataFrame) -> None:
    filename = "delivery_monthly.csv"
    _validate_months(frame, filename)
    for row in frame.itertuples(index=False):
        if row.order_count <= 0:
            _fail(f"{filename} contains a non-positive order count")
        if row.late_order_count < 0 or row.not_late_order_count < 0:
            _fail(f"{filename} contains a negative subgroup count")
        if row.order_count != row.late_order_count + row.not_late_order_count:
            _fail(f"{filename} subgroup counts do not reconcile")
        if row.late_order_count == 0 or row.not_late_order_count == 0:
            _fail(f"{filename} fixed snapshot contains an empty subgroup")
        if not (
            Decimal(row.late_order_count)
            <= row.late_order_review_score_sum
            <= Decimal(row.late_order_count) * Decimal("5")
        ):
            _fail(f"{filename} contains an invalid late review-score sum")
        if not (
            Decimal(row.not_late_order_count)
            <= row.not_late_order_review_score_sum
            <= Decimal(row.not_late_order_count) * Decimal("5")
        ):
            _fail(f"{filename} contains an invalid non-late review-score sum")
        expected_rate = Decimal(row.late_order_count) / Decimal(row.order_count)
        expected_late_mean = row.late_order_review_score_sum / Decimal(
            row.late_order_count
        )
        expected_not_late_mean = row.not_late_order_review_score_sum / Decimal(
            row.not_late_order_count
        )
        if not _decimal_close(row.late_rate, expected_rate):
            _fail(f"{filename} contains a late-rate mismatch")
        if not _decimal_close(row.late_mean_order_review_score, expected_late_mean):
            _fail(f"{filename} contains a late-mean mismatch")
        if not _decimal_close(
            row.not_late_mean_order_review_score, expected_not_late_mean
        ):
            _fail(f"{filename} contains a non-late-mean mismatch")
        if not _decimal_close(
            row.mean_score_gap, expected_late_mean - expected_not_late_mean
        ):
            _fail(f"{filename} contains a review-score-gap mismatch")


def _validate_delivery_sensitivity(frame: pd.DataFrame) -> None:
    filename = "delivery_sensitivity.csv"
    expected = dict(DELIVERY_SENSITIVITY_COHORTS)
    if set(frame["cohort"]) != set(expected):
        _fail(f"{filename} does not contain the approved sensitivity cohorts")
    rows = frame.set_index("cohort")
    for row in frame.itertuples(index=False):
        if row.cohort_label != expected[row.cohort]:
            _fail(f"{filename} has an invalid cohort label")
        if row.order_count <= 0 or row.late_order_count < 0 or row.not_late_order_count < 0:
            _fail(f"{filename} contains an invalid cohort count")
        if row.order_count != row.late_order_count + row.not_late_order_count:
            _fail(f"{filename} subgroup counts do not reconcile")
        if row.late_order_count == 0 or row.not_late_order_count == 0:
            _fail(f"{filename} fixed snapshot contains an empty subgroup")
        expected_rate = Decimal(row.late_order_count) / Decimal(row.order_count)
        if not _decimal_close(row.late_rate, expected_rate):
            _fail(f"{filename} contains a late-rate mismatch")
        for score in (
            row.late_mean_order_review_score,
            row.not_late_mean_order_review_score,
        ):
            if not Decimal("1") <= score <= Decimal("5"):
                _fail(f"{filename} contains an invalid review-score mean")
        if not _decimal_close(
            row.mean_score_gap,
            row.late_mean_order_review_score - row.not_late_mean_order_review_score,
        ):
            _fail(f"{filename} contains a review-score-gap mismatch")

    all_orders = rows.loc["all_orders"]
    without_inversions = rows.loc["without_chronology_inversions"]
    if int(all_orders["order_count"]) != 95_824 or int(all_orders["late_order_count"]) != 6_381:
        _fail(f"{filename} does not reconcile to the approved full cohort")
    if int(without_inversions["order_count"]) != 94_458:
        _fail(f"{filename} does not reconcile to the approved inversion exclusion")
    for column in ("order_count", "late_order_count", "not_late_order_count"):
        if int(without_inversions[column]) > int(all_orders[column]):
            _fail(f"{filename} inversion-excluded cohort exceeds the full cohort")


def _validate_cross_file(data: DashboardData) -> None:
    trade = data.trade_monthly_overview.set_index("purchase_month")
    category = data.category_mix.groupby("purchase_month", sort=True).agg(
        gross_item_value=("gross_item_value", _sum_decimal)
    )
    seller = data.seller_concentration.set_index("purchase_month")
    for month in APPROVED_MONTHS:
        if category.at[month, "gross_item_value"] != trade.at[month, "gross_item_value"]:
            _fail("category and trade monthly product values do not reconcile")
        if seller.at[month, "total_gross_item_value"] != trade.at[month, "gross_item_value"]:
            _fail("seller and trade monthly product values do not reconcile")
        if int(seller.at[month, "active_seller_count"]) != int(
            trade.at[month, "active_seller_count"]
        ):
            _fail("seller and trade monthly active-seller counts do not reconcile")

    timing = data.delivery_timing_summary
    late = timing["delivery_timing_group"].isin(LATE_DELIVERY_GROUPS)
    late_count = int(timing.loc[late, "order_count"].sum())
    not_late_count = int(timing.loc[~late, "order_count"].sum())
    late_score_sum = _sum_decimal(timing.loc[late, "order_review_score_sum"])
    not_late_score_sum = _sum_decimal(
        timing.loc[~late, "order_review_score_sum"]
    )
    sensitivity = data.delivery_sensitivity.set_index("cohort").loc["all_orders"]
    if (
        int(sensitivity["late_order_count"]) != late_count
        or int(sensitivity["not_late_order_count"]) != not_late_count
    ):
        _fail("delivery timing and sensitivity subgroup counts do not reconcile")
    late_mean = late_score_sum / Decimal(late_count)
    not_late_mean = not_late_score_sum / Decimal(not_late_count)
    if not _decimal_close(
        sensitivity["late_mean_order_review_score"], late_mean
    ) or not _decimal_close(
        sensitivity["not_late_mean_order_review_score"], not_late_mean
    ):
        _fail("delivery timing and sensitivity review means do not reconcile")
    if not _decimal_close(
        sensitivity["mean_score_gap"], late_mean - not_late_mean
    ):
        _fail("delivery timing and sensitivity score gaps do not reconcile")


def load_dashboard_data(data_dir: Path) -> DashboardData:
    """Load and fully validate all committed aggregate inputs, or fail closed."""

    directory = Path(data_dir)
    if not directory.is_dir():
        _fail("dashboard data directory is missing")
    manifest = _load_manifest(directory)
    frames = {
        filename: _read_csv(
            directory,
            filename,
            spec,
            manifest["files"][filename],
        )
        for filename, spec in FILE_SPECS.items()
    }

    _validate_trade(frames["trade_monthly_overview.csv"])
    _validate_category(frames["category_mix.csv"])
    _validate_seller(frames["seller_concentration.csv"])
    _validate_delivery_timing(frames["delivery_timing_summary.csv"])
    _validate_delivery_monthly(frames["delivery_monthly.csv"])
    _validate_delivery_sensitivity(frames["delivery_sensitivity.csv"])

    data = DashboardData(
        trade_monthly_overview=frames["trade_monthly_overview.csv"],
        category_mix=frames["category_mix.csv"],
        seller_concentration=frames["seller_concentration.csv"],
        delivery_timing_summary=frames["delivery_timing_summary.csv"],
        delivery_monthly=frames["delivery_monthly.csv"],
        delivery_sensitivity=frames["delivery_sensitivity.csv"],
        manifest=manifest,
    )
    _validate_cross_file(data)
    return data


def _parse_month_argument(value: str | date | datetime | pd.Timestamp) -> pd.Timestamp:
    if isinstance(value, str):
        parsed = _parse_csv_month(value, "month filter")
    else:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError):
            _fail("month filter is invalid")
        if parsed.tz is not None:
            _fail("month filter must be timezone-naive")
        if parsed != parsed.normalize() or parsed.day != 1:
            _fail("month filter must be the first day of a month")
    if parsed not in APPROVED_MONTHS:
        _fail("month filter is outside the approved 18-month period")
    return parsed


def filter_months(
    frame: pd.DataFrame,
    start_month: str | date | datetime | pd.Timestamp,
    end_month: str | date | datetime | pd.Timestamp,
) -> pd.DataFrame:
    """Return an inclusive, sorted period slice without mutating the input."""

    if "purchase_month" not in frame.columns:
        _fail("period filtering requires a purchase_month column")
    start = _parse_month_argument(start_month)
    end = _parse_month_argument(end_month)
    if start > end:
        _fail("start month must not be after end month")
    month_values = frame["purchase_month"]
    if not pd.api.types.is_datetime64_any_dtype(month_values):
        _fail("purchase_month must be a validated datetime column")
    if month_values.isna().any() or not month_values.isin(APPROVED_MONTHS).all():
        _fail("purchase_month contains a missing or unapproved month")
    result = frame.loc[month_values.between(start, end)].copy()
    return result.sort_values("purchase_month", kind="mergesort").reset_index(drop=True)


def compute_trade_kpis(frame: pd.DataFrame) -> TradeKpis:
    """Recompute selected-period trade KPIs from monthly additive inputs."""

    required = {
        "purchase_month",
        "gross_item_value",
        "freight_amount",
        "ordered_item_row_count",
        "active_seller_count",
    }
    if not required.issubset(frame.columns) or frame.empty:
        _fail("trade KPI input is empty or missing required columns")
    ordered = frame.sort_values("purchase_month", kind="mergesort")
    try:
        gross = _sum_decimal(ordered["gross_item_value"])
        freight = _sum_decimal(ordered["freight_amount"])
        item_rows = int(ordered["ordered_item_row_count"].sum())
        active_sellers = int(ordered.iloc[-1]["active_seller_count"])
    except (TypeError, ValueError):
        _fail("trade KPI input has invalid validated types")
    if gross < 0 or freight < 0 or item_rows < 0 or active_sellers < 0:
        _fail("trade KPI input contains an invalid negative value")
    return TradeKpis(
        gross_item_value=gross,
        freight_amount=freight,
        ordered_item_row_count=item_rows,
        active_seller_count=active_sellers,
    )


def compute_delivery_kpis(frame: pd.DataFrame) -> DeliveryKpis:
    """Recompute selected-period delivery KPIs from raw counts and score sums."""

    required = {
        "order_count",
        "late_order_count",
        "not_late_order_count",
        "late_order_review_score_sum",
        "not_late_order_review_score_sum",
    }
    if not required.issubset(frame.columns) or frame.empty:
        _fail("delivery KPI input is empty or missing required columns")
    try:
        order_count = int(frame["order_count"].sum())
        late_count = int(frame["late_order_count"].sum())
        not_late_count = int(frame["not_late_order_count"].sum())
        late_score_sum = _sum_decimal(frame["late_order_review_score_sum"])
        not_late_score_sum = _sum_decimal(
            frame["not_late_order_review_score_sum"]
        )
    except (TypeError, ValueError):
        _fail("delivery KPI input has invalid validated types")
    if min(order_count, late_count, not_late_count) < 0:
        _fail("delivery KPI input contains a negative count")
    if order_count != late_count + not_late_count:
        _fail("delivery KPI subgroup counts do not reconcile")
    if late_score_sum < 0 or not_late_score_sum < 0:
        _fail("delivery KPI input contains a negative review-score sum")

    late_rate = (
        Decimal(late_count) / Decimal(order_count) if order_count else None
    )
    late_mean = late_score_sum / Decimal(late_count) if late_count else None
    not_late_mean = (
        not_late_score_sum / Decimal(not_late_count) if not_late_count else None
    )
    gap = late_mean - not_late_mean if late_mean is not None and not_late_mean is not None else None
    return DeliveryKpis(
        order_count=order_count,
        late_order_count=late_count,
        not_late_order_count=not_late_count,
        late_rate=late_rate,
        late_mean_order_review_score=late_mean,
        not_late_mean_order_review_score=not_late_mean,
        mean_score_gap=gap,
    )
