"""분할 추출의 오케스트레이션 — OUTLINE → LINES 병렬 → 병합 → 그라운딩 (design.md §3.3).

**LLM 호출 없이** 가짜 프로바이더로 끝까지 흘려 본다. 진짜 모델의 성실한 응답을 흉내 낸 것이라
분할·병합·병렬·캐시·진행 표시가 이어지는지를 본다. 값이 맞는지는 실물로만 알 수 있다.
"""

from __future__ import annotations

import json
import threading

import pytest
from app import batch_service
from app.config import Settings
from app.domain.models import Batch, BatchFile, GroundingIssue
from app.extraction import Extractor, chunking
from app.extraction import extractor as extractor_mod
from app.extraction.extractor import STAGE_LINES, STAGE_OUTLINE, _to_raw_po
from app.extraction.preprocess import SourceDoc
from app.extraction.providers import cache as llm_cache
from app.extraction.providers.base import LLMError
from app.masters.loader import load_customer
from app.storage import BatchRepo
from llm_fakes import BoomProvider, FakeProvider, lines_payload, make_doc, outline_payload

TOKENS_FOR_9_LINES = 1120           # floor(1120 × 0.7 / 80) = 9 줄


def settings(tmp_path, masters_dir, **over) -> Settings:
    base = {"llm_provider": "mock", "masters_dir": masters_dir, "storage_dir": tmp_path,
            "llm_max_tokens": TOKENS_FOR_9_LINES, "llm_max_concurrency": 4}
    return Settings(**{**base, **over})


def make(tmp_path, masters_dir, provider, **over) -> Extractor:
    return Extractor(settings(tmp_path, masters_dir, **over), provider=provider,
                     sleep=lambda _s: None)


@pytest.fixture
def msc(masters_dir):
    return load_customer("msc", masters_dir)


@pytest.fixture
def kl(masters_dir):
    return load_customer("kl", masters_dir)


@pytest.fixture
def as_file(monkeypatch):
    """`parse_file` 이 파일 대신 이 문서를 읽게 한다 (합성 문서를 디스크에 쓰지 않는다)."""
    def use(doc: SourceDoc) -> None:
        monkeypatch.setattr(extractor_mod, "load_document", lambda _p: doc)
    return use


# ── 끝까지 ─────────────────────────────────────────────────────────────
def test_outline_lines_merge_and_grounding_run_end_to_end(tmp_path, masters_dir, as_file):
    doc, blocks = make_doc([20, 15, 7])                 # 21 · 16 · 8 줄 → 청크 3 + 2 + 1
    as_file(doc)
    fake = FakeProvider(doc, outline_payload(doc, blocks))

    result = make(tmp_path, masters_dir, fake).parse_file("x.htm", "MSC")

    assert len(fake.of("outline_purchase_order")) == 1
    assert len(fake.of("extract_lines")) == 6
    raw = result.raw
    assert [len(s.lines) for s in raw.shipments] == [20, 15, 7]
    assert [ln.line_no for ln in raw.shipments[0].lines] == list(range(1, 21))   # 오더 안에서 1부터
    assert [ln.line_no for ln in raw.shipments[2].lines] == list(range(1, 8))
    # 합계(품목 수·총 수량) 교차검증까지 통과 = 누락도 중복도 없다는 뜻이다
    assert result.error_count == 0 and result.warn_count == 0, [
        i.model_dump() for i in result.issues]
    assert raw.header.po_number.page == 1                                         # src 에서 계산
    assert result.cached is False and result.provider == "fake"


def test_every_chunk_call_stays_inside_its_own_block(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20, 15, 7])
    fake = FakeProvider(doc, outline_payload(doc, blocks))
    make(tmp_path, masters_dir, fake).extract_payload(doc, msc)

    for start, end in fake.line_ranges:
        assert any(lo <= start and end <= hi for lo, hi in blocks), (start, end)
    covered = sorted(n for s, e in fake.line_ranges for n in range(s, e + 1))
    assert covered == sorted(n for lo, hi in blocks for n in range(lo, hi + 1))   # 빈틈·겹침 0


def test_a_split_none_customer_uses_the_same_two_pass_path(tmp_path, masters_dir, kl):
    """`split.by: none` 도 같은 구조다 — 골격이 `line_range` 를 주고 그것을 줄 수로 나눈다."""
    doc, _ = make_doc([25])
    fake = FakeProvider(doc, outline_payload(doc, None))
    ex = make(tmp_path, masters_dir, fake).extract_payload(doc, kl)

    assert len(fake.of("extract_lines")) >= 3
    assert "shipments" not in ex.payload and len(ex.payload["lines"]) == 25
    assert [ln["line_no"] for ln in ex.payload["lines"]] == list(range(1, 26))
    assert ex.issues == []


def test_the_outline_and_lines_prompts_carry_the_expected_pieces(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20])
    fake = FakeProvider(doc, outline_payload(doc, blocks))
    make(tmp_path, masters_dir, fake).extract_payload(doc, msc)

    assert fake.of("outline_purchase_order")[0].doc_text == doc.numbered_text()
    second = fake.of("extract_lines")[1]                    # 앞머리 발췌 + 자기 구간
    assert f"L{second.start:06d}| " in second.doc_text
    assert "L000002| " in second.doc_text                   # 앞머리 문맥
    first = fake.of("extract_lines")[0]
    assert f"L{first.start:06d}" in first.doc_text


# ── 병렬 ───────────────────────────────────────────────────────────────
def test_completion_order_does_not_change_the_result(tmp_path, masters_dir, msc):
    """뒤 청크가 먼저 끝나도(병렬) 결과는 문서 순서다."""
    doc, blocks = make_doc([20, 15, 7])
    outline = outline_payload(doc, blocks)

    sequential = make(tmp_path / "a", masters_dir, FakeProvider(doc, outline),
                      llm_max_concurrency=1).extract_payload(doc, msc)
    reversed_fake = FakeProvider(doc, outline, delay=lambda s, e: max(0.0, (60 - s) * 0.004))
    parallel = make(tmp_path / "b", masters_dir, reversed_fake,
                    llm_max_concurrency=6).extract_payload(doc, msc)

    assert parallel.payload == sequential.payload


def test_chunks_really_run_on_worker_threads(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20, 15])
    fake = FakeProvider(doc, outline_payload(doc, blocks))
    make(tmp_path, masters_dir, fake).extract_payload(doc, msc)
    assert all(c.thread.startswith("po2sap-chunk") for c in fake.of("extract_lines"))
    assert fake.of("outline_purchase_order")[0].thread == threading.current_thread().name


def test_the_concurrency_limit_is_honoured(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20, 20, 20])
    running, peak, lock = 0, 0, threading.Lock()

    def handler(start, end):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        threading.Event().wait(0.03)
        with lock:
            running -= 1
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    make(tmp_path, masters_dir, fake, llm_max_concurrency=2).extract_payload(doc, msc)
    assert peak == 2


# ── 진행 콜백: 메인 스레드에서만 ────────────────────────────────────────
def test_progress_is_reported_from_the_calling_thread_only(tmp_path, masters_dir, msc):
    """워커 스레드에서 스트림릿 위젯을 만지면 경고가 나거나 화면이 오동작한다."""
    doc, blocks = make_doc([20, 15, 7])
    fake = FakeProvider(doc, outline_payload(doc, blocks),
                        delay=lambda s, e: 0.005)                       # 워커가 실제로 겹치게
    seen: list[tuple[str, int, int, str, threading.Thread]] = []

    def on_progress(stage, done, total, label):
        seen.append((stage, done, total, label, threading.current_thread()))

    make(tmp_path, masters_dir, fake).extract_payload(doc, msc, on_progress=on_progress)

    assert seen
    assert {t for *_rest, t in seen} == {threading.current_thread()}
    assert all(c.thread != threading.current_thread().name for c in fake.of("extract_lines"))

    stages = [(stage, done, total) for stage, done, total, *_ in seen]
    assert stages[:2] == [(STAGE_OUTLINE, 0, 1), (STAGE_OUTLINE, 1, 1)]
    lines = [(d, t) for s, d, t in stages if s == STAGE_LINES]
    assert lines[0] == (0, 6) and lines[-1] == (6, 6)                    # 처음 0/6 끝 6/6
    assert [d for d, _ in lines] == sorted(d for d, _ in lines)          # 줄어들지 않는다
    assert {label for *_x, label, _t in seen} == {doc.filename}


def test_progress_callback_is_optional(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([5])
    make(tmp_path, masters_dir, FakeProvider(doc, outline_payload(doc, blocks))) \
        .extract_payload(doc, msc)


# ── 저장된 응답: 문서 단위 픽스처가 이기고, 그러면 호출이 없다 ─────────────
def test_a_document_fixture_means_the_provider_is_never_called(tmp_path, masters_dir, fixtures_dir):
    boom = BoomProvider()
    progress = []
    result = make(tmp_path, masters_dir, boom).parse_file(
        fixtures_dir / "msc" / "PO-SAMPLE-0001.htm", "MSC",
        on_progress=lambda *a: progress.append(a))

    assert boom.calls == 0
    assert result.cached is True and result.provider == "fixture"
    assert progress == []                             # 청크 로직에 들어가지 않는다
    assert len(result.raw.shipments) == 2 and result.error_count == 0


def write_fixture(directory, name: str, payload: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps({"payload": payload, "model": "fixture", "provider": "fixture"}),
        encoding="utf-8")


def test_document_fixture_wins_over_chunk_fixtures(tmp_path, masters_dir, as_file):
    doc, blocks = make_doc([8])
    as_file(doc)
    fx = tmp_path / "fx"
    doc_level = {"header": {"po_number": {"value": "1234", "src": 2, "confidence": 0.99}},
                 "shipments": [{"src": blocks[0][0], "src_end": blocks[0][1],
                                "lines": [{"src": blocks[0][0] + 1, "confidence": 0.99,
                                           "item_code": "ITEM-0001", "quantity": "11"}]}],
                 "totals": {}}
    write_fixture(fx, llm_cache.fixture_name("MSC", doc.filename), doc_level)
    # 골격·청크 픽스처도 같이 있지만 — 문서 단위가 있으니 읽히지 않는다
    write_fixture(fx, llm_cache.outline_fixture_name("MSC", doc.filename),
                  outline_payload(doc, blocks))
    write_fixture(fx, llm_cache.chunk_fixture_name("MSC", doc.filename, 1),
                  lines_payload(doc, *blocks[0]))

    boom = BoomProvider()
    extractor = make(tmp_path, masters_dir, boom)
    extractor._fixtures_dir = fx
    result = extractor.parse_file("x.htm", "MSC")

    assert boom.calls == 0
    assert len(result.raw.shipments[0].lines) == 1          # 문서 단위(1건)가 이겼다 — 청크였다면 8건


def test_call_level_fixtures_replay_the_whole_path_without_a_document_fixture(
        tmp_path, masters_dir, msc):
    """문서 단위 픽스처가 없을 때만 쓰이는 보조 수단 — 골격 1개 + 청크 N개."""
    doc, blocks = make_doc([20, 15])
    outline = outline_payload(doc, blocks)
    policy = chunking.chunk_policy(msc)
    plan = chunking.plan(outline, doc, policy, TOKENS_FOR_9_LINES)

    fx = tmp_path / "fx"
    write_fixture(fx, llm_cache.outline_fixture_name("MSC", doc.filename), outline)
    for c in plan:
        write_fixture(fx, llm_cache.chunk_fixture_name("MSC", doc.filename, c.chunk_index),
                      lines_payload(doc, c.start, c.end))

    boom = BoomProvider()
    extractor = make(tmp_path, masters_dir, boom)
    extractor._fixtures_dir = fx
    ex = extractor.extract_payload(doc, msc)

    assert boom.calls == 0 and ex.cached is True and ex.issues == []
    assert [len(s["lines"]) for s in ex.payload["shipments"]] == [20, 15]


def test_a_missing_chunk_fixture_fails_only_that_chunk(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20])
    outline = outline_payload(doc, blocks)
    plan = chunking.plan(outline, doc, chunking.chunk_policy(msc), TOKENS_FOR_9_LINES)
    fx = tmp_path / "fx"
    write_fixture(fx, llm_cache.outline_fixture_name("MSC", doc.filename), outline)
    for c in plan[:-1]:                                     # 마지막 청크 픽스처만 빠졌다
        write_fixture(fx, llm_cache.chunk_fixture_name("MSC", doc.filename, c.chunk_index),
                      lines_payload(doc, c.start, c.end))

    extractor = make(tmp_path, masters_dir, FakeProvider(doc, outline,
                     lines_handler=lambda s, e: (_ for _ in ()).throw(LLMError("재생할 응답 없음"))))
    extractor._fixtures_dir = fx
    ex = extractor.extract_payload(doc, msc)

    failed = [i for i in ex.issues if i.code == "CHUNK_FAILED"]
    assert len(failed) == 1 and plan[-1].label() in failed[0].message


# ── 런타임 캐시: 호출 1회 단위 ─────────────────────────────────────────
def test_a_second_run_is_served_entirely_from_the_cache(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20, 15])
    outline = outline_payload(doc, blocks)
    first = make(tmp_path, masters_dir, FakeProvider(doc, outline)).extract_payload(doc, msc)
    assert first.cached is False

    boom = BoomProvider()
    second = make(tmp_path, masters_dir, boom).extract_payload(doc, msc)
    assert boom.calls == 0 and second.cached is True
    assert second.payload == first.payload


def test_only_the_changed_chunk_is_called_again(tmp_path, masters_dir, msc):
    """캐시 키는 그 호출에 **실제로 보낸 텍스트**다 — 문서 끝의 한 줄이 바뀌면 마지막 청크만 다시 부른다."""
    doc, blocks = make_doc([30])
    make(tmp_path, masters_dir, FakeProvider(doc, outline_payload(doc, blocks))) \
        .extract_payload(doc, msc)

    last = doc.pages[0].rsplit("\n", 2)
    edited_text = "\n".join([last[0], last[1].replace("| 40", "| 41"), last[2]])
    assert edited_text != doc.pages[0]
    edited = SourceDoc(filename=doc.filename, ext="htm", pages=[edited_text])
    fake = FakeProvider(edited, outline_payload(edited, blocks))
    make(tmp_path, masters_dir, fake).extract_payload(edited, msc)

    assert len(fake.of("outline_purchase_order")) == 1      # 전체 텍스트가 바뀌었으니 골격은 다시
    assert len(fake.of("extract_lines")) == 1               # 나머지 청크는 캐시에서
    assert fake.of("extract_lines")[0].end >= blocks[0][1] - 1


def test_the_cache_key_separates_pass_kinds_and_texts(masters_dir):
    from app.extraction.providers.base import DocumentInput

    def key(text, kind):
        return llm_cache.cache_key(document=DocumentInput(text=text), prompt_version="v3",
                                   customer="MSC", model="m", pass_kind=kind)

    assert key("t", "outline") != key("t", "lines")           # 같은 텍스트라도 패스가 다르면 다른 응답
    assert key("t1", "lines") != key("t2", "lines")
    assert key("t", "lines") == key("t", "lines")


def test_the_cache_key_does_not_include_hints(tmp_path, masters_dir, msc):
    """hints 를 한 글자 고칠 때마다 캐시가 전량 무효화되면 규칙 튜닝이 매번 유료가 된다."""
    doc, blocks = make_doc([8])
    make(tmp_path, masters_dir, FakeProvider(doc, outline_payload(doc, blocks))) \
        .extract_payload(doc, msc)
    import dataclasses
    tuned = dataclasses.replace(msc, extraction={**msc.extraction, "hints": "완전히 다른 힌트"})
    boom = BoomProvider()
    make(tmp_path, masters_dir, boom).extract_payload(doc, tuned)
    assert boom.calls == 0


# ── 실패의 범위 ────────────────────────────────────────────────────────
def test_an_outline_failure_fails_the_whole_file(tmp_path, masters_dir, msc):
    """경계를 모르면 나눌 수도 없다."""
    doc, blocks = make_doc([8])
    fake = FakeProvider(doc, outline_error=LLMError("골격 실패"))
    with pytest.raises(LLMError, match="골격 실패"):
        make(tmp_path, masters_dir, fake).extract_payload(doc, msc)
    assert fake.of("extract_lines") == []


def test_unusable_block_ranges_fail_the_file_with_a_clear_message(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([8, 8])
    outline = outline_payload(doc, blocks)
    outline["shipments"][1]["src"] = blocks[0][1]            # 앞 블록과 겹친다
    fake = FakeProvider(doc, outline)
    with pytest.raises(ValueError, match="겹칩니다"):
        make(tmp_path, masters_dir, fake).extract_payload(doc, msc)
    assert fake.of("extract_lines") == []                    # 경계를 못 믿으면 품목 호출도 하지 않는다


def test_one_failed_chunk_keeps_every_other_chunk_and_blocks_only_its_order(
        tmp_path, masters_dir, as_file):
    doc, blocks = make_doc([20, 15])
    as_file(doc)
    bad = blocks[1][0]                                       # 둘째 블록의 첫 청크

    def handler(start, end):
        if start == bad:
            raise LLMError("400 bad request")
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    result = make(tmp_path, masters_dir, fake).parse_file("x.htm", "MSC")

    assert len(result.raw.shipments[0].lines) == 20          # 첫 오더는 온전하다
    assert 0 < len(result.raw.shipments[1].lines) < 15       # 둘째 오더는 빠진 만큼 적다
    failed = [i for i in result.issues if i.code == "CHUNK_FAILED"]
    assert len(failed) == 1 and failed[0].level == "error"
    assert failed[0].field == "shipments[2].lines"
    assert f"L{bad:06d}~" in failed[0].message
    assert "400 bad request" in failed[0].message
    assert result.error_count >= 1                           # 전송이 막힌다 (합계 불일치도 함께)


def test_an_unexpected_worker_error_fails_only_its_chunk(tmp_path, masters_dir, msc):
    doc, blocks = make_doc([20, 15])
    bad = blocks[1][0]

    def handler(start, end):
        if start == bad:
            raise KeyError("버그")                           # 예상 밖의 예외
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = make(tmp_path, masters_dir, fake).extract_payload(doc, msc)
    failed = [i for i in ex.issues if i.code == "CHUNK_FAILED"]
    assert len(failed) == 1 and "KeyError" in failed[0].message
    assert len(ex.payload["shipments"][0]["lines"]) == 20


def test_a_line_read_from_outside_its_chunk_is_flagged(tmp_path, masters_dir, as_file):
    """구간 밖을 참조하지 말라는 지시를 어긴 값은 믿을 수 없다 — 🔴 (design §3.4-0)."""
    doc, blocks = make_doc([8, 8])
    as_file(doc)
    lo1, hi1 = blocks[0]
    lo2, hi2 = blocks[1]

    def handler(start, end):
        if start == lo1:                                      # 첫 블록의 호출이 둘째 블록 품목까지 읽어 온다
            return lines_payload(doc, lo1, hi2)
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    result = make(tmp_path, masters_dir, fake).parse_file("x.htm", "MSC")

    out_of_range = [i for i in result.issues
                    if i.code == "EVIDENCE_NOT_FOUND" and "구간" in i.message]
    assert out_of_range and all(i.level == "error" for i in out_of_range)
    assert all(i.field.startswith("shipments[1].lines[") for i in out_of_range)
    # 넘어 읽은 품목은 그 오더에 남아 🔴 를 달고 있다 — 사람이 보고 지운다 (조용히 버리지 않는다)
    assert len(result.raw.shipments[0].lines) > 8


def test_read_outline_calls_only_the_outline_and_returns_the_plan(tmp_path, masters_dir, msc):
    """`parse_one.py --outline-only` — 호출 1회, 품목은 읽지 않는다."""
    doc, blocks = make_doc([20, 15])
    fake = FakeProvider(doc, outline_payload(doc, blocks))
    outline, policy, chunks, cached = make(tmp_path, masters_dir, fake).read_outline(doc, msc)

    assert [c.kind for c in fake.calls] == ["outline_purchase_order"]
    assert cached is False and len(chunks) == 5              # 21줄→3 · 16줄→2
    assert policy["max_lines_per_chunk"] > 0
    assert outline.payload["shipments"][0]["src"] == blocks[0][0]


# ── 배치 서비스: 진행 콜백 통과 · 오더 단위 이슈 배분 ────────────────────
def batch_settings(tmp_path, masters_dir):
    return Settings(llm_provider="mock", masters_dir=masters_dir, storage_dir=tmp_path)


def new_batch(settings, name: str, data: bytes, customer="MSC") -> str:
    repo = BatchRepo(settings.storage_dir)
    batch = Batch(batch_id=repo.new_id(), customer=customer, status="PARSING",
                  created_at=repo.now(), files=[BatchFile(file_id="f1", name=name)])
    repo.save_upload(batch.batch_id, "f1", name, data)
    repo.save(batch)
    return batch.batch_id


def test_parse_batch_passes_the_progress_callback_through(
        tmp_path, masters_dir, fixtures_dir, monkeypatch):
    cfg = batch_settings(tmp_path, masters_dir)
    sample = fixtures_dir / "msc" / "PO-SAMPLE-0001.htm"
    batch_id = new_batch(cfg, sample.name, sample.read_bytes())
    seen: dict = {}

    class Recording:
        def __init__(self, settings):
            self._real = Extractor(settings)

        def parse_file(self, path, customer, *, display_name=None, on_progress=None):
            seen["callback"] = on_progress
            on_progress("골격 파악", 1, 2, display_name)
            return self._real.parse_file(path, customer, display_name=display_name)

    monkeypatch.setattr(batch_service, "Extractor", Recording)
    calls = []
    batch_service.parse_batch(batch_id, cfg, on_progress=lambda *a: calls.append(a))

    assert seen["callback"] is not None
    assert calls == [("골격 파악", 1, 2, "PO-SAMPLE-0001.htm")]
    batch = BatchRepo(cfg.storage_dir).load(batch_id)
    assert batch.files[0].status == "DONE" and batch.rows


def test_parse_batch_works_without_a_callback(tmp_path, masters_dir, fixtures_dir):
    cfg = batch_settings(tmp_path, masters_dir)
    sample = fixtures_dir / "msc" / "PO-SAMPLE-0001.htm"
    batch_id = new_batch(cfg, sample.name, sample.read_bytes())
    batch_service.parse_batch(batch_id, cfg)
    assert BatchRepo(cfg.storage_dir).load(batch_id).files[0].status == "DONE"


def test_start_batch_hands_the_callback_to_parse_batch(tmp_path, masters_dir, monkeypatch):
    pytest.importorskip("streamlit")
    from types import SimpleNamespace

    from ui import service

    cfg = batch_settings(tmp_path, masters_dir)
    monkeypatch.setattr(service, "settings", lambda: cfg)
    captured = {}

    def fake_parse(batch_id, settings, *, on_progress=None):
        captured["on_progress"] = on_progress
        repo = BatchRepo(settings.storage_dir)
        batch = repo.load(batch_id)
        batch.files[0].status = "DONE"
        batch.status = "READY"
        repo.save(batch)

    monkeypatch.setattr(service, "parse_batch", fake_parse)

    def cb(*_a):
        return None

    upload = SimpleNamespace(name="a.htm", getvalue=lambda: b"<html></html>")
    batch = service.start_batch("MSC", [upload], on_progress=cb)

    assert captured["on_progress"] is cb
    assert batch.status == "READY"
    # 생략해도 된다
    captured.clear()
    service.start_batch("MSC", [upload])
    assert captured["on_progress"] is None


def test_ui_tick_updates_one_bar_in_place():
    """`st.write` 로 줄을 쌓지 않는다 — 막대 하나만 갱신한다."""
    pytest.importorskip("streamlit")
    from ui.views import convert

    class Bar:
        def __init__(self):
            self.calls = []

        def progress(self, value, text=None):
            self.calls.append((value, text))

    bar = Bar()
    tick = convert._ticker(bar)
    tick("품목 읽기", 3, 6, "a.htm")
    tick("품목 읽기", 6, 6, "a.htm")
    tick("골격 파악", 0, 0, "a.htm")                  # total 0 이어도 나누기 오류가 없다
    assert bar.calls[0] == (0.5, "a.htm — 품목 읽기 3/6")
    assert bar.calls[1][0] == 1.0
    assert bar.calls[2][0] == 0.0


def raw_with_two_shipments(issue_shipment_rows: bool = True):
    def item(src):
        return {"src": src, "confidence": 0.99, "item_code": f"ITEM-{src:04d}", "quantity": "1"}

    payload = {"header": {}, "totals": {}, "shipments": [
        {"lines": [item(3), item(4)]},
        {"lines": [item(8)] if issue_shipment_rows else []},
    ]}
    return _to_raw_po(payload, customer_code="X", source_file="f.htm")


def issue(field: str, level="error", code="CHUNK_FAILED") -> GroundingIssue:
    return GroundingIssue(level=level, field=field, code=code, message="m")


def test_an_order_level_issue_reaches_every_row_of_that_order_only():
    by_row = batch_service._grounding_by_row([issue("shipments[1].lines")],
                                             raw_with_two_shipments())
    assert sorted(by_row) == [0, 1]                          # 첫 오더의 두 행. 둘째 오더(행 2)는 아님


def test_an_order_level_issue_with_no_rows_falls_back_to_every_row():
    """구간을 통째로 못 읽어 그 오더에 행이 없다 — 막아야 할 이슈가 사라지면 안 된다."""
    by_row = batch_service._grounding_by_row([issue("shipments[2].lines")],
                                             raw_with_two_shipments(issue_shipment_rows=False))
    assert sorted(by_row) == [0, 1]                          # 있는 행 전부에 붙는다


def test_a_line_level_issue_still_goes_to_its_own_row():
    by_row = batch_service._grounding_by_row(
        [issue("shipments[1].lines[2].quantity", code="EVIDENCE_NOT_FOUND")],
        raw_with_two_shipments())
    assert sorted(by_row) == [1] and by_row[1][0].field == "quantity"


def test_a_chunk_failure_blocks_the_rows_of_that_order_in_a_parsed_batch(
        tmp_path, masters_dir, monkeypatch):
    """파일 → 배치까지: 청크 실패가 그 오더의 행에 🔴 로 붙고 나머지 오더는 깨끗하다."""
    doc, blocks = make_doc([20, 15])
    bad = blocks[1][0]

    def handler(start, end):
        if start == bad:
            raise LLMError("읽기 실패")
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    cfg = settings(tmp_path, masters_dir)
    monkeypatch.setattr(extractor_mod, "load_document", lambda _p: doc)
    monkeypatch.setattr(batch_service, "Extractor",
                        lambda s: Extractor(s, provider=fake, sleep=lambda _x: None))

    batch_id = new_batch(cfg, doc.filename, b"<html></html>")
    batch_service.parse_batch(batch_id, cfg)
    batch = BatchRepo(cfg.storage_dir).load(batch_id)

    assert batch.files[0].status == "DONE"
    assert batch.status == "NEEDS_REVIEW"
    codes_by_row = [{i.code for i in r.issues} for r in batch.rows]
    assert len(batch.rows) > 20
    assert all("CHUNK_FAILED" not in c for c in codes_by_row[:20])            # 첫 오더
    assert all("CHUNK_FAILED" in c for c in codes_by_row[20:])                # 둘째 오더 전 행


def test_a_file_with_no_rows_reports_why(tmp_path, masters_dir, monkeypatch):
    """행이 없으면 이슈를 붙일 곳이 없다 — 이유가 사라지지 않게 파일의 실패 사유로 올린다."""
    doc, blocks = make_doc([8])

    def handler(start, end):
        raise LLMError("모든 청크 실패")

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    cfg = settings(tmp_path, masters_dir)
    monkeypatch.setattr(extractor_mod, "load_document", lambda _p: doc)
    monkeypatch.setattr(batch_service, "Extractor",
                        lambda s: Extractor(s, provider=fake, sleep=lambda _x: None))

    batch_id = new_batch(cfg, doc.filename, b"<html></html>")
    batch_service.parse_batch(batch_id, cfg)
    entry = BatchRepo(cfg.storage_dir).load(batch_id).files[0]

    assert entry.status == "FAILED" and entry.row_count == 0
    assert "읽지 못해" in entry.error and "모든 청크 실패" in entry.error


def test_revalidation_does_not_clear_an_unread_section(tmp_path, masters_dir, monkeypatch):
    """`검증` 버튼이 CHUNK_FAILED 를 지우면 빠진 품목을 안고 전송이 열린다.

    읽지 못한 구간은 값이 아니라 **행 자체가 없다**는 뜻이라 화면에서 고칠 수 없다 —
    다시 변환해야 풀린다. 그래서 값 검증(`validate_row`)이 다시 돌아도 서버가 들고 있다.
    """
    doc, blocks = make_doc([20, 15])
    bad = blocks[1][0]

    def handler(start, end):
        if start == bad:
            raise LLMError("읽기 실패")
        return lines_payload(doc, start, end)

    cfg = settings(tmp_path, masters_dir)
    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    monkeypatch.setattr(extractor_mod, "load_document", lambda _p: doc)
    monkeypatch.setattr(batch_service, "Extractor",
                        lambda s: Extractor(s, provider=fake, sleep=lambda _x: None))
    batch_id = new_batch(cfg, doc.filename, b"<html></html>")
    batch_service.parse_batch(batch_id, cfg)

    repo = BatchRepo(cfg.storage_dir)
    batch = repo.load(batch_id)
    second_order_rows = [r for r in batch.rows if any(i.code == "CHUNK_FAILED" for i in r.issues)]
    assert second_order_rows

    edits = [{"row_id": r.row_id, "fields": {}} for r in batch.rows]
    assert batch_service.merge_edits(batch, edits, cfg) == []

    after = {r.row_id: {i.code for i in r.issues} for r in batch.rows}
    assert all("CHUNK_FAILED" in after[r.row_id] for r in second_order_rows)     # 그대로 남았다
    assert all("CHUNK_FAILED" not in v for k, v in after.items()
               if k not in {r.row_id for r in second_order_rows})                # 다른 오더는 아니다
    assert batch.status == "NEEDS_REVIEW"                                        # 전송은 계속 막힌다
