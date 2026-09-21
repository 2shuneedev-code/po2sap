"""환각 차단 — 합계 교차검증 · 신뢰도 · 품목 누락.

앵커(`src`) 대조 자체는 `test_grounding_anchor.py`, 판정 사다리는 `test_anchor.py`.
"""

from __future__ import annotations

from app.domain.models import ExtractedValue, POLine, POShipment, POTotals, RawPO
from app.extraction import grounding
from app.extraction.preprocess import SourceDoc

# 줄 번호: 1=PAGE 1 머리글, 2=발주번호, 3=출하처, 4=품목1, 5=품목2
LINES = [
    "Purchase Order #PO-1",
    "SID TOOL - ELKHART WAREHOUSE",
    "10 | 09876543 | END MILL 6MM",
    "15 | 09876544 | DRILL 8MM",
]


def doc(lines: list[str] = LINES, has_text_layer: bool = True) -> SourceDoc:
    return SourceDoc(
        filename="f.htm", ext="htm", pages=["\n".join(lines)], has_text_layer=has_text_layer
    )


def ev(value, src, confidence=0.99):
    return ExtractedValue(value=value, src=src, page=1, confidence=confidence)


def line(no, item, qty, src):
    return POLine(line_no=no, src=src, item_code=ev(item, src), quantity=ev(qty, src))


def codes(issues, level=None):
    return [i.code for i in issues if level is None or i.level == level]


def test_anchored_values_are_clean():
    raw = RawPO(customer_code="X", source_file="f.htm", lines=[line(1, "09876543", "10", 4)])
    assert grounding.verify(raw, doc()) == []


def test_value_not_on_the_anchored_line_is_an_error():
    """값이 다른 줄에 있으면 — 모델이 엉뚱한 줄을 가리켰거나 값을 지어냈다."""
    raw = RawPO(customer_code="X", source_file="f.htm", lines=[line(1, "09876543", "10", 5)])
    assert "EVIDENCE_NOT_FOUND" in codes(grounding.verify(raw, doc()), "error")


def test_scanned_document_skips_anchor_check():
    """텍스트 레이어가 없으면 대조할 원문이 없다 — 앵커 검사를 건너뛴다."""
    raw = RawPO(customer_code="X", source_file="f.pdf", lines=[line(1, "09876543", "10", 999)])
    found = grounding.verify(raw, doc(has_text_layer=False))
    assert "EVIDENCE_NOT_FOUND" not in codes(found)
    assert "EVIDENCE_WEAK" not in codes(found)


def test_low_confidence():
    raw = RawPO(
        customer_code="X", source_file="f.htm",
        lines=[POLine(
            line_no=1, src=4,
            item_code=ExtractedValue(value="09876543", src=4, page=1, confidence=0.5),
            quantity=ev("10", 4),
        )],
    )
    # 필수 필드(item_code)가 0.7 미만이면 오류
    assert "LOW_CONFIDENCE" in codes(grounding.verify(raw, doc()), "error")


def test_no_lines_is_an_error():
    raw = RawPO(customer_code="X", source_file="f.htm")
    assert "NO_LINES" in codes(grounding.verify(raw, doc()), "error")


def test_totals_compare_against_order_lines_not_summary():
    """분할 문서에서 합계는 요약표가 아니라 실제 오더 품목과 대조한다 (§2.1-2)."""
    raw = RawPO(
        customer_code="X", source_file="f.htm",
        shipments=[
            POShipment(lines=[line(1, "09876543", "10", 4)]),
            POShipment(lines=[line(1, "09876544", "15", 5)]),
        ],
        totals=POTotals(line_count=2, total_qty="25"),
    )
    assert "TOTAL_MISMATCH" not in codes(grounding.verify(raw, doc()))


def test_totals_mismatch_detected():
    raw = RawPO(
        customer_code="X", source_file="f.htm",
        lines=[line(1, "09876543", "10", 4)],
        totals=POTotals(line_count=2, total_qty="25"),
    )
    assert codes(grounding.verify(raw, doc()), "error").count("TOTAL_MISMATCH") == 2


def test_empty_shipment_block_detected():
    """출하처 블록을 찾았는데 그 블록의 품목표를 못 읽으면 오더가 통째로 빈다 (§2.1-3)."""
    raw = RawPO(
        customer_code="X", source_file="f.htm",
        shipments=[
            POShipment(lines=[line(1, "09876543", "10", 4)]),
            POShipment(ship_to_text=ev("ELKHART", 3), lines=[]),
        ],
    )
    issues = grounding.verify(raw, doc())
    assert any(i.field == "shipments[2].lines" and i.code == "NO_LINES" for i in issues)


def test_shipment_values_are_grounded():
    raw = RawPO(
        customer_code="X", source_file="f.htm",
        shipments=[POShipment(
            ship_to_text=ev("어딘가", 3),
            lines=[line(1, "09876543", "10", 4)],
        )],
    )
    issues = grounding.verify(raw, doc())
    assert any(i.field == "shipments[1].ship_to_text" and i.code == "EVIDENCE_NOT_FOUND"
               for i in issues)
