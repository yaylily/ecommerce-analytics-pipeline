from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.lib import (
    APPROVED_MONTH_STRINGS,
    compute_delivery_kpis,
    compute_trade_kpis,
    filter_months,
    load_dashboard_data,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPOSITORY_ROOT / "dashboard" / "app.py"
DATA_DIR = REPOSITORY_ROOT / "dashboard" / "data"


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


class DashboardAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_dashboard_data(DATA_DIR)

    def _run_app(self) -> AppTest:
        return AppTest.from_file(APP_PATH, default_timeout=10).run()

    def _metric_values(self, app: AppTest) -> dict[str, str]:
        return {metric.label: metric.value for metric in app.metric}

    def _visible_text(self, app: AppTest) -> str:
        text_values = [
            element.value
            for collection in (
                app.title,
                app.subheader,
                app.caption,
                app.markdown,
                app.info,
                app.warning,
                app.error,
            )
            for element in collection
            if isinstance(element.value, str)
        ]
        text_values.extend(metric.label for metric in app.metric)
        text_values.extend(str(metric.value) for metric in app.metric)
        return "\n".join(text_values)

    def test_default_render_has_two_tabs_and_approved_widgets(self) -> None:
        app = self._run_app()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual([tab.label for tab in app.tabs], ["거래 구성", "배송·리뷰"])

        expected_months = list(APPROVED_MONTH_STRINGS)
        for key, expected_value in (
            ("trade_start_month", expected_months[0]),
            ("trade_end_month", expected_months[-1]),
            ("delivery_start_month", expected_months[0]),
            ("delivery_end_month", expected_months[-1]),
        ):
            with self.subTest(key=key):
                widget = app.get_by_key(key)
                self.assertEqual(widget.options, expected_months)
                self.assertEqual(widget.value, expected_value)

        category_widget = app.get_by_key("trade_category_groups")
        self.assertEqual(
            category_widget.options,
            [
                "health_beauty",
                "watches_gifts",
                "bed_bath_table",
                "sports_leisure",
                "computers_accessories",
                "Other",
            ],
        )
        self.assertEqual(category_widget.value, category_widget.options)

        concentration_widget = app.get_by_key("trade_concentration_series")
        self.assertEqual(
            concentration_widget.options, ["Top 1", "Top 10", "상위 10%"]
        )
        self.assertEqual(concentration_widget.value, concentration_widget.options)

        metric_labels = set(self._metric_values(app))
        self.assertTrue(
            {
                "상품 거래액",
                "배송비",
                "주문상품 행 수",
                "마지막 월 활동 판매자",
                "선택 기간 지연률",
                "지연 주문 평균 리뷰",
                "비지연 주문 평균 리뷰",
                "지연-비지연 평균 차이",
            }.issubset(metric_labels)
        )
        self.assertIn(
            "분석 대상 88,489건 · 지연 5,972건 · 비지연 82,517건",
            self._visible_text(app),
        )

    def test_changed_periods_recompute_metrics_from_validated_inputs(self) -> None:
        trade_start, trade_end = "2018-06", "2018-07"
        delivery_start, delivery_end = "2017-02", "2017-03"
        app = self._run_app()

        app.get_by_key("trade_start_month").set_value(trade_start)
        app.get_by_key("trade_end_month").set_value(trade_end)
        app.get_by_key("delivery_start_month").set_value(delivery_start)
        app.get_by_key("delivery_end_month").set_value(delivery_end)
        app.run()

        self.assertEqual(len(app.exception), 0)
        trade = compute_trade_kpis(
            filter_months(
                self.data.trade_monthly_overview, trade_start, trade_end
            )
        )
        delivery = compute_delivery_kpis(
            filter_months(
                self.data.delivery_monthly, delivery_start, delivery_end
            )
        )
        metrics = self._metric_values(app)
        expected = {
            "상품 거래액": _amount(trade.gross_item_value),
            "배송비": _amount(trade.freight_amount),
            "주문상품 행 수": _integer(trade.ordered_item_row_count),
            "마지막 월 활동 판매자": _integer(trade.active_seller_count),
            "선택 기간 지연률": _percent(delivery.late_rate),
            "지연 주문 평균 리뷰": _score(
                delivery.late_mean_order_review_score
            ),
            "비지연 주문 평균 리뷰": _score(
                delivery.not_late_mean_order_review_score
            ),
            "지연-비지연 평균 차이": _score(
                delivery.mean_score_gap, signed=True
            ),
        }
        for label, value in expected.items():
            with self.subTest(label=label):
                self.assertEqual(metrics[label], value)
        self.assertIn(
            f"분석 대상 {delivery.order_count:,}건 · "
            f"지연 {delivery.late_order_count:,}건 · 비지연 {delivery.not_late_order_count:,}건",
            self._visible_text(app),
        )

    def test_empty_trade_series_selections_show_guidance_without_crash(self) -> None:
        app = self._run_app()

        app.get_by_key("trade_category_groups").set_value([])
        app.get_by_key("trade_concentration_series").set_value([])
        app.run()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(
            {message.value for message in app.info},
            {
                "category 구성 차트를 보려면 하나 이상의 그룹을 선택하세요.",
                "판매자 집중도 차트를 보려면 하나 이상의 계열을 선택하세요.",
            },
        )
        metric_labels = set(self._metric_values(app))
        self.assertIn("상품 거래액", metric_labels)
        self.assertIn("선택 기간 지연률", metric_labels)

    def test_reversed_period_warns_and_keeps_the_other_tab_available(self) -> None:
        cases = (
            (
                "trade_start_month",
                "trade_end_month",
                "상품 거래액",
                "선택 기간 지연률",
            ),
            (
                "delivery_start_month",
                "delivery_end_month",
                "선택 기간 지연률",
                "상품 거래액",
            ),
        )
        for start_key, end_key, omitted_metric, retained_metric in cases:
            with self.subTest(start_key=start_key):
                app = self._run_app()
                app.get_by_key(start_key).set_value(APPROVED_MONTH_STRINGS[-1])
                app.get_by_key(end_key).set_value(APPROVED_MONTH_STRINGS[0])
                app.run()

                self.assertEqual(len(app.exception), 0)
                self.assertIn(
                    "시작 월은 종료 월보다 늦을 수 없습니다.",
                    [message.value for message in app.warning],
                )
                self.assertEqual(
                    [tab.label for tab in app.tabs], ["거래 구성", "배송·리뷰"]
                )
                metric_labels = set(self._metric_values(app))
                self.assertNotIn(omitted_metric, metric_labels)
                self.assertIn(retained_metric, metric_labels)

    def test_public_copy_keeps_data_and_interpretation_boundaries_visible(self) -> None:
        app = self._run_app()

        self.assertEqual(len(app.exception), 0)
        visible = self._visible_text(app)
        self.assertIn("상품 거래액은 회사 매출·순매출·이익이 아닙니다.", visible)
        self.assertIn("배송 지연이 리뷰를 변화시켰다는 인과 분석이 아닙니다.", visible)
        self.assertIn("기간 필터 미적용", visible)
        self.assertIn("예정일 대비 배송 구간", visible)

        for forbidden in (
            "order_id",
            "seller_id",
            "customer_id",
            "product_id",
            "review_comment",
            "POSTGRES_PASSWORD",
            ".env",
            "지연이 리뷰 하락을 유발",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, visible)


if __name__ == "__main__":
    unittest.main()
