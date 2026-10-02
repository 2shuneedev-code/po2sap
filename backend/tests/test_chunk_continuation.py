"""나눠 읽는 경계에 걸린 품목 — 시작한 구간이 끝까지 읽는다 (design §3.3.2).

KL 4507628839 의 11번 품목은 L120~L125 인데 첫 구간이 L122 에서 끝나 `Brand:`(L124)가
다음 구간으로 넘어가 사라졌다. 이제 구간은 품목 시작 줄 기준이다 — 구간 끝 뒤의
`continuation_lines` 줄을 함께 보내 그 품목을 완성하고, 그 줄에서 시작한 품목은 다음
구간의 것이라 병합에서 버린다.
"""

from __future__ import annotations

from app.extraction import chunking
from app.extraction.merge import merge
from app.extraction.preprocess import SourceDoc
from app.extraction.prompt import build_lines_prompt

POLICY = {
    "enabled": True, "max_lines_per_chunk": 10, "tokens_per_line": 1, "safety_ratio": 1.0,
    "header_context_lines": 0, "continuation_lines": 4,
}


def _doc(n: int) -> SourceDoc:
    return SourceDoc(filename="d.pdf", ext="pdf", pages=["\n".join(f"line {i}" for i in range(1, n + 1))],
                     has_text_layer=True)


def test_plan_reads_past_the_boundary_but_not_past_the_block():
    doc = _doc(40)
    chunks = chunking.plan({"line_range": {"src": 1, "src_end": 25}}, doc, POLICY, max_tokens=1000)
    assert [(c.start, c.end, c.tail_end) for c in chunks] == [
        (1, 9, 13), (10, 17, 21), (18, 25, 25),          # 마지막 구간은 블록 밖으로 이어 읽지 않는다
    ]


def test_plan_without_continuation_keeps_the_old_boundaries():
    doc = _doc(40)
    policy = {**POLICY, "continuation_lines": 0}
    chunks = chunking.plan({"line_range": {"src": 1, "src_end": 25}}, doc, policy, max_tokens=1000)
    assert all(c.tail_end == c.end for c in chunks)


def test_merge_keeps_items_by_start_line_and_allows_tail_evidence():
    doc = _doc(40)
    first = chunking.Chunk(None, 1, 1, 9, read_end=13)
    second = chunking.Chunk(None, 2, 10, 17, read_end=21)
    payload, issues = merge({"line_range": {"src": 1, "src_end": 25}}, [
        # 첫 구간: 9번 줄에서 시작해 12번 줄까지 이어지는 품목 + 이어 읽은 줄에서 시작한 품목(버린다)
        (first, {"lines": [{"src": 9, "src_end": 12, "item_code": "A"},
                           {"src": 11, "item_code": "B-dup"}]}),
        (second, {"lines": [{"src": 11, "item_code": "B"}]}),
    ], doc)
    assert [(it["src"], it["item_code"]) for it in payload["lines"]] == [(9, "A"), (11, "B")]
    assert payload["lines"][0]["chunk"] == [1, 13]          # 근거 줄은 이어 읽은 줄까지 허용
    assert not issues


def test_prompt_marks_continuation_lines():
    text = build_lines_prompt("KL", None, "", "L000120| item", 100, 122,
                              continuation="L000123| ISO\nL000124| Brand: WIDIA GTD")
    assert "이어 읽을 줄" in text and "Brand: WIDIA GTD" in text
    assert "구간에서 시작하는 품목만" in text
    plain = build_lines_prompt("KL", None, "", "L000120| item", 100, 122)
    assert "이어 읽을 줄" not in plain


def test_whole_block_chunk_gets_the_plain_instruction():
    """경계에 걸릴 일이 없는 구간에 '앞 품목 줄은 무시' 를 붙이면 블록 머리와 함께 품목까지
    버린 적이 있다(SID TOOL 7988114 HARRISBURG 0건) — 그런 구간은 예전 지시 그대로다."""
    plain = build_lines_prompt("SID", None, "", "L000145| Contact", 145, 202)
    assert "구간의 품목만" in plain and "앞 구간" not in plain
    mid = build_lines_prompt("KL", None, "", "L000123| ISO", 123, 160, mid_block=True)
    assert "앞 구간 품목의 것이니 무시" in mid


def test_plan_marks_only_later_chunks_as_mid_block():
    chunks = chunking.plan({"line_range": {"src": 1, "src_end": 25}}, _doc(40), POLICY, max_tokens=1000)
    assert [c.mid_block for c in chunks] == [False, True, True]
