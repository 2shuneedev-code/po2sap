"""청크 경계 계산 — design.md §3.3.3. **LLM 호출 없이** 합성 골격으로 본다.

경계는 블록 먼저, 그다음 줄 수다. 겹침 0 · 빈틈 0, 블록을 넘는 청크는 없다.
"""

from __future__ import annotations

import math
import shutil

import pytest
from app.config import Settings
from app.extraction import chunking
from app.extraction.chunking import Chunk, ChunkPlanError, chunk_policy, plan
from app.extraction.preprocess import SourceDoc
from app.masters.loader import MasterError, load_customer

POLICY = {
    "enabled": True,
    "max_lines_per_chunk": 10,
    "tokens_per_line": 80,
    "safety_ratio": 0.7,
    "header_context_lines": 40,
}
BIG = 10**9            # max_tokens 쪽 한도가 걸리지 않게


def doc_of(n_lines: int) -> SourceDoc:
    """전체 줄 수가 `n_lines` 인 문서 (PAGE 머리글 1줄 + 본문 n-1줄)."""
    return SourceDoc(filename="d.htm", ext="htm",
                     pages=["\n".join(f"row {i}" for i in range(n_lines - 1))])


def covered(chunks: list[Chunk]) -> list[int]:
    return [n for c in chunks for n in range(c.start, c.end + 1)]


def block(src: int, end: int) -> dict:
    return {"src": src, "src_end": end}


# ── 개수와 분포 ────────────────────────────────────────────────────────
def test_block_within_the_limit_is_one_chunk():
    chunks = plan({"shipments": [block(5, 14)]}, doc_of(50), POLICY, BIG)
    assert [(c.start, c.end) for c in chunks] == [(5, 14)]
    assert chunks[0].shipment_index == 0


def test_limit_times_two_plus_one_is_three_chunks_without_gap_or_overlap():
    chunks = plan({"shipments": [block(1, 21)]}, doc_of(50), POLICY, BIG)      # 21 = 10×2+1
    assert len(chunks) == 3
    assert covered(chunks) == list(range(1, 22))                              # 겹침 0 · 빈틈 0
    assert all(c.size <= POLICY["max_lines_per_chunk"] for c in chunks)


def test_split_is_even_so_the_last_chunk_is_not_a_stub():
    """21줄을 10+10+1 이 아니라 7+7+7 로 — 마지막만 1줄짜리가 되면 그 호출이 낭비다."""
    chunks = plan({"shipments": [block(1, 21)]}, doc_of(50), POLICY, BIG)
    assert [c.size for c in chunks] == [7, 7, 7]
    uneven = plan({"shipments": [block(1, 22)]}, doc_of(50), POLICY, BIG)     # 22 = 8+7+7
    assert sorted(c.size for c in uneven) == [7, 7, 8]
    assert [c.size for c in uneven][0] == 8                                    # 남는 줄은 앞쪽이


def test_chunk_index_is_a_document_wide_sequence_starting_at_one():
    chunks = plan({"shipments": [block(1, 15), block(20, 40)]}, doc_of(50), POLICY, BIG)
    assert [c.chunk_index for c in chunks] == list(range(1, len(chunks) + 1))


# ── 블록 ───────────────────────────────────────────────────────────────
def test_no_chunk_crosses_a_block_boundary():
    blocks = [block(2, 13), block(15, 30), block(31, 33)]
    chunks = plan({"shipments": blocks}, doc_of(50), POLICY, BIG)
    for c in chunks:
        b = blocks[c.shipment_index]
        assert b["src"] <= c.start and c.end <= b["src_end"]
    for i, b in enumerate(blocks):                                             # 블록마다 정확히 덮는다
        own = [c for c in chunks if c.shipment_index == i]
        assert covered(own) == list(range(b["src"], b["src_end"] + 1))


def test_gaps_between_blocks_are_not_read():
    """블록 사이의 줄(요약표·서식)은 읽지 않는다 — 청크는 블록 안에만 있다."""
    chunks = plan({"shipments": [block(2, 5), block(20, 22)]}, doc_of(50), POLICY, BIG)
    assert set(covered(chunks)).isdisjoint(range(6, 20))


def test_without_blocks_the_line_range_is_split_too():
    """`split.by: none` — 골격이 `line_range` 하나를 주고 그것을 줄 수로 나눈다."""
    chunks = plan({"line_range": block(3, 32)}, doc_of(50), POLICY, BIG)
    assert len(chunks) == 3
    assert covered(chunks) == list(range(3, 33))
    assert all(c.shipment_index is None for c in chunks)


def test_empty_shipments_and_no_line_range_yield_no_chunks():
    assert plan({"shipments": []}, doc_of(50), POLICY, BIG) == []
    assert plan({}, doc_of(50), POLICY, BIG) == []


def test_disabled_chunking_is_one_chunk_per_block():
    off = {**POLICY, "enabled": False}
    chunks = plan({"shipments": [block(1, 40), block(41, 49)]}, doc_of(50), off, BIG)
    assert [(c.start, c.end) for c in chunks] == [(1, 40), (41, 49)]


# ── 한도 ───────────────────────────────────────────────────────────────
def test_the_token_limit_wins_when_it_is_smaller():
    """max_tokens × safety / tokens_per_line = 800×0.7/80 = 7 < 10."""
    assert math.floor(800 * 0.7 / 80) == 7
    chunks = plan({"shipments": [block(1, 21)]}, doc_of(50), POLICY, 800)
    assert len(chunks) == 3 and all(c.size == 7 for c in chunks)
    assert chunking.line_limit(POLICY, 800) == 7
    assert chunking.line_limit(POLICY, BIG) == 10


def test_limit_is_at_least_one_line():
    assert chunking.line_limit(POLICY, 1) == 1


# ── 정책 병합 ──────────────────────────────────────────────────────────
@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def test_base_defaults_reach_every_customer(masters_dir):
    """`_base` 에 있는 기본값이 거래처 파일에 적지 않아도 전 거래처에 들어온다."""
    for code in ("msc", "kl", "ygjp"):
        policy = chunk_policy(load_customer(code, masters_dir))
        assert set(policy) == set(chunking.CHUNKING_KEYS)
        assert policy["enabled"] is True


def test_customer_overriding_one_key_keeps_the_other_defaults(workspace):
    """SCHEMA §1 의 유일한 예외 — `extraction.chunking` 은 **키 단위로** 합친다."""
    base_before = chunk_policy(load_customer("msc", workspace))

    path = workspace / "customers" / "msc.yaml"
    text = path.read_text(encoding="utf-8")
    assert "  page_limit: 40" in text
    path.write_text(
        text.replace("  page_limit: 40", "  page_limit: 40\n  chunking:\n    max_lines_per_chunk: 150"),
        encoding="utf-8",
    )
    policy = chunk_policy(load_customer("msc", workspace))
    assert policy["max_lines_per_chunk"] == 150
    for key in chunking.CHUNKING_KEYS:
        if key != "max_lines_per_chunk":
            assert policy[key] == base_before[key], key


def test_raising_the_base_default_reaches_a_customer_that_overrides_another_key(workspace):
    """거래처가 한 값만 덮었어도 나머지는 `_base` 를 따라간다 — 낡은 값에 묶이지 않는다."""
    msc = workspace / "customers" / "msc.yaml"
    msc.write_text(
        msc.read_text(encoding="utf-8").replace(
            "  page_limit: 40", "  page_limit: 40\n  chunking:\n    safety_ratio: 0.5"),
        encoding="utf-8",
    )
    base = workspace / "_base" / "sap_defaults.yaml"
    base.write_text(
        base.read_text(encoding="utf-8").replace(
            "max_lines_per_chunk: 120", "max_lines_per_chunk: 90"),
        encoding="utf-8",
    )
    policy = chunk_policy(load_customer("msc", workspace))
    assert policy["safety_ratio"] == 0.5             # 거래처가 덮은 값
    assert policy["max_lines_per_chunk"] == 90       # `_base` 를 따라간 값


def test_a_master_without_base_defaults_fails_loudly_instead_of_guessing(masters_dir):
    """코드에 기본값을 숨겨 두지 않는다 (design §3.3.3) — 없으면 없다고 말한다."""
    master = load_customer("msc", masters_dir)
    master.extraction = {k: v for k, v in master.extraction.items() if k != "chunking"}
    with pytest.raises(MasterError, match="청크 정책"):
        chunk_policy(master)                          # settings 도 없다 → 채울 곳이 없다


def test_policy_falls_back_to_the_base_file_through_settings(masters_dir):
    master = load_customer("msc", masters_dir)
    master.extraction = {k: v for k, v in master.extraction.items() if k != "chunking"}
    policy = chunk_policy(master, Settings(masters_dir=masters_dir))
    assert policy["max_lines_per_chunk"] > 0


# ── OUTLINE 이 준 구간 검증 ────────────────────────────────────────────
def test_block_outside_the_document_is_rejected():
    with pytest.raises(ChunkPlanError, match="문서 범위"):
        plan({"shipments": [block(40, 60)]}, doc_of(50), POLICY, BIG)
    with pytest.raises(ChunkPlanError, match="문서 범위"):
        plan({"shipments": [block(0, 10)]}, doc_of(50), POLICY, BIG)


def test_inverted_block_is_rejected():
    with pytest.raises(ChunkPlanError, match="뒤입니다"):
        plan({"shipments": [block(20, 10)]}, doc_of(50), POLICY, BIG)


def test_missing_anchor_is_rejected():
    with pytest.raises(ChunkPlanError, match="줄 번호가 없습니다"):
        plan({"shipments": [{"src": 5}]}, doc_of(50), POLICY, BIG)
    with pytest.raises(ChunkPlanError):
        plan({"line_range": {"src_end": 9}}, doc_of(50), POLICY, BIG)


def test_overlapping_blocks_are_rejected():
    with pytest.raises(ChunkPlanError, match="겹칩니다"):
        plan({"shipments": [block(2, 20), block(15, 30)]}, doc_of(50), POLICY, BIG)


def test_touching_at_one_line_counts_as_overlap_but_adjacent_blocks_do_not():
    with pytest.raises(ChunkPlanError, match="겹칩니다"):
        plan({"shipments": [block(2, 20), block(20, 30)]}, doc_of(50), POLICY, BIG)
    ok = plan({"shipments": [block(2, 20), block(21, 30)]}, doc_of(50), POLICY, BIG)
    assert covered(ok) == list(range(2, 31))


def test_all_problems_are_reported_at_once():
    with pytest.raises(ChunkPlanError) as info:
        plan({"shipments": [block(20, 10), block(40, 99)]}, doc_of(50), POLICY, BIG)
    message = str(info.value)
    assert "블록 1" in message and "블록 2" in message


def test_the_blocks_may_arrive_out_of_document_order_but_not_overlap():
    """OUTLINE 이 순서를 뒤섞어 줘도 겹치지만 않으면 받는다 — 청크는 OUTLINE 순서를 따른다."""
    chunks = plan({"shipments": [block(30, 35), block(2, 8)]}, doc_of(50), POLICY, BIG)
    assert [c.shipment_index for c in chunks] == [0, 1]
    assert (chunks[0].start, chunks[1].start) == (30, 2)


def test_chunking_module_knows_no_customer_names():
    """P2 — 이 모듈은 거래처를 모른다. `split.by` 도 정책 dict 도 아닌 것으로 분기하지 않는다."""
    import inspect

    source = inspect.getsource(chunking).upper()
    for name in ("MSC", "YGJP", "KENNAMETAL"):
        assert name not in source
