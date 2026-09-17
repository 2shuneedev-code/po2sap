"""PO2SAP — 사내 발주서 변환 도구.

실행:
    streamlit run app/main.py

사내 서버에서 이것 하나만 띄우면 된다. 백엔드 API 서버는 필요 없다 —
화면이 `backend/app` 모듈을 직접 부른다. 환경 차이는 `.env` 뿐이다.
"""

from __future__ import annotations

import streamlit as st

from ui.service import health  # noqa: E402
from ui.views import brands, convert  # noqa: E402

PAGES = {
    "P/O 변환": convert.render,
    "브랜드 매핑": brands.render,
}


def main() -> None:
    with st.sidebar:
        st.markdown("### 📄 PO2SAP")
        page = st.radio("메뉴", list(PAGES), label_visibility="collapsed")
        st.divider()

    PAGES[page]()

    with st.sidebar:
        st.divider()
        _health_panel()


def _health_panel() -> None:
    """EAI 주소가 비어 있으면 눈에 띄게 알린다 — 검수를 다 끝내고 전송에서야
    막히는 일을 막는다."""
    info = health()
    masters_ok, masters_detail = info["masters"]
    llm_ok, llm_detail = info["llm"]
    endpoint = info["eai_endpoint"]

    problems = []
    if not masters_ok:
        problems.append("마스터")
    if not llm_ok:
        problems.append("LLM")
    if not endpoint:
        problems.append("EAI 주소")

    with st.expander("⚠️ 설정 확인 필요" if problems else "✅ 정상", expanded=bool(problems)):
        st.caption(f"마스터 — {masters_detail}")
        st.caption(f"LLM — {llm_detail}")
        st.caption(f"EAI — {endpoint or '**미설정** (.env 의 EAI_ENDPOINT)'}")

