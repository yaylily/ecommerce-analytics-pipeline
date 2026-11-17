from __future__ import annotations

import unittest

import altair as alt

from dashboard.views import _line_spec


class DashboardViewSpecTest(unittest.TestCase):
    def test_line_spec_has_explicit_axis_domain_and_tooltip_format(self) -> None:
        spec = _line_spec(
            title="월별 지연률",
            x_title="구매월",
            y_title="지연률",
            y_domain=[0, 1],
            percent_axis=True,
        )

        encoding = spec["encoding"]
        self.assertEqual(encoding["x"]["field"], "purchase_month")
        self.assertEqual(encoding["x"]["sort"], "ascending")
        self.assertEqual(encoding["y"]["scale"], {"domain": [0, 1]})
        self.assertEqual(encoding["y"]["axis"], {"format": ".0%"})
        self.assertEqual(encoding["tooltip"][1]["format"], ".2%")

    def test_multiseries_line_spec_uses_color_dash_and_shape_and_is_valid(self) -> None:
        spec = _line_spec(
            title="판매자 집중도",
            x_title="구매월",
            y_title="비중",
            series_field="표시 계열",
            y_domain=[0, 1],
            percent_axis=True,
        )

        encoding = spec["encoding"]
        for channel in ("color", "strokeDash", "shape"):
            with self.subTest(channel=channel):
                self.assertEqual(encoding[channel]["field"], "표시 계열")

        complete_spec = {
            **spec,
            "data": {
                "values": [
                    {
                        "purchase_month": "2017-02",
                        "표시 계열": "Top 1",
                        "value": 0.1,
                    }
                ]
            },
        }
        alt.Chart.from_dict(complete_spec, validate=True)


if __name__ == "__main__":
    unittest.main()
