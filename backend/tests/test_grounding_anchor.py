"""앵커(`src`) 그라운딩 — design.md §3.4 의 ① 앵커 존재 ② 청크 구간 ③ 줄 대조 ④ 품번 백스톱.

판정 사다리 자체(exact/numeric/date/fuzzy)는 `test_anchor.py`. 여기서는 그 결과가
어떤 이슈로 올라가는지, 그리고 스캔본이 건너뛰어지는지를 본다.
"""

from __future__ import annotations

from app.domain.models import ExtractedValue, POHeader, POLine, RawPO
from app.extraction import grounding
from app.extraction.preprocess import SourceDoc

# 문서 줄 번호: 1=PAGE 1
LINES = [
    "Purchase Order #PO-1",                                # 2
    "Date of Order | 2/17/26",                             # 3
    "Ship on Or Before | 3/10/26",                         # 4
    "SID TOOL - ELKHART WAREHOUSE",                        # 5
    "1000 INDUSTRIAL PKWY, ELKHART, IN 46514",             # 6
    "10 | 09876543 | YG-EM0600 | END MILL 6MM 4FL",        # 7
    "1,250 | 09876544 | YG-DR0800 | DRILL 8MM HSS",        # 8
]
PO, DATE, SHIP_BY, SHIP1, SHIP2, ITEM1, ITEM2 = 2, 3, 4, 5, 6, 7, 8
LINE_COUNT = 1 + len(LINES)                                # 8


def doc(has_text_layer: bool = True) -> SourceDoc:
    return SourceDoc(
        filename="f.htm", ext="htm", pages=["\n".join(LINES)], has_text_layer=has_text_layer
    )


def val(value, src, *, src_end=None, confidence=0.99):
    return ExtractedValue(value=value, src=src, src_end=src_end, confidence=confidence)


def header_raw(**fields) -> RawPO:
    """헤더 값 하나로 검증한다 — 품목 누락(NO_LINES)은 이 테스트의 관심사가 아니다."""
    return RawPO(customer_code="X", source_file="f.htm", header=POHeader(**fields))


def item_raw(**fields) -> RawPO:
    return RawPO(customer_code="X", source_file="f.htm", lines=[POLine(line_no=1, **fields)])


def found(raw, **kw):
    return [(i.field, i.level, i.code) for i in grounding.verify(raw, doc(), **kw)
            if i.code != "NO_LINES"]


# ── ① 앵커 존재 ────────────────────────────────────────────────────────
def test_missing_src_is_an_error():
    raw = header_raw(po_number=val("PO-1", None))
    assert found(raw) == [("header.po_number", "error", "EVIDENCE_NOT_FOUND")]


def test_src_zero_is_an_error():
    assert found(header_raw(po_number=val("PO-1", 0))) == [
        ("header.po_number", "error", "EVIDENCE_NOT_FOUND")]


def test_src_beyond_the_document_is_an_error():
    assert found(header_raw(po_number=val("PO-1", LINE_COUNT + 1))) == [
        ("header.po_number", "error", "EVIDENCE_NOT_FOUND")]


def test_src_end_before_src_or_beyond_the_document_is_an_error():
    assert found(header_raw(ship_to_text=val("x", SHIP2, src_end=SHIP1)))[0][1] == "error"
    assert found(header_raw(ship_to_text=val("x", SHIP1, src_end=LINE_COUNT + 5)))[0][1] == "error"


def test_the_last_line_of_the_document_is_a_valid_anchor():
    raw = item_raw(src=ITEM2, item_code=val("YG-DR0800", ITEM2))
    assert found(raw) == []


def test_empty_values_are_not_checked():
    """읽지 못한(생략된) 필드에 앵커를 요구하지 않는다."""
    assert found(header_raw(po_number=ExtractedValue())) == []


# ── ② 청크 구간 ────────────────────────────────────────────────────────
def test_src_outside_the_chunk_range_is_an_error():
    raw = item_raw(src=ITEM1, item_code=val("YG-EM0600", ITEM1))
    assert found(raw, allowed_range=(ITEM1, ITEM2)) == []                # 구간 안
    assert found(raw, allowed_range=(ITEM2, ITEM2)) == [
        ("lines[1].item_code", "error", "EVIDENCE_NOT_FOUND")]           # 구간 밖


def test_a_multiline_anchor_must_fit_inside_the_chunk_range():
    raw = header_raw(ship_to_text=val("SID TOOL - ELKHART WAREHOUSE", SHIP1, src_end=SHIP2))
    assert found(raw, allowed_range=(SHIP1, SHIP2)) == []
    assert found(raw, allowed_range=(SHIP1, SHIP1))[0][1] == "error"      # 끝줄이 벗어남


def test_no_chunk_range_means_no_range_check():
    assert found(item_raw(src=ITEM1, item_code=val("YG-EM0600", ITEM1))) == []


# ── ③ 줄 대조 ──────────────────────────────────────────────────────────
def test_exact_value_passes():
    assert found(header_raw(po_number=val("PO-1", PO))) == []


def test_numeric_value_passes_after_normalisation():
    """원문 `1,250` → 값 `1250`."""
    raw = item_raw(src=ITEM2, quantity=val("1250", ITEM2), item_code=val("YG-DR0800", ITEM2))
    assert found(raw) == []


def test_date_value_passes_after_normalisation():
    """원문 `2/17/26` → 값 `2026-02-17`."""
    raw = header_raw(po_date=val("2026-02-17", DATE), requested_date=val("2026-03-10", SHIP_BY))
    assert found(raw) == []


def test_date_that_cannot_be_mapped_back_is_a_warning_not_an_error():
    raw = header_raw(po_date=val("2026-02-18", DATE))       # 그 줄은 2/17/26 이다
    assert found(raw) == [("header.po_date", "warn", "EVIDENCE_WEAK")]


def test_value_missing_from_the_anchored_line_is_an_error():
    raw = header_raw(po_number=val("PO-1", DATE))            # 3번 줄에는 PO-1 이 없다
    assert found(raw) == [("header.po_number", "error", "EVIDENCE_NOT_FOUND")]


def test_partial_match_is_a_weak_warning():
    raw = item_raw(src=ITEM1, description=val("END MILL 6MM 4FL LONG", ITEM1))
    assert found(raw) == [("lines[1].description", "warn", "EVIDENCE_WEAK")]


def test_a_value_only_on_a_neighbouring_line_is_not_found():
    """앵커는 줄 단위다. 이웃 줄에 있는 값은 그 줄을 가리켜야 통과한다."""
    raw = header_raw(ship_to_text=val("1000 INDUSTRIAL PKWY, ELKHART, IN 46514", SHIP1))
    assert found(raw)[0][2] == "EVIDENCE_NOT_FOUND"
    ok = header_raw(ship_to_text=val("1000 INDUSTRIAL PKWY, ELKHART, IN 46514", SHIP2))
    assert found(ok) == []


def test_multiline_value_with_src_end_passes():
    raw = header_raw(ship_to_text=val(
        "SID TOOL - ELKHART WAREHOUSE 1000 INDUSTRIAL PKWY, ELKHART, IN 46514",
        SHIP1, src_end=SHIP2))
    assert found(raw) == []


# ── ④ 품번 백스톱 ──────────────────────────────────────────────────────
def test_invented_part_number_is_an_error():
    raw = item_raw(src=ITEM1, item_code=val("YG-XX9999", ITEM1))
    assert ("lines[1].item_code", "error", "EVIDENCE_NOT_FOUND") in found(raw)


def test_a_part_number_from_another_line_is_caught_by_the_anchor():
    """다른 줄의 품번을 가리키면 앵커 대조가 먼저 잡는다 — 백스톱까지 갈 일이 없다."""
    raw = item_raw(src=ITEM1, item_code=val("YG-DR0800", ITEM1))
    assert found(raw) == [("lines[1].item_code", "error", "EVIDENCE_NOT_FOUND")]


def test_backstop_upgrades_a_weak_anchor_to_an_error_when_the_code_is_nowhere():
    """앵커에서 '비슷함'(🟡)으로 통과해도 문서 전체에 없는 품번이면 🔴 하나만 남는다."""
    doc_ = SourceDoc(filename="f.htm", ext="htm",
                     pages=["Item YG-EM0600 END MILL\nSecond line"], has_text_layer=True)
    raw = item_raw(src=2, our_item=val("YG-EM0600 END MILL 7", 2))
    result = [(i.level, i.code) for i in grounding.verify(raw, doc_) if i.code != "NO_LINES"]
    assert result == [("error", "EVIDENCE_NOT_FOUND")]


def test_backstop_is_stricter_than_numeric_matching_for_part_numbers():
    """수치로는 같아도(`1250` = `1,250`) 품번은 문자열이다 — 문서에 그대로 있어야 한다."""
    raw = item_raw(src=ITEM2, our_item=val("1250", ITEM2))       # 8번 줄은 "1,250 | …"
    assert found(raw) == [("lines[1].our_item", "error", "EVIDENCE_NOT_FOUND")]


def test_backstop_ignores_codes_shorter_than_four_alphanumerics():
    """3자 이하는 우연히 겹치므로 백스톱 대상이 아니다."""
    doc_ = SourceDoc(filename="f.htm", ext="htm", pages=["Qty 1,25"], has_text_layer=True)
    raw = item_raw(src=2, our_item=val("125", 2))                # 수치로만 같다 → 앵커는 통과
    assert [i for i in grounding.verify(raw, doc_) if i.code != "NO_LINES"] == []


def test_backstop_applies_to_the_two_item_columns_only():
    """description 같은 다른 필드는 백스톱을 타지 않는다."""
    raw = item_raw(src=ITEM2, description=val("1250", ITEM2))    # 수치 통과, 백스톱 없음
    assert found(raw) == []


# ── 스캔본 ─────────────────────────────────────────────────────────────
def test_scanned_document_skips_every_anchor_check():
    raw = item_raw(item_code=val("YG-XX9999", None), quantity=val("5", 9999))
    result = grounding.verify(raw, doc(has_text_layer=False))
    assert [i for i in result if i.code in ("EVIDENCE_NOT_FOUND", "EVIDENCE_WEAK")] == []


def test_scanned_document_still_applies_the_confidence_threshold():
    raw = item_raw(item_code=val("YG-EM0600", None, confidence=0.5))
    result = grounding.verify(raw, doc(has_text_layer=False))
    assert ("lines[1].item_code", "error", "LOW_CONFIDENCE") in [
        (i.field, i.level, i.code) for i in result]


# ── 경로 표기 (batch_service 가 정규식으로 읽는다) ─────────────────────
def test_issue_paths_keep_the_format_batch_service_parses():
    from app.domain.models import POShipment

    raw = RawPO(
        customer_code="X", source_file="f.htm",
        header=POHeader(po_number=val("PO-1", None)),
        shipments=[POShipment(
            ship_to_text=val("zz", None),
            lines=[POLine(line_no=1, src=None, quantity=val("5", None))],
        )],
    )
    fields = {i.field for i in grounding.verify(raw, doc())}
    assert {"header.po_number", "shipments[1].ship_to_text",
            "shipments[1].lines[1].quantity"} <= fields
