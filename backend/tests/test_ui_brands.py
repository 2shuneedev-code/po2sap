"""참조표 스프레드시트의 저장 변환 — 표의 행이 파일 컬럼으로 그대로 가는가.

빈 줄은 없는 것으로 보고, 나머지는 **걸러내지 않고** 넘긴다 — 틀린 행은
저장 함수(`set_sap_rows` · `set_rows`)의 검증이 이유와 함께 거부해야 사람이 고칠 수 있다.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("streamlit")

from ui.views.sheet import records  # noqa: E402

HEADS = {"코드": "zbrand", "브랜드명": "zbrant"}


def test_rows_keep_order_and_fill_scope_columns():
    frame = pd.DataFrame([{"코드": "001", "브랜드명": "YG"}, {"코드": "002", "브랜드명": "OEM"}])
    out = records(frame, HEADS, {"kunnr": "100161", "name1": "BFT"})
    assert [r["zbrand"] for r in out] == ["001", "002"]
    assert all(r["kunnr"] == "100161" and r["name1"] == "BFT" for r in out)


def test_blank_lines_are_ignored_including_nan_and_none():
    frame = pd.DataFrame([{"코드": None, "브랜드명": float("nan")}, {"코드": "", "브랜드명": " "}])
    assert records(frame, HEADS, {"kunnr": "1"}) == []


def test_incomplete_rows_are_passed_on_for_validation():
    frame = pd.DataFrame([{"코드": "", "브랜드명": "이름만"}])
    assert records(frame, HEADS, {}) == [{"zbrand": "", "zbrant": "이름만"}]


def test_values_are_trimmed_and_explicit_values_win_over_fill():
    heads = {"고객코드": "kunnr", "코드": "zbrand"}
    frame = pd.DataFrame([{"고객코드": " 200 ", "코드": " 9999 "}])
    assert records(frame, heads, {"kunnr": "100"}) == [{"kunnr": "200", "zbrand": "9999"}]
