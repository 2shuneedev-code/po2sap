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
