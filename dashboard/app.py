"""Entrypoint for the aggregate-backed Olist analysis dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dashboard.lib import DashboardDataError, load_dashboard_data  # noqa: E402
from dashboard.views import render_dashboard  # noqa: E402


DATA_DIR = Path(__file__).resolve().parent / "data"

st.set_page_config(
    page_title="Olist 거래·배송 분석",
    page_icon=None,
    layout="wide",
)

st.title("Olist 거래·배송 분석")
st.write(
    "검증된 집계에서 거래 구성과 배송·리뷰의 관찰 관계를 기간과 표시 그룹별로 "
    "반복 확인합니다."
)

try:
    dashboard_data = load_dashboard_data(DATA_DIR)
except DashboardDataError:
    st.error(
        "Dashboard 집계 파일의 계약 또는 checksum이 일치하지 않습니다. "
        "검증된 데이터 bundle을 다시 생성해 주세요."
    )
    st.stop()

render_dashboard(dashboard_data)

st.divider()
st.caption(
    "Source: [Brazilian E-Commerce Public Dataset by Olist]"
    "(https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) "
    "(2016–2018 snapshot) · License: "
    "[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)"
)
