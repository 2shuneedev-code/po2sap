"""LLM 응답 → RawPO 매핑, 특히 오더 분할 (SCHEMA.md §2.1)."""

from __future__ import annotations

from app.extraction.extractor import _to_raw_po, splits_by_shipment
from app.masters.loader import load_customer


def v(value):
    return {"value": value, "evidence": value, "page": 1, "confidence": 0.99}


def line(no, item):
    return {"line_no": no, "item_code": v(item), "quantity": v("1")}


def payload(**over):
    base = {
        "header": {"po_number": v("PO-1")},
        "lines": [line(1, "A"), line(2, "B")],
        "totals": {"line_count": 2, "total_qty": "2", "total_amount": None},
        "notes": [],
    }
    base.update(over)
    return base


def raw(**over):
    return _to_raw_po(payload(**over), customer_code="X", source_file="f.htm")


def test_split_flag_comes_from_yaml_not_customer_name(masters_dir):
    """P2 — 거래처 이름으로 분기하지 않는다. split.by 가 정한다."""
    assert splits_by_shipment(load_customer("msc", masters_dir)) is True
    assert splits_by_shipment(load_customer("kl", masters_dir)) is False
    assert splits_by_shipment(load_customer("ygjp", masters_dir)) is False


def test_no_split_uses_top_level_lines():
    r = raw()
    assert not r.is_split
    assert len(r.all_lines) == 2


def test_split_ignores_summary_table():
    """분할 문서의 최상위 lines 는 요약표다 — 오더를 만들지 않는다 (§2.1-2)."""
    r = raw(shipments=[
        {"ship_to_text": v("ELKHART"), "lines": [line(1, "A")]},
        {"ship_to_text": v("RENO"), "lines": [line(1, "B")]},
    ])
    assert r.is_split
    assert len(r.lines) == 2                      # 요약표는 그대로 보존
    assert len(r.all_lines) == 2                  # 그러나 오더 품목은 출하처 것
    assert [ln.item_code.value for ln in r.all_lines] == ["A", "B"]


def test_line_no_restarts_per_order():
    """§2.1-6 — line_no 는 오더 단위 안에서 1부터."""
    r = raw(shipments=[
        {"lines": [line(9, "A"), line(9, "B")]},   # 모델이 엉뚱한 번호를 줘도
        {"lines": [{"item_code": v("C")}]},        # 아예 빠져도
    ])
    assert [ln.line_no for ln in r.shipments[0].lines] == [9, 9]   # 준 값은 존중
    assert [ln.line_no for ln in r.shipments[1].lines] == [1]      # 없으면 순번


def test_posex_not_invented():
    """§3.1 — 인쇄된 품목번호가 없으면 비운다. 생성은 ⑥ FIELDS 의 몫."""
    r = raw()
    assert all(ln.posex.is_empty() for ln in r.all_lines)


def test_standard_keys_are_mapped():
    r = _to_raw_po(
        {
            "header": {
                "po_number": v("PO-1"), "currency_text": v("USD"),
                "incoterms_text": v("FCA"), "payment_terms_text": v("NET 30"),
                "packing_spec": v("S-Y,B-Y"), "remark_default": v("공통비고"),
            },
            "lines": [{
                "line_no": 1, "posex": v("00001"), "net_value": v("100"),
                "delivery_date": v("2026-06-05"), "remark": v("#1 stock"),
            }],
            "totals": {}, "notes": [],
        },
        customer_code="X", source_file="f.pdf",
    )
    h, ln = r.header, r.lines[0]
    assert (h.currency_text.value, h.incoterms_text.value) == ("USD", "FCA")
    assert (h.packing_spec.value, h.remark_default.value) == ("S-Y,B-Y", "공통비고")
    assert (ln.posex.value, ln.net_value.value) == ("00001", "100")
    assert (ln.delivery_date.value, ln.remark.value) == ("2026-06-05", "#1 stock")


def test_malformed_response_is_absorbed():
    """모델이 스키마를 벗어나도 죽지 않는다 — 검증이 뒤에서 잡는다."""
    r = _to_raw_po(
        {"header": {"po_number": "그냥문자열"}, "lines": [None], "shipments": [None]},
        customer_code="X", source_file="f.htm",
    )
    assert r.header.po_number.value == "그냥문자열"
    assert len(r.lines) == 1 and len(r.shipments) == 1
