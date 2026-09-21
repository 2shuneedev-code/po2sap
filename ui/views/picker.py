"""좌측 거래처 선택 — SAP 브랜드 마스터의 전 고객(430곳)에서 고른다.

규칙이 없는 고객도 목록에 있다. 브랜드 원문 키를 미리 채워둘 수 있고,
어디까지 설정됐는지 한눈에 보이기 때문이다. 다만 **업로드는 막는다** —
규칙 없이 파싱하면 빈 필드가 그대로 전송되고, 그건 아무도 모르게 틀린
오더가 나가는 길이다.
"""

from __future__ import annotations

import streamlit as st

from ui.service import CatalogEntry, catalog

SCOPES = {
    "전체": "all",
    "규칙 있음": "configured",
    "규칙 없음": "unconfigured",
}

# 정렬은 **이름순 하나**다. 사이드바는 좁고, 고객을 찾는 길은 검색이면 된다.
# 선택지를 늘리면 매번 고르게 만들 뿐 찾는 속도가 빨라지지 않는다.
_SORT = "name"

# 스트림릿 버튼 라벨은 기본이 **가운데 정렬**이다. 거래처가 수백 곳이면
# 이름 시작 위치가 제각각이라 눈으로 훑기 어렵다. 왼쪽으로 붙인다.
_LEFT_ALIGN = """
<style>
section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; }
section[data-testid="stSidebar"] .stButton button p { text-align: left; }
</style>
"""


def customer_picker(key: str) -> CatalogEntry | None:
    """사이드바 거래처 목록. 고른 고객을 돌려준다.

    목록은 **SAP 브랜드 마스터의 전 고객(430곳)** 이다. 규칙이 없는 곳도 보여야
    브랜드를 미리 채워둘 수 있고 어디까지 왔는지 보인다.

    거르는 수단은 **검색과 범위 드롭다운 둘뿐**이다. 정렬은 이름순 고정 —
    사이드바는 좁고, 고객을 찾는 길은 검색이면 충분하다.
    """
    state_key = f"{key}_kunnr"

    with st.sidebar:
        st.caption("거래처")
        q = st.text_input(
            "검색", key=f"{key}_q", placeholder="고객명 · 고객코드 (Enter)",
            help="고객명 · SAP 명 · 고객코드 · 거래처코드를 함께 찾습니다",
            label_visibility="collapsed",
        )
        scope_label = st.selectbox(
            "범위", list(SCOPES), key=f"{key}_scope", label_visibility="collapsed",
        )

        rows = catalog(q, SCOPES[scope_label], _SORT)
        st.caption(f"{len(rows):,}곳")

        if not rows:
            st.info("해당하는 고객이 없습니다.")
            return None

        selected = st.session_state.get(state_key, "")
        current = next((r for r in rows if r.kunnr == selected), None)

        st.markdown(_LEFT_ALIGN, unsafe_allow_html=True)
        with st.container(height=420, border=False):
            for row in rows:
                _entry_button(row, state_key, active=row.kunnr == selected)

    return current


def _entry_button(row: CatalogEntry, state_key: str, *, active: bool) -> None:
    # ✅ 전용 규칙 있음 · 🟡 공용 설정으로 읽음 · · 브랜드가 없어 못 읽음
    mark = "✅" if row.configured else ("🟡" if row.ready else "·")
    label = f"{mark} {row.name}"
    st.button(
        label,
        key=f"{state_key}_{row.kunnr}",
        use_container_width=True,
        type="primary" if active else "tertiary",
        help=f"{row.kunnr}"
             + (f" · {row.code}" if row.code else " · 전용 규칙 없음 (공용 설정으로 읽음)")
             + f" · 브랜드 {row.mapped_count}/{row.brand_count}",
        on_click=lambda k=row.kunnr: st.session_state.__setitem__(state_key, k),
    )


def customer_header(entry: CatalogEntry) -> None:
    """선택된 고객의 머리말. 규칙 설정 여부를 숨기지 않는다."""
    st.subheader(entry.name, anchor=False)
    bits = [f"고객코드 `{entry.kunnr}`"]
    bits.append(f"거래처 **{entry.code}**" if entry.code else "전용 규칙 없음 (공용 설정)")
    if entry.sap_name and entry.sap_name != entry.name:
        bits.append(f"SAP 명 {entry.sap_name}")
    if entry.file_types:
        bits.append("/".join(t.upper() for t in entry.file_types))
    bits.append(f"브랜드 매핑 {entry.mapped_count}/{entry.brand_count}")
    st.caption(" · ".join(bits))
