"""스캔본(텍스트 레이어 없음) — design.md §3.3.6 · D13. **LLM 호출 없이** 본다.

줄 번호가 없는 문서는 나눌 수 없다. 그래서 단일 호출로 읽고, 한도를 넘으면 **조용히 잘린 결과를
내보내지 않고 명시적으로 거부한다.** 청크 분할·병합·앵커 대조는 이 경로를 타지 않는다.
"""

from __future__ import annotations

import dataclasses

import pytest
from app.config import Settings
from app.extraction import Extractor
from app.extraction import extractor as extractor_mod
from app.extraction.extractor import SCAN_REFUSED, ScanNotSupportedError
from app.extraction.preprocess import SourceDoc
from app.extraction.providers.base import LLMTruncatedError, ToolCallResult
from app.masters.loader import load_customer
from llm_fakes import BoomProvider, FakeProvider

PDF = b"%PDF-1.4 fake"


def scan_doc(pages: int = 2) -> SourceDoc:
    return SourceDoc(filename="scan.pdf", ext="pdf", pages=[""] * pages,
                     has_text_layer=False, raw_bytes=PDF)


def scan_payload() -> dict:
    """줄 번호(src) 없이 페이지(page)만 준 응답 — 스캔용 툴 스키마가 요구하는 모양이다."""
    return {
        "header": {"po_number": {"value": "PO-777", "page": 1, "confidence": 0.95}},
        "lines": [
            {"page": 1, "confidence": 0.95, "item_code": "ZZ-NOT-IN-ANY-TEXT", "quantity": "5"},
            {"page": 2, "confidence": 0.95, "item_code": "ZZ-SECOND", "quantity": "7"},
        ],
        "totals": {},
        "notes": [],
    }


def master_with(masters_dir, code="kl", **extraction):
    master = load_customer(code, masters_dir)
    return dataclasses.replace(master, extraction={**master.extraction, **extraction})


def extractor(tmp_path, masters_dir, provider, **over) -> Extractor:
    settings = Settings(llm_provider="mock", masters_dir=masters_dir, storage_dir=tmp_path, **over)
    return Extractor(settings, provider=provider, sleep=lambda _s: None)


# ── input: text 인데 텍스트가 없다 — 예전에는 빈 결과였다 ────────────────
def test_text_mode_without_a_text_layer_fails_loudly_and_calls_nothing(tmp_path, masters_dir):
    """거의 빈 텍스트를 보내고 빈 결과를 받던 함정 — 명시적 오류로 바뀌었다."""
    boom = BoomProvider()
    master = load_customer("kl", masters_dir)
    assert master.extraction["input"] == "text"

    with pytest.raises(ScanNotSupportedError, match="텍스트 PDF|원본\\(텍스트\\)"):
        extractor(tmp_path, masters_dir, boom).extract_payload(scan_doc(), master)
    assert boom.calls == 0


def test_the_refusal_is_a_value_error_so_the_batch_marks_only_that_file(tmp_path, masters_dir):
    """`batch_service` 는 (LLMError, MasterError, ValueError, FileNotFoundError) 를 잡는다."""
    assert issubclass(ScanNotSupportedError, ValueError)


# ── 스캔 경로: 단일 호출 ────────────────────────────────────────────────
def test_a_scan_is_read_in_one_call_with_the_scan_tool(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(), single=scan_payload())
    master = master_with(masters_dir, input="auto")

    ex = extractor(tmp_path, masters_dir, fake).extract_payload(scan_doc(), master)

    assert [c.kind for c in fake.calls] == ["extract_purchase_order"]      # OUTLINE/LINES 를 안 쓴다
    assert ex.anchored is False and ex.stamp_pages is False

    schema = fake.tools[0]["input_schema"]
    item = schema["properties"]["lines"]["items"]
    assert "src" not in item["properties"] and "src" not in item["required"]
    assert "page" in item["required"]                                       # 대신 page 를 요구한다


def test_the_scan_call_sends_the_pdf_not_text(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(), single=scan_payload())
    seen = []
    original = fake.extract

    def spy(**kw):
        seen.append(kw["document"])
        return original(**kw)

    fake.extract = spy                                        # type: ignore[method-assign]
    extractor(tmp_path, masters_dir, fake).extract_payload(
        scan_doc(), master_with(masters_dir, input="auto"))
    assert seen[0].pdf_bytes == PDF and seen[0].text is None


def test_chunking_and_merging_are_never_reached_by_a_scan(tmp_path, masters_dir, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("스캔 경로가 청크 로직을 탔다")

    monkeypatch.setattr(extractor_mod.chunking, "plan", forbidden)
    monkeypatch.setattr(extractor_mod.merge_mod, "merge", forbidden)
    fake = FakeProvider(scan_doc(), single=scan_payload())
    extractor(tmp_path, masters_dir, fake).extract_payload(
        scan_doc(), master_with(masters_dir, input="auto"))


def test_scan_of_a_split_customer_keeps_lines_inside_each_shipment_block(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(), single={"header": {}, "shipments": [], "totals": {}})
    extractor(tmp_path, masters_dir, fake).extract_payload(
        scan_doc(), master_with(masters_dir, code="msc", input="image"))
    block = fake.tools[0]["input_schema"]["properties"]["shipments"]["items"]
    assert "lines" in block["properties"]
    assert "src" not in block["properties"] and "src_end" not in block["properties"]


# ── 근거 검증: 앵커는 건너뛴다 ──────────────────────────────────────────
@pytest.fixture
def parse_scan(tmp_path, masters_dir, monkeypatch):
    """`parse_file` 을 끝까지 — 파일 대신 스캔 문서를 돌려주는 것만 갈아끼운다."""
    def run(doc: SourceDoc, provider, **extraction):
        master = master_with(masters_dir, **{"input": "auto", **extraction})
        monkeypatch.setattr(extractor_mod, "load_document", lambda _p: doc)
        monkeypatch.setattr(extractor_mod, "load_customer", lambda *_a, **_k: master)
        return extractor(tmp_path, masters_dir, provider).parse_file("ignored.pdf", "KL")

    return run


def test_anchor_checks_do_not_run_on_a_scan(parse_scan):
    """대조할 원문이 없다 — 품번이 어느 텍스트에도 없어도, src 가 없어도 🔴 로 막지 않는다."""
    result = parse_scan(scan_doc(), FakeProvider(scan_doc(), single=scan_payload()))

    assert [i for i in result.issues
            if i.code in ("EVIDENCE_NOT_FOUND", "EVIDENCE_WEAK")] == []
    lines = result.raw.all_lines
    assert [ln.item_code.value for ln in lines] == ["ZZ-NOT-IN-ANY-TEXT", "ZZ-SECOND"]


def test_the_page_comes_from_the_model_on_a_scan_and_is_not_overwritten(parse_scan):
    """텍스트 경로는 `src` 로 페이지를 계산하지만 스캔은 줄이 없어 모델이 준 값이 유일한 위치다."""
    result = parse_scan(scan_doc(), FakeProvider(scan_doc(), single=scan_payload()))
    assert result.raw.header.po_number.page == 1
    first, second = result.raw.all_lines
    assert first.quantity.page == 1 and second.quantity.page == 2


def test_confidence_and_totals_still_apply_on_a_scan(parse_scan):
    payload = scan_payload()
    payload["lines"][0]["confidence"] = 0.3
    payload["totals"] = {"total_qty": "100"}
    result = parse_scan(scan_doc(), FakeProvider(scan_doc(), single=payload))
    codes = {(i.level, i.code) for i in result.issues}
    assert ("error", "LOW_CONFIDENCE") in codes and ("error", "TOTAL_MISMATCH") in codes


def test_image_mode_skips_the_anchor_check_even_when_the_pdf_has_a_text_layer(parse_scan):
    """`input: image` 는 텍스트가 있어도 이미지로 읽힌다 — src 를 요구하지 않았으니 대조도 없다."""
    doc = SourceDoc(filename="t.pdf", ext="pdf", pages=["real text " * 30],
                    has_text_layer=True, raw_bytes=PDF)
    result = parse_scan(doc, FakeProvider(doc, single=scan_payload()), input="image")
    assert [i for i in result.issues if i.code == "EVIDENCE_NOT_FOUND"] == []
    assert result.raw.header.po_number.page == 1            # 모델이 준 페이지가 살아 있다


# ── 한도: 재귀 없이 즉시 실패 ───────────────────────────────────────────
def test_truncated_scan_fails_immediately_without_splitting(tmp_path, masters_dir):
    """쪼갤 수단이 없다 — 재귀도 재시도도 없이 한 번 부르고 끝낸다."""
    fake = FakeProvider(scan_doc(), single=scan_payload())

    def truncated(**_kw):
        fake.calls.append(None)                                # type: ignore[arg-type]
        raise LLMTruncatedError("잘림")

    fake.extract = truncated                                   # type: ignore[method-assign]
    with pytest.raises(ScanNotSupportedError, match="스캔 발주서는 처리할 수 없습니다"):
        extractor(tmp_path, masters_dir, fake, llm_chunk_split_depth=5, llm_chunk_retries=5) \
            .extract_payload(scan_doc(), master_with(masters_dir, input="auto"))
    assert len(fake.calls) == 1


def test_scan_result_reporting_max_tokens_is_refused_too(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(), single=scan_payload(), stop_reason="max_tokens")
    with pytest.raises(ScanNotSupportedError) as info:
        extractor(tmp_path, masters_dir, fake).extract_payload(
            scan_doc(), master_with(masters_dir, input="auto"))
    assert str(info.value) == SCAN_REFUSED
    assert len(fake.calls) == 1


def test_a_refused_scan_is_never_cached(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(), single=scan_payload(), stop_reason="max_tokens")
    with pytest.raises(ScanNotSupportedError):
        extractor(tmp_path, masters_dir, fake).extract_payload(
            scan_doc(), master_with(masters_dir, input="auto"))
    assert not list((tmp_path / "llm_cache").glob("*.json"))


def test_page_limit_is_checked_before_any_call(tmp_path, masters_dir):
    boom = BoomProvider()
    with pytest.raises(ScanNotSupportedError, match="스캔 발주서는 처리할 수 없습니다") as info:
        extractor(tmp_path, masters_dir, boom).extract_payload(
            scan_doc(pages=5), master_with(masters_dir, input="auto", page_limit=3))
    assert "5쪽" in str(info.value) and "3쪽" in str(info.value)
    assert boom.calls == 0


def test_within_the_page_limit_is_read(tmp_path, masters_dir):
    fake = FakeProvider(scan_doc(3), single=scan_payload())
    ex = extractor(tmp_path, masters_dir, fake).extract_payload(
        scan_doc(pages=3), master_with(masters_dir, input="auto", page_limit=3))
    assert ex.payload["lines"]


def test_a_scan_response_is_cached_and_replayed(tmp_path, masters_dir):
    master = master_with(masters_dir, input="auto")
    first = FakeProvider(scan_doc(), single=scan_payload())
    extractor(tmp_path, masters_dir, first).extract_payload(scan_doc(), master)

    boom = BoomProvider()
    ex = extractor(tmp_path, masters_dir, boom).extract_payload(scan_doc(), master)
    assert boom.calls == 0 and ex.cached is True


def test_a_non_pdf_without_text_is_not_sent_as_a_pdf(tmp_path, masters_dir):
    empty_htm = SourceDoc(filename="e.htm", ext="htm", pages=[""], has_text_layer=False,
                          raw_bytes=b"<html></html>")
    with pytest.raises(ValueError, match="문자 정보가 없는"):
        extractor(tmp_path, masters_dir, BoomProvider()).extract_payload(
            empty_htm, master_with(masters_dir, input="auto"))


def test_tool_call_result_is_still_constructible_without_a_stop_reason():
    """기존 프로바이더·픽스처 코드가 stop_reason 없이 만들어도 깨지지 않는다."""
    assert ToolCallResult(payload={}).stop_reason == ""
