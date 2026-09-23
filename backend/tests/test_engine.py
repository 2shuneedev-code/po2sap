"""규칙엔진 ②~⑦ — masters/SCHEMA.md §2.

엔진은 마스터가 시킨 것만 한다. 거래처 이름으로 분기하지 않으므로(원칙 P2)
테스트도 거래처를 **설정으로** 밀어 넣어 확인한다.

2026-09-23: msc/kl/ygjp 는 거래처 전용 규칙(결정표·csv_map·keyword_map·expr
조합)을 걷어내고 기본(profiles/standard, `csv_choice`)만 쓴다. 그 예외
로직에 대한 엔진 테스트(결정표·on_no_match:error·날짜 조립식 BSTKD 등)는
합성 마스터로 뒤덮기보다, 예외가 다시 생길 때 그 거래처 파일과 함께
다시 쓴다 — 지금은 **기본 동작**만 확인한다.
"""

from __future__ import annotations

import json

import pytest
from app.config import Settings
from app.domain.models import ExtractedValue as EV
from app.domain.models import POHeader, POLine, POTotals, RawPO
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
    # 🔴 는 전송을 막으므로 0 이어야 한다. **경고 수는 박지 않는다** —
    # 마스터에서 `required: warn` 인 필드가 늘고 주는 것은 정상이고,
    # 그때마다 멀쩡한 테스트가 죽으면 안 된다 (CLAUDE.md §5).
    assert msc_result.error_count == 0


def test_every_send_field_is_present(msc_result, masters_dir):
    """계약 §4·5 — columns 의 전 필드가 키로 존재한다. 값이 없어도 ""."""
    import yaml

    base = yaml.safe_load((masters_dir / "_base" / "sap_defaults.yaml").read_text("utf-8"))
    expected = list(base["field_specs"])
    assert msc_result.columns == expected
    for row in msc_result.rows:
        assert list(row.fields) == expected
        assert all(isinstance(v, str) for v in row.fields.values())


def test_group_falls_back_to_receiving_loc_without_a_split_config(msc_result):
    """split.group_label 이 없으면 shipment 의 receiving_loc 을 쓴다 (SCHEMA §4.3)."""
    assert [r.group for r in msc_result.rows] == ["ELK", "HAR"]


def test_summary_table_did_not_become_orders(msc_result):
    """§2.1-2 — 상단 요약표를 쓰면 수량이 두 배가 된다."""
    assert sorted(r.fields["KWMENG"] for r in msc_result.rows) == ["10", "15"]


def test_base_defaults_feed_every_row_the_same_way(msc_result):
    """거래처 전용 예외가 없으니 두 출하처 모두 같은 기본값을 받는다.

    (KUNNR2 가 출하처마다 달라지는 것은 걷어낸 예외였다 — 다시 얹을 때 이
    테스트를 갱신한다.)
    """
    a, b = msc_result.rows
    assert a.fields["BSTKD"] == b.fields["BSTKD"] == "PO-SAMPLE-0001"
    assert a.fields["KUNNR2"] == b.fields["KUNNR2"] == "100249"
    assert a.fields["KUNNR1"] == a.fields["KUNNR3"] == "100249"
    assert a.fields["AUART"] == "ZEXP"


def test_brand_is_blank_with_a_warning_when_many_candidates(msc_result):
    """MSC 는 브랜드 후보가 여럿이다 — 문구 판별 예외를 걷어냈으니 비워 둔다."""
    for row in msc_result.rows:
        assert row.fields["ZBRAND"] == ""
        assert any(i.field == "" and i.severity == "warn" for i in row.issues)
        assert not [i for i in row.issues if i.severity == "error"]


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
                        brand_text=ev("YG BRAND"), currency_text=ev("JPY")),
        lines=[POLine(line_no=1, item_code=ev("E24201502SE"), quantity=ev("15"))],
    )
    result = build(raw, master, masters_dir)
    row = result.rows[0]
    assert row.group == ""                                     # 분할 없음
    assert row.fields["BSTKD"] == "10972"                       # 기본: doc 그대로
    assert row.fields["WAERK"] == "JPY"                         # 기본: currency 규칙
    assert row.fields["KUNNR1"] == row.fields["KUNNR3"] == "3200"
    assert row.fields["KUNNR2"] == "3200"                       # 기본: KUNNR 과 동일


def test_line_level_format_still_applies_without_customer_overrides(masters_dir):
    """예외 규칙(pack_remark 등)을 걷어내도 **기본 포맷 검증**은 그대로 동작한다."""
    master = load_customer("kl", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("4507628839")),
        lines=[POLine(line_no=1, posex=ev("00001"), quantity=ev("24"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert row.fields["BSTKD"] == "4507628839"
    assert row.fields["KWMENG"] == "24"


def test_required_true_still_blocks_sending(masters_dir):
    """KWMENG 은 프로필에서도 `required: true` 다 — 예외가 없어도 막는다."""
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1")),
        lines=[POLine(line_no=1, item_code=ev("X"))],          # quantity 없음
    )
    row = build(raw, master, masters_dir).rows[0]
    codes = {(i.field, i.code) for i in row.issues}
    assert ("KWMENG", "REQUIRED_MISSING") in codes
    assert row.error_count >= 1


def test_required_warn_does_not_block_sending(masters_dir):
    """MATNR 은 공용 프로필에서 `required: warn` 이다 — 없어도 막지 않는다.

    거래처 전용 예외(옛 msc.yaml 의 `required: true`)를 걷어낸 결과다.
    확정되면 그 거래처 파일에서 다시 `true` 로 올린다(CLAUDE.md §5).
    """
    master = load_customer("msc", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("PO-1")),
        lines=[POLine(line_no=1, quantity=ev("1"))],            # item_code 없음
    )
    row = build(raw, master, masters_dir).rows[0]
    codes = {(i.field, i.code, i.severity) for i in row.issues}
    assert ("MATNR", "REQUIRED_MISSING", "warn") in codes
    assert row.error_count == 0


def test_format_error_is_reported_not_swallowed(masters_dir):
    """수량이 숫자가 아니면 ""로 넘기지 않는다 — 사람이 봐야 한다."""
    master = load_customer("ygjp", masters_dir)
    raw = raw_po(
        header=POHeader(po_number=ev("1")),
        lines=[POLine(line_no=1, item_code=ev("X"), quantity=ev("스물다섯"))],
    )
    row = build(raw, master, masters_dir).rows[0]
    assert any(i.field == "KWMENG" and i.code == "FORMAT_ERROR" for i in row.issues)
