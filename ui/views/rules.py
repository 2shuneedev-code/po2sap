"""규칙 카드 렌더 — `build_preview` 응답을 **모양 그대로** 그린다.

★ 이 파일에 거래처별 분기가 하나도 없다. 규칙이 YAML 에서 바뀌면 화면이
따라온다 — 문서와 실동작이 어긋날 자리를 없앤 것이다 (CLAUDE.md P2).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

# `kind` 는 아이콘 하나 고르는 데만 쓴다. 모르는 kind 는 기본 아이콘.
ICON = {
    "table": "▦",
    "csv_map": "🔤",
    "value_map": "🔤",
    "keyword_map": "🔤",
    "lookup": "🔎",
}


def rule_preview(preview: dict) -> None:
    fixed = preview.get("fixed") or []
    rules = preview.get("rules") or []
    split = preview.get("split") or {}
    todos = preview.get("todos") or []

    if todos:
        st.warning(
            "**확인 중인 값** — "
            + " · ".join(f"`{t['field']}` ({t['note']})" for t in todos),
            icon="⚠️",
        )

    if split.get("by") not in (None, "", "none") and split.get("label"):
        st.info(f"**오더 분할** — {split['label']}", icon="🔀")

    if fixed:
        st.markdown("**고정값** — 발주서를 읽기 전에 이미 정해진 값")
        cols = st.columns(min(len(fixed), 4))
        for index, item in enumerate(fixed):
            with cols[index % len(cols)]:
                st.metric(
                    label=f"{item['label']} · {item['field']}",
                    value=item["value"],
                    help=item.get("note") or None,
                )

    if rules:
        st.markdown("**자동 판별 규칙**")
        for rule in rules:
            _rule_card(rule)

    if preview.get("footer"):
        st.caption(preview["footer"])


def _rule_card(rule: dict) -> None:
    icon = ICON.get(rule.get("kind", ""), "•")
    columns = rule.get("columns") or []
    rows = rule.get("rows") or []
    count = f" ({len(rows)}건)" if rows else ""

    with st.expander(f"{icon}  {rule.get('label') or rule.get('id')}{count}", expanded=not rows):
        if rule.get("note"):
            st.caption(rule["note"])
        if columns and rows:
            # 행 길이가 컬럼 수와 다를 수 있다 — 짧으면 채우고 길면 자른다.
            fixed_rows = [
                (list(r) + [""] * len(columns))[: len(columns)] for r in rows
            ]
            st.dataframe(
                pd.DataFrame(fixed_rows, columns=columns),
                width="stretch", hide_index=True,
            )
            if len(rows) > 1:
                st.caption("위에서부터 순서대로 확인합니다.")
        elif not rule.get("note"):
            st.caption("표시할 표가 없습니다.")
