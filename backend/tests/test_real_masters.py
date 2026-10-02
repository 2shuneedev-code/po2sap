"""실물 `masters/` 의 거래처 전용 규칙 — 사본이 아니라 **원본 그대로** 읽는다.

`conftest.masters_dir` 는 실물 거래처 파일을 빼고 합성 거래처만 얹는다. 실물 규칙은
여기서 본다 (읽기만 한다 — 원본을 고치지 않는다). 설계: `CUSTOMER_RULES.md` §4.

기대값은 숫자를 박지 않고 참조표에서 끌어온다 — 참조표가 바뀌어도 테스트가 따라온다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from app.domain.models import ExtractedValue as EV
from app.domain.models import POHeader, POLine, POShipment, RawPO
from app.masters.loader import load_customer
from app.rules.engine import build

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "masters"


def ev(value: str) -> EV:
    return EV(value=value, src=1, page=1, confidence=0.99)


def _ref_rows(name: str) -> list[dict[str, str]]:
    with (REAL / "refs" / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ── 전 거래처 ─────────────────────────────────────────────────────────
def test_real_masters_have_no_errors(validate_masters):
    base = validate_masters.load_base_fields(REAL)
    for code in validate_masters.customer_codes(REAL):
        report = validate_masters.validate_customer(code, base, REAL)
        assert not report.errors, (code, report.errors)


def test_customer_numbers_are_unique():
    """같은 고객코드가 두 파일에 있으면 어느 규칙이 쓰일지 정해지지 않는다."""
    seen: dict[str, str] = {}
    for path in sorted((REAL / "customers").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        no = load_customer(path.stem, REAL).customer_no
        assert no not in seen, f"{path.name} 와 {seen[no]} 가 둘 다 {no}"
        seen[no] = path.name


# ── SID TOOL (sid.yaml) ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def sid():
    return load_customer("sid", REAL)


def _sid_po(lines_by_city: dict[str, list[POLine]], brand: str = "ACCUPRO TAPS (Y)") -> RawPO:
    return RawPO(
        customer_code="SID", source_file="f.htm",
        header=POHeader(po_number=ev("7988114"), brand_text=ev(brand),
                        currency_text=ev("United States Dollars")),
        shipments=[
            POShipment(ship_to_text=ev(f"SID TOOL - {city} WAREHOUSE"), lines=lines)
            for city, lines in lines_by_city.items()
        ],
    )


def _line(no: int, our_item: str, qty: str = "10") -> POLine:
    return POLine(line_no=no, our_item=ev(our_item), item_code=ev(f"T{no}"), quantity=ev(qty))


def test_sid_routes_each_warehouse(sid):
    result = build(_sid_po({
        "ELKHART": [_line(1, "00000001")],
        "Harrisburg": [_line(1, "00000002")],
        "RENO": [_line(1, "00000003")],
        "ATLANTA": [_line(1, "00000004")],
    }), sid, REAL)
    got = [(r.fields["KUNNR2"], r.fields["BSTKD"], r.fields["ZPKRE"]) for r in result.rows]
    assert got == [
        ("100249", "7988114(ELKHART)", "C"),
        ("319677", "7988114(HARRISBURG)", "N"),
        ("319678", "7988114(RENO)", "O"),
        ("319679", "7988114(ATLANTA)", "A"),
    ]


def test_sid_appends_sid_ref_values_to_packing_remark(sid):
    rows = _ref_rows("sid_ref.csv")
    color = next(r for r in rows if r["color_ring"])
    hertel = next(r for r in rows if r["hertel_no"])
    result = build(_sid_po({"ATLANTA": [
        _line(1, color["your_code"]), _line(2, hertel["your_code"]),
    ]}), sid, REAL)
    assert [r.fields["ZPKRE"] for r in result.rows] == [
        f"A,{color['color_ring']}", f"A,{hertel['hertel_no']}",
    ]
    assert not [i for r in result.rows for i in r.issues if "sid_ref" in i.message]


def test_sid_unknown_city_warns_but_does_not_block(sid):
    result = build(_sid_po({"DALLAS": [_line(1, "00000001")]}), sid, REAL)
    row = result.rows[0]
    assert row.fields["BSTKD"] == "7988114"            # 도시를 모르면 PO번호만
    assert row.fields["KUNNR2"] == ""
    assert not [i for i in row.issues if i.severity == "error"]
    assert any(i.severity == "warn" for i in row.issues)


@pytest.mark.parametrize(("brand", "code"), [
    ("HERTEL (GP END MILLS) (APO)", "038"),
    ("INTERSTATE DRILLS", "127"),
    ("ACCUPRO TAPS (Y)", "205"),
    ("CLASS C SOLUTIONS", "428"),
])
def test_sid_brand_from_ordered_from(sid, brand, code):
    row = build(_sid_po({"RENO": [_line(1, "1")]}, brand), sid, REAL).rows[0]
    assert row.fields["ZBRAND"] == code
    # 값은 전용 규칙이 채웠다 — 드롭다운 후보 규칙의 "후보가 N개" 안내가 붙으면 안 된다
    assert not [i for i in row.issues if "후보" in i.message]


def test_sid_unknown_brand_is_blank_with_a_warning(sid):
    row = build(_sid_po({"RENO": [_line(1, "1")]}, "SOMETHING ELSE"), sid, REAL).rows[0]
    assert row.fields["ZBRAND"] == ""
    assert any(i.severity == "warn" and "브랜드" in i.message for i in row.issues)


def test_sid_brand_codes_are_registered_for_the_customer(sid):
    registered = {r["zbrand"] for r in _ref_rows("brand_master.csv") if r["kunnr"] == sid.customer_no}
    codes = {e["value"] for e in sid.rules["brand_text_match"]["entries"]}
    assert codes <= registered


# ── KL (kl.yaml) ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def kl():
    return load_customer("kl", REAL)


def _kl_po(brands: list[str], po: str = "4507628839 / 040") -> RawPO:
    return RawPO(
        customer_code="KL", source_file="f.pdf",
        header=POHeader(po_number=ev(po), currency_text=ev("USD")),
        lines=[
            POLine(line_no=n, posex=ev(f"{n:05d}"), our_item=ev(f"27486{n:02d}"),
                   quantity=ev("24"), brand_text=ev(b))
            for n, b in enumerate(brands, start=1)
        ],
    )


def test_kl_po_number_drops_the_part_after_slash(kl):
    assert build(_kl_po(["WIDIA GTD"]), kl, REAL).rows[0].fields["BSTKD"] == "4507628839"
    assert build(_kl_po(["WIDIA GTD"], "4507628839"), kl, REAL).rows[0].fields["BSTKD"] == "4507628839"


def test_kl_posex_is_an_integer(kl):
    rows = build(_kl_po(["", ""]), kl, REAL).rows
    assert [r.fields["POSEX"] for r in rows] == ["1", "2"]


def test_kl_brand_text_goes_to_packing_remark_and_remark(kl):
    rows = build(_kl_po(["WIDIA GTD", "Kennametal", "OTHER", ""]), kl, REAL).rows
    assert [(r.fields["ZPKRE"], r.fields["EMPST"]) for r in rows] == [
        ("WGT", "WGT"), ("KMT", "KMT"), ("", ""), ("", ""),
    ]
    assert not [i for r in rows for i in r.issues if i.field in ("ZPKRE", "EMPST")]


def test_kl_brand_is_left_to_the_shared_dropdown(kl):
    assert "brand_text_match" not in (kl.rules or {})
    assert kl.fields["ZBRAND"]["rule"] == "brand_code"


# ── YGJP (ygjp.yaml) ─────────────────────────────────────────────────
def _ygjp_po(brand: str, item_code: str = "E24201502SE") -> RawPO:
    return RawPO(
        customer_code="YGJP", source_file="f.pdf",
        header=POHeader(po_number=ev("10972"), po_date=ev("2026-05-18"),
                        brand_text=ev(brand), currency_text=ev("JPY")),
        lines=[POLine(line_no=1, item_code=ev(item_code), our_item=ev("1515X16"), quantity=ev("15"))],
    )


def _ygjp_brands(masters: Path) -> list[dict[str, str]]:
    ygjp = load_customer("ygjp", masters)
    return [r for r in _ref_rows("brand_master.csv") if r["kunnr"] == ygjp.customer_no]


def test_ygjp_fixed_ship_to_and_order_number():
    row = build(_ygjp_po("YG BRAND"), load_customer("ygjp", REAL), REAL).rows[0]
    assert row.fields["KUNNR2"] == "319854"
    assert row.fields["BSTKD"] == "01-20260518-10972"


def test_ygjp_brand_name_contained_in_the_line_picks_its_code():
    brand = _ygjp_brands(REAL)[0]
    line = f"{brand['zbrant'].lower()} S-Y,B-Y"             # 포장지시가 붙고 대소문자가 달라도
    row = build(_ygjp_po(line), load_customer("ygjp", REAL), REAL).rows[0]
    assert row.fields["ZBRAND"] == brand["zbrand"]
    assert row.fields["ZSHCO"] == ("A" if brand["zbrand"] in ("471", "507") else "L")


def test_ygjp_unknown_brand_is_blank_and_shipping_condition_is_l():
    row = build(_ygjp_po("NOT A BRAND"), load_customer("ygjp", REAL), REAL).rows[0]
    assert row.fields["ZBRAND"] == ""
    assert row.fields["ZSHCO"] == "L"
    assert any(i.severity == "warn" and "브랜드" in i.message for i in row.issues)


@pytest.mark.parametrize("code", ["471", "507"])
def test_ygjp_shipping_condition_a_for_471_507(tmp_path, code):
    """지금 마스터 3200 에는 471·507 이 없다 — 사본에 한 줄 얹어 A 분기를 본다."""
    import shutil

    masters = tmp_path / "masters"
    shutil.copytree(REAL, masters)
    with (masters / "refs" / "brand_master.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write(f'\n3200,"YG-1 JAPAN CO., LTD.",{code},TEST BRAND {code}\n')
    row = build(_ygjp_po(f"TEST BRAND {code} YG STD"), load_customer("ygjp", masters), masters).rows[0]
    assert (row.fields["ZBRAND"], row.fields["ZSHCO"]) == (code, "A")


def test_ygjp_missing_product_id_warns_even_with_your_code():
    row = build(_ygjp_po("YG BRAND", item_code=""), load_customer("ygjp", REAL), REAL).rows[0]
    assert row.fields["KDMAT"] == "1515X16"
    assert any(i.field == "MATNR" and i.severity == "warn" for i in row.issues)
