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
SORTS = {
    "이름순": "name",
    "고객코드순": "kunnr",
    "업로드 가능 먼저": "ready",
}


def customer_picker(key: str, *, ready_first: bool = False) -> CatalogEntry | None:
    """사이드바 거래처 목록. 고른 고객을 돌려준다.

    목록은 **SAP 브랜드 마스터의 전 고객(430곳)** 이다. 규칙이 없는 곳도 보여야
    브랜드를 미리 채워둘 수 있고 어디까지 왔는지 보인다. `ready_first` 는
    업로드 가능한 곳을 위로 올릴 뿐, 나머지를 숨기지 않는다.
    """
    state_key = f"{key}_kunnr"

    with st.sidebar:
        st.caption("거래처")
        q = st.text_input(
            "검색", key=f"{key}_q", placeholder="고객명 · 고객코드 (Enter)",
            help="고객명 · SAP 명 · 고객코드 · 거래처코드를 함께 찾습니다",
            label_visibility="collapsed",
        )
        # 두 칸으로 나누면 "업로드 가능 먼저" 가 잘린다 — 사이드바는 좁다.
        scope_label = st.selectbox("범위", list(SCOPES), key=f"{key}_scope")
        sort_label = st.selectbox(
            "정렬", list(SORTS), key=f"{key}_sort", index=2 if ready_first else 0,
        )

        rows = catalog(q, SCOPES[scope_label], SORTS[sort_label])
        st.caption(f"{len(rows):,}곳")

        if not rows:
            st.info("해당하는 고객이 없습니다.")
            return None

        selected = st.session_state.get(state_key, "")
        current = next((r for r in rows if r.kunnr == selected), None)

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
