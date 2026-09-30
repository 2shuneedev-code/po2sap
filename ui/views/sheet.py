"""참조표 스프레드시트 — Brand Master · Shipping Master 가 같이 쓴다.

원본 CSV 를 **그대로** 표로 펴고, 고친 표를 저장하면 원본이 바뀐다. 고객을 고르면
그 고객 행만, 안 고르면 파일 전체를 편다. 저장은 암호로 잠근다(`ui/auth.py`).

엑셀에서 여러 칸을 잡아 붙여넣으면 그대로 들어간다. 사내 서버(http)에서도
되도록 `ui/main.py` 가 클립보드 보정을 넣는다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

_VERSION = "sheet_version"


def records(edited: pd.DataFrame, columns: dict[str, str], fill: dict[str, str]) -> list[dict]:
    """표의 행 → 파일 컬럼 dict. 빈 줄은 버리고, 빈 칸은 `fill` 로 채운다.

    `columns` 는 {표 머리글: 파일 컬럼}. 화면에서 떼어놨다 — 테스트가 잡는다.
    """
    out = []
    for record in edited.to_dict("records"):
        row = {col: _text(record.get(head)) for head, col in columns.items()}
        if not any(row.values()):
            continue
        for col, value in fill.items():
            if not row.get(col):
                row[col] = value
        out.append(row)
    return out


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


# 스트림릿 표는 **붙여넣기로 행을 늘리지 않는다** — 빈 표나 마지막 행 아래에
# 붙여넣으면 조용히 버려진다(2026-09-30 실제 크롬·클립보드로 확인). 편집이 열려
# 있으면 빈 행을 미리 깔아 둔다. 저장 때 빈 행은 버리므로(`records`) 원본엔 안 남는다.
SPARE_ROWS = 30


def editor(frame: pd.DataFrame, *, key: str, unlocked: bool, column_config: dict) -> pd.DataFrame:
    """잠겨 있으면 조회만. 저장 뒤에는 키를 바꿔 **새 원본으로** 다시 편다 —
    같은 키면 방금 저장한 추가 행이 한 번 더 얹힌다."""
    version = st.session_state.get(_VERSION, 0)
    if unlocked:
        blank = pd.DataFrame([dict.fromkeys(frame.columns, "")] * SPARE_ROWS)
        frame = pd.concat([frame, blank], ignore_index=True)
    return st.data_editor(
        frame,
        disabled=not unlocked,
        num_rows="dynamic" if unlocked else "fixed",
        width="stretch",
        hide_index=True,
        height=min(640, 40 + 35 * (len(frame) + 2)),
        key=f"{key}_{version}",
        column_config=column_config,
    )


def saved() -> None:
    """저장 성공 뒤 부른다 — 다음 렌더에서 표가 원본을 새로 읽는다."""
    st.session_state[_VERSION] = st.session_state.get(_VERSION, 0) + 1


def paste_hint() -> None:
    st.caption(
        "엑셀에서 여러 칸을 잡아 복사한 뒤, 표에서 붙여넣을 **첫 칸을 한 번 클릭**하고 "
        "Ctrl+V 하세요 (칸 안에 들어가 편집 중이면 한 칸에만 들어갑니다). 새 행은 아래 "
        f"**빈 행 {SPARE_ROWS}줄**에 붙여넣으세요 — 빈 행은 저장 때 버립니다. "
        "더 필요하면 표 아래 **+**, 삭제는 행 왼쪽을 골라 Delete."
    )
