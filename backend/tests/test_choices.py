"""`fields.*.choices` — 값은 전용 규칙이, 드롭다운 후보는 공용 `csv_choice` 가 준다 (SCHEMA §4.6)."""

from __future__ import annotations

import shutil

import pytest
import yaml
from app.config import Settings
from app.masters.loader import load_customer
from app.preview import field_choices

KEYWORD_RULE = {
    "kind": "keyword_map",
    "source": "header.brand_text",
    "entries": [{"contains": "HERTEL", "value": "038"}],
    "on_no_match": {"action": "warn", "message": "x"},
}


@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def _set_brand(workspace, field: dict) -> None:
    path = workspace / "customers" / "msc.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    data.setdefault("rules", {})["brand_text_match"] = KEYWORD_RULE
    data.setdefault("fields", {})["ZBRAND"] = field
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")


def test_choices_points_dropdown_at_shared_csv_choice(workspace):
    _set_brand(workspace, {"from": "rule", "rule": "brand_text_match", "choices": "brand_code"})
    choices = field_choices("msc", Settings(masters_dir=workspace))
    assert len(choices["ZBRAND"]) > 1                      # 이 고객의 브랜드 후보 전부


def test_without_choices_a_non_choice_rule_has_no_dropdown(workspace):
    _set_brand(workspace, {"from": "rule", "rule": "brand_text_match"})
    assert "ZBRAND" not in field_choices("msc", Settings(masters_dir=workspace))


@pytest.mark.parametrize("target", ["nope", "brand_text_match"])
def test_validator_rejects_choices_that_is_not_a_csv_choice(validate_masters, workspace, target):
    _set_brand(workspace, {"from": "rule", "rule": "brand_text_match", "choices": target})
    base = validate_masters.load_base_fields(workspace)
    report = validate_masters.validate_customer("msc", base, workspace)
    assert any("choices" in e for e in report.errors), report.errors


def test_choices_loads_through_the_customer_loader(workspace):
    _set_brand(workspace, {"from": "rule", "rule": "brand_text_match", "choices": "brand_code"})
    assert load_customer("msc", workspace).fields["ZBRAND"]["choices"] == "brand_code"


@pytest.mark.parametrize(("expr", "bad"), [
    ('if(in(field.ZBRAND, ["471"]), "A", header.po_number)', True),   # 원문과 섞임
    ('if(in(field.ZBRAND, ["471"]), "A", "L")', False),
])
def test_validator_keeps_derived_fields_to_field_refs_only(validate_masters, workspace, expr, bad):
    path = workspace / "customers" / "msc.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    data.setdefault("fields", {})["ZSHCO"] = {"from": "expr", "expr": expr}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")
    base = validate_masters.load_base_fields(workspace)
    report = validate_masters.validate_customer("msc", base, workspace)
    assert any("field.*" in e for e in report.errors) is bad, report.errors
