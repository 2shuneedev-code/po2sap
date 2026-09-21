"""규칙엔진 ②~⑦ — masters/SCHEMA.md §2.

엔진은 마스터가 시킨 것만 한다. 거래처 이름으로 분기하지 않으므로(원칙 P2)
테스트도 거래처를 **설정으로** 밀어 넣어 확인한다.
"""

from __future__ import annotations

import json

import pytest
from app.config import Settings
from app.domain.models import ExtractedValue as EV
from app.domain.models import POHeader, POLine, POShipment, POTotals, RawPO
from app.extraction import Extractor
from app.masters.loader import load_customer
from app.rules.engine import build

SAMPLE = "PO-SAMPLE-0001.htm"


@pytest.fixture(scope="module")
def msc_result(fixtures_dir, masters_dir):
    settings = Settings(llm_provider="mock")
    parsed = Extractor(settings).parse_file(fixtures_dir / "msc" / SAMPLE, "MSC")
    return build(parsed.raw, load_customer("msc", masters_dir), masters_dir, file_name=SAMPLE)


# ── 관통 ───────────────────────────────────────────────────────────────
def test_one_row_per_item_per_order_unit(msc_result):
    assert len(msc_result.rows) == 2
    assert msc_result.error_count == 0 and msc_result.warn_count == 0


def test_every_send_field_is_present(msc_result, masters_dir):
    """계약 §4·5 — columns 의 전 필드가 키로 존재한다. 값이 없어도 ""."""
    import yaml

    base = yaml.safe_load((masters_dir / "_base" / "sap_defaults.yaml").read_text("utf-8"))
    expected = list(base["field_specs"])
    assert msc_result.columns == expected
    for row in msc_result.rows:
        assert list(row.fields) == expected
        assert all(isinstance(v, str) for v in row.fields.values())


def test_split_produces_different_orders(msc_result):
    """D11 — 출하처마다 BSTKD·KUNNR2 가 달라진다. 나머지는 같다."""
    a, b = msc_result.rows
    assert a.fields["BSTKD"] != b.fields["BSTKD"]
    assert (a.fields["KUNNR2"], b.fields["KUNNR2"]) == ("100249", "319677")
    assert a.fields["KUNNR1"] == b.fields["KUNNR1"] == "100249"


def test_group_label_comes_from_a_derived_var(msc_result):
    """split.group_label 이 결정표의 파생변수를 가리킨다 (SCHEMA §4.3)."""
    assert [r.group for r in msc_result.rows] == ["ELKHART", "HARRISBURG"]


def test_summary_table_did_not_become_orders(msc_result):
    """§2.1-2 — 상단 요약표를 쓰면 수량이 두 배가 된다."""
    assert sorted(r.fields["KWMENG"] for r in msc_result.rows) == ["10", "15"]


def test_expr_and_table_and_rule_all_feed_fields(msc_result):
    row = msc_result.rows[0]
    assert row.fields["BSTKD"] == "PO-SAMPLE-0001(ELKHART)"   # expr + 파생변수
    assert row.fields["ZBRAND"] == "38"                        # csv_map 규칙
    assert row.fields["KUNNR2"] == "100249"                    # 결정표
    assert row.fields["ZPKRE2"].startswith("C")                # expr + lookup
    assert row.fields["AUART"] == "ZEXP"                       # _base 공통값
    assert row.fields["KUNNR3"] == "100249"                    # meta.customer_no


def test_matches_golden(msc_result, fixtures_dir):
    golden = json.loads(
        (fixtures_dir / "golden" / "msc__PO-SAMPLE-0001.rows.json").read_text("utf-8")
    )
    assert msc_result.model_dump() == golden


# ── 설정만 바꿔 확인하는 것들 ──────────────────────────────────────────
def ev(value):
    return EV(value=value, src=1, page=1, confidence=0.99)


def raw_po(*, lines, header=None, shipments=None, totals=None, customer="MSC"):
    return RawPO(
        customer_code=customer, source_file="f.htm",
        header=header or POHeader(), lines=lines,
        shipments=shipments or [], totals=totals or POTotals(),
    )


def test_no_split_customer_uses_top_level_lines(masters_dir):
    master = load_customer("ygjp", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("10972"), po_date=ev("2026-05-18"),
                        brand_text=ev("YG BRAND"), packing_spec=ev("S-Y,B-Y")),
        lines=[POLine(line_no=1, item_code=ev("E24201502SE"), quantity=ev("15"))],
    )
    result = build(raw, master, masters_dir)
    row = result.rows[0]
    assert row.group == ""                                     # 분할 없음
    assert row.fields["BSTKD"] == "01-20260518-10972"           # expr + date_yyyymmdd
    assert row.fields["ZBRAND"] == "1"                          # csv_map (YG BRAND)
    assert row.fields["ZSHCO"] == "L"                           # in() 판정 — 471/507 아님
    assert row.fields["ZPKRE2"] == "S-Y,B-Y"
    assert row.fields["WAERK"] == "JPY"
    assert row.fields["KUNNR1"] == row.fields["KUNNR3"] == "3200"


def test_in_operator_picks_the_other_branch(masters_dir):
    """contains 로 쓰면 brand_code='1' 도 참이 됐다 (SCHEMA §4.7.3)."""
    master = load_customer("ygjp", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("1"), po_date=ev("2026-01-01"),
                        brand_text=ev("YG BRAND (COMINIX)")),
        lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("1"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert row.fields["ZBRAND"] == "471"
    assert row.fields["ZSHCO"] == "A"


def test_line_level_rule_and_doc_posex(masters_dir):
    master = load_customer("kl", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("4507628839"), brand_text=ev("WIDIA GTD")),
        lines=[POLine(line_no=1, posex=ev("00001"), quantity=ev("24"),
                      brand_text=ev("KENNAMETAL"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert row.fields["POSEX"] == "1"                 # format: integer
    assert row.fields["ZPKRE2"] == row.fields["EMPST"] == "KMT"   # 라인 브랜드 우선
    assert row.fields["ZBRAND"] == "2"


def test_required_missing_blocks_sending(masters_dir):
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1"), brand_text=ev("HERTEL")),
        lines=[POLine(line_no=1, quantity=ev("1"))],          # item_code 없음
        shipments=[POShipment(ship_to_text=ev("ELKHART"),
                              lines=[POLine(line_no=1, quantity=ev("1"))])],
    )
    row = build(raw, master, masters_dir).rows[0]
    codes = {(i.field, i.code) for i in row.issues}
    assert ("MATNR", "REQUIRED_MISSING") in codes
    assert row.error_count >= 1


def test_table_no_match_is_an_error(masters_dir):
    """on_no_match: error — 출하처 도시를 못 읽으면 오더가 잘못 나간다."""
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1"), brand_text=ev("HERTEL")),
        lines=[],
        shipments=[POShipment(ship_to_text=ev("어디에도 없는 창고"),
                              lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("1"))])],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert any(i.code == "TABLE_NO_MATCH" and i.severity == "error" for i in row.issues)


def test_rule_no_match_is_an_error(masters_dir):
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1"), brand_text=ev("모르는 브랜드")),
        lines=[],
        shipments=[POShipment(ship_to_text=ev("ELKHART"),
                              lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("1"))])],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert any(i.code == "RULE_NO_MATCH" and i.severity == "error" for i in row.issues)


def test_format_error_is_reported_not_swallowed(masters_dir):
    """수량이 숫자가 아니면 ""로 넘기지 않는다 — 사람이 봐야 한다."""
    master = load_customer("ygjp", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("1"), po_date=ev("2026-01-01"), brand_text=ev("YG BRAND")),
        lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("스물다섯"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert any(i.field == "KWMENG" and i.code == "FORMAT_ERROR" for i in row.issues)


def test_bad_date_surfaces_as_an_error(masters_dir):
    master = load_customer("ygjp", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("1"), po_date=ev("언젠가"), brand_text=ev("YG BRAND")),
        lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("1"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert any(i.field == "BSTKD" and i.severity == "error" for i in row.issues)


def test_shipment_total_mismatch_is_caught(masters_dir):
    """블록을 놓치면 화면에 아예 안 나타난다 — 합계로만 잡을 수 있다."""
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1"), brand_text=ev("HERTEL")),
        lines=[],
        shipments=[POShipment(ship_to_text=ev("ELKHART"),
                              lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("10"))])],
        totals=POTotals(total_qty="25"),                       # 요약표는 25인데 10만 들어옴
    )
    result = build(raw, master, masters_dir)
    assert any(i.code == "TOTAL_MISMATCH" for r in result.rows for i in r.issues)
