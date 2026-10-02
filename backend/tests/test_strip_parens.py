"""`format: strip_parens` — 품번 뒤에 붙어 오는 괄호를 통째로 뗀다 (SCHEMA §4.6)."""

from __future__ import annotations

import pytest
from app.rules.primitives import apply_format


@pytest.mark.parametrize(("raw", "expected"), [
    ("D1103036(1pc)", "D1103036"),
    ("D1103036 (1pc)", "D1103036"),
    ("D1103036（1pc）", "D1103036"),
    ("D1103036", "D1103036"),
    ("(1pc)", ""),
    ("", ""),
])
def test_strip_parens(raw, expected):
    assert apply_format("strip_parens", raw) == expected
