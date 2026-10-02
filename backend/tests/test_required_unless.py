"""`required_unless` — 대신할 필드 중 하나라도 값이 있으면 비어도 통과한다 (SCHEMA §4.6)."""

from __future__ import annotations

import pytest
from app.validation import validate_row

FIELDS = {"MATNR": {"required": "warn", "required_unless": ["KDMAT"]}, "KDMAT": {}}
SPECS = {"MATNR": {"label": "자재번호"}}


@pytest.mark.parametrize(("matnr", "kdmat", "warned"), [
    ("", "", True),
    ("", "C-100", False),
    ("M-1", "", False),
    ("M-1", "C-100", False),
])
def test_warns_only_when_both_are_blank(matnr, kdmat, warned):
    issues = validate_row({"MATNR": matnr, "KDMAT": kdmat}, FIELDS, SPECS)
    assert bool([i for i in issues if i.field == "MATNR"]) is warned


def test_message_names_both_fields():
    [issue] = validate_row({"MATNR": "", "KDMAT": ""}, FIELDS, SPECS)
    assert issue.severity == "warn"
    assert "MATNR" in issue.message and "KDMAT" in issue.message


@pytest.mark.parametrize(("value", "warned"), [("0", True), ("0.000", True), ("15", False), ("", False)])
def test_nonzero_warns_only_on_zero(value, warned):
    """검수 저장(merge_edits)도 validate_row 를 다시 돌린다 — 그래서 경고가 사라지지 않는다."""
    issues = validate_row({"KWMENG": value}, {"KWMENG": {"nonzero": "warn"}}, {})
    assert bool([i for i in issues if i.code == "ZERO_VALUE"]) is warned
