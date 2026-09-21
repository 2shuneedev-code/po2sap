"""전처리 — 줄 번호 앵커 (design.md §3.3.5).

번호와 줄은 1:1 이다. OUTLINE 이 말한 412 와 LINES 청크가 말한 412 가 같은 줄이어야
하므로, 슬라이스가 번호를 다시 매기면 청크 분할 전체가 무너진다.
"""

from __future__ import annotations

import re

import pytest
from app.extraction.preprocess import SourceDoc, load_document


def make(*pages: str) -> SourceDoc:
    return SourceDoc(filename="f.pdf", ext="pdf", pages=list(pages))


# 두 페이지. 줄 번호는 아래와 같다.
#   1 ===== PAGE 1 =====      4 ===== PAGE 2 =====
#   2 alpha                   5 delta
#   3 beta                    6 (빈 줄)
#                             7 epsilon
TWO_PAGES = ("alpha\nbeta", "delta\n\nepsilon")


def test_numbered_text_format():
    text = make("alpha\nbeta").numbered_text()
    assert text.splitlines() == [
        "L000001| ===== PAGE 1 =====",
        "L000002| alpha",
        "L000003| beta",
    ]


def test_every_line_matches_the_documented_format():
    for row in make(*TWO_PAGES).numbered_text().splitlines():
        assert re.fullmatch(r"L\d{6}\| .*", row) or row == "L000006| ", row


def test_page_header_takes_a_line_and_numbers_are_one_to_one():
    """페이지 머리글도 한 줄이고, 빈 줄도 한 줄이다 — 번호 n 은 언제나 n 번째 줄이다."""
    doc = make(*TWO_PAGES)
    assert doc.line_count == 7
    assert doc.doc_lines == [
        "===== PAGE 1 =====", "alpha", "beta",
        "===== PAGE 2 =====", "delta", "", "epsilon",
    ]
    rows = doc.numbered_text().splitlines()
    assert len(rows) == doc.line_count
    for n, row in enumerate(rows, start=1):
        assert row.startswith(f"L{n:06d}| ")
        assert row[len("L000001| "):] == doc.line_at(n)


def test_line_at_is_one_based_and_none_outside():
    doc = make(*TWO_PAGES)
    assert doc.line_at(1) == "===== PAGE 1 ====="
    assert doc.line_at(2) == "alpha"
    assert doc.line_at(7) == "epsilon"
    assert doc.line_at(0) is None
    assert doc.line_at(8) is None
    assert doc.line_at(-1) is None


def test_slice_does_not_renumber():
    """구간만 잘라도 번호는 문서 통번호 그대로다."""
    doc = make(*TWO_PAGES)
    assert doc.numbered_text(5, 7).splitlines() == [
        "L000005| delta",
        "L000006| ",
        "L000007| epsilon",
    ]
    assert doc.numbered_text(2, 2) == "L000002| alpha"


def test_slice_is_a_view_of_the_full_text():
    """구간 = 전체에서 같은 번호의 줄을 그대로 뽑은 것."""
    doc = make(*TWO_PAGES)
    full = doc.numbered_text().splitlines()
    assert doc.numbered_text(3, 6).splitlines() == full[2:6]


def test_slice_bounds_are_clamped_to_the_document():
    doc = make(*TWO_PAGES)
    assert doc.numbered_text(0, 999) == doc.numbered_text()
    assert doc.numbered_text(6, 999).splitlines()[0] == "L000006| "
    assert doc.numbered_text(9, 12) == ""


def test_slice_text_has_no_numbers_and_includes_both_ends():
    doc = make(*TWO_PAGES)
    assert doc.slice_text(2, 3) == "alpha\nbeta"
    assert doc.slice_text(5, 5) == "delta"
    assert doc.slice_text(3, 2) == ""             # 거꾸로 준 구간은 비어 있다
    assert doc.slice_text(6, 99) == "\nepsilon"   # 문서 끝으로 잘린다


def test_page_of_maps_a_line_back_to_its_page():
    doc = make(*TWO_PAGES)
    assert [doc.page_of(n) for n in range(1, 8)] == [1, 1, 1, 2, 2, 2, 2]


def test_page_of_counts_the_page_header_as_part_of_its_page():
    doc = make(*TWO_PAGES)
    assert doc.page_of(4) == 2                    # 두 번째 페이지의 머리글 줄


def test_page_of_is_none_outside_the_document():
    doc = make(*TWO_PAGES)
    assert doc.page_of(0) is None
    assert doc.page_of(8) is None


def test_a_page_with_no_text_still_owns_its_header_line():
    doc = make("", "x")                            # 스캔본처럼 텍스트 없는 페이지
    assert doc.doc_lines == ["===== PAGE 1 =====", "", "===== PAGE 2 =====", "x"]
    assert doc.page_of(2) == 1 and doc.page_of(4) == 2


def test_empty_document_has_no_lines():
    doc = make()
    assert doc.line_count == 0
    assert doc.numbered_text() == ""
    assert doc.page_of(1) is None


def test_full_text_is_unchanged():
    """`full_text` 는 번호도 머리글도 없는 원문 그대로다 — 품번 백스톱이 이걸 본다."""
    doc = make(*TWO_PAGES)
    assert doc.full_text == "alpha\nbeta\ndelta\n\nepsilon"
    assert "L000001" not in doc.full_text and "PAGE" not in doc.full_text


def test_real_html_fixture_round_trips(fixtures_dir):
    doc = load_document(fixtures_dir / "msc" / "PO-SAMPLE-0001.htm")
    rows = doc.numbered_text().splitlines()
    assert rows[0] == "L000001| ===== PAGE 1 ====="
    assert len(rows) == doc.line_count
    # 번호가 가리키는 줄이 실제로 그 원문이다
    n = next(i for i, t in enumerate(doc.doc_lines, start=1) if t.startswith("Date of Order"))
    assert rows[n - 1] == f"L{n:06d}| Date of Order | 2/17/26"
    assert doc.slice_text(n, n) == "Date of Order | 2/17/26"
    assert doc.page_of(n) == 1


def test_replaced_copy_recomputes_lines():
    """`dataclasses.replace` 로 만든 사본(파일명만 바꾼 것)이 낡은 줄 캐시를 물고 가지 않는다."""
    from dataclasses import replace

    doc = make("a")
    assert doc.line_count == 2
    other = replace(doc, filename="g.pdf", pages=["a", "b"])
    assert other.line_count == 4
    assert doc.line_count == 2


@pytest.mark.parametrize("pages", [["x"], ["a\nb", "c"], ["", "", ""]])
def test_line_count_matches_numbered_rows(pages):
    doc = make(*pages)
    assert len(doc.numbered_text().splitlines()) == doc.line_count
