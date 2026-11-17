#!/usr/bin/env python3
"""Deepen the validated delivery-review analysis without redefining its mart."""

from __future__ import annotations

import argparse
import filecmp
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "ecommerce-analytics-pipeline-matplotlib"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(Path(tempfile.gettempdir()) / "ecommerce-analytics-pipeline-cache"),
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATION = "analytics.mart_delivery_review_orders"
REPORT_FILE = Path("delivery-review-deepening-analysis.md")
SEVERITY_FIGURE = Path("figures/delivery-review-delay-severity.png")
MONTHLY_FIGURE = Path("figures/delivery-review-monthly-stability.png")
ARTIFACT_FILES = (REPORT_FILE, SEVERITY_FIGURE, MONTHLY_FIGURE)
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ANALYSIS_START = pd.Timestamp("2017-02-01")
ANALYSIS_END_EXCLUSIVE = pd.Timestamp("2018-08-01")
APPROVED_MONTHS = tuple(
    pd.date_range(ANALYSIS_START, ANALYSIS_END_EXCLUSIVE, freq="MS", inclusive="left")
)
FLOAT_ABS_TOLERANCE = 1e-12
EXPECTED_LATE_DELAY_ANCHORS = {
    "late_delay_p25": 3.0,
    "late_delay_median": 7.0,
    "late_delay_p75": 13.0,
    "late_delay_max": 188,
}

SEVERITY_ORDER = (
    "early",
    "promised_date",
    "late_1_3",
    "late_4_7",
    "late_8_14",
    "late_15_plus",
)
SEVERITY_LABELS = {
    "early": "Early",
    "promised_date": "Promised date",
    "late_1_3": "Late 1-3 days",
    "late_4_7": "Late 4-7 days",
    "late_8_14": "Late 8-14 days",
    "late_15_plus": "Late 15+ days",
}
SEVERITY_COLORS = {
    "early": "#4C78A8",
    "promised_date": "#72B7B2",
    "late_1_3": "#F2CF5B",
    "late_4_7": "#F2A541",
    "late_8_14": "#E9783A",
    "late_15_plus": "#C44E52",
}
INVERSION_FLAGS = (
    "is_approval_before_purchase",
    "is_carrier_before_purchase",
    "is_carrier_before_approval",
    "is_customer_before_purchase",
    "is_customer_before_carrier",
)
MISSING_DATE_FLAGS = (
    "is_approval_date_missing",
    "is_carrier_date_missing",
)
REQUIRED_COLUMNS = (
    "order_id",
    "order_status",
    "order_purchase_timestamp",
    "delivery_days_vs_estimate",
    "delivery_timing_status",
    "is_late",
    "review_count",
    "review_score_sum",
    "order_avg_review_score",
    *MISSING_DATE_FLAGS,
    *INVERSION_FLAGS,
)

SEVERITY_SQL_CASE = """
case
    when delivery_days_vs_estimate < 0 then 'early'
    when delivery_days_vs_estimate = 0 then 'promised_date'
    when delivery_days_vs_estimate between 1 and 3 then 'late_1_3'
    when delivery_days_vs_estimate between 4 and 7 then 'late_4_7'
    when delivery_days_vs_estimate between 8 and 14 then 'late_8_14'
    else 'late_15_plus'
end
""".strip()

INVERSION_SQL_EXPRESSION = " or ".join(
    f"coalesce({flag}, false)" for flag in INVERSION_FLAGS
)


class DeliveryReviewDeepeningError(RuntimeError):
    """Expected analysis failure that can be displayed without leaking secrets."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        password = os.environ.get("PGPASSWORD")
        if not password:
            raise DeliveryReviewDeepeningError(
                "PGPASSWORD is required; copy .env.example to .env and set a local password"
            )
        host = os.environ.get("PGHOST", "127.0.0.1")
        if host.lower() not in LOCAL_DATABASE_HOSTS:
            raise DeliveryReviewDeepeningError("PGHOST must be a local loopback host")
        try:
            port = int(os.environ.get("PGPORT", "55432"))
        except ValueError:
            raise DeliveryReviewDeepeningError("PGPORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise DeliveryReviewDeepeningError("PGPORT must be between 1 and 65535")
        return cls(
            host=host,
            port=port,
            dbname=os.environ.get("PGDATABASE", "olist"),
            user=os.environ.get("PGUSER", "olist"),
            password=password,
        )

    def connection_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "connect_timeout": 10,
            "application_name": "ecommerce_analytics_delivery_review_deepening",
        }


@dataclass(frozen=True)
class GroupMetrics:
    name: str
    order_count: int
    order_share: float
    review_row_count: int
    review_score_sum: int
    order_review_score_sum: Decimal
    low_score_order_count: int
    mean_review_score: float | None
    median_review_score: float | None
    low_score_rate: float | None


@dataclass(frozen=True)
class MonthlyMetrics:
    purchase_month: pd.Timestamp
    order_count: int
    late_order_count: int
    not_late_order_count: int
    review_row_count: int
    review_score_sum: int
    late_order_review_score_sum: Decimal
    not_late_order_review_score_sum: Decimal
    late_rate: float | None
    late_mean_review_score: float | None
    not_late_mean_review_score: float | None
    mean_score_gap: float | None


@dataclass(frozen=True)
class CohortMetrics:
    name: str
    order_count: int
    late_order_count: int
    not_late_order_count: int
    review_row_count: int
    review_score_sum: int
    late_order_review_score_sum: Decimal
    not_late_order_review_score_sum: Decimal
    late_rate: float | None
    late_mean_review_score: float | None
    not_late_mean_review_score: float | None
    mean_score_gap: float | None


@dataclass(frozen=True)
class DeepeningSummary:
    total_orders: int
    review_row_count: int
    review_score_sum: int
    order_review_score_sum: Decimal
    low_score_order_count: int
    overall_mean_review_score: float
    overall_median_review_score: float
    overall_low_score_rate: float
    chronology_inversion_order_count: int
    inversion_flag_null_counts: tuple[tuple[str, int], ...]
    late_delay_p25: float | None
    late_delay_median: float | None
    late_delay_p75: float | None
    late_delay_max: int | None
    severity: tuple[GroupMetrics, ...]
    monthly: tuple[MonthlyMetrics, ...]
    sensitivity: tuple[CohortMetrics, ...]

    def severity_group(self, name: str) -> GroupMetrics:
        return next(group for group in self.severity if group.name == name)

    def sensitivity_cohort(self, name: str) -> CohortMetrics:
        return next(cohort for cohort in self.sensitivity if cohort.name == name)


@dataclass(frozen=True)
class DatabaseBaselines:
    overall: dict[str, Any]
    severity: pd.DataFrame
    monthly: pd.DataFrame
    sensitivity: pd.DataFrame


def connect_database(config: DatabaseConfig) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(**config.connection_kwargs())
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"database connection failed: {type(exc).__name__}"
        ) from None


def _records_to_frame(cursor: psycopg.Cursor[Any]) -> pd.DataFrame:
    rows = cursor.fetchall()
    columns = [column.name for column in cursor.description or ()]
    return pd.DataFrame.from_records(rows, columns=columns)


def _fetch_frame(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    query = f"""
        select
            {', '.join(REQUIRED_COLUMNS)}
        from {SOURCE_RELATION}
        order by order_id
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return _records_to_frame(cursor)
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"mart read failed: {type(exc).__name__}"
        ) from None


def _fetch_overall_baseline(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    flag_null_counts = ",\n            ".join(
        f"count(*) filter (where {flag} is null)::bigint "
        f"as {flag}_null_count"
        for flag in INVERSION_FLAGS
    )
    query = f"""
        select
            count(*)::bigint as total_orders,
            count(distinct order_id)::bigint as distinct_orders,
            sum(review_count)::bigint as review_row_count,
            sum(review_score_sum)::bigint as review_score_sum,
            sum(order_avg_review_score) as order_review_score_sum,
            count(*) filter (
                where order_avg_review_score <= 2
            )::bigint as low_score_order_count,
            count(*) filter (
                where {INVERSION_SQL_EXPRESSION}
            )::bigint as chronology_inversion_order_count,
            percentile_cont(0.25) within group (
                order by delivery_days_vs_estimate
            ) filter (where is_late) as late_delay_p25,
            percentile_cont(0.5) within group (
                order by delivery_days_vs_estimate
            ) filter (where is_late) as late_delay_median,
            percentile_cont(0.75) within group (
                order by delivery_days_vs_estimate
            ) filter (where is_late) as late_delay_p75,
            max(delivery_days_vs_estimate) filter (
                where is_late
            )::bigint as late_delay_max,
            percentile_cont(0.5) within group (
                order by order_avg_review_score::double precision
            ) as overall_median_review_score,
            {flag_null_counts}
        from {SOURCE_RELATION}
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
            columns = [column.name for column in cursor.description or ()]
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"overall baseline read failed: {type(exc).__name__}"
        ) from None
    if row is None:
        raise DeliveryReviewDeepeningError("overall baseline query returned no row")
    return dict(zip(columns, row, strict=True))


def _fetch_severity_baseline(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    query = f"""
        with severity_groups(severity_group, sort_order) as (
            values
                ('early', 1),
                ('promised_date', 2),
                ('late_1_3', 3),
                ('late_4_7', 4),
                ('late_8_14', 5),
                ('late_15_plus', 6)
        ),
        labeled as (
            select
                {SEVERITY_SQL_CASE} as severity_group,
                review_count,
                review_score_sum,
                order_avg_review_score
            from {SOURCE_RELATION}
        ),
        aggregated as (
            select
                severity_group,
                count(*)::bigint as order_count,
                sum(review_count)::bigint as review_row_count,
                sum(review_score_sum)::bigint as review_score_sum,
                sum(order_avg_review_score) as order_review_score_sum,
                count(*) filter (
                    where order_avg_review_score <= 2
                )::bigint as low_score_order_count,
                percentile_cont(0.5) within group (
                    order by order_avg_review_score::double precision
                ) as median_review_score
            from labeled
            group by severity_group
        )
        select
            groups.severity_group,
            coalesce(aggregated.order_count, 0)::bigint as order_count,
            coalesce(aggregated.review_row_count, 0)::bigint as review_row_count,
            coalesce(aggregated.review_score_sum, 0)::bigint as review_score_sum,
            coalesce(
                aggregated.order_review_score_sum, 0::numeric
            ) as order_review_score_sum,
            coalesce(
                aggregated.low_score_order_count, 0
            )::bigint as low_score_order_count,
            aggregated.median_review_score
        from severity_groups as groups
        left join aggregated using (severity_group)
        order by groups.sort_order
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return _records_to_frame(cursor)
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"severity baseline read failed: {type(exc).__name__}"
        ) from None


def _fetch_monthly_baseline(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    query = f"""
        with months as (
            select generate_series(
                date '2017-02-01',
                date '2018-07-01',
                interval '1 month'
            )::date as purchase_month
        ),
        aggregated as (
            select
                date_trunc('month', order_purchase_timestamp)::date
                    as purchase_month,
                count(*)::bigint as order_count,
                count(distinct order_id)::bigint as distinct_orders,
                count(*) filter (where is_late)::bigint as late_order_count,
                count(*) filter (where not is_late)::bigint
                    as not_late_order_count,
                sum(review_count)::bigint as review_row_count,
                sum(review_score_sum)::bigint as review_score_sum,
                sum(order_avg_review_score) filter (
                    where is_late
                ) as late_order_review_score_sum,
                sum(order_avg_review_score) filter (
                    where not is_late
                ) as not_late_order_review_score_sum
            from {SOURCE_RELATION}
            where order_purchase_timestamp >= date '2017-02-01'
                and order_purchase_timestamp < date '2018-08-01'
            group by 1
        )
        select
            months.purchase_month,
            coalesce(aggregated.order_count, 0)::bigint as order_count,
            coalesce(aggregated.distinct_orders, 0)::bigint as distinct_orders,
            coalesce(aggregated.late_order_count, 0)::bigint as late_order_count,
            coalesce(
                aggregated.not_late_order_count, 0
            )::bigint as not_late_order_count,
            coalesce(aggregated.review_row_count, 0)::bigint as review_row_count,
            coalesce(aggregated.review_score_sum, 0)::bigint as review_score_sum,
            coalesce(
                aggregated.late_order_review_score_sum, 0::numeric
            ) as late_order_review_score_sum,
            coalesce(
                aggregated.not_late_order_review_score_sum, 0::numeric
            ) as not_late_order_review_score_sum
        from months
        left join aggregated using (purchase_month)
        order by months.purchase_month
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return _records_to_frame(cursor)
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"monthly baseline read failed: {type(exc).__name__}"
        ) from None


def _fetch_sensitivity_baseline(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    query = f"""
        with base as (
            select
                *,
                ({INVERSION_SQL_EXPRESSION}) as has_chronology_inversion
            from {SOURCE_RELATION}
        ),
        cohort_names(cohort_name, sort_order) as (
            values
                ('all_orders', 1),
                ('without_chronology_inversions', 2)
        )
        select
            cohorts.cohort_name,
            count(base.order_id)::bigint as order_count,
            count(distinct base.order_id)::bigint as distinct_orders,
            count(base.order_id) filter (
                where base.is_late
            )::bigint as late_order_count,
            count(base.order_id) filter (
                where not base.is_late
            )::bigint as not_late_order_count,
            coalesce(sum(base.review_count), 0)::bigint as review_row_count,
            coalesce(sum(base.review_score_sum), 0)::bigint as review_score_sum,
            coalesce(sum(base.order_avg_review_score) filter (
                where base.is_late
            ), 0::numeric) as late_order_review_score_sum,
            coalesce(sum(base.order_avg_review_score) filter (
                where not base.is_late
            ), 0::numeric) as not_late_order_review_score_sum
        from cohort_names as cohorts
        left join base
            on cohorts.cohort_name = 'all_orders'
            or (
                cohorts.cohort_name = 'without_chronology_inversions'
                and not base.has_chronology_inversion
            )
        group by cohorts.cohort_name, cohorts.sort_order
        order by cohorts.sort_order
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return _records_to_frame(cursor)
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"sensitivity baseline read failed: {type(exc).__name__}"
        ) from None


def load_analysis_snapshot(
    connection: psycopg.Connection[Any],
) -> tuple[pd.DataFrame, DatabaseBaselines]:
    """Read mart rows and independent SQL baselines from one read-only snapshot."""

    try:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            frame = _fetch_frame(connection)
            baselines = DatabaseBaselines(
                overall=_fetch_overall_baseline(connection),
                severity=_fetch_severity_baseline(connection),
                monthly=_fetch_monthly_baseline(connection),
                sensitivity=_fetch_sensitivity_baseline(connection),
            )
    except psycopg.Error as exc:
        raise DeliveryReviewDeepeningError(
            f"read-only snapshot failed: {type(exc).__name__}"
        ) from None
    return frame, baselines


def _validate_boolean_column(
    frame: pd.DataFrame, column: str, *, nullable: bool
) -> pd.Series:
    values = frame[column]
    if not nullable and values.isna().any():
        raise DeliveryReviewDeepeningError(f"{column} contains NULL values")
    non_null = values.dropna()
    if not non_null.isin([True, False]).all():
        raise DeliveryReviewDeepeningError(
            f"{column} must contain only booleans"
        )
    return values.astype("boolean" if nullable else bool)


def _as_decimal(value: Any, *, column: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise DeliveryReviewDeepeningError(
            f"{column} contains a non-numeric value"
        ) from None
    if not normalized.is_finite():
        raise DeliveryReviewDeepeningError(
            f"{column} contains a non-finite value"
        )
    return normalized


def _decimal_sum(values: pd.Series) -> Decimal:
    return sum(values.tolist(), Decimal(0))


def _mean_from_sum(total: Decimal, count: int) -> float | None:
    if count == 0:
        return None
    return float(total / Decimal(count))


def _median(values: pd.Series) -> float | None:
    if values.empty:
        return None
    ordered = sorted(values.tolist())
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / Decimal(2))


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def validate_analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Fail closed if the final mart no longer satisfies the analysis contract."""

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DeliveryReviewDeepeningError(
            "analysis input is missing required columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise DeliveryReviewDeepeningError("analysis input is empty")

    validated = frame.loc[:, REQUIRED_COLUMNS].copy()
    non_nullable = [
        column
        for column in REQUIRED_COLUMNS
        if column not in INVERSION_FLAGS
    ]
    if validated[non_nullable].isna().any().any():
        raise DeliveryReviewDeepeningError(
            "analysis input contains NULL in a required value"
        )
    if validated["order_id"].duplicated().any():
        raise DeliveryReviewDeepeningError("analysis input contains duplicate order_id")
    if not validated["order_status"].eq("delivered").all():
        raise DeliveryReviewDeepeningError(
            "analysis input contains non-delivered orders"
        )

    try:
        validated["order_purchase_timestamp"] = pd.to_datetime(
            validated["order_purchase_timestamp"], errors="raise"
        )
    except (TypeError, ValueError):
        raise DeliveryReviewDeepeningError(
            "order_purchase_timestamp contains an invalid timestamp"
        ) from None
    if validated["order_purchase_timestamp"].isna().any():
        raise DeliveryReviewDeepeningError(
            "order_purchase_timestamp contains an invalid timestamp"
        )

    integer_columns = (
        "delivery_days_vs_estimate",
        "review_count",
        "review_score_sum",
    )
    for column in integer_columns:
        try:
            numeric = pd.to_numeric(validated[column], errors="raise")
        except (TypeError, ValueError):
            raise DeliveryReviewDeepeningError(
                f"analysis input contains non-numeric {column}"
            ) from None
        if not (numeric % 1 == 0).all():
            raise DeliveryReviewDeepeningError(f"{column} must be an integer")
        validated[column] = numeric.astype("int64")

    validated["order_avg_review_score"] = validated[
        "order_avg_review_score"
    ].map(lambda value: _as_decimal(value, column="order_avg_review_score"))

    validated["is_late"] = _validate_boolean_column(
        validated, "is_late", nullable=False
    )
    for column in MISSING_DATE_FLAGS:
        validated[column] = _validate_boolean_column(
            validated, column, nullable=False
        )
    for column in INVERSION_FLAGS:
        validated[column] = _validate_boolean_column(
            validated, column, nullable=True
        )

    allowed_statuses = {"early", "promised_date", "late"}
    if not validated["delivery_timing_status"].isin(allowed_statuses).all():
        raise DeliveryReviewDeepeningError(
            "delivery_timing_status contains an unapproved value"
        )
    expected_status = pd.Series(
        "promised_date", index=validated.index, dtype="object"
    )
    expected_status.loc[validated["delivery_days_vs_estimate"] < 0] = "early"
    expected_status.loc[validated["delivery_days_vs_estimate"] > 0] = "late"
    if not validated["delivery_timing_status"].eq(expected_status).all():
        raise DeliveryReviewDeepeningError(
            "delivery_timing_status does not match delivery day difference"
        )
    if not validated["is_late"].eq(
        validated["delivery_days_vs_estimate"] > 0
    ).all():
        raise DeliveryReviewDeepeningError(
            "is_late does not match delivery day difference"
        )

    if not (validated["review_count"] >= 1).all():
        raise DeliveryReviewDeepeningError("review_count must be at least one")
    if not (
        (validated["review_score_sum"] >= validated["review_count"])
        & (
            validated["review_score_sum"]
            <= validated["review_count"] * 5
        )
    ).all():
        raise DeliveryReviewDeepeningError(
            "review_score_sum is outside the 1-5 domain"
        )
    expected_average = (
        validated["review_score_sum"] / validated["review_count"]
    ).astype(float)
    if not all(
        math.isclose(actual, expected, rel_tol=0.0, abs_tol=FLOAT_ABS_TOLERANCE)
        for actual, expected in zip(
            validated["order_avg_review_score"].map(float),
            expected_average,
            strict=True,
        )
    ):
        raise DeliveryReviewDeepeningError(
            "order_avg_review_score does not equal score sum divided by review count"
        )
    return validated


def assign_severity_group(frame: pd.DataFrame) -> pd.Series:
    days = frame["delivery_days_vs_estimate"]
    groups = pd.Series(index=frame.index, dtype="object")
    groups.loc[days < 0] = "early"
    groups.loc[days == 0] = "promised_date"
    groups.loc[days.between(1, 3)] = "late_1_3"
    groups.loc[days.between(4, 7)] = "late_4_7"
    groups.loc[days.between(8, 14)] = "late_8_14"
    groups.loc[days >= 15] = "late_15_plus"
    if groups.isna().any():
        raise DeliveryReviewDeepeningError(
            "one or more orders were not assigned to a severity group"
        )
    return groups


def chronology_inversion_mask(frame: pd.DataFrame) -> pd.Series:
    return frame.loc[:, INVERSION_FLAGS].fillna(False).astype(bool).any(axis=1)


def _group_metrics(
    frame: pd.DataFrame, *, name: str, denominator: int
) -> GroupMetrics:
    low_score = frame["order_avg_review_score"] <= 2
    count = int(len(frame))
    score_sum = _decimal_sum(frame["order_avg_review_score"])
    return GroupMetrics(
        name=name,
        order_count=count,
        order_share=count / denominator if denominator else 0.0,
        review_row_count=int(frame["review_count"].sum()),
        review_score_sum=int(frame["review_score_sum"].sum()),
        order_review_score_sum=score_sum,
        low_score_order_count=int(low_score.sum()),
        mean_review_score=_mean_from_sum(score_sum, count),
        median_review_score=_median(frame["order_avg_review_score"]),
        low_score_rate=_ratio(int(low_score.sum()), count),
    )


def _cohort_metrics(frame: pd.DataFrame, *, name: str) -> CohortMetrics:
    late = frame.loc[frame["is_late"]]
    not_late = frame.loc[~frame["is_late"]]
    late_sum = _decimal_sum(late["order_avg_review_score"])
    not_late_sum = _decimal_sum(not_late["order_avg_review_score"])
    late_mean = _mean_from_sum(late_sum, len(late))
    not_late_mean = _mean_from_sum(not_late_sum, len(not_late))
    gap = (
        late_mean - not_late_mean
        if late_mean is not None and not_late_mean is not None
        else None
    )
    return CohortMetrics(
        name=name,
        order_count=int(len(frame)),
        late_order_count=int(len(late)),
        not_late_order_count=int(len(not_late)),
        review_row_count=int(frame["review_count"].sum()),
        review_score_sum=int(frame["review_score_sum"].sum()),
        late_order_review_score_sum=late_sum,
        not_late_order_review_score_sum=not_late_sum,
        late_rate=_ratio(int(len(late)), int(len(frame))),
        late_mean_review_score=late_mean,
        not_late_mean_review_score=not_late_mean,
        mean_score_gap=gap,
    )


def _monthly_metrics(frame: pd.DataFrame) -> tuple[MonthlyMetrics, ...]:
    period = frame.loc[
        (frame["order_purchase_timestamp"] >= ANALYSIS_START)
        & (frame["order_purchase_timestamp"] < ANALYSIS_END_EXCLUSIVE)
    ].copy()
    period["purchase_month"] = (
        period["order_purchase_timestamp"].dt.to_period("M").dt.to_timestamp()
    )

    results: list[MonthlyMetrics] = []
    for purchase_month in APPROVED_MONTHS:
        month = period.loc[period["purchase_month"].eq(purchase_month)]
        late = month.loc[month["is_late"]]
        not_late = month.loc[~month["is_late"]]
        late_sum = _decimal_sum(late["order_avg_review_score"])
        not_late_sum = _decimal_sum(not_late["order_avg_review_score"])
        late_mean = _mean_from_sum(late_sum, len(late))
        not_late_mean = _mean_from_sum(not_late_sum, len(not_late))
        gap = (
            late_mean - not_late_mean
            if late_mean is not None and not_late_mean is not None
            else None
        )
        results.append(
            MonthlyMetrics(
                purchase_month=pd.Timestamp(purchase_month),
                order_count=int(len(month)),
                late_order_count=int(len(late)),
                not_late_order_count=int(len(not_late)),
                review_row_count=int(month["review_count"].sum()),
                review_score_sum=int(month["review_score_sum"].sum()),
                late_order_review_score_sum=late_sum,
                not_late_order_review_score_sum=not_late_sum,
                late_rate=_ratio(int(len(late)), int(len(month))),
                late_mean_review_score=late_mean,
                not_late_mean_review_score=not_late_mean,
                mean_score_gap=gap,
            )
        )
    return tuple(results)


def summarize_deepening(frame: pd.DataFrame) -> DeepeningSummary:
    working = frame.copy()
    working["severity_group"] = assign_severity_group(working)
    inversion_mask = chronology_inversion_mask(working)
    total_orders = int(len(working))

    severity = tuple(
        _group_metrics(
            working.loc[working["severity_group"].eq(name)],
            name=name,
            denominator=total_orders,
        )
        for name in SEVERITY_ORDER
    )
    sensitivity = (
        _cohort_metrics(working, name="all_orders"),
        _cohort_metrics(
            working.loc[~inversion_mask],
            name="without_chronology_inversions",
        ),
    )
    order_review_score_sum = _decimal_sum(working["order_avg_review_score"])
    late_days = working.loc[working["is_late"], "delivery_days_vs_estimate"]
    overall_median = _median(working["order_avg_review_score"])
    if overall_median is None:
        raise DeliveryReviewDeepeningError("analysis input is empty")
    summary = DeepeningSummary(
        total_orders=total_orders,
        review_row_count=int(working["review_count"].sum()),
        review_score_sum=int(working["review_score_sum"].sum()),
        order_review_score_sum=order_review_score_sum,
        low_score_order_count=int(
            (working["order_avg_review_score"] <= 2).sum()
        ),
        overall_mean_review_score=float(
            order_review_score_sum / Decimal(total_orders)
        ),
        overall_median_review_score=overall_median,
        overall_low_score_rate=float(
            (working["order_avg_review_score"] <= 2).sum() / total_orders
        ),
        chronology_inversion_order_count=int(inversion_mask.sum()),
        inversion_flag_null_counts=tuple(
            (flag, int(working[flag].isna().sum()))
            for flag in INVERSION_FLAGS
        ),
        late_delay_p25=(
            float(late_days.quantile(0.25)) if not late_days.empty else None
        ),
        late_delay_median=(
            float(late_days.quantile(0.5)) if not late_days.empty else None
        ),
        late_delay_p75=(
            float(late_days.quantile(0.75)) if not late_days.empty else None
        ),
        late_delay_max=(int(late_days.max()) if not late_days.empty else None),
        severity=severity,
        monthly=_monthly_metrics(working),
        sensitivity=sensitivity,
    )
    _validate_summary_internal_reconciliation(summary, working)
    return summary


def _validate_summary_internal_reconciliation(
    summary: DeepeningSummary, frame: pd.DataFrame
) -> None:
    exact_severity_checks = {
        "order_count": sum(group.order_count for group in summary.severity),
        "review_row_count": sum(
            group.review_row_count for group in summary.severity
        ),
        "review_score_sum": sum(
            group.review_score_sum for group in summary.severity
        ),
        "low_score_order_count": sum(
            group.low_score_order_count for group in summary.severity
        ),
        "order_review_score_sum": sum(
            (group.order_review_score_sum for group in summary.severity),
            Decimal(0),
        ),
    }
    expected = {
        "order_count": summary.total_orders,
        "review_row_count": summary.review_row_count,
        "review_score_sum": summary.review_score_sum,
        "low_score_order_count": summary.low_score_order_count,
        "order_review_score_sum": summary.order_review_score_sum,
    }
    if exact_severity_checks != expected:
        raise DeliveryReviewDeepeningError(
            "severity groups do not reconcile to the full analysis cohort"
        )
    if not math.isclose(
        sum(group.order_share for group in summary.severity),
        1.0,
        rel_tol=0.0,
        abs_tol=FLOAT_ABS_TOLERANCE,
    ):
        raise DeliveryReviewDeepeningError("severity shares do not sum to one")
    late_group_count = sum(
        group.order_count
        for group in summary.severity
        if group.name.startswith("late_")
    )
    if late_group_count != int(frame["is_late"].sum()):
        raise DeliveryReviewDeepeningError(
            "late severity groups do not reconcile to is_late"
        )

    if tuple(month.purchase_month for month in summary.monthly) != APPROVED_MONTHS:
        raise DeliveryReviewDeepeningError(
            "monthly summaries do not contain the approved 18-month key set"
        )

    period = frame.loc[
        (frame["order_purchase_timestamp"] >= ANALYSIS_START)
        & (frame["order_purchase_timestamp"] < ANALYSIS_END_EXCLUSIVE)
    ]
    monthly_exact = (
        sum(month.order_count for month in summary.monthly),
        sum(month.review_row_count for month in summary.monthly),
        sum(month.review_score_sum for month in summary.monthly),
        sum(
            (
                month.late_order_review_score_sum
                + month.not_late_order_review_score_sum
                for month in summary.monthly
            ),
            Decimal(0),
        ),
    )
    period_exact = (
        int(len(period)),
        int(period["review_count"].sum()),
        int(period["review_score_sum"].sum()),
        _decimal_sum(period["order_avg_review_score"]),
    )
    if monthly_exact != period_exact:
        raise DeliveryReviewDeepeningError(
            "monthly summaries do not reconcile to the approved period"
        )

    all_orders = summary.sensitivity_cohort("all_orders")
    if (
        all_orders.order_count,
        all_orders.review_row_count,
        all_orders.review_score_sum,
        all_orders.late_order_review_score_sum
        + all_orders.not_late_order_review_score_sum,
    ) != (
        summary.total_orders,
        summary.review_row_count,
        summary.review_score_sum,
        summary.order_review_score_sum,
    ):
        raise DeliveryReviewDeepeningError(
            "all-orders sensitivity cohort does not reconcile"
        )
    without_inversions = summary.sensitivity_cohort(
        "without_chronology_inversions"
    )
    if (
        summary.total_orders - without_inversions.order_count
        != summary.chronology_inversion_order_count
    ):
        raise DeliveryReviewDeepeningError(
            "chronology sensitivity exclusion count does not reconcile"
        )


def validate_expected_snapshot(summary: DeepeningSummary) -> None:
    """Lock the contract's preflight anchors for the fixed Olist snapshot."""

    for field_name, expected in EXPECTED_LATE_DELAY_ANCHORS.items():
        actual = getattr(summary, field_name)
        if actual is None or float(actual) != float(expected):
            raise DeliveryReviewDeepeningError(
                f"fixed-snapshot anchor changed: {field_name}"
            )


def _assert_exact(name: str, actual: Any, expected: Any) -> None:
    if _as_decimal(actual, column=name) != _as_decimal(expected, column=name):
        raise DeliveryReviewDeepeningError(
            f"pandas and SQL exact values differ for {name}"
        )


def _assert_exact_decimal(name: str, actual: Any, expected: Any) -> None:
    actual_decimal = _as_decimal(actual, column=name)
    expected_decimal = _as_decimal(expected, column=name)
    if actual_decimal != expected_decimal:
        raise DeliveryReviewDeepeningError(
            f"pandas and SQL exact decimal values differ for {name}"
        )


def _assert_derived_float(name: str, actual: Any, expected: Any) -> None:
    # pandas represents SQL NULL medians as NaN in a numeric baseline column.
    actual_missing = pd.isna(actual)
    expected_missing = pd.isna(expected)
    if actual_missing or expected_missing:
        if actual_missing and expected_missing:
            return
        raise DeliveryReviewDeepeningError(
            f"pandas and SQL derived values differ for {name}"
        )
    if not math.isclose(
        float(actual),
        float(expected),
        rel_tol=0.0,
        abs_tol=FLOAT_ABS_TOLERANCE,
    ):
        raise DeliveryReviewDeepeningError(
            f"pandas and SQL derived values differ for {name}"
        )


def reconcile_with_database(
    summary: DeepeningSummary, baselines: DatabaseBaselines
) -> None:
    overall_exact = {
        "total_orders": summary.total_orders,
        "distinct_orders": summary.total_orders,
        "review_row_count": summary.review_row_count,
        "review_score_sum": summary.review_score_sum,
        "low_score_order_count": summary.low_score_order_count,
        "chronology_inversion_order_count": summary.chronology_inversion_order_count,
    }
    for key, actual in overall_exact.items():
        _assert_exact(f"overall.{key}", actual, baselines.overall[key])
    _assert_exact_decimal(
        "overall.order_review_score_sum",
        summary.order_review_score_sum,
        baselines.overall["order_review_score_sum"],
    )
    _assert_derived_float(
        "overall.mean_review_score",
        summary.overall_mean_review_score,
        _as_decimal(
            baselines.overall["order_review_score_sum"],
            column="overall.order_review_score_sum",
        )
        / Decimal(int(baselines.overall["total_orders"])),
    )
    _assert_derived_float(
        "overall.median_review_score",
        summary.overall_median_review_score,
        baselines.overall["overall_median_review_score"],
    )
    _assert_derived_float(
        "overall.low_score_rate",
        summary.overall_low_score_rate,
        int(baselines.overall["low_score_order_count"])
        / int(baselines.overall["total_orders"]),
    )
    for field_name in (
        "late_delay_p25",
        "late_delay_median",
        "late_delay_p75",
    ):
        _assert_derived_float(
            f"overall.{field_name}",
            getattr(summary, field_name),
            baselines.overall[field_name],
        )
    if summary.late_delay_max is None:
        if baselines.overall["late_delay_max"] is not None:
            raise DeliveryReviewDeepeningError(
                "pandas and SQL late-delay max differ"
            )
    else:
        _assert_exact(
            "overall.late_delay_max",
            summary.late_delay_max,
            baselines.overall["late_delay_max"],
        )
    for flag, null_count in summary.inversion_flag_null_counts:
        _assert_exact(
            f"overall.{flag}_null_count",
            null_count,
            baselines.overall[f"{flag}_null_count"],
        )

    sql_severity = baselines.severity.set_index("severity_group")
    if set(sql_severity.index) != set(SEVERITY_ORDER):
        raise DeliveryReviewDeepeningError(
            "SQL severity baseline does not contain the approved groups"
        )
    for group in summary.severity:
        baseline = sql_severity.loc[group.name]
        for field_name in (
            "order_count",
            "review_row_count",
            "review_score_sum",
            "low_score_order_count",
        ):
            _assert_exact(
                f"severity.{group.name}.{field_name}",
                getattr(group, field_name),
                baseline[field_name],
            )
        _assert_exact_decimal(
            f"severity.{group.name}.order_review_score_sum",
            group.order_review_score_sum,
            baseline["order_review_score_sum"],
        )
        sql_count = int(baseline["order_count"])
        sql_score_sum = _as_decimal(
            baseline["order_review_score_sum"],
            column=f"severity.{group.name}.order_review_score_sum",
        )
        _assert_derived_float(
            f"severity.{group.name}.order_share",
            group.order_share,
            sql_count / int(baselines.overall["total_orders"]),
        )
        _assert_derived_float(
            f"severity.{group.name}.mean_review_score",
            group.mean_review_score,
            _mean_from_sum(sql_score_sum, sql_count),
        )
        _assert_derived_float(
            f"severity.{group.name}.median_review_score",
            group.median_review_score,
            baseline["median_review_score"],
        )
        _assert_derived_float(
            f"severity.{group.name}.low_score_rate",
            group.low_score_rate,
            _ratio(int(baseline["low_score_order_count"]), sql_count),
        )

    sql_monthly = baselines.monthly.copy()
    sql_monthly["purchase_month"] = pd.to_datetime(sql_monthly["purchase_month"])
    sql_monthly = sql_monthly.set_index("purchase_month")
    pandas_months = tuple(month.purchase_month for month in summary.monthly)
    if tuple(sql_monthly.index) != APPROVED_MONTHS or pandas_months != APPROVED_MONTHS:
        raise DeliveryReviewDeepeningError(
            "pandas or SQL monthly keys differ from the approved 18 months"
        )
    for month in summary.monthly:
        baseline = sql_monthly.loc[month.purchase_month]
        for field_name in (
            "order_count",
            "late_order_count",
            "not_late_order_count",
            "review_row_count",
            "review_score_sum",
        ):
            _assert_exact(
                f"monthly.{month.purchase_month:%Y-%m}.{field_name}",
                getattr(month, field_name),
                baseline[field_name],
            )
        _assert_exact(
            f"monthly.{month.purchase_month:%Y-%m}.distinct_orders",
            month.order_count,
            baseline["distinct_orders"],
        )
        for field_name in (
            "late_order_review_score_sum",
            "not_late_order_review_score_sum",
        ):
            _assert_exact_decimal(
                f"monthly.{month.purchase_month:%Y-%m}.{field_name}",
                getattr(month, field_name),
                baseline[field_name],
            )
        sql_late_count = int(baseline["late_order_count"])
        sql_not_late_count = int(baseline["not_late_order_count"])
        sql_late_sum = _as_decimal(
            baseline["late_order_review_score_sum"],
            column="monthly.late_order_review_score_sum",
        )
        sql_not_late_sum = _as_decimal(
            baseline["not_late_order_review_score_sum"],
            column="monthly.not_late_order_review_score_sum",
        )
        sql_late_mean = _mean_from_sum(sql_late_sum, sql_late_count)
        sql_not_late_mean = _mean_from_sum(
            sql_not_late_sum, sql_not_late_count
        )
        sql_gap = (
            sql_late_mean - sql_not_late_mean
            if sql_late_mean is not None and sql_not_late_mean is not None
            else None
        )
        derived = {
            "late_rate": _ratio(sql_late_count, int(baseline["order_count"])),
            "late_mean_review_score": sql_late_mean,
            "not_late_mean_review_score": sql_not_late_mean,
            "mean_score_gap": sql_gap,
        }
        for field_name, expected in derived.items():
            _assert_derived_float(
                f"monthly.{month.purchase_month:%Y-%m}.{field_name}",
                getattr(month, field_name),
                expected,
            )

    sql_sensitivity = baselines.sensitivity.set_index("cohort_name")
    expected_cohorts = {cohort.name for cohort in summary.sensitivity}
    if set(sql_sensitivity.index) != expected_cohorts:
        raise DeliveryReviewDeepeningError(
            "pandas and SQL sensitivity cohorts differ"
        )
    for cohort in summary.sensitivity:
        baseline = sql_sensitivity.loc[cohort.name]
        for field_name in (
            "order_count",
            "late_order_count",
            "not_late_order_count",
            "review_row_count",
            "review_score_sum",
        ):
            _assert_exact(
                f"sensitivity.{cohort.name}.{field_name}",
                getattr(cohort, field_name),
                baseline[field_name],
            )
        _assert_exact(
            f"sensitivity.{cohort.name}.distinct_orders",
            cohort.order_count,
            baseline["distinct_orders"],
        )
        for field_name in (
            "late_order_review_score_sum",
            "not_late_order_review_score_sum",
        ):
            _assert_exact_decimal(
                f"sensitivity.{cohort.name}.{field_name}",
                getattr(cohort, field_name),
                baseline[field_name],
            )
        sql_late_count = int(baseline["late_order_count"])
        sql_not_late_count = int(baseline["not_late_order_count"])
        sql_late_mean = _mean_from_sum(
            _as_decimal(
                baseline["late_order_review_score_sum"],
                column="sensitivity.late_order_review_score_sum",
            ),
            sql_late_count,
        )
        sql_not_late_mean = _mean_from_sum(
            _as_decimal(
                baseline["not_late_order_review_score_sum"],
                column="sensitivity.not_late_order_review_score_sum",
            ),
            sql_not_late_count,
        )
        sql_gap = (
            sql_late_mean - sql_not_late_mean
            if sql_late_mean is not None and sql_not_late_mean is not None
            else None
        )
        derived = {
            "late_rate": _ratio(sql_late_count, int(baseline["order_count"])),
            "late_mean_review_score": sql_late_mean,
            "not_late_mean_review_score": sql_not_late_mean,
            "mean_score_gap": sql_gap,
        }
        for field_name, expected in derived.items():
            _assert_derived_float(
                f"sensitivity.{cohort.name}.{field_name}",
                getattr(cohort, field_name),
                expected,
            )


def _severity_markdown_rows(summary: DeepeningSummary) -> str:
    rows = [
        "| "
        + " | ".join(
            (
                "전체 final cohort",
                f"{summary.total_orders:,}",
                "100.00%",
                f"{summary.overall_mean_review_score:.2f}",
                f"{summary.overall_median_review_score:.2f}",
                f"{summary.overall_low_score_rate:.2%}",
            )
        )
        + " |"
    ]
    for group in summary.severity:
        rows.append(
            "| "
            + " | ".join(
                (
                    SEVERITY_LABELS[group.name],
                    f"{group.order_count:,}",
                    f"{group.order_share:.2%}",
                    _format_optional(group.mean_review_score, ".2f"),
                    _format_optional(group.median_review_score, ".2f"),
                    _format_optional(group.low_score_rate, ".2%"),
                )
            )
            + " |"
        )
    return "\n".join(rows)


def _monthly_markdown_rows(summary: DeepeningSummary) -> str:
    rows = []
    for month in summary.monthly:
        rows.append(
            "| "
            + " | ".join(
                (
                    month.purchase_month.strftime("%Y-%m"),
                    f"{month.order_count:,}",
                    f"{month.late_order_count:,}",
                    _format_optional(month.late_rate, ".2%"),
                    _format_optional(month.not_late_mean_review_score, ".2f"),
                    _format_optional(month.late_mean_review_score, ".2f"),
                    _format_optional(month.mean_score_gap, ".2f"),
                )
            )
            + " |"
        )
    return "\n".join(rows)


def _sensitivity_markdown_rows(summary: DeepeningSummary) -> str:
    labels = {
        "all_orders": "전체 final cohort",
        "without_chronology_inversions": "chronology 역전 제외",
    }
    rows = []
    for cohort in summary.sensitivity:
        rows.append(
            "| "
            + " | ".join(
                (
                    labels[cohort.name],
                    f"{cohort.order_count:,}",
                    f"{cohort.late_order_count:,}",
                    _format_optional(cohort.late_rate, ".2%"),
                    _format_optional(cohort.not_late_mean_review_score, ".4f"),
                    _format_optional(cohort.late_mean_review_score, ".4f"),
                    _format_optional(cohort.mean_score_gap, ".4f"),
                )
            )
            + " |"
        )
    return "\n".join(rows)


def _format_optional(value: float | None, specification: str) -> str:
    if value is None:
        return "N/A"
    return format(value, specification)


def _severity_shape_note(summary: DeepeningSummary) -> str:
    late_groups = [
        summary.severity_group(name)
        for name in ("late_1_3", "late_4_7", "late_8_14", "late_15_plus")
    ]
    means = [group.mean_review_score for group in late_groups]
    if any(value is None for value in means):
        return "빈 지연 구간이 있어 구간 간 단조성은 판단하지 않았다."
    numeric_means = [float(value) for value in means if value is not None]
    late_8_14_mean = numeric_means[2]
    late_15_plus_mean = numeric_means[3]
    values = (
        f"8–14일 지연 평균은 {late_8_14_mean:.2f}점, 15일 이상은 "
        f"{late_15_plus_mean:.2f}점이었다."
    )
    if math.isclose(
        late_8_14_mean,
        late_15_plus_mean,
        rel_tol=0.0,
        abs_tol=FLOAT_ABS_TOLERANCE,
    ):
        return values + " 두 긴 지연 구간 평균은 같아 마지막 구간에서 plateau를 보였다."
    if late_8_14_mean < late_15_plus_mean:
        return (
            values
            + " 8–14일 평균이 조금 더 낮아 지연 구간 전체가 일수와 함께 "
            "엄격하게 단조 악화한 형태는 아니었다."
        )
    if all(
        left > right
        for left, right in zip(numeric_means, numeric_means[1:], strict=True)
    ):
        return values + " 네 late 구간 평균은 이 고정 snapshot에서 순서대로 낮아졌다."
    return (
        values
        + " 마지막 구간 평균은 더 낮았지만, 네 late 구간 전체는 엄격한 단조 감소 "
        "형태가 아니었다."
    )


def render_report(summary: DeepeningSummary) -> str:
    all_orders = summary.sensitivity_cohort("all_orders")
    without_inversions = summary.sensitivity_cohort(
        "without_chronology_inversions"
    )
    longest_delay = summary.severity_group("late_15_plus")
    comparable_months = [
        month for month in summary.monthly if month.mean_score_gap is not None
    ]
    negative_months = sum(
        month.mean_score_gap is not None and month.mean_score_gap < 0
        for month in comparable_months
    )
    longest_mean = longest_delay.mean_review_score
    not_late_mean = all_orders.not_late_mean_review_score
    if longest_mean is not None and not_late_mean is not None:
        headline_difference = abs(longest_mean - not_late_mean)
        if math.isclose(
            headline_difference,
            0.0,
            rel_tol=0.0,
            abs_tol=FLOAT_ABS_TOLERANCE,
        ):
            headline = (
                f"15일 이상 지연 그룹 {longest_delay.order_count:,}건과 전체 "
                f"not-late의 주문 동일가중 평균 리뷰는 모두 {longest_mean:.2f}점이었다."
            )
        else:
            headline_direction = "낮게" if longest_mean < not_late_mean else "높게"
            headline = (
                f"15일 이상 지연 그룹 {longest_delay.order_count:,}건의 주문 동일가중 "
                f"평균 리뷰는 {longest_mean:.2f}점이었고, 전체 not-late 평균 "
                f"{not_late_mean:.2f}점보다 {headline_difference:.2f}점 "
                f"{headline_direction} 관찰됐다."
            )
    else:
        headline = "15일 이상 지연 또는 not-late 그룹이 비어 평균 비교는 N/A다."
    severity_shape_note = _severity_shape_note(summary)
    if (
        all_orders.mean_score_gap is not None
        and without_inversions.mean_score_gap is not None
    ):
        sensitivity_delta = (
            without_inversions.mean_score_gap - all_orders.mean_score_gap
        )
        sensitivity_sentence = (
            f"전체 평균 차이는 {all_orders.mean_score_gap:.4f}점, 역전 제외 후 "
            f"{without_inversions.mean_score_gap:.4f}점으로 {sensitivity_delta:+.4f}점 "
            "변했다."
        )
    else:
        sensitivity_sentence = "비교 그룹이 비어 평균 차이 변화는 N/A다."
    return f"""# 배송 지연 강도·시점 안정성 분석 결과

## 분석 질문과 대상

배송 지연 강도에 따라 주문 동일가중 평균 리뷰가 어떻게 달라지는지, 기존
late-vs-not-late 차이가 비교 가능한 구매월 구간에서도 같은 방향으로 관찰되는지
확인했다.

입력은 검증된 `{SOURCE_RELATION}` 한 개이며 한 행은 배송 완료·날짜 비교 가능·리뷰 보유
주문 1건이다. 전체 final cohort는 {summary.total_orders:,}건이다. 지연 강도는 예정일 대비
달력 날짜 차이로 정의하며 총 배송 소요일을 뜻하지 않는다.

## 한 줄 결과

{headline} 평균 차이를 계산할 수 있는 승인 비교 기간 {len(comparable_months)}개월 중
{negative_months}개월에서 late 평균이 not-late 평균보다 낮았다. 이는 기술통계이며 배송
지연의 인과 효과가 아니다.

## 1. 배송 지연 강도별 리뷰

![배송 지연 강도별 주문 리뷰](figures/delivery-review-delay-severity.png)

| 배송 상태·지연 강도 | 주문 수 | 전체 비중 | 평균 리뷰 | 중앙값 | 주문 평균 2점 이하 비율 |
|---|---:|---:|---:|---:|---:|
{_severity_markdown_rows(summary)}

- `early`는 예정일 전 배송, `promised_date`는 예정일 당일 배송이다.
- late 구간은 1–3일, 4–7일, 8–14일, 15일 이상으로 사전에 고정했다.
- 평균과 중앙값은 원천 리뷰 행이 아니라 주문 안에서 먼저 평균된 값을 주문별로 동일
  가중한 결과다.
- 평균 2점 이하 비율의 분모는 각 구간 주문 수다.
- {severity_shape_note}

## 2. 구매월별 late-vs-not-late 안정성

![구매월별 지연률과 리뷰 평균 차이](figures/delivery-review-monthly-stability.png)

주 분석 기간은 원천 coverage 경계를 제외한 2017-02부터 2018-07 구매월이다. 월별
지연률 분모는 해당 월 final cohort이며, 점수 차이는 `late 평균 - not-late 평균`이다.

| 구매월 | 전체 주문 | late 주문 | late 비율 | not-late 평균 | late 평균 | 평균 차이 |
|---|---:|---:|---:|---:|---:|---:|
{_monthly_markdown_rows(summary)}

월별 결과가 같은 방향이라고 해서 계절, 판매자·상품 구성이나 지역 차이가 통제됐다는
뜻은 아니다. 월별 표본 수와 final cohort의 선택 조건을 함께 봐야 한다.

## 3. Chronology sensitivity

원천 timestamp의 논리적 순서 역전 flag가 하나라도 true인
{summary.chronology_inversion_order_count:,}건을 제외한 뒤 같은 headline 지표를 다시
계산했다. 승인·출고 timestamp가 없다는 missing flag만으로는 제외하지 않았다.

| cohort | 주문 수 | late 주문 | late 비율 | not-late 평균 | late 평균 | 평균 차이 |
|---|---:|---:|---:|---:|---:|---:|
{_sensitivity_markdown_rows(summary)}

{sensitivity_sentence} 이 비교는 결과의 민감도를 확인하는 절차다.
역전 flag가 있는 행을 업무 오류라고 판정하거나 기본 cohort에서 삭제하는 정책 변경이
아니다.

## 계산·검증 기준

- 전체 {summary.total_orders:,}건, 리뷰 원천 {summary.review_row_count:,}행, 리뷰 점수 합
  {summary.review_score_sum:,}, 주문별 평균 점수 합을 severity 그룹과 SQL baseline에 exact 대사
- severity 각 구간과 월별 집계의 주문 수·리뷰 행 수·점수 합·주문별 평균 점수 합을
  SQL과 exact 대사
- 비율과 평균은 exact 분자·분모에서 각각 다시 계산하고, 중앙값 등 파생 실수의 표현
  일치에만 절대 오차 `1e-12` 적용
- 지연 일수 anchor `p25=3`, `median=7`, `p75=13`, `max=188` 재현 확인
- 같은 `repeatable read`, `read only` transaction에서 mart와 독립 SQL baseline을 조회
- 보고서와 차트에는 주문 ID, 리뷰 원문이나 행 단위 데이터를 포함하지 않음

## 해석과 한계

- 리뷰가 있고 배송일을 비교할 수 있는 delivered 주문만 포함하므로 선택 편향이 있을 수
  있다. 기존 검증에서 late 그룹의 리뷰 coverage가 상대적으로 낮았다.
- 지연 일수는 총 배송 기간이 아니라 실제 배송일과 예정일의 달력 날짜 차이다.
- 구간 경계와 평균 2점 이하 기준은 설명을 위한 분석 정책이며 업무상 절대 기준이 아니다.
- 판매자·카테고리·상품·지역과 계절 같은 교란요인을 통제하지 않았다.
- 심한 지연 구간의 표본 수가 작으면 평균과 비율이 불안정할 수 있어 주문 수를 함께
  표시했다.
- 통계적 유의성, 예측 성능이나 인과 효과를 검정하지 않았다.
- chronology 제외 결과는 민감도 확인이며 해당 행을 오류로 판정한 결과가 아니다.
- 2016–2018년 고정 Olist 공개 데이터의 기술통계로 현재 시장 전체를 대표하지 않는다.

## 재현 방법

로컬 PostgreSQL에 검증된 mart가 구축되고 `.env`가 준비된 상태에서 실행한다.

```bash
.venv/bin/python scripts/analyze_delivery_review_deepening.py build
.venv/bin/python scripts/analyze_delivery_review_deepening.py check
```

`build`는 SQL↔pandas 대사가 통과한 뒤 이 보고서와 차트 2개를 임시 위치에 모두 만든 후
교체한다. `check`는 같은 입력과 고정 의존성 환경에서 다시 만든 산출물이 기존 파일과
같은지 확인하며 기존 파일을 수정하지 않는다.
"""


def create_severity_figure(summary: DeepeningSummary) -> plt.Figure:
    labels = [SEVERITY_LABELS[group.name] for group in summary.severity]
    means = [
        group.mean_review_score
        if group.mean_review_score is not None
        else math.nan
        for group in summary.severity
    ]
    colors = [SEVERITY_COLORS[group.name] for group in summary.severity]

    fig, ax = plt.subplots(figsize=(11, 6.2))
    bars = ax.bar(labels, means, color=colors, edgecolor="white", width=0.68)
    median_positions = [
        index
        for index, group in enumerate(summary.severity)
        if group.median_review_score is not None
    ]
    ax.scatter(
        median_positions,
        [summary.severity[index].median_review_score for index in median_positions],
        marker="D",
        s=48,
        color="#222222",
        label="Median",
        zorder=3,
        clip_on=False,
    )
    for bar, group in zip(bars, summary.severity, strict=True):
        if group.mean_review_score is None:
            annotation = "N/A\nn=0\n<=2: N/A"
            annotation_height = 0.15
        else:
            annotation = (
                f"mean {group.mean_review_score:.2f}\n"
                f"n={group.order_count:,}\n"
                f"<=2: {_format_optional(group.low_score_rate, '.1%')}"
            )
            annotation_height = min(group.mean_review_score + 0.12, 4.85)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            annotation_height,
            annotation,
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )
    ax.set_ylim(0, 5)
    ax.set_yticks(range(0, 6))
    ax.set_ylabel("Order-weighted review score (1-5)")
    ax.set_xlabel("Delivery timing relative to promised date")
    ax.set_title(
        "Review scores by delivery delay severity",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=16,
    )
    ax.legend(frameon=False, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", rotation=12)
    fig.text(
        0.01,
        0.01,
        (
            "Cohort: delivered orders with comparable dates and reviews. "
            "Bars show means; diamonds show medians. Descriptive, not causal."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return fig


def create_monthly_stability_figure(summary: DeepeningSummary) -> plt.Figure:
    labels = [month.purchase_month.strftime("%Y-%m") for month in summary.monthly]
    positions = list(range(len(labels)))
    late_rates = [
        month.late_rate * 100 if month.late_rate is not None else math.nan
        for month in summary.monthly
    ]
    gaps = [
        month.mean_score_gap if month.mean_score_gap is not None else math.nan
        for month in summary.monthly
    ]

    fig, (rate_ax, gap_ax) = plt.subplots(
        2,
        1,
        figsize=(12, 7.4),
        sharex=True,
        gridspec_kw={"height_ratios": (1, 1.25)},
    )
    rate_ax.plot(
        positions,
        late_rates,
        color="#E9783A",
        marker="o",
        linewidth=2,
    )
    rate_ax.fill_between(positions, late_rates, color="#FCE1D4", alpha=0.8)
    finite_late_rates = [value for value in late_rates if math.isfinite(value)]
    rate_upper = max(finite_late_rates) * 1.2 if finite_late_rates else 1.0
    rate_ax.set_ylim(0, max(rate_upper, 1.0))
    rate_ax.set_ylabel("Late orders (%)")
    rate_ax.set_title(
        "Monthly late rate and observed review-score gap",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    rate_ax.spines[["top", "right"]].set_visible(False)
    rate_ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)

    colors = [
        "#C44E52" if math.isfinite(gap) and gap < 0 else "#4C78A8"
        for gap in gaps
    ]
    gap_ax.bar(positions, gaps, color=colors, edgecolor="white")
    gap_ax.axhline(0, color="#222222", linewidth=1)
    gap_ax.set_ylim(-5, 5)
    gap_ax.set_ylabel("Late minus not-late mean score")
    gap_ax.set_xlabel("Purchase month")
    gap_ax.set_xticks(positions, labels, rotation=45, ha="right")
    gap_ax.spines[["top", "right"]].set_visible(False)
    gap_ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    rate_ax.set_axisbelow(True)
    gap_ax.set_axisbelow(True)
    fig.text(
        0.01,
        0.01,
        (
            "Purchase months 2017-02 to 2018-07. Denominator: monthly final cohort. "
            "Negative gap means the late-group mean was lower. Descriptive, not causal."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def _save_figure(figure: plt.Figure, path: Path) -> None:
    figure.savefig(
        path,
        format="png",
        dpi=160,
        facecolor="white",
        metadata={"Software": "ecommerce-analytics-pipeline"},
    )
    plt.close(figure)


def write_artifacts(summary: DeepeningSummary, reports_dir: Path) -> None:
    figures_dir = reports_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / REPORT_FILE).write_text(
        render_report(summary), encoding="utf-8"
    )
    _save_figure(
        create_severity_figure(summary), reports_dir / SEVERITY_FIGURE
    )
    _save_figure(
        create_monthly_stability_figure(summary), reports_dir / MONTHLY_FIGURE
    )


def build_artifacts(summary: DeepeningSummary, reports_dir: Path) -> None:
    reports_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="delivery-review-deepening-", dir=reports_dir.parent
    ) as temporary_directory:
        temporary_reports = Path(temporary_directory) / "reports"
        write_artifacts(summary, temporary_reports)
        backup_root = Path(temporary_directory) / "backups"
        replaced: list[Path] = []
        existing_targets: set[Path] = set()
        for relative_path in ARTIFACT_FILES:
            target = reports_dir / relative_path
            if target.is_file():
                existing_targets.add(relative_path)
                backup = backup_root / relative_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
        try:
            for relative_path in ARTIFACT_FILES:
                source = temporary_reports / relative_path
                target = reports_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)
                replaced.append(relative_path)
        except OSError:
            for relative_path in reversed(replaced):
                target = reports_dir / relative_path
                if relative_path in existing_targets:
                    shutil.copy2(backup_root / relative_path, target)
                else:
                    target.unlink(missing_ok=True)
            raise


def check_artifacts(summary: DeepeningSummary, reports_dir: Path) -> None:
    with tempfile.TemporaryDirectory(
        prefix="delivery-review-deepening-check-", dir=reports_dir.parent
    ) as temporary_directory:
        temporary_reports = Path(temporary_directory) / "reports"
        write_artifacts(summary, temporary_reports)
        mismatches = []
        for relative_path in ARTIFACT_FILES:
            expected = reports_dir / relative_path
            actual = temporary_reports / relative_path
            if not expected.is_file() or not filecmp.cmp(
                expected, actual, shallow=False
            ):
                mismatches.append(str(relative_path))
        if mismatches:
            raise DeliveryReviewDeepeningError(
                "committed deepening artifacts are stale or missing: "
                + ", ".join(mismatches)
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or check the delivery-review deepening analysis"
    )
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPOSITORY_ROOT / "reports",
        help="artifact root used by build/check (default: repository reports directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv(REPOSITORY_ROOT / ".env")
    try:
        config = DatabaseConfig.from_environment()
        with connect_database(config) as connection:
            frame, baselines = load_analysis_snapshot(connection)
        validated = validate_analysis_frame(frame)
        summary = summarize_deepening(validated)
        reconcile_with_database(summary, baselines)
        validate_expected_snapshot(summary)
        if args.command == "build":
            build_artifacts(summary, args.reports_dir)
        else:
            check_artifacts(summary, args.reports_dir)
    except DeliveryReviewDeepeningError as exc:
        print(f"delivery-review deepening failed: {exc}", file=sys.stderr)
        return 1

    all_orders = summary.sensitivity_cohort("all_orders")
    print(
        "delivery-review deepening passed: "
        f"orders={summary.total_orders}, months={len(summary.monthly)}, "
        f"late_rate={all_orders.late_rate:.8f}, "
        f"score_gap={all_orders.mean_score_gap:.8f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
