"""브랜드 후보 화면의 저장 변환 — 표의 행이 보정 행으로 그대로 가는가.

빈 줄은 없는 것으로 보고, 나머지는 **걸러내지 않고** 넘긴다 — 틀린 행은
`set_manual` 의 검증이 이유와 함께 거부해야 사람이 고칠 수 있다.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

from ui.views.brands import rows_for_save  # noqa: E402

MSC = "100249"


def row(action: str, code: str, name: str = "", note: str = "") -> dict:
    return {"동작": action, "코드": code, "브랜드명": name, "비고": note}


def test_rows_become_manual_rows_in_order():
    out = rows_for_save(MSC, [row("add", "9999", "NEW", "n"), row("suppress", "38", note="단종")])
    assert [(r.action, r.zbrand, r.zbrant, r.note) for r in out] == [
        ("add", "9999", "NEW", "n"), ("suppress", "38", "", "단종"),
    ]
    assert {r.kunnr for r in out} == {MSC}


def test_blank_lines_are_ignored():
    assert rows_for_save(MSC, [row("", ""), {"동작": None, "코드": None}]) == []


def test_incomplete_rows_are_passed_on_for_validation():
    """코드만 있고 동작이 비었으면 조용히 버리지 않는다 — 저장이 거부하게 둔다."""
    out = rows_for_save(MSC, [row("", "38", note="n")])
    assert len(out) == 1 and out[0].action == ""


def test_values_are_trimmed():
    out = rows_for_save(MSC, [row("add", " 9999 ", " NEW ", " 메모 ")])
    assert (out[0].zbrand, out[0].zbrant, out[0].note) == ("9999", "NEW", "메모")
