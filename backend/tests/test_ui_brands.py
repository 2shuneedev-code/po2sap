"""브랜드 매핑 화면의 저장 묶음 — 화면에서 지운 매핑이 파일에 남으면 안 된다.

`set_keys` 는 (고객, 코드) 묶음을 통째로 교체한다. 그래서 표에서 사라진 코드를
**빈 묶음으로 명시하지 않으면** 파일에 그대로 남는다. 화면에는 없는데 발주서는
그 문구로 계속 판정되는 상태가 가장 나쁘다 — 아무도 눈치채지 못한다.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

from backend.app.masters.brands import BrandKey  # noqa: E402
from ui.views.brands import group_for_save  # noqa: E402

MSC = "100249"


def key(zbrand: str, text: str, match: str = "contains") -> BrandKey:
    return BrandKey(kunnr=MSC, zbrand=zbrand, match=match, text=text, note="")


def row(code: str, text: str, match: str = "contains", note: str = "") -> dict:
    return {"브랜드코드": code, "원문 문구": text, "비교": match, "비고": note}


def test_rows_group_by_brand_code():
    out = group_for_save(MSC, [], [row("38", "HERTEL"), row("38", "HERTEL TOOL"),
                                   row("127", "INTERSTATE")])
    assert set(out) == {"38", "127"}
    assert [k.text for k in out["38"]] == ["HERTEL", "HERTEL TOOL"]


def test_row_order_is_preserved():
    """행 순서가 곧 판정 우선순위다 (SCHEMA §4.5). 뒤섞이면 판정이 바뀐다."""
    out = group_for_save(MSC, [], [row("38", "B"), row("38", "A"), row("38", "C")])
    assert [k.text for k in out["38"]] == ["B", "A", "C"]


def test_removed_code_is_cleared_not_forgotten():
    """★ 표에서 통째로 지운 코드는 빈 묶음으로 나가야 지워진다."""
    before = [key("38", "HERTEL"), key("127", "INTERSTATE")]
    out = group_for_save(MSC, before, [row("38", "HERTEL")])

    assert out["127"] == [], "지운 코드가 빈 묶음으로 나오지 않으면 파일에 남는다"
    assert [k.text for k in out["38"]] == ["HERTEL"]


def test_blank_rows_are_dropped():
    """스트림릿 동적 표는 맨 아래 빈 줄을 항상 들고 있다."""
    out = group_for_save(MSC, [], [row("38", "HERTEL"), row("", ""), row("205", "")])
    assert set(out) == {"38"}


def test_clearing_every_row_still_clears_the_file():
    before = [key("38", "HERTEL")]
    out = group_for_save(MSC, before, [])
    assert out == {"38": []}


def test_match_mode_defaults_to_contains():
    out = group_for_save(MSC, [], [{"브랜드코드": "38", "원문 문구": "HERTEL"}])
    assert out["38"][0].match == "contains"


def test_equals_mode_survives():
    out = group_for_save(MSC, [], [row("38", "HERTEL", match="equals")])
    assert out["38"][0].match == "equals"


def test_note_is_carried():
    out = group_for_save(MSC, [], [row("38", "HERTEL", note="2026-09 현업 확인")])
    assert out["38"][0].note == "2026-09 현업 확인"


def test_keys_carry_the_customer_number():
    out = group_for_save(MSC, [], [row("38", "HERTEL")])
    assert out["38"][0].kunnr == MSC
