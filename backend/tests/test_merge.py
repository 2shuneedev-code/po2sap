"""청크 결과 병합 — design.md §3.3.4. **LLM 호출 없이** 합성 응답으로 본다."""

from __future__ import annotations

import random

from app.extraction.chunking import Chunk
from app.extraction.merge import merge
from app.extraction.preprocess import SourceDoc

# 3쪽짜리 문서: 줄 1=PAGE 1, 2..9 본문 / 10=PAGE 2, 11..19 / 20=PAGE 3 ...
DOC = SourceDoc(
    filename="d.htm", ext="htm",
    pages=["\n".join(f"a{i}" for i in range(8)),
           "\n".join(f"b{i}" for i in range(9)),
           "\n".join(f"c{i}" for i in range(9))],
)


def item(src: int, **extra) -> dict:
    return {"src": src, "confidence": 0.99, "item_code": f"P{src}", "quantity": "1", **extra}


def outline(*, blocks: int = 2, line_range: bool = False) -> dict:
    if line_range:
        return {"header": {}, "line_range": {"src": 2, "src_end": 19}, "totals": {}}
    return {
        "header": {"po_number": {"value": "1", "src": 2, "confidence": 0.9}},
        "shipments": [{"src": 2 + 8 * i, "src_end": 9 + 8 * i} for i in range(blocks)],
        "totals": {"line_count": 4},
        "notes": ["n"],
    }


def chunk(shipment, index, start, end) -> Chunk:
    return Chunk(shipment, index, start, end)


def codes(issues):
    return [(i.level, i.code) for i in issues]


# ── 이어 붙이기 ────────────────────────────────────────────────────────
def test_chunks_are_appended_in_order_and_line_no_restarts_per_order():
    payload, issues = merge(outline(), [
        (chunk(0, 1, 2, 5), {"lines": [item(3), item(4)]}),
        (chunk(0, 2, 6, 9), {"lines": [item(7)]}),
        (chunk(1, 3, 10, 14), {"lines": [item(11), item(12)]}),
    ], DOC)
    assert issues == []
    first, second = payload["shipments"]
    assert [ln["src"] for ln in first["lines"]] == [3, 4, 7]
    assert [ln["line_no"] for ln in first["lines"]] == [1, 2, 3]            # 오더 단위 안에서 1부터
    assert [ln["line_no"] for ln in second["lines"]] == [1, 2]              # 다음 오더는 다시 1


def test_the_model_supplied_line_numbers_are_ignored():
    """모델이 준 번호는 청크 안에서만 센 값이다 — 두 청크가 다 1 부터 세도 겹치지 않는다."""
    payload, _ = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 5), {"lines": [item(3, line_no=1), item(4, line_no=2)]}),
        (chunk(0, 2, 6, 9), {"lines": [item(7, line_no=1)]}),
    ], DOC)
    assert [ln["line_no"] for ln in payload["shipments"][0]["lines"]] == [1, 2, 3]


def test_arrival_order_does_not_matter():
    """병렬로 읽으면 끝나는 순서가 뒤죽박죽이다 — 결과는 문서 순서여야 한다."""
    results = [
        (chunk(0, 1, 2, 5), {"lines": [item(3), item(4)]}),
        (chunk(0, 2, 6, 9), {"lines": [item(7)]}),
        (chunk(1, 3, 10, 14), {"lines": [item(11)]}),
        (chunk(1, 4, 15, 19), {"lines": [item(16), item(17)]}),
    ]
    expected, _ = merge(outline(), results, DOC)
    rng = random.Random(7)
    for _ in range(10):
        shuffled = results[:]
        rng.shuffle(shuffled)
        payload, _ = merge(outline(), shuffled, DOC)
        assert payload == expected
    assert [ln["src"] for ln in expected["shipments"][1]["lines"]] == [11, 16, 17]


def test_pieces_of_a_split_chunk_keep_their_position():
    """절단으로 쪼갠 조각은 같은 청크 번호로 오고 위치(start)로 정렬된다."""
    payload, _ = merge(outline(blocks=1), [
        (chunk(0, 1, 6, 9), {"lines": [item(7), item(8)]}),
        (chunk(0, 1, 2, 5), {"lines": [item(3)]}),
    ], DOC)
    assert [ln["src"] for ln in payload["shipments"][0]["lines"]] == [3, 7, 8]


def test_outline_parts_survive_and_the_input_is_not_mutated():
    src = outline()
    before = repr(src)
    payload, _ = merge(src, [(chunk(0, 1, 2, 9), {"lines": [item(3)]})], DOC)
    assert repr(src) == before                                               # 원본 골격은 그대로
    assert payload["header"]["po_number"]["value"] == "1"
    assert payload["totals"] == {"line_count": 4} and payload["notes"] == ["n"]
    assert "lines" not in src["shipments"][0]


def test_line_range_outline_puts_lines_at_the_top_level():
    payload, issues = merge(outline(line_range=True), [
        (chunk(None, 1, 2, 9), {"lines": [item(3)]}),
        (chunk(None, 2, 10, 19), {"lines": [item(11)]}),
    ], DOC)
    assert issues == []
    assert "line_range" not in payload and "shipments" not in payload
    assert [ln["line_no"] for ln in payload["lines"]] == [1, 2]


def test_posex_is_left_alone():
    """POSEX 생성은 ⑥ FIELDS 의 몫이다 — 병합은 만들지 않는다 (§2.1-7)."""
    payload, _ = merge(outline(blocks=1), [(chunk(0, 1, 2, 9), {"lines": [item(3)]})], DOC)
    assert "posex" not in payload["shipments"][0]["lines"][0]


# ── 중복 ───────────────────────────────────────────────────────────────
def test_duplicate_src_keeps_the_first_and_warns():
    payload, issues = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 5), {"lines": [item(4, quantity="1")]}),
        (chunk(0, 2, 6, 9), {"lines": [item(4, quantity="99"), item(7)]}),
    ], DOC)
    lines = payload["shipments"][0]["lines"]
    assert [(ln["src"], ln["quantity"]) for ln in lines] == [(4, "1"), (7, "1")]
    assert codes(issues) == [("warn", "DUPLICATE_LINE")]
    assert issues[0].field == "shipments[1].lines"
    assert "L000004" in issues[0].message


def test_the_same_src_in_different_orders_is_not_a_duplicate():
    payload, issues = merge(outline(), [
        (chunk(0, 1, 2, 9), {"lines": [item(5)]}),
        (chunk(1, 2, 10, 19), {"lines": [item(5)]}),        # 오더가 다르면 별개다
    ], DOC)
    assert issues == []
    assert all(len(s["lines"]) == 1 for s in payload["shipments"])


# ── 실패한 청크 ────────────────────────────────────────────────────────
def test_a_failed_chunk_keeps_the_rest_and_says_which_lines_are_missing():
    payload, issues = merge(outline(), [
        (chunk(0, 1, 2, 5), {"lines": [item(3)]}),
        (chunk(0, 2, 6, 9), None),
        (chunk(1, 3, 10, 14), {"lines": [item(11), item(12)]}),
    ], DOC)
    assert [ln["src"] for ln in payload["shipments"][0]["lines"]] == [3]     # 나머지는 살아 있다
    assert len(payload["shipments"][1]["lines"]) == 2
    assert codes(issues) == [("error", "CHUNK_FAILED")]
    assert "L000006~L000009" in issues[0].message                            # 빠진 줄 범위


def test_a_failed_chunk_is_reported_at_order_level_so_it_reaches_every_row_of_it():
    """`shipments[i].lines` (1-기준) — `batch_service._grounding_by_row` 가 그 오더 전 행에 붙인다."""
    _, issues = merge(outline(), [(chunk(1, 1, 10, 19), None)], DOC)
    assert issues[0].field == "shipments[2].lines"
    _, issues = merge(outline(line_range=True), [(chunk(None, 1, 2, 19), None)], DOC)
    assert issues[0].field == "lines"


def test_the_failure_reason_is_appended_when_given():
    _, issues = merge(outline(blocks=1), [(chunk(0, 5, 2, 9), None)], DOC,
                      reasons={5: "시간 초과"})
    assert "시간 초과" in issues[0].message


def test_two_failed_pieces_each_report_their_own_range():
    _, issues = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 5), None), (chunk(0, 1, 6, 9), None),
    ], DOC)
    assert [("L000002~L000005" in i.message, "L000006~L000009" in i.message) for i in issues] \
        == [(True, False), (False, True)]


# ── 빈 청크 ────────────────────────────────────────────────────────────
def test_an_empty_chunk_is_a_warning_not_an_error():
    """구간에 진짜 품목이 없을 수도 있다."""
    payload, issues = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 5), {"lines": []}),
        (chunk(0, 2, 6, 9), {}),
        (chunk(0, 3, 6, 9), {"lines": [item(7)]}),
    ], DOC)
    assert codes(issues) == [("warn", "EMPTY_CHUNK"), ("warn", "EMPTY_CHUNK")]
    assert len(payload["shipments"][0]["lines"]) == 1


# ── 페이지 ─────────────────────────────────────────────────────────────
def test_page_is_computed_from_src_by_code():
    """`page` 는 모델에게 묻지 않는다 — `src` 로 코드가 계산한다 (P1)."""
    payload, _ = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 19), {"lines": [item(3, page=99), item(12), item(20), item(0)]}),
    ], DOC)
    pages = {ln["src"]: ln["page"] for ln in payload["shipments"][0]["lines"]}
    assert pages[3] == 1                       # 모델이 99 라 해도 무시한다
    assert pages[12] == 2
    assert pages[20] == 3
    assert pages[0] is None                    # 범위 밖 줄 번호는 페이지가 없다


def test_the_reading_range_travels_with_each_line_for_the_grounding_check():
    payload, _ = merge(outline(blocks=1), [(chunk(0, 1, 6, 9), {"lines": [item(7)]})], DOC)
    assert payload["shipments"][0]["lines"][0]["chunk"] == [6, 9]


def test_a_line_without_src_is_kept_so_the_grounding_can_flag_it():
    payload, issues = merge(outline(blocks=1), [
        (chunk(0, 1, 2, 9), {"lines": [{"confidence": 0.9, "item_code": "X"}]}),
    ], DOC)
    assert issues == []
    assert payload["shipments"][0]["lines"][0]["page"] is None
