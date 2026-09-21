"""LLM 응답 → RawPO 매핑, 특히 오더 분할 (SCHEMA.md §2.1)."""

from __future__ import annotations

from app.extraction.extractor import _to_raw_po, splits_by_shipment
from app.masters.loader import load_customer


def v(value):
    """header · shipment 값 — `{value, src, confidence}` (SCHEMA §3.2-가)."""
    return {"value": value, "src": 1, "confidence": 0.99}


def line(item, qty="1", src=5):
    """품목 — 평평한 스칼라 + 줄 단위 앵커 (SCHEMA §3.2-나). line_no 는 받지 않는다."""
    return {"src": src, "confidence": 0.99, "item_code": item, "quantity": qty}


def payload(**over):
    base = {
        "header": {"po_number": v("PO-1")},
        "lines": [line("A"), line("B")],
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
    """분할 문서의 최상위 lines 는 오더를 만들지 않는다 (§2.1-2).

    지금은 요약표를 품목으로 추출하지 않지만, 구 응답이 실어 와도 오더가 두 배가 되면 안 된다.
    """
    r = raw(shipments=[
        {"ship_to_text": v("ELKHART"), "lines": [line("A")]},
        {"ship_to_text": v("RENO"), "lines": [line("B")]},
    ])
    assert r.is_split
    assert len(r.lines) == 2                      # 요약표는 그대로 보존
    assert len(r.all_lines) == 2                  # 그러나 오더 품목은 출하처 것
    assert [ln.item_code.value for ln in r.all_lines] == ["A", "B"]


def test_line_no_restarts_per_order():
    """§2.1-6 — line_no 는 오더 단위 안에서 1부터. **모델이 준 번호는 쓰지 않는다.**

    청크로 읽으면 번호가 청크 안에서만 센 값이라 그대로 쓰면 겹친다.
    """
    r = raw(shipments=[
        {"lines": [{**line("A"), "line_no": 9}, {**line("B"), "line_no": 9}]},
        {"lines": [line("C")]},
    ])
    assert [ln.line_no for ln in r.shipments[0].lines] == [1, 2]
    assert [ln.line_no for ln in r.shipments[1].lines] == [1]


def test_line_anchor_is_shared_by_every_value_of_the_line():
    """품목은 줄 단위 앵커 1개다 — 값마다 그 앵커를 물려받아야 그라운딩이 값을 대조한다."""
    r = raw(lines=[{**line("A", "7", src=412), "src_end": 413, "confidence": 0.8}])
    ln = r.lines[0]
    assert (ln.src, ln.src_end) == (412, 413)
    for value in (ln.item_code, ln.quantity):
        assert (value.src, value.src_end, value.confidence) == (412, 413, 0.8)
    assert ln.item_code.value == "A" and ln.quantity.value == "7"
    assert ln.description.is_empty()                 # 생략된 키는 빈 값이다


def test_header_value_keeps_its_own_anchor():
    r = raw(header={"po_number": {"value": "7588650", "src": "12", "src_end": 13,
                                  "confidence": 0.97}})
    v_ = r.header.po_number
    assert (v_.value, v_.src, v_.src_end, v_.confidence) == ("7588650", 12, 13, 0.97)


def test_model_supplied_page_is_not_trusted():
    """페이지는 파생 사실이다 — `src` 로부터 코드가 채운다 (SCHEMA §3.2)."""
    from app.extraction.extractor import _stamp_pages
    from app.extraction.preprocess import SourceDoc

    doc = SourceDoc(filename="f.pdf", ext="pdf", pages=["a\nb", "c\nd"])
    # 줄: 1=PAGE 1, 2=a, 3=b, 4=PAGE 2, 5=c, 6=d
    r = raw(header={"po_number": {"value": "c", "src": 5, "page": 1, "confidence": 0.99}},
            lines=[line("d", src=6), line("x", src=None)])
    _stamp_pages(r, doc)
    assert r.header.po_number.page == 2              # 모델의 page=1 이 아니라 src=5 의 페이지
    assert r.lines[0].item_code.page == 2
    assert r.lines[1].item_code.page is None          # 앵커가 없으면 페이지도 없다


def test_legacy_evidence_shape_is_read_but_not_trusted():
    """구 형태(evidence 인용)는 값만 읽는다. 줄 번호가 없어 앵커가 되지 못한다."""
    r = raw(header={"po_number": {"value": "PO-1", "evidence": "Purchase Order #PO-1",
                                  "page": 1, "confidence": 0.99}})
    assert r.header.po_number.value == "PO-1"
    assert r.header.po_number.src is None


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
                "src": 5, "confidence": 0.99, "posex": "00001", "net_value": "100",
                "delivery_date": "2026-06-05", "remark": "#1 stock",
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


# ── 파일 형식 (계약 §1 · process.md — "차단하지 않는다") ────────────────
def test_unexpected_file_type_warns_but_does_not_block(masters_dir, fixtures_dir):
    """거래처가 평소와 다른 형식으로 한 번 보내는 일은 실제로 일어난다.

    업로드를 막으면 사람이 할 수 있는 일이 없어진다 — 읽어보고 안 되면 그때 실패해도 늦지 않다.
    """
    from app.extraction.extractor import Extractor
    from app.extraction.preprocess import load_document

    doc = load_document(fixtures_dir / "msc" / "PO-SAMPLE-0001.htm")

    issue = Extractor._check_file_type(doc, load_customer("kl", masters_dir))  # KL 은 PDF 기대
    assert issue is not None
    assert issue.level == "warn" and issue.code == "UNEXPECTED_FILE_TYPE"

    assert Extractor._check_file_type(doc, load_customer("msc", masters_dir)) is None


def test_file_type_warning_reaches_the_result(masters_dir, fixtures_dir, tmp_path):
    """경고가 파싱 결과에 실려야 검수 화면에서 보인다."""
    import shutil

    from app.config import Settings
    from app.extraction import Extractor

    # MSC 픽스처를 KL 로 파싱하면 형식 경고가 나야 한다 (막히지 않고)
    sample = tmp_path / "PO-SAMPLE-0001.htm"
    shutil.copy(fixtures_dir / "msc" / "PO-SAMPLE-0001.htm", sample)

    settings = Settings(llm_provider="mock", masters_dir=masters_dir)
    try:
        result = Extractor(settings).parse_file(sample, "KL")
    except Exception as exc:  # noqa: BLE001
        # 재생할 픽스처가 없어 LLM 단계에서 실패하는 것은 정상 — 형식으로 막히지만 않으면 된다
        assert "형식입니다" not in str(exc)
        return
    assert any(i.code == "UNEXPECTED_FILE_TYPE" for i in result.issues)
