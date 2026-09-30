"""PO2SAP — 사내 발주서 변환 도구.

실행:
    streamlit run app/main.py

사내 서버에서 이것 하나만 띄우면 된다. 백엔드 API 서버는 필요 없다 —
화면이 `backend/app` 모듈을 직접 부른다. 환경 차이는 `.env` 뿐이다.
"""

from __future__ import annotations

import streamlit as st

from backend.app.rules.reftable import RefTableError  # noqa: E402
from ui.service import health  # noqa: E402
from ui.views import brands, convert, shipping  # noqa: E402

PAGES = {
    "P/O Transfer": convert.render,
    "Brand Master": brands.render,
    "Shipping Master": shipping.render,
}

# 사이드바 머리(접기 버튼 줄)를 띄워서 PO2SAP 제목이 맨 위에 오게 한다.
# 대신 제목·메뉴·거래처 구역 사이는 넉넉히 — 붙어 있으면 어디서 구역이 바뀌는지 안 보인다.
_SIDEBAR_TIGHT = """
<style>
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
  position: absolute; top: 0; right: 0; z-index: 2;
  padding: 0.5rem 0.5rem 0 0; height: auto; min-height: 0;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 1.25rem; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }
section[data-testid="stSidebar"] hr { margin: 0.75rem 0; }
section[data-testid="stSidebar"] h3 { padding: 0 !important; margin: 0 0 1rem !important; font-size: 1.4rem; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(h3) { margin-bottom: 0.75rem; }
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] { gap: 0.5rem; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { margin-top: 0.25rem; }
</style>
"""


# 사내 서버는 http://서버IP:8501 로 연다. 브라우저는 https·localhost 가 아니면
# `navigator.clipboard` 를 **아예 주지 않는다.** 스트림릿 표(glide-data-grid)는
# 붙여넣기 때 `navigator.clipboard.read` 부터 확인하다가 거기서 예외가 나고,
# 여러 칸 붙여넣기가 죽는다(칸 안 편집 중일 때만 한 칸이 들어간다).
# 빈 clipboard 객체를 주면 표는 붙여넣기 **이벤트의 clipboardData** 로 넘어간다 —
# 원래 있는 대체 경로다. 복사는 이벤트로 되고, writeText 만 옛 방식으로 채운다.
# 고정 문자열이다 — 사용자 입력이 섞이지 않는다.
_CLIPBOARD_SHIM = """
<script>
(function () {
  try {
    if (window.isSecureContext || navigator.clipboard) return;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: function (text) {
          return new Promise(function (resolve, reject) {
            var box = document.createElement("textarea");
            box.value = text;
            box.style.position = "fixed";
            box.style.opacity = "0";
            document.body.appendChild(box);
            box.select();
            try { document.execCommand("copy"); resolve(); }
            catch (e) { reject(e); }
            finally { box.remove(); }
          });
        }
      }
    });
  } catch (e) { /* 보정 실패는 조용히 — 한 칸 붙여넣기는 그대로 된다 */ }
})();
</script>
"""


def main() -> None:
    st.html(_CLIPBOARD_SHIM, unsafe_allow_javascript=True)
    with st.sidebar:
        st.markdown(_SIDEBAR_TIGHT, unsafe_allow_html=True)
        st.markdown("### 📄 PO2SAP")
        page = st.radio("메뉴", list(PAGES), label_visibility="collapsed")
        st.divider()

    try:
        PAGES[page]()
    except RefTableError as exc:
        # 참조표가 깨지면 전 화면이 트레이스백이 된다 — 무엇을 고치면 되는지만 보여준다.
        st.error(f"참조표를 읽지 못했습니다 — {exc}", icon="🚫")

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

