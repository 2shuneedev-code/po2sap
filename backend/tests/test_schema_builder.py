"""추출 스키마 — masters/SCHEMA.md §3.1 표준 키와 일치해야 한다.

§3.1 이 SSOT 다. 이 테스트는 코드가 거기서 이탈하는 것을 막는다.
"""

from __future__ import annotations

import re

from app.extraction.schema_builder import build_tool, build_tool_schema

VALUE_KEYS = {"value", "evidence", "page", "confidence"}


def _std_keys(schema_md: str) -> dict[str, set[str]]:
    """SCHEMA.md §3.1 의 코드블록에서 표준 키를 읽어온다."""
    body = schema_md.split("### 3.1 표준 키")[1].split("```")[1]
    out: dict[str, set[str]] = {}
    current = None
    for line in body.splitlines():
        m = re.match(r"^(header|shipment|line):\s*(.*)$", line.strip())
        if m:
            current = m.group(1)
            out[current] = set()
            rest = m.group(2)
        elif current and line.strip():
            rest = line.strip()
        else:
            continue
        out[current] |= {k.strip() for k in rest.split(",") if k.strip()}
    return out


def test_matches_schema_md_standard_keys(masters_dir):
    """코드의 키 목록이 SCHEMA.md §3.1 과 정확히 같은가."""
    expected = _std_keys((masters_dir / "SCHEMA.md").read_text(encoding="utf-8"))
    props = build_tool_schema(include_shipments=True)["properties"]

    header = set(props["header"]["properties"]) - {"extra"}
    line = set(props["lines"]["items"]["properties"]) - {"extra"}
    shipment = set(props["shipments"]["items"]["properties"]) - {"lines"}

    assert header == expected["header"]
    assert line == expected["line"]
    assert shipment == expected["shipment"]


def test_shipments_only_when_split():
    without = build_tool_schema()["properties"]
    assert "shipments" not in without

    with_split = build_tool_schema(include_shipments=True)["properties"]
    assert "shipments" in with_split
    assert "lines" in with_split["shipments"]["items"]["properties"]


def test_every_value_is_a_four_part_set():
    """모든 값은 {value, evidence, page, confidence} — 근거 없이는 검증할 수 없다."""
    props = build_tool_schema(include_shipments=True)["properties"]
    for key, spec in props["header"]["properties"].items():
        if key == "extra":
            continue
        assert set(spec["properties"]) == VALUE_KEYS, key
    for key, spec in props["lines"]["items"]["properties"].items():
        if key in {"extra", "line_no"}:
            continue
        assert set(spec["properties"]) == VALUE_KEYS, key


def test_extra_fields_land_in_both_namespaces():
    props = build_tool_schema([{"name": "contract_no", "description": "계약번호"}])["properties"]
    assert "contract_no" in props["header"]["properties"]["extra"]["properties"]
    assert "contract_no" in props["lines"]["items"]["properties"]["extra"]["properties"]


def test_tool_wrapper():
    tool = build_tool()
    assert tool["name"] == "extract_purchase_order"
    assert tool["input_schema"]["type"] == "object"
