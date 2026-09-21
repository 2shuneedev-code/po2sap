"""앵커 판정 사다리 — exact → numeric → date → fuzzy → miss (design.md §3.4)."""

from __future__ import annotations

import pytest
from app.extraction.anchor import AnchorResult as R
from app.extraction.anchor import locate


# ── exact ──────────────────────────────────────────────────────────────
def test_exact_ignores_case_and_whitespace():
    assert locate("End  Mill 6MM", "10 | 09876543 | END MILL   6MM | 12.50") is R.EXACT


def test_exact_multiline_value_matches_joined_lines():
    src = "SID TOOL - ELKHART WAREHOUSE\n1000 INDUSTRIAL PKWY, ELKHART, IN 46514"
    assert locate("SID TOOL - ELKHART WAREHOUSE 1000 INDUSTRIAL PKWY, ELKHART, IN 46514", src) is R.EXACT


def test_exact_does_not_match_inside_a_bigger_number():
    """수량 `5` 가 줄의 `15` 안에서 찾아지면 수량 오독을 못 거른다."""
    assert locate("5", "15 | 09876544 | DRILL 8MM") is R.MISS
    assert locate("1", "Qty 1,250.00") is not R.EXACT       # 1 은 1,250 의 일부가 아니다
    assert locate("10", "Rev 10.5") is not R.EXACT           # 10 은 10.5 의 일부가 아니다


def test_exact_allows_letters_next_to_digits():
    assert locate("10", "Qty 10EA") is R.EXACT


# ── numeric ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value, source", [
    ("1250", "Quantity 1,250.00"),
    ("12.5", "Price 12.50"),
    ("1250.00", "Qty: 1,250"),
    ("12.5", "Preis 12,50 EUR"),                 # 유럽식 소수점
    ("1250", "Menge 1.250,00"),                  # 유럽식 천 단위 + 소수점
    ("1250", "$1,250.00 USD"),
])
def test_numeric_passes_when_the_value_is_the_same_number(value, source):
    assert locate(value, source) is R.NUMERIC


def test_numeric_rejects_a_different_number():
    assert locate("1250", "Quantity 1,205.00") is R.MISS


def test_numeric_ignores_a_hyphen_in_a_part_number():
    """`YG-0600` 의 `-` 를 음수로 읽으면 600 이 맞지 않는다."""
    assert locate("600", "YG-0600 END MILL") is R.NUMERIC


# ── date ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("source", [
    "Date of Order | 2/17/26",
    "Date of Order | 02/17/2026",
    "Date of Order | 2/17/2026",
    "Date: 17/02/2026",
    "Date: 17.02.2026",
    "Date: 20260217",
    "Date: 17-Feb-26",
    "Date: 17 FEB 2026",
    "Date: Feb 17, 2026",
    "Date: February 17th, 2026",
    "Date: 2026/02/17",
    "Date: 2026.02.17",
])
def test_date_is_mapped_back_to_common_notations(source):
    assert locate("2026-02-17", source) is R.DATE


def test_date_iso_in_source_is_exact():
    assert locate("2026-02-17", "Date: 2026-02-17") is R.EXACT


def test_date_not_matched_inside_another_date():
    """`12/17/26` 안의 `2/17/26` 은 다른 날짜다 — 통과시키면 안 된다."""
    assert locate("2026-02-17", "Date of Order | 12/17/26") is R.FUZZY


def test_date_that_cannot_be_mapped_back_is_fuzzy_not_miss():
    """못 만들어 본 표기일 수 있다 — 멀쩡한 값을 🔴 로 막지 않는다 (design.md §3.4)."""
    assert locate("2026-02-17", "Date of Order | Seventeenth of February") is R.FUZZY
    assert locate("2026-02-17", "no date here at all") is R.FUZZY


def test_invalid_date_is_not_treated_as_a_date():
    assert locate("2026-13-45", "totally different text") is R.MISS


# ── fuzzy / miss ───────────────────────────────────────────────────────
def test_fuzzy_when_most_tokens_are_present():
    assert locate("END MILL 6MM 4FL LONG", "10 | 09876543 | END MILL 6MM 4FL") is R.FUZZY


def test_miss_when_the_value_is_not_there():
    assert locate("HARRISBURG", "SID TOOL - ELKHART WAREHOUSE") is R.MISS


def test_miss_when_half_of_a_short_value_is_present():
    assert locate("DRILL 9MM", "15 | 09876544 | DRILL 8MM") is R.MISS


def test_empty_inputs_are_a_miss():
    assert locate("", "abc") is R.MISS
    assert locate(None, "abc") is R.MISS
    assert locate("abc", "") is R.MISS


def test_passed_covers_exact_numeric_date_only():
    assert {r for r in R if r.passed} == {R.EXACT, R.NUMERIC, R.DATE}
