"""전용 규칙이 없는 거래처 — 공용 프로필로 브랜드까지 뽑아낸다.

SAP 브랜드 마스터에 브랜드가 등록된 고객이면 전용 YAML 없이도 발주서를 읽어
**브랜드·발주번호·품번·수량**이 나와야 한다. 전 거래처 테스트 배포가 그래야
가능하다.

동시에 **모르는 값이 조용히 나가면 안 된다.** 출하처처럼 문서를 봐도 알 수 없는
값은 비어 있고 검수가 빨갛게 막아야 한다. 그럴듯한 기본값(출하처 = 판매처)을
넣으면 사람이 확인 없이 전송하고 틀린 곳으로 오더가 간다.
"""

from __future__ import annotations

import csv
import shutil

import pytest
from app.domain.models import ExtractedValue, POHeader, POLine, RawPO
from app.masters import brands as brand_store
from app.masters import load_customer
from app.rules.engine import build

# 전용 규칙이 없고 브랜드는 등록된 고객 (SOCIETE OTELO)
KUNNR = "100251"
ZBRAND = "86"
BRAND_TEXT = "OTELO BRAND"


@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


@pytest.fixture
def mapped(workspace):
    """현업이 브랜드 매핑 화면에서 문구를 등록한 상태."""
    brand_store.set_keys(workspace, KUNNR, ZBRAND, [
        brand_store.BrandKey(kunnr=KUNNR, zbrand=ZBRAND, match="contains",
                             text=BRAND_TEXT, note="테스트"),
    ])
    return workspace


def value(text: str) -> ExtractedValue:
    return ExtractedValue(value=text, confidence=0.95)


def raw_po(brand_text: str = BRAND_TEXT) -> RawPO:
    return RawPO(
        customer_code=KUNNR,
        source_file="po.pdf",
        header=POHeader(
            po_number=value("PO-77001"),
            brand_text=value(brand_text),
            ship_to_text=value("SOME WAREHOUSE, LYON"),
        ),
        lines=[
            POLine(line_no=1, item_code=value("YG-EM1000"), quantity=value("12")),
            POLine(line_no=2, item_code=value("YG-DR2000"), quantity=value("5")),
        ],
    )


def rows_for(masters, brand_text: str = BRAND_TEXT):
    master = load_customer(KUNNR, masters)
    return master, build(raw_po(brand_text), master, masters, file_name="po.pdf")


# ── 공용 프로필이 붙는가 ──────────────────────────────────────────────
def test_customer_without_rules_still_loads(workspace):
    master = load_customer(KUNNR, workspace)
    assert master.customer_no == KUNNR
    assert master.raw["meta"]["generic"] is True, "공용 설정임을 표시해야 화면이 알린다"


def test_generic_customer_declares_every_send_field(workspace):
    """전송 필드는 `_base` 가 정한다 — 공용이라고 일부만 나가면 안 된다."""
    master = load_customer(KUNNR, workspace)
    assert set(master.fields) == set(master.raw["field_specs"])


def test_customer_with_no_brands_at_all_is_an_error(workspace):
    """브랜드가 없으면 판정할 근거가 없다 — 조용히 넘어가지 않는다."""
    from app.masters import MasterError

    with pytest.raises(MasterError):
        load_customer("999999", workspace)


# ── 브랜드가 실제로 나오는가 ──────────────────────────────────────────
def test_brand_comes_out_for_a_customer_without_rules(mapped):
    """★ 이 테스트가 이번 변경의 핵심이다."""
    _, result = rows_for(mapped)

    assert len(result.rows) == 2
    for row in result.rows:
        assert row.fields["ZBRAND"] == ZBRAND, "전용 규칙 없이도 브랜드가 나와야 한다"


def test_document_values_come_out(mapped):
    _, result = rows_for(mapped)
    assert [r.fields["MATNR"] for r in result.rows] == ["YG-EM1000", "YG-DR2000"]
    assert [r.fields["KWMENG"] for r in result.rows] == ["12", "5"]
    assert all(r.fields["BSTKD"] == "PO-77001" for r in result.rows)


def test_customer_number_fills_sold_to(mapped):
    _, result = rows_for(mapped)
    assert all(r.fields["KUNNR1"] == KUNNR for r in result.rows)


# ── 모르는 값은 막는가 ───────────────────────────────────────────────
def test_ship_to_is_blank_and_blocks_sending(mapped):
    """★ 출하처를 추측해 채우면 틀린 곳으로 오더가 나간다. 비우고 막는다."""
    _, result = rows_for(mapped)

    for row in result.rows:
        assert row.fields["KUNNR2"] == "", "모르는 출하처를 채워 넣으면 안 된다"
        blocking = [i for i in row.issues if i.severity == "error" and i.field == "KUNNR2"]
        assert blocking, "빈 출하처가 검수를 막지 않으면 조용히 전송된다"


def test_unmapped_brand_text_is_an_error(workspace):
    """매핑되지 않은 문구는 오류다 — 빈 브랜드로 전송되면 안 된다."""
    _, result = rows_for(workspace, brand_text="듣도 보도 못한 브랜드")
    assert all(
        any(i.severity == "error" and i.field == "ZBRAND" for i in row.issues)
        for row in result.rows
    )


def test_brand_not_registered_for_this_customer_is_refused(workspace):
    """다른 고객 코드를 끌어다 쓰면 `value_check` 가 막는다 (SAP 이 거부할 값)."""
    with pytest.raises(brand_store.BrandError):
        brand_store.set_keys(workspace, KUNNR, "99999", [
            brand_store.BrandKey(kunnr=KUNNR, zbrand="99999", match="contains",
                                 text="X", note=""),
        ])


# ── 전용 규칙이 생기면 그쪽이 이긴다 ──────────────────────────────────
def test_a_dedicated_rules_file_wins_over_the_generic_profile(workspace):
    master = load_customer("MSC", workspace)
    assert master.raw["meta"].get("generic") is not True
    assert master.code == "MSC"


def test_mapped_count_is_visible(mapped):
    """화면이 '몇 개나 매핑됐는지'를 보여줄 수 있어야 한다."""
    path = mapped / "refs" / "brand_keys.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["kunnr"] == KUNNR]
    assert len(rows) == 1
