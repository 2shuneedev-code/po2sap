"""전용 규칙이 없는 거래처 — 공용 프로필로 브랜드까지 뽑아낸다.

SAP 브랜드 마스터에 브랜드가 등록된 고객이면 전용 YAML 없이도 발주서를 읽어
**발주번호·품번·수량**이 나와야 한다. 브랜드는 후보 수로 판정한다
(`csv_choice`, SCHEMA §4.5) — 후보가 1개면 자동으로 채우고, 여럿이면 비운다.
원문 문구는 보지 않는다. 전 거래처 테스트 배포가 그래야 가능하다.

**막지는 않는다.** 이 프로그램의 본업은 발주서 내용을 표로 옮기는 것이다.
모르는 값은 노랗게 표시만 하고 전송을 막지 않는다 — 거래처 규칙이 확정되면
그 거래처 파일에서 `required: true` 로 올려 막으면 된다.

다만 **추측해서 채우지는 않는다.** 그럴듯해서 사람이 확인 없이 넘기는 값은
만들지 않는다. 비워 두면 최소한 빈 칸이 보인다.
"""

from __future__ import annotations

import pytest
from app.domain.models import ExtractedValue, POHeader, POLine, RawPO
from app.masters import load_customer
from app.rules.engine import build

# 전용 규칙이 없고 브랜드 후보가 **여럿**인 고객 (SOCIETE OTELO — 13개)
MANY_KUNNR = "100251"
# 전용 규칙이 없고 브랜드 후보가 **하나뿐**인 고객 (INGERSOLL CUTTING TOOL — 1개)
ONE_KUNNR = "100203"
ONE_ZBRAND = "002"


def value(text: str) -> ExtractedValue:
    return ExtractedValue(value=text, confidence=0.95)


def raw_po(kunnr: str) -> RawPO:
    return RawPO(
        customer_code=kunnr,
        source_file="po.pdf",
        header=POHeader(
            po_number=value("PO-77001"),
            ship_to_text=value("SOME WAREHOUSE, LYON"),
        ),
        lines=[
            POLine(line_no=1, item_code=value("YG-EM1000"), quantity=value("12")),
            POLine(line_no=2, item_code=value("YG-DR2000"), quantity=value("5")),
        ],
    )


def rows_for(masters, kunnr: str):
    master = load_customer(kunnr, masters)
    return master, build(raw_po(kunnr), master, masters, file_name="po.pdf")


# ── 공용 프로필이 붙는가 ──────────────────────────────────────────────
def test_customer_without_rules_still_loads(masters_dir):
    master = load_customer(MANY_KUNNR, masters_dir)
    assert master.customer_no == MANY_KUNNR
    assert master.raw["meta"]["generic"] is True, "공용 설정임을 표시해야 화면이 알린다"


def test_generic_customer_declares_every_send_field(masters_dir):
    """전송 필드는 `_base` 가 정한다 — 공용이라고 일부만 나가면 안 된다."""
    master = load_customer(MANY_KUNNR, masters_dir)
    assert set(master.fields) == set(master.raw["field_specs"])


def test_customer_with_no_brands_at_all_is_an_error(masters_dir):
    """브랜드가 없으면 판정할 근거가 없다 — 조용히 넘어가지 않는다."""
    from app.masters import MasterError

    with pytest.raises(MasterError):
        load_customer("999999", masters_dir)


# ── 브랜드가 후보 수로 판정되는가 (csv_choice, SCHEMA §4.5) ─────────────
def test_brand_auto_fills_when_only_one_candidate(masters_dir):
    """★ 후보가 1개면 원문을 보지 않고도 자동으로 채운다."""
    _, result = rows_for(masters_dir, ONE_KUNNR)

    assert len(result.rows) == 2
    for row in result.rows:
        assert row.fields["ZBRAND"] == ONE_ZBRAND, "후보가 하나뿐이면 자동으로 채워야 한다"
        assert not [i for i in row.issues if i.field == "ZBRAND"]


def test_brand_stays_blank_when_many_candidates(masters_dir):
    """★ 후보가 여럿이면 원문과 무관하게 비워 두고 사람이 고르게 한다.

    추측해서 하나를 집으면 그럴듯해서 사람이 확인 없이 넘긴다 — 그래서 비운다.
    """
    _, result = rows_for(masters_dir, MANY_KUNNR)

    for row in result.rows:
        assert row.fields["ZBRAND"] == "", "후보가 여럿이면 비워 둬야 한다"
        assert any(i.field == "" and i.severity == "warn" for i in row.issues), \
            "후보가 여럿인데 아무 표시도 없으면 조용히 나간다"
        assert not [i for i in row.issues if i.severity == "error"], \
            "값을 옮기는 것이 본업이다 — 브랜드 미확정으로 전송을 막지 않는다"


def test_document_values_come_out(masters_dir):
    _, result = rows_for(masters_dir, MANY_KUNNR)
    assert [r.fields["MATNR"] for r in result.rows] == ["YG-EM1000", "YG-DR2000"]
    assert [r.fields["KWMENG"] for r in result.rows] == ["12", "5"]
    assert all(r.fields["BSTKD"] == "PO-77001" for r in result.rows)


def test_customer_number_fills_sold_to(masters_dir):
    _, result = rows_for(masters_dir, MANY_KUNNR)
    assert all(r.fields["KUNNR1"] == MANY_KUNNR for r in result.rows)


def test_kunnr2_defaults_to_the_same_customer_number(masters_dir):
    """KUNNR1/2/3 은 기본이 전부 같은 값이다 — 조건이 생기면 거래처 파일이 덮어쓴다."""
    _, result = rows_for(masters_dir, MANY_KUNNR)
    assert all(r.fields["KUNNR2"] == MANY_KUNNR for r in result.rows)


# ── 모르는 값은 막는가 ───────────────────────────────────────────────
def test_shipping_condition_is_blank_but_does_not_block(masters_dir):
    """★ 출하조건(ZSHCO) 참조표가 없으면 추측해 채우지 않는다. 다만 막지도 않는다.

    추측값은 그럴듯해서 사람이 확인 없이 넘긴다. 빈 칸은 최소한 눈에 띈다.
    """
    _, result = rows_for(masters_dir, MANY_KUNNR)

    for row in result.rows:
        assert row.fields["ZSHCO"] == "", "미확보 참조표 값을 채워 넣으면 안 된다"
        assert not [i for i in row.issues if i.severity == "error"], \
            "값을 옮기는 것이 본업이다 — 빈 출하조건으로 전송을 막지 않는다"


# ── 전용 규칙이 생기면 그쪽이 이긴다 ──────────────────────────────────
def test_a_dedicated_rules_file_wins_over_the_generic_profile(masters_dir):
    master = load_customer("MSC", masters_dir)
    assert master.raw["meta"].get("generic") is not True
    assert master.code == "MSC"
