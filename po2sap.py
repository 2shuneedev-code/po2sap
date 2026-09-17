"""PO2SAP — 사내 발주서 변환 도구. 스트림릿 진입점.

사내 서버:
    streamlit run po2sap.py --server.address 0.0.0.0 --server.port 8501

이것 하나만 띄우면 된다. 별도 API 서버가 필요 없다 — 화면이 `backend/app`
모듈을 직접 부른다. 환경 차이는 `.env` 뿐이다 (CLAUDE.md §3).

FastAPI(`backend/app/main.py`)는 외부 연동용으로 그대로 남아 있고, 전송처럼
되돌릴 수 없는 동작은 양쪽이 **같은 함수**(`send_service.send_batch`)를 부른다.
"""

from __future__ import annotations

import streamlit as st

# 스트림릿의 첫 명령이어야 한다.
st.set_page_config(
    page_title="PO2SAP — 발주서 변환",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui.main import main  # noqa: E402

main()
