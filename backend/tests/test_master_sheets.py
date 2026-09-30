"""Brand Master · Shipping Master 스프레드시트 저장 — **원본 CSV 를 직접** 고친다.

고객 한 곳만 고치면 그 고객 블록 자리를 지키고 나머지 행은 한 글자도 안 바뀐다.
검사를 하나라도 통과 못 하면 파일을 건드리지 않는다.
"""

from __future__ import annotations

import shutil

import pytest
from app.config import Settings
from app.masters import brands, shipping
from app.preview import field_choices


@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def _customers_by_count(masters):
    counts: dict[str, int] = {}
    for r in brands.load_sap_rows(masters):
        counts[r.kunnr] = counts.get(r.kunnr, 0) + 1
    return counts


# ── Brand Master ──────────────────────────────────────────────────────
def test_scoped_save_replaces_only_that_customer_in_place(workspace):
    before = brands.load_sap_rows(workspace)
    kunnr = before[len(before) // 2].kunnr
    new = [brands.SapRow(kunnr=kunnr, zbrand="9999", zbrant="NEW", name1="X")]

    brands.set_sap_rows(workspace, new, kunnr=kunnr)

    after = brands.load_sap_rows(workspace)
    others_before = [r for r in before if r.kunnr != kunnr]
    assert [r for r in after if r.kunnr != kunnr] == others_before
    first = next(i for i, r in enumerate(before) if r.kunnr == kunnr)
    assert after[first] == new[0]


def test_saved_candidates_are_what_the_rule_engine_sees(workspace):
    kunnr = brands.load_sap_rows(workspace)[0].kunnr
    rows = [brands.SapRow(kunnr=kunnr, zbrand=c, zbrant=f"B{c}") for c in ("901", "902")]
    brands.set_sap_rows(workspace, rows, kunnr=kunnr)
    assert brands.registered_codes(workspace, kunnr) == {"901", "902"}


def test_whole_file_save_replaces_everything(workspace):
    rows = [brands.SapRow(kunnr="1", zbrand="001", zbrant="A")]
    brands.set_sap_rows(workspace, rows)
    assert brands.load_sap_rows(workspace) == rows


def test_file_keeps_bom_so_excel_reads_korean(workspace):
    kunnr = brands.load_sap_rows(workspace)[0].kunnr
    brands.set_sap_rows(workspace, [brands.SapRow(kunnr=kunnr, zbrand="001", zbrant="한글")],
                        kunnr=kunnr)
    assert (workspace / brands.MASTER_FILE).read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("row, message", [
    (brands.SapRow(kunnr="", zbrand="001"), "고객코드"),
    (brands.SapRow(kunnr="K", zbrand=""), "브랜드 코드"),
    (brands.SapRow(kunnr="K", zbrand="12345"), "자까지"),
])
def test_bad_rows_are_refused_and_the_file_is_untouched(workspace, row, message):
    path = workspace / brands.MASTER_FILE
    before = path.read_bytes()
    with pytest.raises(brands.BrandError, match=message):
        brands.set_sap_rows(workspace, [row])
    assert path.read_bytes() == before


def test_duplicate_code_for_one_customer_is_refused(workspace):
    row = brands.SapRow(kunnr="K", zbrand="001")
    with pytest.raises(brands.BrandError, match="두 번"):
        brands.set_sap_rows(workspace, [row, row])


def test_scoped_save_refuses_another_customers_row(workspace):
    with pytest.raises(brands.BrandError, match="행만"):
        brands.set_sap_rows(workspace, [brands.SapRow(kunnr="B", zbrand="001")], kunnr="A")


def test_backup_is_taken_before_overwriting(workspace, tmp_path):
    from app.masters import backup

    storage = tmp_path / "storage"
    kunnr = brands.load_sap_rows(workspace)[0].kunnr
    brands.set_sap_rows(workspace, [brands.SapRow(kunnr=kunnr, zbrand="001")],
                        kunnr=kunnr, storage_dir=storage)
    assert backup.history(workspace / brands.MASTER_FILE, storage)


# ── Shipping Master ───────────────────────────────────────────────────
def test_shipping_whole_file_save_and_blank_rows_dropped(workspace):
    rows = [
        shipping.ShippingRow(kunnr="1", zshco="01", vsart="02"),
        shipping.ShippingRow(kunnr="2"),                     # 값이 둘 다 비면 버린다
    ]
    shipping.set_rows(workspace, rows)
    assert shipping.load(workspace) == [rows[0]]


def test_shipping_scoped_save_keeps_other_customers(workspace):
    shipping.set_rows(workspace, [shipping.ShippingRow(kunnr=k, zshco="01") for k in "ABC"])
    shipping.set_rows(workspace, [shipping.ShippingRow(kunnr="B", vsart="09")], kunnr="B")
    assert [(r.kunnr, r.zshco, r.vsart) for r in shipping.load(workspace)] == [
        ("A", "01", ""), ("B", "", "09"), ("C", "01", ""),
    ]


def test_shipping_refuses_two_rows_for_one_customer(workspace):
    rows = [shipping.ShippingRow(kunnr="A", zshco="01"), shipping.ShippingRow(kunnr="A", vsart="02")]
    with pytest.raises(shipping.ShippingError, match="두 개"):
        shipping.set_rows(workspace, rows)


# ── 검수 표 드롭다운 ──────────────────────────────────────────────────
def test_dropdown_only_when_there_are_several_candidates(workspace):
    settings = Settings(masters_dir=workspace)
    counts = _customers_by_count(workspace)
    many = next(k for k, n in counts.items() if n > 1)
    one = next((k for k, n in counts.items() if n == 1), None)

    choices = field_choices(many, settings)
    assert len(choices["ZBRAND"]) == counts[many]
    assert all(len(option) == 2 and option[1] for option in choices["ZBRAND"])  # 코드 · 이름
    assert "ZSHCO" not in choices                  # 고객 1곳 = 값 1개 → 드롭다운 아님
    if one:
        assert "ZBRAND" not in field_choices(one, settings)
