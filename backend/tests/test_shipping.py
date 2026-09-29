"""출하 마스터 — 고객별 ZSHCO·VSART 가 `refs/shipping_master.csv` 에서 온다."""

from __future__ import annotations

import shutil

import pytest
from app.config import Settings
from app.extraction import Extractor
from app.masters import shipping
from app.masters.loader import load_customer
from app.rules.engine import build

SAMPLE = "PO-SAMPLE-0001.htm"


@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def _rows(fixtures_dir, masters, code="msc"):
    parsed = Extractor(Settings(llm_provider="mock")).parse_file(fixtures_dir / code / SAMPLE, code.upper())
    return build(parsed.raw, load_customer(code, masters), masters, file_name=SAMPLE).rows


def test_registered_customer_gets_its_values(workspace, fixtures_dir):
    kunnr = load_customer("msc", workspace).customer_no
    shipping.set_row(workspace, shipping.ShippingRow(kunnr=kunnr, zshco="01", vsart="02"))

    for row in _rows(fixtures_dir, workspace):
        assert row.fields["ZSHCO"] == "01"
        assert row.fields["VSART"] == "02"
        assert not [i for i in row.issues if i.field == "ZSHCO"]


def test_unregistered_customer_leaves_zshco_blank_and_defaults_vsart(workspace, fixtures_dir):
    for row in _rows(fixtures_dir, workspace):
        assert row.fields["ZSHCO"] == ""
        assert any(i.field == "ZSHCO" and i.severity == "warn" for i in row.issues)
        assert row.fields["VSART"] == "04"


def test_blank_vsart_in_a_row_falls_back_to_default(workspace, fixtures_dir):
    """빈 값은 후보가 아니다 — 행이 있어도 빈 칸이면 기본값으로 간다."""
    kunnr = load_customer("msc", workspace).customer_no
    shipping.set_row(workspace, shipping.ShippingRow(kunnr=kunnr, zshco="01"))
    for row in _rows(fixtures_dir, workspace):
        assert row.fields["VSART"] == "04"


def test_set_row_keeps_position_and_deletes_when_blank(workspace):
    for k in ("1", "2", "3"):
        shipping.set_row(workspace, shipping.ShippingRow(kunnr=k, zshco="0" + k))
    shipping.set_row(workspace, shipping.ShippingRow(kunnr="2", zshco="09"))
    assert [(r.kunnr, r.zshco) for r in shipping.load(workspace)] == [("1", "01"), ("2", "09"), ("3", "03")]

    assert shipping.set_row(workspace, shipping.ShippingRow(kunnr="2")) is None
    assert [r.kunnr for r in shipping.load(workspace)] == ["1", "3"]


def test_too_long_value_is_rejected_before_writing(workspace):
    before = (workspace / shipping.FILE).read_bytes()
    with pytest.raises(shipping.ShippingError):
        shipping.set_row(workspace, shipping.ShippingRow(kunnr="1", zshco="X" * 50))
    assert (workspace / shipping.FILE).read_bytes() == before


def test_save_leaves_a_backup(workspace, tmp_path):
    shipping.set_row(workspace, shipping.ShippingRow(kunnr="1", zshco="01"))
    shipping.set_row(workspace, shipping.ShippingRow(kunnr="1", zshco="02"), storage_dir=tmp_path / "st")
    assert list((tmp_path / "st").rglob("*shipping_master*"))
