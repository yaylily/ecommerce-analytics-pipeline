#!/usr/bin/env python3
"""Analyze the validated delivery-review mart with pandas."""

from __future__ import annotations

import argparse
import filecmp
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
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
REPORT_FILE = Path("delivery-review-analysis.md")
SHARE_FIGURE = Path("figures/delivery-review-cohort-share.png")
SCORE_FIGURE = Path("figures/delivery-review-average-score.png")
ARTIFACT_FILES = (REPORT_FILE, SHARE_FIGURE, SCORE_FIGURE)
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
GROUP_ORDER = ("not_late", "late")
GROUP_LABELS = {"not_late": "Not late", "late": "Late"}
GROUP_COLORS = {"not_late": "#4C78A8", "late": "#F28E2B"}
GROUP_HATCHES = {"not_late": "", "late": "//"}
REQUIRED_COLUMNS = (
    "order_id",
    "order_status",
    "delivery_days_vs_estimate",
    "delivery_timing_status",
    "is_late",
    "review_count",
    "review_score_sum",
    "order_avg_review_score",
)
EXPECTED_SNAPSHOT_COUNTS = {
    "total_orders": 95824,
    "early_orders": 88163,
    "promised_date_orders": 1280,
    "late_orders": 6381,
    "not_late_orders": 89443,
    "review_row_count": 96353,
    "review_score_sum": 400413,
    "multi_review_order_count": 525,
}
EXPECTED_SNAPSHOT_ROUNDED = {
    "late_rate": 0.06659083,
    "overall_avg_review_score": 4.15615782,
    "not_late_avg_review_score": 4.29058916,
    "late_avg_review_score": 2.27182260,
    "avg_score_difference": -2.01876657,
}
FLOAT_ABS_TOLERANCE = 1e-10


class DeliveryReviewAnalysisError(RuntimeError):
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
            raise DeliveryReviewAnalysisError(
                "PGPASSWORD is required; copy .env.example to .env and set a local password"
            )
        host = os.environ.get("PGHOST", "127.0.0.1")
        if host.lower() not in LOCAL_DATABASE_HOSTS:
            raise DeliveryReviewAnalysisError("PGHOST must be a local loopback host")
        raw_port = os.environ.get("PGPORT", "55432")
        try:
            port = int(raw_port)
        except ValueError:
            raise DeliveryReviewAnalysisError("PGPORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise DeliveryReviewAnalysisError("PGPORT must be between 1 and 65535")
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
            "application_name": "ecommerce_analytics_delivery_review_analysis",
        }


@dataclass(frozen=True)
class DeliveryGroupSummary:
    order_count: int
    order_share: float
    review_row_count: int
    review_score_sum: int
    multi_review_order_count: int
    avg_review_score: float


@dataclass(frozen=True)
class DeliveryReviewSummary:
    total_orders: int
    early_orders: int
    promised_date_orders: int
    review_row_count: int
    review_score_sum: int
    multi_review_order_count: int
    overall_avg_review_score: float
    not_late: DeliveryGroupSummary
    late: DeliveryGroupSummary
    avg_score_difference: float

    @property
    def late_rate(self) -> float:
        return self.late.order_share


def connect_database(config: DatabaseConfig) -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(**config.connection_kwargs())
    except psycopg.Error as exc:
        raise DeliveryReviewAnalysisError(
            f"database connection failed: {type(exc).__name__}"
        ) from None


def _fetch_frame(connection: psycopg.Connection[Any]) -> pd.DataFrame:
    query = """
        select
            order_id,
            order_status,
            delivery_days_vs_estimate,
            delivery_timing_status,
            is_late,
            review_count,
            review_score_sum,
            order_avg_review_score
        from analytics.mart_delivery_review_orders
        order by order_id
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [column.name for column in cursor.description or ()]
    except psycopg.Error as exc:
        raise DeliveryReviewAnalysisError(
            f"mart read failed: {type(exc).__name__}"
        ) from None
    return pd.DataFrame.from_records(rows, columns=columns)


def _fetch_database_summary(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    query = """
        select
            count(*)::bigint as total_orders,
            count(distinct order_id)::bigint as distinct_orders,
            count(*) filter (
                where delivery_timing_status = 'early'
            )::bigint as early_orders,
            count(*) filter (
                where delivery_timing_status = 'promised_date'
            )::bigint as promised_date_orders,
            count(*) filter (where is_late)::bigint as late_orders,
            count(*) filter (where not is_late)::bigint as not_late_orders,
            sum(review_count)::bigint as review_row_count,
            sum(review_score_sum)::bigint as review_score_sum,
            count(*) filter (
                where review_count > 1
            )::bigint as multi_review_order_count,
            avg(order_avg_review_score) as overall_avg_review_score,
            avg(order_avg_review_score) filter (
                where not is_late
            ) as not_late_avg_review_score,
            avg(order_avg_review_score) filter (
                where is_late
            ) as late_avg_review_score
        from analytics.mart_delivery_review_orders
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
            columns = [column.name for column in cursor.description or ()]
    except psycopg.Error as exc:
        raise DeliveryReviewAnalysisError(
            f"database aggregate read failed: {type(exc).__name__}"
        ) from None
    if row is None:
        raise DeliveryReviewAnalysisError("database aggregate query returned no row")
    return dict(zip(columns, row, strict=True))


def load_analysis_snapshot(
    connection: psycopg.Connection[Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read mart rows and the SQL baseline from one read-only snapshot."""

    try:
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            frame = _fetch_frame(connection)
            database_summary = _fetch_database_summary(connection)
    except psycopg.Error as exc:
        raise DeliveryReviewAnalysisError(
            f"read-only snapshot failed: {type(exc).__name__}"
        ) from None
    return frame, database_summary


def validate_analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Fail closed when the final mart no longer matches its approved contract."""

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DeliveryReviewAnalysisError(
            "analysis input is missing required columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise DeliveryReviewAnalysisError("analysis input is empty")

    validated = frame.loc[:, REQUIRED_COLUMNS].copy()
    if validated.isna().any().any():
        raise DeliveryReviewAnalysisError("analysis input contains NULL values")
    if validated["order_id"].duplicated().any():
        raise DeliveryReviewAnalysisError("analysis input contains duplicate order_id")
    if not validated["order_status"].eq("delivered").all():
        raise DeliveryReviewAnalysisError("analysis input contains non-delivered orders")

    numeric_columns = (
        "delivery_days_vs_estimate",
        "review_count",
        "review_score_sum",
        "order_avg_review_score",
    )
    for column in numeric_columns:
        try:
            validated[column] = pd.to_numeric(validated[column], errors="raise")
        except (TypeError, ValueError):
            raise DeliveryReviewAnalysisError(
                f"analysis input contains non-numeric {column}"
            ) from None

    if not validated["is_late"].isin([True, False]).all():
        raise DeliveryReviewAnalysisError("is_late must contain only booleans")
    validated["is_late"] = validated["is_late"].astype(bool)

    allowed_statuses = {"early", "promised_date", "late"}
    if not validated["delivery_timing_status"].isin(allowed_statuses).all():
        raise DeliveryReviewAnalysisError(
            "delivery_timing_status contains an unapproved value"
        )

    expected_status = pd.Series(
        "promised_date", index=validated.index, dtype="object"
    )
    expected_status.loc[validated["delivery_days_vs_estimate"] < 0] = "early"
    expected_status.loc[validated["delivery_days_vs_estimate"] > 0] = "late"
    if not validated["delivery_timing_status"].eq(expected_status).all():
        raise DeliveryReviewAnalysisError(
            "delivery_timing_status does not match delivery day difference"
        )
    if not validated["is_late"].eq(
        validated["delivery_days_vs_estimate"] > 0
    ).all():
        raise DeliveryReviewAnalysisError("is_late does not match delivery day difference")

    if not (validated["review_count"] >= 1).all():
        raise DeliveryReviewAnalysisError("review_count must be at least one")
    if not (validated["review_count"] % 1 == 0).all():
        raise DeliveryReviewAnalysisError("review_count must be an integer")
    if not (
        (validated["review_score_sum"] >= validated["review_count"])
        & (validated["review_score_sum"] <= validated["review_count"] * 5)
    ).all():
        raise DeliveryReviewAnalysisError("review_score_sum is outside the 1-5 domain")
    expected_average = (
        validated["review_score_sum"] / validated["review_count"]
    ).astype(float)
    actual_average = validated["order_avg_review_score"].astype(float)
    if not all(
        math.isclose(actual, expected, rel_tol=0.0, abs_tol=FLOAT_ABS_TOLERANCE)
        for actual, expected in zip(actual_average, expected_average, strict=True)
    ):
        raise DeliveryReviewAnalysisError(
            "order_avg_review_score does not equal score sum divided by review count"
        )
    if set(validated["is_late"].unique()) != {False, True}:
        raise DeliveryReviewAnalysisError(
            "analysis requires both late and not-late orders"
        )
    return validated


def summarize_delivery_reviews(frame: pd.DataFrame) -> DeliveryReviewSummary:
    working = frame.copy()
    working["delivery_group"] = working["is_late"].map(
        {False: "not_late", True: "late"}
    )
    working["is_multi_review"] = working["review_count"] > 1

    grouped = (
        working.groupby("delivery_group", sort=False, observed=True)
        .agg(
            order_count=("order_id", "size"),
            review_row_count=("review_count", "sum"),
            review_score_sum=("review_score_sum", "sum"),
            multi_review_order_count=("is_multi_review", "sum"),
            avg_review_score=("order_avg_review_score", "mean"),
        )
        .reindex(GROUP_ORDER)
    )
    if grouped.isna().any().any():
        raise DeliveryReviewAnalysisError("one delivery comparison group is empty")

    total_orders = int(len(working))

    def group_summary(name: str) -> DeliveryGroupSummary:
        row = grouped.loc[name]
        order_count = int(row["order_count"])
        return DeliveryGroupSummary(
            order_count=order_count,
            order_share=order_count / total_orders,
            review_row_count=int(row["review_row_count"]),
            review_score_sum=int(row["review_score_sum"]),
            multi_review_order_count=int(row["multi_review_order_count"]),
            avg_review_score=float(row["avg_review_score"]),
        )

    not_late = group_summary("not_late")
    late = group_summary("late")
    return DeliveryReviewSummary(
        total_orders=total_orders,
        early_orders=int(working["delivery_timing_status"].eq("early").sum()),
        promised_date_orders=int(
            working["delivery_timing_status"].eq("promised_date").sum()
        ),
        review_row_count=int(working["review_count"].sum()),
        review_score_sum=int(working["review_score_sum"].sum()),
        multi_review_order_count=int(working["is_multi_review"].sum()),
        overall_avg_review_score=float(working["order_avg_review_score"].mean()),
        not_late=not_late,
        late=late,
        avg_score_difference=late.avg_review_score - not_late.avg_review_score,
    )


def reconcile_with_database(
    summary: DeliveryReviewSummary, database_summary: dict[str, Any]
) -> None:
    expected_counts = {
        "total_orders": summary.total_orders,
        "distinct_orders": summary.total_orders,
        "early_orders": summary.early_orders,
        "promised_date_orders": summary.promised_date_orders,
        "late_orders": summary.late.order_count,
        "not_late_orders": summary.not_late.order_count,
        "review_row_count": summary.review_row_count,
        "review_score_sum": summary.review_score_sum,
        "multi_review_order_count": summary.multi_review_order_count,
    }
    for key, expected in expected_counts.items():
        if int(database_summary[key]) != expected:
            raise DeliveryReviewAnalysisError(
                f"pandas and database counts differ for {key}"
            )

    expected_floats = {
        "overall_avg_review_score": summary.overall_avg_review_score,
        "not_late_avg_review_score": summary.not_late.avg_review_score,
        "late_avg_review_score": summary.late.avg_review_score,
    }
    for key, expected in expected_floats.items():
        if not math.isclose(
            float(database_summary[key]),
            expected,
            rel_tol=0.0,
            abs_tol=FLOAT_ABS_TOLERANCE,
        ):
            raise DeliveryReviewAnalysisError(
                f"pandas and database averages differ for {key}"
            )


def validate_expected_snapshot(summary: DeliveryReviewSummary) -> None:
    observed_counts = {
        "total_orders": summary.total_orders,
        "early_orders": summary.early_orders,
        "promised_date_orders": summary.promised_date_orders,
        "late_orders": summary.late.order_count,
        "not_late_orders": summary.not_late.order_count,
        "review_row_count": summary.review_row_count,
        "review_score_sum": summary.review_score_sum,
        "multi_review_order_count": summary.multi_review_order_count,
    }
    for key, expected in EXPECTED_SNAPSHOT_COUNTS.items():
        if observed_counts[key] != expected:
            raise DeliveryReviewAnalysisError(
                f"fixed snapshot regression failed for {key}"
            )

    observed_rounded = {
        "late_rate": round(summary.late_rate, 8),
        "overall_avg_review_score": round(summary.overall_avg_review_score, 8),
        "not_late_avg_review_score": round(summary.not_late.avg_review_score, 8),
        "late_avg_review_score": round(summary.late.avg_review_score, 8),
        "avg_score_difference": round(summary.avg_score_difference, 8),
    }
    for key, expected in EXPECTED_SNAPSHOT_ROUNDED.items():
        if observed_rounded[key] != expected:
            raise DeliveryReviewAnalysisError(
                f"fixed snapshot regression failed for {key}"
            )


def render_report(summary: DeliveryReviewSummary) -> str:
    return f"""# 배송 지연·리뷰 분석 결과

## 분석 질문과 대상

약속한 달력 날짜를 넘긴 주문과 넘기지 않은 주문의 주문별 평균 리뷰 점수(1–5점)를
비교했다.
입력은 검증된 `{SOURCE_RELATION}` 한 개이며, 한 행은 배송 완료·날짜
비교 가능·리뷰 보유 주문 1건이다. 최종 분석 대상은 {summary.total_orders:,}건이다.

비교 불가능한 배송일과 리뷰가 없는 주문은 입력 mart에서 이미 제외돼 있다. 전체 포함·
제외 건수와 upstream 검산은 [배송 지연·리뷰 mart 검증](delivery-review-mart-validation.md)에
기록돼 있다.

## 한 줄 결과

최종 분석 대상에서 지연 주문은 {summary.late.order_count:,}건
({summary.late_rate:.2%})이었다. 지연 주문의 주문 동일가중 평균 리뷰 점수는
{summary.late.avg_review_score:.2f}점, 비지연 주문은
{summary.not_late.avg_review_score:.2f}점으로, 지연 그룹이
{abs(summary.avg_score_difference):.2f}점 낮게 관찰됐다.

이 차이는 관찰된 관계이며 배송 지연의 인과 효과가 아니다.

## 1. 분석 대상 내부의 배송 지연 비율

![분석 대상 내 지연·비지연 주문 비율](figures/delivery-review-cohort-share.png)

- 비지연: {summary.not_late.order_count:,}건
  ({summary.not_late.order_share:.2%})
- 지연: {summary.late.order_count:,}건 ({summary.late.order_share:.2%})
- 비지연은 예정일보다 일찍 도착한 주문과 예정일 당일 도착한 주문을 합친 값이다.

## 2. 배송 지연 여부별 평균 리뷰 점수

![배송 지연 여부별 주문 평균 리뷰 점수](figures/delivery-review-average-score.png)

- 비지연 주문 평균: {summary.not_late.avg_review_score:.2f}점
- 지연 주문 평균: {summary.late.avg_review_score:.2f}점
- 지연 - 비지연 관찰 차이: {summary.avg_score_difference:.2f}점

한 주문에 리뷰가 여러 개 있으면 주문 안에서 먼저 평균을 냈다. 그다음 주문별 평균을
다시 평균해 각 주문에 같은 가중치를 부여했다. 최종 {summary.total_orders:,}건에는 리뷰
원천 {summary.review_row_count:,}행이 연결돼 있으며, 복수 리뷰 주문
{summary.multi_review_order_count:,}건도 주문 1건으로 동일하게 가중됐다.

## 해석

이번 결과는 배송 약속 준수 여부와 리뷰 지표를 함께 모니터링하고, 지연 그룹의 낮은
평가가 어떤 판매자·카테고리·지역에서 반복되는지 후속 진단할 근거가 될 수 있다.
그러나 현재 비교만으로 배송 지연이 점수 차이를 만들었다거나 배송 개선 시 점수가
{abs(summary.avg_score_difference):.2f}점 상승한다고 말할 수는 없다.

## 계산·검증 기준

- 지연: `delivery_days_vs_estimate > 0`
- 비지연: `early + promised_date`
- 지연률 분모: 최종 배송 완료·날짜 비교 가능·리뷰 보유 주문
- 리뷰 평균: 주문 안의 리뷰를 먼저 평균한 뒤 주문을 동일 가중
- SQL 기준 집계와 pandas의 주문 수, 리뷰 행 수, 점수 합과 그룹별 평균을 같은
  read-only snapshot에서 대사
- 고정 Olist snapshot 회귀 수치도 함께 검사

## 실행 결과

- pandas `build`와 `check`: 성공
- 전체 dbt build: 20개 모델과 245개 data test, 총 265개 노드 통과
- PostgreSQL 연동을 포함한 Python unittest: 34개 통과

## 한계

- 리뷰가 있고 배송일을 비교할 수 있는 완료 주문만 포함하므로 선택 편향이 있을 수 있다.
- 배송 지연은 timestamp 시각이 아니라 달력 날짜 기준이다.
- 판매자·카테고리·지역·계절 같은 교란 요인을 통제하지 않았다.
- chronology flag가 있는 주문도 임의로 제거하지 않았다.
- 통계적 유의성이나 인과 효과를 검정하지 않았다.
- 2016–2018년 고정 Olist 공개 데이터의 결과로 현재 시장 전체를 대표하지 않는다.

## 재현 방법

로컬 PostgreSQL에 검증된 mart가 구축되고 `.env`가 준비된 상태에서 실행한다.

```bash
.venv/bin/python scripts/analyze_delivery_reviews.py build
.venv/bin/python scripts/analyze_delivery_reviews.py check
```

`build`는 SQL↔pandas 대사가 통과한 뒤 이 보고서와 차트 2개를 생성한다. `check`는 같은
고정 의존성 환경과 입력에서 다시 만든 산출물이 커밋된 파일과 같은지 확인하며 기존
파일을 수정하지 않는다.
"""


def create_cohort_share_figure(summary: DeliveryReviewSummary) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 3.4))
    left = 0.0
    for group_name in GROUP_ORDER:
        group = getattr(summary, group_name)
        share_percent = group.order_share * 100
        if group_name == "late":
            annotation = f"Late\n{group.order_share:.1%}"
            annotation_size = 9
        else:
            annotation = (
                f"Not late\n{group.order_count:,} ({group.order_share:.1%})"
            )
            annotation_size = 10
        ax.barh(
            [0],
            [share_percent],
            left=left,
            color=GROUP_COLORS[group_name],
            edgecolor="white",
            linewidth=1.2,
            hatch=GROUP_HATCHES[group_name],
            label=GROUP_LABELS[group_name],
        )
        ax.text(
            left + share_percent / 2,
            0,
            annotation,
            ha="center",
            va="center",
            color="white",
            fontsize=annotation_size,
            fontweight="bold",
        )
        left += share_percent

    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.set_xlabel("Share of analysis cohort (%)")
    ax.set_title(
        f"Late orders account for {summary.late_rate:.1%} of the analysis cohort",
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=18,
    )
    ax.legend(frameon=False, ncols=2, loc="upper right", bbox_to_anchor=(1, 1.28))
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color="#D9D9D9", linewidth=0.7)
    ax.set_axisbelow(True)
    fig.text(
        0.01,
        0.02,
        (
            f"Source: Olist public dataset (2016-2018). Cohort: {summary.total_orders:,} "
            f"delivered orders with comparable dates and reviews. "
            f"Late: {summary.late.order_count:,} orders."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    return fig


def create_average_score_figure(summary: DeliveryReviewSummary) -> plt.Figure:
    labels = [GROUP_LABELS[name] for name in GROUP_ORDER]
    groups = [getattr(summary, name) for name in GROUP_ORDER]
    values = [group.avg_review_score for group in groups]
    colors = [GROUP_COLORS[name] for name in GROUP_ORDER]
    hatches = [GROUP_HATCHES[name] for name in GROUP_ORDER]

    fig, ax = plt.subplots(figsize=(8, 5.2))
    bars = ax.bar(labels, values, color=colors, width=0.58, edgecolor="white")
    for bar, hatch, group in zip(bars, hatches, groups, strict=True):
        bar.set_hatch(hatch)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.10,
            f"{group.avg_review_score:.2f}\nn={group.order_count:,}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_ylim(0, 5)
    ax.set_yticks(range(0, 6))
    ax.set_xlabel("Delivery timing group")
    ax.set_ylabel("Order-weighted average review score (1-5)")
    ax.set_title(
        (
            "Observed late-order average is "
            f"{abs(summary.avg_score_difference):.2f} points lower"
        ),
        loc="left",
        fontsize=15,
        fontweight="bold",
        pad=16,
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7)
    ax.set_axisbelow(True)
    fig.text(
        0.01,
        0.01,
        (
            "Source: Olist public dataset (2016-2018). Reviews are averaged within "
            "each order first. Descriptive association; not causal."
        ),
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
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


def write_artifacts(summary: DeliveryReviewSummary, reports_dir: Path) -> None:
    figures_dir = reports_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / REPORT_FILE).write_text(render_report(summary), encoding="utf-8")
    _save_figure(
        create_cohort_share_figure(summary), reports_dir / SHARE_FIGURE
    )
    _save_figure(create_average_score_figure(summary), reports_dir / SCORE_FIGURE)


def build_artifacts(summary: DeliveryReviewSummary, reports_dir: Path) -> None:
    reports_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="delivery-review-analysis-", dir=reports_dir.parent
    ) as temporary_directory:
        temporary_reports = Path(temporary_directory) / "reports"
        write_artifacts(summary, temporary_reports)
        for relative_path in ARTIFACT_FILES:
            source = temporary_reports / relative_path
            target = reports_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)


def check_artifacts(summary: DeliveryReviewSummary, reports_dir: Path) -> None:
    with tempfile.TemporaryDirectory(
        prefix="delivery-review-analysis-check-", dir=reports_dir.parent
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
            raise DeliveryReviewAnalysisError(
                "committed analysis artifacts are stale or missing: "
                + ", ".join(mismatches)
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or check the delivery-review pandas analysis"
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
            frame, database_summary = load_analysis_snapshot(connection)
        validated = validate_analysis_frame(frame)
        summary = summarize_delivery_reviews(validated)
        reconcile_with_database(summary, database_summary)
        validate_expected_snapshot(summary)
        if args.command == "build":
            build_artifacts(summary, args.reports_dir)
        else:
            check_artifacts(summary, args.reports_dir)
    except DeliveryReviewAnalysisError as exc:
        print(f"delivery-review analysis failed: {exc}", file=sys.stderr)
        return 1

    print(
        "delivery-review analysis passed: "
        f"orders={summary.total_orders}, late={summary.late.order_count}, "
        f"not_late={summary.not_late.order_count}, "
        f"difference={summary.avg_score_difference:.8f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
