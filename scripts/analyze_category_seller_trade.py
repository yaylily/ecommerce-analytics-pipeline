#!/usr/bin/env python3
"""Analyze validated category and seller trade marts with pandas."""

from __future__ import annotations

import argparse
import filecmp
import os
import sys
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

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

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATEGORY_RELATION = "analytics.mart_category_trade_monthly"
SELLER_RELATION = "analytics.mart_seller_trade_monthly"
REPORT_FILE = Path("category-seller-analysis.md")
OVERVIEW_FIGURE = Path("figures/category-seller-monthly-overview.png")
CATEGORY_FIGURE = Path("figures/category-seller-category-mix.png")
CONCENTRATION_FIGURE = Path("figures/category-seller-concentration.png")
ARTIFACT_FILES = (
    REPORT_FILE,
    OVERVIEW_FIGURE,
    CATEGORY_FIGURE,
    CONCENTRATION_FIGURE,
)
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PRIMARY_START = pd.Timestamp("2017-02-01")
PRIMARY_END_EXCLUSIVE = pd.Timestamp("2018-08-01")
PRIMARY_MONTHS = tuple(
    pd.date_range(
        PRIMARY_START,
        PRIMARY_END_EXCLUSIVE - pd.offsets.MonthBegin(1),
        freq="MS",
    )
)
OTHER_GROUP_KEY = "__other__"
OTHER_GROUP_LABEL = "Other"
MAPPING_STATUSES = ("mapped", "missing_source", "unmapped_translation")
SHARE_TOLERANCE = Decimal("1e-12")
TOP_CATEGORY_COUNT = 5
TOP_SELLER_COUNT = 10
MONEY_COLUMNS = (
    "gross_item_value",
    "freight_amount",
    "item_side_amount",
)
CATEGORY_REQUIRED_COLUMNS = (
    "purchase_month",
    "category_key",
    "category_display_name",
    "category_mapping_status",
    *MONEY_COLUMNS,
    "ordered_item_row_count",
)
SELLER_REQUIRED_COLUMNS = (
    "purchase_month",
    "seller_id",
    *MONEY_COLUMNS,
    "ordered_item_row_count",
)
EXPECTED_PRIMARY_SNAPSHOT = {
    "month_count": 18,
    "category_row_count": 1132,
    "seller_row_count": 14458,
    "ordered_item_row_count": 101825,
    "gross_item_value": Decimal("12230652.13"),
    "freight_amount": Decimal("2029493.87"),
    "item_side_amount": Decimal("14260146.00"),
}
EXPECTED_TOP_CATEGORY_KEYS = (
    "beleza_saude",
    "relogios_presentes",
    "cama_mesa_banho",
    "esporte_lazer",
    "informatica_acessorios",
)
CATEGORY_COLORS = (
    "#4C78A8",
    "#F58518",
    "#E45756",
    "#72B7B2",
    "#54A24B",
    "#BAB0AC",
)
CONCENTRATION_SERIES = (
    ("top1_share", "Top 1", "#4C78A8", "o"),
    ("top10_share", "Top 10", "#F58518", "s"),
    ("top10_percent_share", "Top 10%", "#54A24B", "^"),
)


class CategorySellerAnalysisError(RuntimeError):
    """Expected analysis failure that is safe to display."""


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
            raise CategorySellerAnalysisError(
                "PGPASSWORD is required; copy .env.example to .env and set a local password"
            )
        host = os.environ.get("PGHOST", "127.0.0.1")
        if host.lower() not in LOCAL_DATABASE_HOSTS:
            raise CategorySellerAnalysisError("PGHOST must be a local loopback host")
        raw_port = os.environ.get("PGPORT", "55432")
        try:
            port = int(raw_port)
        except ValueError:
            raise CategorySellerAnalysisError("PGPORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise CategorySellerAnalysisError("PGPORT must be between 1 and 65535")
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
            "application_name": "ecommerce_analytics_category_seller_analysis",
        }


@dataclass(frozen=True)
class SqlBaselines:
    monthly_totals: pd.DataFrame
    top_categories: pd.DataFrame
    category_mix: pd.DataFrame
    seller_concentration: pd.DataFrame
    mapping_summary: pd.DataFrame


@dataclass(frozen=True)
class TradeAnalysisResult:
    monthly_overview: pd.DataFrame
    category_mix: pd.DataFrame
    seller_concentration: pd.DataFrame
    mapping_summary: pd.DataFrame
    top_categories: pd.DataFrame
    period_gross_item_value: Decimal
    period_freight_amount: Decimal
    period_item_side_amount: Decimal
    period_ordered_item_row_count: int
    category_row_count: int
    seller_row_count: int


def connect_database(config: DatabaseConfig) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(**config.connection_kwargs())
    except psycopg.Error as exc:
        raise CategorySellerAnalysisError(
            f"database connection failed: {type(exc).__name__}"
        ) from None


def _fetch_query_frame(
    connection: psycopg.Connection[Any],
    query: str,
    params: tuple[Any, ...] = (),
) -> pd.DataFrame:
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [column.name for column in cursor.description or ()]
    except psycopg.Error as exc:
        raise CategorySellerAnalysisError(
            f"analysis query failed: {type(exc).__name__}"
        ) from None
    return pd.DataFrame.from_records(rows, columns=columns)


def _fetch_category_frame(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    return _fetch_query_frame(
        connection,
        """
        select
            purchase_month,
            category_key,
            category_display_name,
            category_mapping_status,
            gross_item_value,
            freight_amount,
            item_side_amount,
            ordered_item_row_count
        from analytics.mart_category_trade_monthly
        order by purchase_month, category_key
        """,
    )


def _fetch_seller_frame(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    return _fetch_query_frame(
        connection,
        """
        select
            purchase_month,
            seller_id,
            gross_item_value,
            freight_amount,
            item_side_amount,
            ordered_item_row_count
        from analytics.mart_seller_trade_monthly
        order by purchase_month, seller_id
        """,
    )


def _fetch_sql_baselines(connection: psycopg.Connection[Any]) -> SqlBaselines:
    period_params = (PRIMARY_START.date(), PRIMARY_END_EXCLUSIVE.date())
    monthly_totals = _fetch_query_frame(
        connection,
        """
        with category as (
            select
                purchase_month,
                count(*)::bigint as category_row_count,
                sum(gross_item_value) as category_gross_item_value,
                sum(freight_amount) as category_freight_amount,
                sum(item_side_amount) as category_item_side_amount,
                sum(ordered_item_row_count)::bigint as category_item_row_count
            from analytics.mart_category_trade_monthly
            group by purchase_month
        ), seller as (
            select
                purchase_month,
                count(*)::bigint as seller_row_count,
                count(distinct seller_id)::bigint as active_seller_count,
                sum(gross_item_value) as seller_gross_item_value,
                sum(freight_amount) as seller_freight_amount,
                sum(item_side_amount) as seller_item_side_amount,
                sum(ordered_item_row_count)::bigint as seller_item_row_count
            from analytics.mart_seller_trade_monthly
            group by purchase_month
        )
        select
            coalesce(category.purchase_month, seller.purchase_month) as purchase_month,
            category.category_row_count,
            seller.seller_row_count,
            seller.active_seller_count,
            category.category_gross_item_value,
            seller.seller_gross_item_value,
            category.category_freight_amount,
            seller.seller_freight_amount,
            category.category_item_side_amount,
            seller.seller_item_side_amount,
            category.category_item_row_count,
            seller.seller_item_row_count
        from category
        full outer join seller using (purchase_month)
        order by purchase_month
        """,
    )
    top_categories = _fetch_query_frame(
        connection,
        """
        select
            category_key,
            min(category_display_name) as category_display_name,
            sum(gross_item_value) as gross_item_value
        from analytics.mart_category_trade_monthly
        where purchase_month >= %s
          and purchase_month < %s
          and category_mapping_status = 'mapped'
        group by category_key
        order by gross_item_value desc, category_key asc
        limit 5
        """,
        period_params,
    )
    category_mix = _fetch_query_frame(
        connection,
        """
        with ranked_categories as (
            select
                category_key,
                row_number() over (
                    order by sum(gross_item_value) desc, category_key asc
                ) as category_rank
            from analytics.mart_category_trade_monthly
            where purchase_month >= %s
              and purchase_month < %s
              and category_mapping_status = 'mapped'
            group by category_key
        ), top_categories as (
            select category_key
            from ranked_categories
            where category_rank <= 5
        ), observed_months as (
            select distinct purchase_month
            from analytics.mart_category_trade_monthly
            where purchase_month >= %s
              and purchase_month < %s
        ), group_keys as (
            select category_key as group_key
            from top_categories
            union all
            select '__other__' as group_key
        ), grouped as (
            select
                mart.purchase_month,
                case
                    when top_categories.category_key is null then '__other__'
                    else mart.category_key
                end as group_key,
                sum(mart.gross_item_value) as gross_item_value
            from analytics.mart_category_trade_monthly as mart
            left join top_categories using (category_key)
            where mart.purchase_month >= %s
              and mart.purchase_month < %s
            group by mart.purchase_month, group_key
        )
        select
            observed_months.purchase_month,
            group_keys.group_key,
            coalesce(grouped.gross_item_value, 0::numeric) as gross_item_value
        from observed_months
        cross join group_keys
        left join grouped
            on observed_months.purchase_month = grouped.purchase_month
            and group_keys.group_key = grouped.group_key
        order by observed_months.purchase_month, group_keys.group_key
        """,
        (*period_params, *period_params, *period_params),
    )
    seller_concentration = _fetch_query_frame(
        connection,
        """
        with ranked as (
            select
                purchase_month,
                seller_id,
                gross_item_value,
                row_number() over (
                    partition by purchase_month
                    order by gross_item_value desc, seller_id asc
                ) as seller_rank,
                count(*) over (
                    partition by purchase_month
                )::bigint as active_seller_count,
                sum(gross_item_value) over (
                    partition by purchase_month
                ) as total_gross_item_value
            from analytics.mart_seller_trade_monthly
            where purchase_month >= %s
              and purchase_month < %s
        )
        select
            purchase_month,
            max(active_seller_count)::bigint as active_seller_count,
            max(total_gross_item_value) as total_gross_item_value,
            sum(gross_item_value) filter (
                where seller_rank <= 1
            ) as top1_gross_item_value,
            sum(gross_item_value) filter (
                where seller_rank <= 10
            ) as top10_gross_item_value,
            greatest(
                1,
                ceil(max(active_seller_count) * 0.10)::bigint
            ) as top10_percent_seller_count,
            sum(gross_item_value) filter (
                where seller_rank <= greatest(
                    1,
                    ceil(active_seller_count * 0.10)::bigint
                )
            ) as top10_percent_gross_item_value
        from ranked
        group by purchase_month
        order by purchase_month
        """,
        period_params,
    )
    mapping_summary = _fetch_query_frame(
        connection,
        """
        select
            category_mapping_status,
            sum(gross_item_value) as gross_item_value,
            sum(ordered_item_row_count)::bigint as ordered_item_row_count
        from analytics.mart_category_trade_monthly
        where purchase_month >= %s
          and purchase_month < %s
        group by category_mapping_status
        order by category_mapping_status
        """,
        period_params,
    )
    return SqlBaselines(
        monthly_totals=monthly_totals,
        top_categories=top_categories,
        category_mix=category_mix,
        seller_concentration=seller_concentration,
        mapping_summary=mapping_summary,
    )


def load_analysis_snapshot(
    connection: psycopg.Connection[Any],
) -> tuple[pd.DataFrame, pd.DataFrame, SqlBaselines]:
    """Read both marts and independent SQL aggregates from one snapshot."""

    try:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            category_frame = _fetch_category_frame(connection)
            seller_frame = _fetch_seller_frame(connection)
            baselines = _fetch_sql_baselines(connection)
    except psycopg.Error as exc:
        raise CategorySellerAnalysisError(
            f"read-only snapshot failed: {type(exc).__name__}"
        ) from None
    return category_frame, seller_frame, baselines


def _as_decimal(value: Any, column: str) -> Decimal:
    if isinstance(value, bool):
        raise CategorySellerAnalysisError(f"{column} contains a boolean")
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise CategorySellerAnalysisError(
            f"{column} contains a non-numeric value"
        ) from None
    if not converted.is_finite():
        raise CategorySellerAnalysisError(f"{column} contains a non-finite value")
    return converted


def _as_positive_integer(value: Any, column: str) -> int:
    decimal_value = _as_decimal(value, column)
    if decimal_value != decimal_value.to_integral_value() or decimal_value <= 0:
        raise CategorySellerAnalysisError(f"{column} must contain positive integers")
    return int(decimal_value)


def _normalize_months(series: pd.Series, frame_name: str) -> pd.Series:
    try:
        converted = pd.to_datetime(series, errors="raise")
    except (TypeError, ValueError):
        raise CategorySellerAnalysisError(
            f"{frame_name} purchase_month contains an invalid date"
        ) from None
    normalized = converted.dt.tz_localize(None).dt.normalize()
    if not normalized.dt.day.eq(1).all():
        raise CategorySellerAnalysisError(
            f"{frame_name} purchase_month must contain month-start dates"
        )
    return normalized


def _validate_text_column(frame: pd.DataFrame, column: str, frame_name: str) -> None:
    if not frame[column].map(lambda value: isinstance(value, str) and bool(value)).all():
        raise CategorySellerAnalysisError(
            f"{frame_name} {column} must contain non-empty text"
        )


def _validate_common_measures(frame: pd.DataFrame, frame_name: str) -> None:
    for column in MONEY_COLUMNS:
        frame[column] = frame[column].map(lambda value: _as_decimal(value, column))
    frame["ordered_item_row_count"] = frame["ordered_item_row_count"].map(
        lambda value: _as_positive_integer(value, "ordered_item_row_count")
    )
    if not frame["gross_item_value"].map(lambda value: value > 0).all():
        raise CategorySellerAnalysisError(
            f"{frame_name} gross_item_value must be positive"
        )
    if not frame["freight_amount"].map(lambda value: value >= 0).all():
        raise CategorySellerAnalysisError(
            f"{frame_name} freight_amount must be non-negative"
        )
    expected_item_side = frame["gross_item_value"] + frame["freight_amount"]
    if not frame["item_side_amount"].eq(expected_item_side).all():
        raise CategorySellerAnalysisError(
            f"{frame_name} item_side_amount does not equal gross plus freight"
        )


def _require_primary_months(months: Iterable[pd.Timestamp], frame_name: str) -> None:
    observed = set(months)
    missing = [month for month in PRIMARY_MONTHS if month not in observed]
    if missing:
        formatted = ", ".join(month.strftime("%Y-%m") for month in missing)
        raise CategorySellerAnalysisError(
            f"{frame_name} is missing approved primary months: {formatted}"
        )


def validate_analysis_frames(
    category_frame: pd.DataFrame, seller_frame: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fail closed when either mart no longer matches the approved contract."""

    missing_category = [
        column for column in CATEGORY_REQUIRED_COLUMNS if column not in category_frame
    ]
    missing_seller = [
        column for column in SELLER_REQUIRED_COLUMNS if column not in seller_frame
    ]
    if missing_category:
        raise CategorySellerAnalysisError(
            "category input is missing required columns: " + ", ".join(missing_category)
        )
    if missing_seller:
        raise CategorySellerAnalysisError(
            "seller input is missing required columns: " + ", ".join(missing_seller)
        )
    if category_frame.empty or seller_frame.empty:
        raise CategorySellerAnalysisError("category and seller inputs must be non-empty")

    category = category_frame.loc[:, CATEGORY_REQUIRED_COLUMNS].copy()
    seller = seller_frame.loc[:, SELLER_REQUIRED_COLUMNS].copy()
    if category.isna().any().any():
        raise CategorySellerAnalysisError("category input contains NULL contract values")
    if seller.isna().any().any():
        raise CategorySellerAnalysisError("seller input contains NULL contract values")

    category["purchase_month"] = _normalize_months(category["purchase_month"], "category")
    seller["purchase_month"] = _normalize_months(seller["purchase_month"], "seller")
    for column in ("category_key", "category_display_name", "category_mapping_status"):
        _validate_text_column(category, column, "category")
    _validate_text_column(seller, "seller_id", "seller")

    if category.duplicated(["purchase_month", "category_key"]).any():
        raise CategorySellerAnalysisError(
            "category input contains duplicate purchase_month/category_key"
        )
    if seller.duplicated(["purchase_month", "seller_id"]).any():
        raise CategorySellerAnalysisError(
            "seller input contains duplicate purchase_month/seller_id"
        )
    if not category["category_mapping_status"].isin(MAPPING_STATUSES).all():
        raise CategorySellerAnalysisError(
            "category input contains an unapproved mapping status"
        )
    if set(category["category_mapping_status"].unique()) != set(MAPPING_STATUSES):
        raise CategorySellerAnalysisError(
            "category input must preserve all approved mapping states"
        )

    category_identity_count = category.groupby("category_key", sort=False).agg(
        display_count=("category_display_name", "nunique"),
        status_count=("category_mapping_status", "nunique"),
    )
    if not (
        category_identity_count["display_count"].eq(1)
        & category_identity_count["status_count"].eq(1)
    ).all():
        raise CategorySellerAnalysisError(
            "a category_key maps to multiple labels or mapping states"
        )

    _validate_common_measures(category, "category")
    _validate_common_measures(seller, "seller")
    category_months = set(category["purchase_month"])
    seller_months = set(seller["purchase_month"])
    if category_months != seller_months:
        raise CategorySellerAnalysisError(
            "category and seller inputs contain different observed months"
        )
    _require_primary_months(category_months, "category input")
    _require_primary_months(seller_months, "seller input")

    return (
        category.sort_values(["purchase_month", "category_key"]).reset_index(drop=True),
        seller.sort_values(["purchase_month", "seller_id"]).reset_index(drop=True),
    )


def _sum_decimal(values: Iterable[Decimal]) -> Decimal:
    return sum(values, Decimal("0"))


def _assert_share_sum(values: Iterable[Decimal], label: str) -> None:
    total = _sum_decimal(values)
    if abs(total - Decimal("1")) > SHARE_TOLERANCE:
        raise CategorySellerAnalysisError(f"{label} shares do not sum to one")


def _primary_slice(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[
        frame["purchase_month"].ge(PRIMARY_START)
        & frame["purchase_month"].lt(PRIMARY_END_EXCLUSIVE)
    ].copy()


def _aggregate_monthly(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby("purchase_month", sort=True, observed=True)
        .agg(
            gross_item_value=("gross_item_value", "sum"),
            freight_amount=("freight_amount", "sum"),
            item_side_amount=("item_side_amount", "sum"),
            ordered_item_row_count=("ordered_item_row_count", "sum"),
        )
        .reset_index()
    )


def _assert_monthly_reconciliation(
    category: pd.DataFrame, seller: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    category_monthly = _aggregate_monthly(category)
    seller_monthly = _aggregate_monthly(seller)
    if not category_monthly["purchase_month"].equals(seller_monthly["purchase_month"]):
        raise CategorySellerAnalysisError("category and seller monthly keys differ")
    for column in (*MONEY_COLUMNS, "ordered_item_row_count"):
        if not category_monthly[column].eq(seller_monthly[column]).all():
            raise CategorySellerAnalysisError(
                f"category and seller monthly totals differ for {column}"
            )
    return category_monthly, seller_monthly


def _select_top_categories(category_primary: pd.DataFrame) -> pd.DataFrame:
    candidates = category_primary.loc[
        category_primary["category_mapping_status"].eq("mapped")
    ]
    totals = (
        candidates.groupby(
            ["category_key", "category_display_name"], sort=False, observed=True
        )["gross_item_value"]
        .sum()
        .reset_index()
        .sort_values(
            ["gross_item_value", "category_key"],
            ascending=[False, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    if len(totals) < TOP_CATEGORY_COUNT:
        raise CategorySellerAnalysisError("fewer than five mapped categories are available")
    selected = totals.head(TOP_CATEGORY_COUNT).copy()
    selected["category_rank"] = range(1, TOP_CATEGORY_COUNT + 1)
    return selected


def add_change_contributions(category_mix: pd.DataFrame) -> pd.DataFrame:
    """Add calendar-month changes without treating a missing month as zero."""

    result = category_mix.copy()
    result["change_contribution"] = None
    for indices in result.groupby("group_key", sort=False).groups.values():
        previous_month: pd.Timestamp | None = None
        previous_value: Decimal | None = None
        for index in indices:
            current_month = result.at[index, "purchase_month"]
            current_value = result.at[index, "gross_item_value"]
            if (
                previous_month is not None
                and current_month == previous_month + pd.offsets.MonthBegin(1)
            ):
                result.at[index, "change_contribution"] = (
                    current_value - previous_value
                )
            previous_month = current_month
            previous_value = current_value
    return result


def _build_category_mix(
    category_primary: pd.DataFrame,
    monthly_overview: pd.DataFrame,
    top_categories: pd.DataFrame,
) -> pd.DataFrame:
    top_keys = tuple(top_categories["category_key"])
    label_by_key = dict(
        zip(
            top_categories["category_key"],
            top_categories["category_display_name"],
            strict=True,
        )
    )
    working = category_primary.copy()
    working["group_key"] = working["category_key"].where(
        working["category_key"].isin(top_keys), OTHER_GROUP_KEY
    )
    grouped = (
        working.groupby(["purchase_month", "group_key"], sort=False, observed=True)[
            "gross_item_value"
        ]
        .sum()
        .reindex(
            pd.MultiIndex.from_product(
                [PRIMARY_MONTHS, (*top_keys, OTHER_GROUP_KEY)],
                names=["purchase_month", "group_key"],
            ),
            fill_value=Decimal("0"),
        )
        .rename("gross_item_value")
        .reset_index()
    )
    monthly_totals = monthly_overview.set_index("purchase_month")["gross_item_value"]
    grouped["month_total_gross_item_value"] = grouped["purchase_month"].map(
        monthly_totals
    )
    if grouped["month_total_gross_item_value"].map(lambda value: value <= 0).any():
        raise CategorySellerAnalysisError("category share denominator must be positive")
    grouped["share"] = grouped.apply(
        lambda row: row["gross_item_value"] / row["month_total_gross_item_value"],
        axis=1,
    )
    grouped["group_label"] = grouped["group_key"].map(label_by_key).fillna(
        OTHER_GROUP_LABEL
    )
    group_rank = {
        key: rank for rank, key in enumerate((*top_keys, OTHER_GROUP_KEY), start=1)
    }
    grouped["group_rank"] = grouped["group_key"].map(group_rank)
    grouped = grouped.sort_values(["purchase_month", "group_rank"]).reset_index(
        drop=True
    )

    grouped = add_change_contributions(grouped)

    for month, month_rows in grouped.groupby("purchase_month", sort=True):
        _assert_share_sum(month_rows["share"], f"category mix {month:%Y-%m}")
    return grouped


def _build_seller_concentration(
    seller_primary: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for month, month_rows in seller_primary.groupby(
        "purchase_month", sort=True, observed=True
    ):
        ranked = month_rows.sort_values(
            ["gross_item_value", "seller_id"],
            ascending=[False, True],
            kind="mergesort",
        ).reset_index(drop=True)
        active_seller_count = len(ranked)
        if active_seller_count == 0:
            raise CategorySellerAnalysisError("seller concentration month is empty")
        total = _sum_decimal(ranked["gross_item_value"])
        if total <= 0:
            raise CategorySellerAnalysisError(
                "seller concentration denominator must be positive"
            )
        exhaustive_shares = [value / total for value in ranked["gross_item_value"]]
        _assert_share_sum(exhaustive_shares, f"seller exhaustive {month:%Y-%m}")

        top10_count = min(TOP_SELLER_COUNT, active_seller_count)
        top10_percent_count = max(1, (active_seller_count + 9) // 10)
        top1_amount = ranked.loc[:0, "gross_item_value"].sum()
        top10_amount = ranked.loc[: top10_count - 1, "gross_item_value"].sum()
        top10_percent_amount = ranked.loc[
            : top10_percent_count - 1, "gross_item_value"
        ].sum()
        record = {
            "purchase_month": month,
            "active_seller_count": active_seller_count,
            "total_gross_item_value": total,
            "top1_seller_count": 1,
            "top10_seller_count": top10_count,
            "top10_percent_seller_count": top10_percent_count,
            "top1_gross_item_value": top1_amount,
            "top10_gross_item_value": top10_amount,
            "top10_percent_gross_item_value": top10_percent_amount,
            "top1_share": top1_amount / total,
            "top10_share": top10_amount / total,
            "top10_percent_share": top10_percent_amount / total,
        }
        if not (
            Decimal("0")
            <= record["top1_share"]
            <= record["top10_share"]
            <= Decimal("1")
        ):
            raise CategorySellerAnalysisError("seller Top 1/Top 10 shares are invalid")
        if not (
            Decimal("0")
            <= record["top1_share"]
            <= record["top10_percent_share"]
            <= Decimal("1")
        ):
            raise CategorySellerAnalysisError(
                "seller Top 1/Top 10% shares are invalid"
            )
        records.append(record)
    return pd.DataFrame.from_records(records)


def _build_mapping_summary(category_primary: pd.DataFrame) -> pd.DataFrame:
    summary = (
        category_primary.groupby("category_mapping_status", sort=False, observed=True)
        .agg(
            gross_item_value=("gross_item_value", "sum"),
            ordered_item_row_count=("ordered_item_row_count", "sum"),
        )
        .reindex(MAPPING_STATUSES)
        .reset_index()
    )
    if summary.isna().any().any():
        raise CategorySellerAnalysisError("one category mapping state is missing")
    gross_total = _sum_decimal(summary["gross_item_value"])
    row_total = int(summary["ordered_item_row_count"].sum())
    summary["gross_item_value_share"] = summary["gross_item_value"].map(
        lambda value: value / gross_total
    )
    summary["ordered_item_row_share"] = summary["ordered_item_row_count"].map(
        lambda value: Decimal(int(value)) / Decimal(row_total)
    )
    _assert_share_sum(summary["gross_item_value_share"], "mapping gross")
    _assert_share_sum(summary["ordered_item_row_share"], "mapping rows")
    return summary


def _validate_change_decomposition(
    monthly_overview: pd.DataFrame, category_mix: pd.DataFrame
) -> None:
    totals = monthly_overview.set_index("purchase_month")["gross_item_value"]
    for position, month in enumerate(PRIMARY_MONTHS):
        rows = category_mix.loc[category_mix["purchase_month"].eq(month)]
        contributions = rows["change_contribution"]
        if position == 0:
            if contributions.notna().any():
                raise CategorySellerAnalysisError(
                    "first primary month contribution must be N/A"
                )
            continue
        if contributions.isna().any():
            raise CategorySellerAnalysisError(
                f"category contribution is missing for {month:%Y-%m}"
            )
        expected_change = totals.loc[month] - totals.loc[PRIMARY_MONTHS[position - 1]]
        if _sum_decimal(contributions) != expected_change:
            raise CategorySellerAnalysisError(
                f"category change contributions do not reconcile for {month:%Y-%m}"
            )


def summarize_trades(
    category: pd.DataFrame, seller: pd.DataFrame
) -> TradeAnalysisResult:
    category_monthly, _ = _assert_monthly_reconciliation(category, seller)
    category_primary = _primary_slice(category)
    seller_primary = _primary_slice(seller)
    primary_monthly = category_monthly.loc[
        category_monthly["purchase_month"].isin(PRIMARY_MONTHS)
    ].copy()
    active_sellers = (
        seller_primary.groupby("purchase_month", sort=True, observed=True)["seller_id"]
        .size()
        .rename("active_seller_count")
    )
    monthly_overview = primary_monthly.merge(
        active_sellers,
        left_on="purchase_month",
        right_index=True,
        how="left",
        validate="one_to_one",
    ).sort_values("purchase_month").reset_index(drop=True)
    if tuple(monthly_overview["purchase_month"]) != PRIMARY_MONTHS:
        raise CategorySellerAnalysisError("primary monthly overview is incomplete")

    top_categories = _select_top_categories(category_primary)
    category_mix = _build_category_mix(
        category_primary, monthly_overview, top_categories
    )
    seller_concentration = _build_seller_concentration(seller_primary)
    mapping_summary = _build_mapping_summary(category_primary)
    _validate_change_decomposition(monthly_overview, category_mix)

    return TradeAnalysisResult(
        monthly_overview=monthly_overview,
        category_mix=category_mix,
        seller_concentration=seller_concentration,
        mapping_summary=mapping_summary,
        top_categories=top_categories,
        period_gross_item_value=_sum_decimal(category_primary["gross_item_value"]),
        period_freight_amount=_sum_decimal(category_primary["freight_amount"]),
        period_item_side_amount=_sum_decimal(category_primary["item_side_amount"]),
        period_ordered_item_row_count=int(
            category_primary["ordered_item_row_count"].sum()
        ),
        category_row_count=len(category_primary),
        seller_row_count=len(seller_primary),
    )


def _normalize_baseline_frame(
    frame: pd.DataFrame,
    *,
    date_columns: tuple[str, ...] = (),
    decimal_columns: tuple[str, ...] = (),
    integer_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    normalized = frame.copy()
    for column in date_columns:
        normalized[column] = pd.to_datetime(normalized[column]).dt.normalize()
    for column in decimal_columns:
        normalized[column] = normalized[column].map(
            lambda value: _as_decimal(value, column)
        )
    for column in integer_columns:
        normalized[column] = normalized[column].map(int)
    return normalized


def _assert_records_equal(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    actual_records = list(actual.loc[:, columns].itertuples(index=False, name=None))
    expected_records = list(expected.loc[:, columns].itertuples(index=False, name=None))
    if actual_records != expected_records:
        raise CategorySellerAnalysisError(f"pandas and SQL differ for {label}")


def reconcile_with_database(
    category: pd.DataFrame,
    seller: pd.DataFrame,
    result: TradeAnalysisResult,
    baselines: SqlBaselines,
) -> None:
    monthly = _normalize_baseline_frame(
        baselines.monthly_totals,
        date_columns=("purchase_month",),
        decimal_columns=(
            "category_gross_item_value",
            "seller_gross_item_value",
            "category_freight_amount",
            "seller_freight_amount",
            "category_item_side_amount",
            "seller_item_side_amount",
        ),
        integer_columns=(
            "category_row_count",
            "seller_row_count",
            "active_seller_count",
            "category_item_row_count",
            "seller_item_row_count",
        ),
    )
    category_monthly = _aggregate_monthly(category)
    seller_monthly = _aggregate_monthly(seller)
    category_counts = (
        category.groupby("purchase_month", sort=True)
        .size()
        .rename("category_row_count")
        .reset_index()
    )
    seller_counts = (
        seller.groupby("purchase_month", sort=True)
        .size()
        .rename("seller_row_count")
        .reset_index()
    )
    actual_monthly = category_monthly.rename(
        columns={
            "gross_item_value": "category_gross_item_value",
            "freight_amount": "category_freight_amount",
            "item_side_amount": "category_item_side_amount",
            "ordered_item_row_count": "category_item_row_count",
        }
    ).merge(
        seller_monthly.rename(
            columns={
                "gross_item_value": "seller_gross_item_value",
                "freight_amount": "seller_freight_amount",
                "item_side_amount": "seller_item_side_amount",
                "ordered_item_row_count": "seller_item_row_count",
            }
        ),
        on="purchase_month",
        how="outer",
        validate="one_to_one",
    )
    actual_monthly = actual_monthly.merge(
        category_counts,
        on="purchase_month",
        how="outer",
        validate="one_to_one",
    ).merge(
        seller_counts,
        on="purchase_month",
        how="outer",
        validate="one_to_one",
    )
    actual_monthly["active_seller_count"] = actual_monthly["seller_row_count"]
    actual_monthly = actual_monthly.sort_values("purchase_month").reset_index(drop=True)
    monthly_columns = tuple(monthly.columns)
    _assert_records_equal(actual_monthly, monthly, monthly_columns, "monthly totals")

    sql_top = _normalize_baseline_frame(
        baselines.top_categories,
        decimal_columns=("gross_item_value",),
    ).sort_values(
        ["gross_item_value", "category_key"],
        ascending=[False, True],
        kind="mergesort",
    )
    pandas_top = result.top_categories.sort_values("category_rank")
    _assert_records_equal(
        pandas_top,
        sql_top,
        ("category_key", "category_display_name", "gross_item_value"),
        "fixed Top 5 categories",
    )

    sql_mix = _normalize_baseline_frame(
        baselines.category_mix,
        date_columns=("purchase_month",),
        decimal_columns=("gross_item_value",),
    ).sort_values(["purchase_month", "group_key"])
    pandas_mix = result.category_mix.sort_values(["purchase_month", "group_key"])
    _assert_records_equal(
        pandas_mix,
        sql_mix,
        ("purchase_month", "group_key", "gross_item_value"),
        "category mix",
    )

    sql_seller = _normalize_baseline_frame(
        baselines.seller_concentration,
        date_columns=("purchase_month",),
        decimal_columns=(
            "total_gross_item_value",
            "top1_gross_item_value",
            "top10_gross_item_value",
            "top10_percent_gross_item_value",
        ),
        integer_columns=("active_seller_count", "top10_percent_seller_count"),
    ).sort_values("purchase_month")
    pandas_seller = result.seller_concentration.sort_values("purchase_month")
    _assert_records_equal(
        pandas_seller,
        sql_seller,
        (
            "purchase_month",
            "active_seller_count",
            "total_gross_item_value",
            "top1_gross_item_value",
            "top10_gross_item_value",
            "top10_percent_seller_count",
            "top10_percent_gross_item_value",
        ),
        "seller concentration",
    )

    sql_mapping = _normalize_baseline_frame(
        baselines.mapping_summary,
        decimal_columns=("gross_item_value",),
        integer_columns=("ordered_item_row_count",),
    ).sort_values("category_mapping_status")
    pandas_mapping = result.mapping_summary.sort_values("category_mapping_status")
    _assert_records_equal(
        pandas_mapping,
        sql_mapping,
        ("category_mapping_status", "gross_item_value", "ordered_item_row_count"),
        "category mapping states",
    )


def validate_expected_snapshot(result: TradeAnalysisResult) -> None:
    observed = {
        "month_count": len(result.monthly_overview),
        "category_row_count": result.category_row_count,
        "seller_row_count": result.seller_row_count,
        "ordered_item_row_count": result.period_ordered_item_row_count,
        "gross_item_value": result.period_gross_item_value,
        "freight_amount": result.period_freight_amount,
        "item_side_amount": result.period_item_side_amount,
    }
    for key, expected in EXPECTED_PRIMARY_SNAPSHOT.items():
        if observed[key] != expected:
            raise CategorySellerAnalysisError(
                f"fixed snapshot regression failed for {key}"
            )
    if tuple(result.top_categories.sort_values("category_rank")["category_key"]) != (
        EXPECTED_TOP_CATEGORY_KEYS
    ):
        raise CategorySellerAnalysisError(
            "fixed snapshot regression failed for Top 5 categories"
        )


def _format_amount(value: Decimal) -> str:
    return f"{value:,.2f}"


def _largest_monthly_change(result: TradeAnalysisResult) -> tuple[pd.Timestamp, Decimal, str, Decimal]:
    overview = result.monthly_overview.copy()
    overview["monthly_change"] = overview["gross_item_value"].diff()
    candidates = overview.dropna(subset=["monthly_change"]).copy()
    largest_index = candidates["monthly_change"].map(abs).idxmax()
    row = candidates.loc[largest_index]
    month = row["purchase_month"]
    month_groups = result.category_mix.loc[
        result.category_mix["purchase_month"].eq(month)
    ].dropna(subset=["change_contribution"])
    group_index = month_groups["change_contribution"].map(abs).idxmax()
    group_row = month_groups.loc[group_index]
    return (
        month,
        row["monthly_change"],
        str(group_row["group_label"]),
        group_row["change_contribution"],
    )


def render_report(result: TradeAnalysisResult) -> str:
    top_total = _sum_decimal(result.top_categories["gross_item_value"])
    top_share = top_total / result.period_gross_item_value
    mapping = result.mapping_summary.set_index("category_mapping_status")
    missing_gross_share = mapping.loc[
        "missing_source", "gross_item_value_share"
    ]
    unmapped_gross_share = mapping.loc[
        "unmapped_translation", "gross_item_value_share"
    ]
    missing_row_share = mapping.loc[
        "missing_source", "ordered_item_row_share"
    ]
    unmapped_row_share = mapping.loc[
        "unmapped_translation", "ordered_item_row_share"
    ]
    overview = result.monthly_overview.sort_values("purchase_month").reset_index(
        drop=True
    )
    first_overview = overview.iloc[0]
    last_overview = overview.iloc[-1]
    concentration = result.seller_concentration.sort_values(
        "purchase_month"
    ).reset_index(drop=True)
    first_concentration = concentration.iloc[0]
    last_concentration = concentration.iloc[-1]
    top1_min = min(concentration["top1_share"])
    top1_max = max(concentration["top1_share"])
    top10_min_row = concentration.loc[
        concentration["top10_share"].map(float).idxmin()
    ]
    top10_max_row = concentration.loc[
        concentration["top10_share"].map(float).idxmax()
    ]
    top10_percent_min_row = concentration.loc[
        concentration["top10_percent_share"].map(float).idxmin()
    ]
    top10_percent_max_row = concentration.loc[
        concentration["top10_percent_share"].map(float).idxmax()
    ]
    top5_monthly = (
        result.category_mix.loc[
            result.category_mix["group_key"].ne(OTHER_GROUP_KEY)
        ]
        .groupby("purchase_month", sort=True)["share"]
        .sum()
        .reset_index(name="top5_share")
    )
    top5_min_row = top5_monthly.loc[
        top5_monthly["top5_share"].map(float).idxmin()
    ]
    top5_max_row = top5_monthly.loc[
        top5_monthly["top5_share"].map(float).idxmax()
    ]
    first_top5_share = top5_monthly.iloc[0]["top5_share"]
    last_top5_share = top5_monthly.iloc[-1]["top5_share"]
    active_min = int(result.monthly_overview["active_seller_count"].min())
    active_max = int(result.monthly_overview["active_seller_count"].max())
    change_month, total_change, change_group, group_change = _largest_monthly_change(
        result
    )
    direction = "증가" if total_change > 0 else "감소"
    group_direction = "증가" if group_change > 0 else "감소"

    top_lines = "\n".join(
        f"- {row.category_display_name}: {_format_amount(row.gross_item_value)} "
        f"({row.gross_item_value / result.period_gross_item_value:.2%})"
        for row in result.top_categories.sort_values("category_rank").itertuples()
    )
    return f"""# 카테고리·판매자 거래 분석 결과

## 분석 질문과 대상

배송 완료 주문상품에서 관찰된 상품 거래액이 어떤 카테고리와 익명 판매자군에
집중됐으며, 그 구성과 집중도가 구매월별로 어떻게 달라졌는지 확인했다.

입력은 검증된 `{CATEGORY_RELATION}`과 `{SELLER_RELATION}`이다. 두 mart는 서로
join하지 않고 같은 read-only snapshot에서 각각 읽은 뒤 월별 가산 지표를 대사했다.
주 분석 기간은 원천 coverage 경계를 제외한 **2017년 2월~2018년 7월 18개월**이다.
2016년 9월~2017년 1월과 2018년 8월은 참고 구간이며 아래 결과 계산에는 포함하지
않았다.

## 한 줄 결과

고정 Top 5 카테고리는 주 분석 기간 상품 거래액의 {top_share:.1%}를 차지했다.
Top 5의 월별 합산 비중은 {top5_min_row['top5_share']:.1%}~{top5_max_row['top5_share']:.1%}였고,
판매자 Top 10 비중은 첫 달 {first_concentration['top10_share']:.1%}에서 마지막 달
{last_concentration['top10_share']:.1%}로 달라졌다. 전체 변화를 단일 카테고리나 판매자
한 곳의 결과로 단정하기보다 월별 구성과 집중도를 함께 점검해야 한다.

## 1. 월별 상품 거래액과 활동 판매자 수

![월별 상품 거래액과 활동 판매자 수](figures/category-seller-monthly-overview.png)

- 주 분석 기간 상품 거래액: {_format_amount(result.period_gross_item_value)}
- 별도 배송비: {_format_amount(result.period_freight_amount)}
- 배송 완료 주문상품 행: {result.period_ordered_item_row_count:,}개
- 월별 활동 판매자 수 범위: {active_min:,}~{active_max:,}명
- 첫 달 → 마지막 달 상품 거래액: {_format_amount(first_overview['gross_item_value'])} →
  {_format_amount(last_overview['gross_item_value'])}
- 첫 달 → 마지막 달 활동 판매자 수: {int(first_overview['active_seller_count']):,}명 →
  {int(last_overview['active_seller_count']):,}명

상품 거래액은 `order_items.price`의 합이며 회사 매출·순매출·이익이 아니다. 배송비는
상품 거래액에 섞지 않고 별도 지표로 유지했다. 금액은 원천 데이터와 같은 금액 단위를
사용했다.

## 2. 고정 Top 5 카테고리와 Other 구성

![고정 Top 5 카테고리와 Other의 월별 구성](figures/category-seller-category-mix.png)

Top 5는 주 분석 기간 전체 상품 거래액으로 한 번 선정하고 같은 카테고리를 매월
추적했다. 나머지 카테고리와 원천 category 누락·번역 미연결은 모두 `Other`다.

{top_lines}

월간 상품 거래액의 절대 변화가 가장 컸던 달은 {change_month:%Y년 %m월}로, 직전 달보다
{_format_amount(abs(total_change))} {direction}했다. 같은 산술 분해에서 절대 변화가
가장 큰 고정 그룹은 `{change_group}`이며 {_format_amount(abs(group_change))}
{group_direction}했다. 이는 변화의 원인을 증명하는 기여도가 아니라 후속 점검 순서를
정하기 위한 기술통계다.

Top 5 합산 비중은 첫 달 {first_top5_share:.1%}, 마지막 달 {last_top5_share:.1%}였다.
최저는 {top5_min_row['purchase_month']:%Y년 %m월} {top5_min_row['top5_share']:.1%},
최고는 {top5_max_row['purchase_month']:%Y년 %m월} {top5_max_row['top5_share']:.1%}였다.
고정된 다섯 category를 추적한 구성 변화이며 원인이나 개별 성과를 뜻하지 않는다.

## 3. 익명 판매자군 거래액 집중도

![판매자 Top 1·Top 10·상위 10% 월별 집중도](figures/category-seller-concentration.png)

- 월별 Top 1 비중 범위: {top1_min:.1%}~{top1_max:.1%}
- 월별 Top 10 비중: 최저 {top10_min_row['purchase_month']:%Y년 %m월}
  {top10_min_row['top10_share']:.1%}, 최고 {top10_max_row['purchase_month']:%Y년 %m월}
  {top10_max_row['top10_share']:.1%}
- 월별 상위 10% 비중: 최저 {top10_percent_min_row['purchase_month']:%Y년 %m월}
  {top10_percent_min_row['top10_percent_share']:.1%}, 최고
  {top10_percent_max_row['purchase_month']:%Y년 %m월}
  {top10_percent_max_row['top10_percent_share']:.1%}
- 첫 달 → 마지막 달 상위 10% 비중: {first_concentration['top10_percent_share']:.1%} →
  {last_concentration['top10_percent_share']:.1%}

Top 1·Top 10·상위 10%는 매월 다시 선정했으므로 동일 판매자군의 성장이나 감소를
뜻하지 않는다. 공개 결과에는 판매자 식별자와 상세 위치를 포함하지 않았다.

## category mapping 잔존 상태

주 분석 기간 category mart의 전체 합계를 보존한 상태에서 확인했다.

| 상태 | 상품 거래액 비중 | 주문상품 행 비중 |
|---|---:|---:|
| mapped (번역 연결) | {mapping.loc['mapped', 'gross_item_value_share']:.3%} | {mapping.loc['mapped', 'ordered_item_row_share']:.3%} |
| missing_source (원천 category 누락) | {missing_gross_share:.3%} | {missing_row_share:.3%} |
| unmapped_translation (번역 미연결) | {unmapped_gross_share:.3%} | {unmapped_row_share:.3%} |

누락·미연결 상태를 정상 category로 바꾸거나 분석에서 조용히 제거하지 않았다.

## 계산·검증 기준

- 모집단: `order_status = 'delivered'`인 주문상품
- 월 기준: 주문 구매월
- 고정 Top 5: 승인 기간의 mapped category 상품 거래액 내림차순, 동률은 내부
  `category_key` 오름차순
- 판매자 집중도: 월별 상품 거래액 내림차순, 동률은 내부 `seller_id` 오름차순
- 상위 10% 판매자 수: `max(1, ceil(활동 판매자 수 × 0.10))`
- category·seller mart의 월별 상품 거래액·배송비·상품 측 합계·주문상품 행 수를
  exact 대사
- SQL 기준 Top 5·category 구성·판매자 집중도·mapping 상태 집계와 pandas 결과 대사
- 비중 합은 반올림 전에 `abs(합계 - 1) <= 1e-12`로 검사

## 해석과 활용

고정 Top 5 구성과 판매자 집중도를 함께 보면 월별 상품 거래액 변화가 넓은 그룹에
분산됐는지 일부 그룹과 함께 나타났는지 우선 점검할 수 있다. 후속 분석에서는 큰
월간 변화가 관찰된 카테고리의 주문상품 수·판매자 수·상품 거래액 변화를 분리해
확인하는 것이 우선이다.

## 한계

- 2016~2018년 고정 Olist 공개 snapshot의 기술통계이며 현재 시장을 대표하지 않는다.
- 배송 완료 주문상품만 포함하므로 취소·미완료 주문의 거래 특성을 설명하지 않는다.
- 상품 거래액 변화만으로 수요·재고·프로모션·판매자 성과의 원인을 단정할 수 없다.
- 방문·광고비·원가·환불 자료가 없어 전환·ROAS·이익을 계산하지 않는다.
- 집중도는 점검 신호이며 실제 사업 위험이나 개선 성과를 증명하지 않는다.

## 재현 방법

로컬 PostgreSQL에 검증된 mart가 구축되고 `.env`가 준비된 상태에서 실행한다.

```bash
.venv/bin/python scripts/analyze_category_seller_trade.py build
.venv/bin/python scripts/analyze_category_seller_trade.py check
```

`build`는 SQL↔pandas 대사와 고정 snapshot 검사가 통과한 뒤 보고서와 차트 3개를
생성한다. `check`는 같은 입력과 고정 의존성 환경에서 산출물을 다시 만들어 커밋된
파일과 같은지 확인하며 기존 파일을 수정하지 않는다.
"""


def _month_axis(ax: plt.Axes) -> None:
    ax.set_xticks(PRIMARY_MONTHS[::2])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_xlim(
        PRIMARY_MONTHS[0] - pd.Timedelta(days=15),
        PRIMARY_MONTHS[-1] + pd.Timedelta(days=15),
    )
    ax.tick_params(axis="x", rotation=45)


def create_monthly_overview_figure(result: TradeAnalysisResult) -> plt.Figure:
    months = result.monthly_overview["purchase_month"]
    gross_millions = [
        float(value / Decimal("1000000"))
        for value in result.monthly_overview["gross_item_value"]
    ]
    active_sellers = result.monthly_overview["active_seller_count"]

    fig, (amount_ax, seller_ax) = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [1.4, 1]},
    )
    amount_ax.bar(months, gross_millions, width=20, color="#4C78A8")
    amount_ax.set_ylim(bottom=0)
    amount_ax.set_ylabel("Gross item value (million source units)")
    amount_ax.set_title(
        "Monthly delivered-item trade and active sellers",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    amount_ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    amount_ax.set_axisbelow(True)
    amount_ax.spines[["top", "right"]].set_visible(False)

    seller_ax.plot(
        months,
        active_sellers,
        color="#F58518",
        linewidth=2.2,
        marker="o",
        markersize=4,
    )
    seller_ax.set_ylim(bottom=0)
    seller_ax.set_ylabel("Active sellers")
    seller_ax.set_xlabel("Purchase month")
    seller_ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    seller_ax.set_axisbelow(True)
    seller_ax.spines[["top", "right"]].set_visible(False)
    _month_axis(seller_ax)
    fig.text(
        0.01,
        0.01,
        (
            "Source: Olist public dataset. Primary period: 2017-02 to 2018-07. "
            "Delivered order items only; gross item value excludes freight."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


def create_category_mix_figure(result: TradeAnalysisResult) -> plt.Figure:
    pivot = result.category_mix.pivot(
        index="purchase_month", columns="group_label", values="share"
    )
    ordered_labels = list(
        result.top_categories.sort_values("category_rank")["category_display_name"]
    ) + [OTHER_GROUP_LABEL]
    pivot = pivot.loc[list(PRIMARY_MONTHS), ordered_labels]
    values = [[float(value) * 100 for value in pivot[label]] for label in ordered_labels]

    fig, ax = plt.subplots(figsize=(11, 6.2))
    ax.stackplot(
        pivot.index,
        values,
        labels=ordered_labels,
        colors=CATEGORY_COLORS,
        alpha=0.95,
    )
    ax.set_ylim(0, 100)
    ax.set_ylabel("Monthly gross item value share (%)")
    ax.set_xlabel("Purchase month")
    ax.set_title(
        "Fixed Top 5 categories and Other: monthly composition",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    ax.legend(
        frameon=False,
        ncols=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
    )
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    _month_axis(ax)
    fig.text(
        0.01,
        0.01,
        (
            "Top 5 selected once over 2017-02 to 2018-07. Other includes all "
            "remaining, missing-source, and unmapped-translation categories."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.11, 1, 1))
    return fig


def create_seller_concentration_figure(result: TradeAnalysisResult) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11, 5.8))
    months = result.seller_concentration["purchase_month"]
    for column, label, color, marker in CONCENTRATION_SERIES:
        values = [float(value) * 100 for value in result.seller_concentration[column]]
        ax.plot(
            months,
            values,
            label=label,
            color=color,
            marker=marker,
            linewidth=2.2,
            markersize=4.5,
        )
    ax.set_ylim(0, 100)
    ax.set_ylabel("Monthly gross item value share (%)")
    ax.set_xlabel("Purchase month")
    ax.set_title(
        "Monthly seller concentration",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )
    ax.legend(frameon=False, ncols=3, loc="upper left")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    _month_axis(ax)
    fig.text(
        0.01,
        0.01,
        (
            "Seller groups are re-ranked each month. Top 10% uses "
            "max(1, ceil(active sellers x 0.10)); identifiers are not shown."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
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


def write_artifacts(result: TradeAnalysisResult, reports_dir: Path) -> None:
    figures_dir = reports_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / REPORT_FILE).write_text(render_report(result), encoding="utf-8")
    _save_figure(
        create_monthly_overview_figure(result), reports_dir / OVERVIEW_FIGURE
    )
    _save_figure(create_category_mix_figure(result), reports_dir / CATEGORY_FIGURE)
    _save_figure(
        create_seller_concentration_figure(result),
        reports_dir / CONCENTRATION_FIGURE,
    )


def build_artifacts(result: TradeAnalysisResult, reports_dir: Path) -> None:
    reports_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="category-seller-analysis-", dir=reports_dir.parent
    ) as temporary_directory:
        temporary_reports = Path(temporary_directory) / "reports"
        write_artifacts(result, temporary_reports)
        for relative_path in ARTIFACT_FILES:
            source = temporary_reports / relative_path
            target = reports_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)


def check_artifacts(result: TradeAnalysisResult, reports_dir: Path) -> None:
    with tempfile.TemporaryDirectory(
        prefix="category-seller-analysis-check-", dir=reports_dir.parent
    ) as temporary_directory:
        temporary_reports = Path(temporary_directory) / "reports"
        write_artifacts(result, temporary_reports)
        mismatches = []
        for relative_path in ARTIFACT_FILES:
            expected = reports_dir / relative_path
            actual = temporary_reports / relative_path
            if not expected.is_file() or not filecmp.cmp(
                expected, actual, shallow=False
            ):
                mismatches.append(str(relative_path))
        if mismatches:
            raise CategorySellerAnalysisError(
                "committed analysis artifacts are stale or missing: "
                + ", ".join(mismatches)
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or check the category-seller pandas analysis"
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
            category_frame, seller_frame, baselines = load_analysis_snapshot(
                connection
            )
        category, seller = validate_analysis_frames(category_frame, seller_frame)
        result = summarize_trades(category, seller)
        reconcile_with_database(category, seller, result, baselines)
        validate_expected_snapshot(result)
        if args.command == "build":
            build_artifacts(result, args.reports_dir)
        else:
            check_artifacts(result, args.reports_dir)
    except CategorySellerAnalysisError as exc:
        print(f"category-seller analysis failed: {exc}", file=sys.stderr)
        return 1

    concentration = result.seller_concentration
    print(
        "category-seller analysis passed: "
        f"months={len(result.monthly_overview)}, "
        f"gross_item_value={result.period_gross_item_value}, "
        f"top10_share_range={min(concentration['top10_share']):.8%}-"
        f"{max(concentration['top10_share']):.8%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
