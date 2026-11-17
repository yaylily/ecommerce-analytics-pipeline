"""Streamlit-only views for the aggregate-backed analysis dashboard."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from dashboard.lib import (
    DashboardData,
    compute_delivery_kpis,
    compute_trade_kpis,
    filter_months,
)


CONCENTRATION_SERIES = {
    "Top 1": "top1_share",
    "Top 10": "top10_share",
    "상위 10%": "top10_percent_share",
}


def _amount(value: Decimal) -> str:
    return f"{value:,.2f}"


def _integer(value: int) -> str:
    return f"{value:,}"


def _percent(value: Decimal | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def _score(value: Decimal | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    specification = "+.2f" if signed else ".2f"
    return f"{format(value, specification)}점"


def _month_options(frame: pd.DataFrame) -> list[str]:
    return sorted(
        frame["purchase_month"].dt.strftime("%Y-%m").unique().tolist()
    )


def _filtered(
    frame: pd.DataFrame, start_month: str, end_month: str
) -> pd.DataFrame | None:
    if start_month > end_month:
        st.warning("시작 월은 종료 월보다 늦을 수 없습니다.")
        return None
    return filter_months(frame, start_month, end_month)


def _render_vega(
    data: pd.DataFrame,
    spec: dict[str, object],
    *,
    alt: str,
    key: str,
    height: int = 330,
) -> None:
    st.vega_lite_chart(
        data,
        spec,
        width="stretch",
        height=height,
        alt=alt,
        key=key,
    )


def _line_spec(
    *,
    title: str,
    x_title: str,
    y_title: str,
    y_field: str = "value",
    series_field: str | None = None,
    y_domain: list[float] | None = None,
    percent_axis: bool = False,
) -> dict[str, object]:
    y: dict[str, object] = {
        "field": y_field,
        "type": "quantitative",
        "title": y_title,
        "axis": {"format": ".0%" if percent_axis else ",.2f"},
    }
    if y_domain is not None:
        y["scale"] = {"domain": y_domain}
    encoding: dict[str, object] = {
        "x": {
            "field": "purchase_month",
            "type": "ordinal",
            "title": x_title,
            "sort": "ascending",
        },
        "y": y,
        "tooltip": [
            {"field": "purchase_month", "type": "nominal", "title": "구매월"},
            {
                "field": y_field,
                "type": "quantitative",
                "title": y_title,
                "format": ".2%" if percent_axis else ",.2f",
            },
        ],
    }
    if series_field is not None:
        encoding["color"] = {
            "field": series_field,
            "type": "nominal",
            "title": "표시 계열",
        }
        encoding["strokeDash"] = {
            "field": series_field,
            "type": "nominal",
            "title": "표시 계열",
        }
        encoding["shape"] = {
            "field": series_field,
            "type": "nominal",
            "title": "표시 계열",
        }
        encoding["tooltip"].insert(1, {  # type: ignore[index, union-attr]
            "field": series_field,
            "type": "nominal",
            "title": "표시 계열",
        })
    return {
        "title": title,
        "mark": {"type": "line", "point": True},
        "encoding": encoding,
    }


def render_trade_tab(data: DashboardData) -> None:
    st.subheader("거래 구성")
    st.caption(
        "배송 완료 주문상품의 상품 거래액·배송비와 익명 판매자군 집중도를 봅니다. "
        "상품 거래액은 회사 매출·순매출·이익이 아닙니다."
    )
    months = _month_options(data.trade_monthly_overview)
    filter_columns = st.columns(2)
    with filter_columns[0]:
        start_month = st.selectbox(
            "거래 시작 월",
            months,
            index=0,
            key="trade_start_month",
        )
    with filter_columns[1]:
        end_month = st.selectbox(
            "거래 종료 월",
            months,
            index=len(months) - 1,
            key="trade_end_month",
        )
    overview = _filtered(data.trade_monthly_overview, start_month, end_month)
    if overview is None:
        return

    kpis = compute_trade_kpis(overview)
    amount_columns = st.columns(2)
    amount_columns[0].metric(
        "상품 거래액",
        _amount(kpis.gross_item_value),
        help="Olist 원천 데이터가 제공하는 금액 값의 합이며 회사 매출·순매출·이익이 아닙니다.",
    )
    amount_columns[1].metric(
        "배송비",
        _amount(kpis.freight_amount),
        help="Olist 원천 데이터의 배송비 값 합계입니다.",
    )
    count_columns = st.columns(2)
    count_columns[0].metric(
        "주문상품 행 수", _integer(kpis.ordered_item_row_count)
    )
    count_columns[1].metric(
        "마지막 월 활동 판매자", _integer(kpis.active_seller_count)
    )
    st.caption(
        f"선택 기간: {start_month}~{end_month} · 금액은 원천 데이터의 금액 단위 · "
        "활동 판매자 수는 기간 합계가 아니라 마지막 선택 월 값"
    )

    gross_chart = overview.loc[:, ["purchase_month", "gross_item_value"]].copy()
    gross_chart["purchase_month"] = gross_chart["purchase_month"].dt.strftime(
        "%Y-%m"
    )
    gross_chart["value"] = gross_chart["gross_item_value"].map(float)
    _render_vega(
        gross_chart,
        _line_spec(
            title="월별 상품 거래액",
            x_title="구매월",
            y_title="상품 거래액 (원천 금액 단위)",
        ),
        alt="선택 기간의 월별 상품 거래액을 나타낸 선 그래프",
        key="trade_monthly_gross_chart",
    )

    category_period = filter_months(data.category_mix, start_month, end_month)
    category_options = (
        category_period.sort_values("group_rank")["group_label"]
        .drop_duplicates()
        .tolist()
    )
    selected_categories = st.multiselect(
        "표시할 category 그룹",
        category_options,
        default=category_options,
        key="trade_category_groups",
    )
    category_exact: pd.DataFrame | None = None
    if not selected_categories:
        st.info("category 구성 차트를 보려면 하나 이상의 그룹을 선택하세요.")
    else:
        category_chart = category_period.loc[
            category_period["group_label"].isin(selected_categories),
            [
                "purchase_month",
                "group_label",
                "group_rank",
                "gross_item_value",
                "share",
            ],
        ].copy()
        category_chart["purchase_month"] = category_chart[
            "purchase_month"
        ].dt.strftime("%Y-%m")
        category_chart["share"] = category_chart["share"].map(float)
        category_chart["gross_item_value"] = category_chart[
            "gross_item_value"
        ].map(float)
        category_exact = category_chart.loc[
            :, ["purchase_month", "group_label", "gross_item_value", "share"]
        ].rename(
            columns={
                "purchase_month": "구매월",
                "group_label": "category 그룹",
                "gross_item_value": "상품 거래액",
                "share": "월 전체 대비 비중",
            }
        )
        _render_vega(
            category_chart,
            {
                "title": "고정 Top 5 category와 Other의 월별 구성",
                "mark": "bar",
                "encoding": {
                    "x": {
                        "field": "purchase_month",
                        "type": "ordinal",
                        "title": "구매월",
                        "sort": "ascending",
                    },
                    "y": {
                        "field": "share",
                        "type": "quantitative",
                        "title": "월 전체 상품 거래액 대비 비중",
                        "stack": "zero",
                        "scale": {"domain": [0, 1]},
                        "axis": {"format": ".0%"},
                    },
                    "color": {
                        "field": "group_label",
                        "type": "nominal",
                        "title": "category 그룹",
                        "sort": category_options,
                    },
                    "order": {"field": "group_rank", "type": "quantitative"},
                    "tooltip": [
                        {
                            "field": "purchase_month",
                            "type": "nominal",
                            "title": "구매월",
                        },
                        {
                            "field": "group_label",
                            "type": "nominal",
                            "title": "category 그룹",
                        },
                        {
                            "field": "share",
                            "type": "quantitative",
                            "title": "월 전체 대비 비중",
                            "format": ".2%",
                        },
                    ],
                },
            },
            alt=(
                "선택한 고정 category 그룹이 각 월 전체 상품 거래액에서 차지하는 "
                "비중을 나타낸 누적 막대 그래프"
            ),
            key="trade_category_mix_chart",
        )
        st.caption(
            "일부 그룹만 선택해도 분모는 선택 그룹 합이 아니라 같은 월 전체 상품 "
            "거래액으로 유지됩니다."
        )

    concentration_options = list(CONCENTRATION_SERIES)
    selected_series = st.multiselect(
        "표시할 판매자 집중도 계열",
        concentration_options,
        default=concentration_options,
        key="trade_concentration_series",
    )
    concentration_exact: pd.DataFrame | None = None
    if not selected_series:
        st.info("판매자 집중도 차트를 보려면 하나 이상의 계열을 선택하세요.")
    else:
        concentration = filter_months(
            data.seller_concentration, start_month, end_month
        )
        selected_columns = [
            CONCENTRATION_SERIES[label] for label in selected_series
        ]
        concentration_exact = concentration.loc[
            :, ["purchase_month", *selected_columns]
        ].copy()
        concentration_exact["purchase_month"] = concentration_exact[
            "purchase_month"
        ].dt.strftime("%Y-%m")
        concentration_exact = concentration_exact.rename(
            columns={
                "purchase_month": "구매월",
                **{
                    CONCENTRATION_SERIES[label]: label
                    for label in selected_series
                },
            }
        )
        for column in selected_series:
            concentration_exact[column] = concentration_exact[column].map(float)
        concentration_chart = concentration.loc[
            :, ["purchase_month", *selected_columns]
        ].melt(
            id_vars="purchase_month",
            value_vars=selected_columns,
            var_name="series_key",
            value_name="value",
        )
        label_by_key = {
            key: label for label, key in CONCENTRATION_SERIES.items()
        }
        concentration_chart["표시 계열"] = concentration_chart["series_key"].map(
            label_by_key
        )
        concentration_chart["purchase_month"] = concentration_chart[
            "purchase_month"
        ].dt.strftime("%Y-%m")
        concentration_chart["value"] = concentration_chart["value"].map(float)
        _render_vega(
            concentration_chart,
            _line_spec(
                title="월별 익명 판매자군 집중도",
                x_title="구매월",
                y_title="월 전체 상품 거래액 대비 비중",
                series_field="표시 계열",
                y_domain=[0, 1],
                percent_axis=True,
            ),
            alt="판매자 Top 1, Top 10, 상위 10%의 월별 상품 거래액 비중 선 그래프",
            key="trade_seller_concentration_chart",
        )
        st.caption(
            "집중도 집단의 구성원은 매월 달라질 수 있으며 개별 판매자 성과나 사업 "
            "위험을 증명하지 않습니다."
        )

    with st.expander("선택 기간의 정확한 월별 값"):
        st.markdown("##### 거래 월별 합계")
        display = overview.loc[
            :,
            [
                "purchase_month",
                "gross_item_value",
                "freight_amount",
                "item_side_amount",
                "ordered_item_row_count",
                "active_seller_count",
            ],
        ].copy()
        display["purchase_month"] = display["purchase_month"].dt.strftime("%Y-%m")
        for column in ("gross_item_value", "freight_amount", "item_side_amount"):
            display[column] = display[column].map(float)
        display = display.rename(
            columns={
                "purchase_month": "구매월",
                "gross_item_value": "상품 거래액",
                "freight_amount": "배송비",
                "item_side_amount": "상품 측 금액 합계",
                "ordered_item_row_count": "주문상품 행 수",
                "active_seller_count": "활동 판매자 수",
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "상품 거래액": st.column_config.NumberColumn(format="localized"),
                "배송비": st.column_config.NumberColumn(format="localized"),
                "상품 측 금액 합계": st.column_config.NumberColumn(
                    format="localized"
                ),
                "주문상품 행 수": st.column_config.NumberColumn(format="localized"),
                "활동 판매자 수": st.column_config.NumberColumn(format="localized"),
            },
            alt="선택 기간의 월별 거래 집계 표",
        )
        if category_exact is not None:
            st.markdown("##### 표시 category 구성")
            st.dataframe(
                category_exact,
                hide_index=True,
                width="stretch",
                column_config={
                    "상품 거래액": st.column_config.NumberColumn(format="localized"),
                    "월 전체 대비 비중": st.column_config.NumberColumn(
                        format="percent"
                    ),
                },
                alt="선택한 category 그룹의 구매월별 상품 거래액과 전체 대비 비중 표",
            )
        if concentration_exact is not None:
            st.markdown("##### 표시 판매자 집중도")
            st.dataframe(
                concentration_exact,
                hide_index=True,
                width="stretch",
                column_config={
                    column: st.column_config.NumberColumn(format="percent")
                    for column in selected_series
                },
                alt="선택한 익명 판매자군의 구매월별 상품 거래액 비중 표",
            )


def render_delivery_tab(data: DashboardData) -> None:
    st.subheader("배송·리뷰")
    st.caption(
        "예정일 대비 배송 구간과 주문별 평균 리뷰 점수의 관찰 관계를 봅니다. "
        "배송 지연이 리뷰를 변화시켰다는 인과 분석이 아닙니다."
    )
    st.markdown("#### 전체 최종 분석 대상의 예정일 대비 배송 구간")
    st.caption(
        "배송일 비교가 가능하고 리뷰가 있는 배송 완료 주문 95,824건 · 기간 필터 미적용"
    )
    timing = data.delivery_timing_summary.sort_values("group_rank").copy()
    timing_chart = timing.loc[:, ["group_label", "group_rank", "order_share"]].copy()
    timing_chart["order_share"] = timing_chart["order_share"].map(float)
    _render_vega(
        timing_chart,
        {
            "title": "예정일 대비 배송 구간별 주문 비중",
            "mark": "bar",
            "encoding": {
                "y": {
                    "field": "group_label",
                    "type": "ordinal",
                    "title": "예정일 대비 배송 구간",
                    "sort": {"field": "group_rank", "order": "ascending"},
                },
                "x": {
                    "field": "order_share",
                    "type": "quantitative",
                    "title": "전체 최종 분석 대상 대비 주문 비중",
                    "scale": {"domain": [0, 1]},
                    "axis": {"format": ".0%"},
                },
                "tooltip": [
                    {
                        "field": "group_label",
                        "type": "nominal",
                        "title": "배송 구간",
                    },
                    {
                        "field": "order_share",
                        "type": "quantitative",
                        "title": "주문 비중",
                        "format": ".2%",
                    },
                ],
            },
        },
        alt="전체 최종 분석 대상에서 예정일 대비 여섯 배송 구간별 주문 비중 막대 그래프",
        key="delivery_timing_share_chart",
    )
    timing_table = timing.loc[
        :,
        [
            "group_label",
            "order_count",
            "order_share",
            "mean_order_review_score",
            "median_order_review_score",
            "low_score_order_rate",
        ],
    ].copy()
    timing_table.columns = [
        "배송 구간",
        "주문 수",
        "주문 비중",
        "평균 리뷰 점수",
        "중앙값",
        "2점 이하 비율",
    ]
    for column in ("주문 비중", "평균 리뷰 점수", "중앙값", "2점 이하 비율"):
        timing_table[column] = timing_table[column].map(float)
    st.dataframe(
        timing_table,
        hide_index=True,
        width="stretch",
        column_config={
            "주문 수": st.column_config.NumberColumn(format="localized"),
            "주문 비중": st.column_config.NumberColumn(format="percent"),
            "평균 리뷰 점수": st.column_config.NumberColumn(format="%.2f점"),
            "중앙값": st.column_config.NumberColumn(format="%.2f점"),
            "2점 이하 비율": st.column_config.NumberColumn(format="percent"),
        },
        alt="예정일 대비 배송 구간별 주문 수와 리뷰 지표 표",
    )

    with st.expander("시간 순서 역전 포함·제외 비교"):
        st.caption(
            "시간 순서 역전은 주문 단계의 timestamp가 기대 순서와 반대로 기록된 상태입니다. "
            "이를 제외해도 관찰 결과가 크게 달라지는지 확인하며, 아래 기간 필터는 "
            "적용되지 않습니다."
        )
        sensitivity = data.delivery_sensitivity.loc[
            :,
            [
                "cohort_label",
                "order_count",
                "late_rate",
                "late_mean_order_review_score",
                "not_late_mean_order_review_score",
                "mean_score_gap",
            ],
        ].copy()
        sensitivity.columns = [
            "cohort",
            "주문 수",
            "지연률",
            "지연 평균",
            "비지연 평균",
            "평균 차이",
        ]
        for column in ("지연률", "지연 평균", "비지연 평균", "평균 차이"):
            sensitivity[column] = sensitivity[column].map(float)
        st.dataframe(
            sensitivity,
            hide_index=True,
            width="stretch",
            column_config={
                "주문 수": st.column_config.NumberColumn(format="localized"),
                "지연률": st.column_config.NumberColumn(format="percent"),
                "지연 평균": st.column_config.NumberColumn(format="%.2f점"),
                "비지연 평균": st.column_config.NumberColumn(format="%.2f점"),
                "평균 차이": st.column_config.NumberColumn(format="%+.2f점"),
            },
            alt="시간 순서 역전 주문 포함·제외 결과 비교 표",
        )

    st.markdown("#### 구매월별 지연률과 리뷰 평균 차이")
    months = _month_options(data.delivery_monthly)
    filter_columns = st.columns(2)
    with filter_columns[0]:
        start_month = st.selectbox(
            "배송 분석 구매 시작 월",
            months,
            index=0,
            key="delivery_start_month",
        )
    with filter_columns[1]:
        end_month = st.selectbox(
            "배송 분석 구매 종료 월",
            months,
            index=len(months) - 1,
            key="delivery_end_month",
        )
    monthly = _filtered(data.delivery_monthly, start_month, end_month)
    if monthly is None:
        return

    kpis = compute_delivery_kpis(monthly)
    metric_columns = st.columns(4)
    metric_columns[0].metric("선택 기간 지연률", _percent(kpis.late_rate))
    metric_columns[1].metric(
        "지연 주문 평균 리뷰", _score(kpis.late_mean_order_review_score)
    )
    metric_columns[2].metric(
        "비지연 주문 평균 리뷰", _score(kpis.not_late_mean_order_review_score)
    )
    metric_columns[3].metric(
        "지연-비지연 평균 차이", _score(kpis.mean_score_gap, signed=True)
    )
    if (
        kpis.late_mean_order_review_score is None
        or kpis.not_late_mean_order_review_score is None
    ):
        st.warning(
            "선택 기간에 지연 또는 비지연 주문이 없어 일부 평균과 차이를 계산할 수 없습니다."
        )
    st.caption(
        f"선택 기간: {start_month}~{end_month} · "
        f"분석 대상 {kpis.order_count:,}건 · "
        f"지연 {kpis.late_order_count:,}건 · 비지연 {kpis.not_late_order_count:,}건 · "
        "월별 평균을 단순 평균하지 않고 "
        "주문 수와 주문 평균 점수 합에서 다시 계산"
    )

    late_rate_chart = monthly.loc[:, ["purchase_month", "late_rate"]].copy()
    late_rate_chart["purchase_month"] = late_rate_chart[
        "purchase_month"
    ].dt.strftime("%Y-%m")
    late_rate_chart["value"] = late_rate_chart["late_rate"].map(float)
    _render_vega(
        late_rate_chart,
        _line_spec(
            title="월별 지연 주문 비율",
            x_title="구매월",
            y_title="해당 월 최종 분석 대상 중 지연 주문 비율",
            y_domain=[0, 1],
            percent_axis=True,
        ),
        alt="선택 기간의 월별 지연 주문 비율 선 그래프",
        key="delivery_monthly_late_rate_chart",
    )

    score_gap_chart = monthly.loc[
        :, ["purchase_month", "mean_score_gap"]
    ].copy()
    score_gap_chart["purchase_month"] = score_gap_chart[
        "purchase_month"
    ].dt.strftime("%Y-%m")
    score_gap_chart["value"] = score_gap_chart["mean_score_gap"].map(float)
    _render_vega(
        score_gap_chart,
        _line_spec(
            title="월별 지연-비지연 주문 평균 리뷰 점수 차이",
            x_title="구매월",
            y_title="지연 평균 - 비지연 평균 (점)",
        ),
        alt="선택 기간의 월별 지연 주문과 비지연 주문 간 평균 리뷰 점수 차이 선 그래프",
        key="delivery_monthly_score_gap_chart",
    )

    with st.expander("해석할 때 확인할 범위"):
        st.markdown(
            "- 리뷰가 있고 실제·예정 배송일을 비교할 수 있는 배송 완료 주문만 포함합니다.\n"
            "- 배송 구간 전체 요약과 월별 분석은 기간·분모가 다릅니다.\n"
            "- 관찰된 차이는 인과 효과, SLA 또는 미래 예측이 아닙니다.\n"
            "- 2016~2018년 고정 공개 데이터의 결과를 현재 시장으로 일반화하지 않습니다."
        )


def render_dashboard(data: DashboardData) -> None:
    trade_tab, delivery_tab = st.tabs(["거래 구성", "배송·리뷰"])
    with trade_tab:
        render_trade_tab(data)
    with delivery_tab:
        render_delivery_tab(data)
