"""추출 스키마 — masters/SCHEMA.md §3.1 표준 키 · §3.2 값 포장과 일치해야 한다.

§3.1 · §3.2 가 SSOT 다. 이 테스트는 코드가 거기서 이탈하는 것을 막는다.
툴은 둘이다 — OUTLINE(골격)과 LINES(품목). design.md §3.3.2.
"""

from __future__ import annotations

import re

from app.extraction.schema_builder import (
    ANCHOR_KEYS,
    LINES_TOOL_NAME,
    OUTLINE_TOOL_NAME,
    SINGLE_TOOL_NAME,
    build_lines_schema,
    build_lines_tool,
    build_outline_schema,
    build_outline_tool,
    build_single_tool,
)

VALUE_KEYS = {"value", "src", "src_end", "confidence"}


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
    """코드의 키 목록이 SCHEMA.md §3.1 과 정확히 같은가.

    `line_no` 는 표준 키지만 **추출이 받지 않는다** (§3.2-나, 병합 후 엔진이 매긴다).
    """
    expected = _std_keys((masters_dir / "SCHEMA.md").read_text(encoding="utf-8"))
    outline = build_outline_schema(include_shipments=True)["properties"]
    lines = build_lines_schema()["properties"]["lines"]["items"]["properties"]

    header = set(outline["header"]["properties"]) - {"extra"}
    line = set(lines) - {"extra"} - ANCHOR_KEYS
    shipment = set(outline["shipments"]["items"]["properties"]) - ANCHOR_KEYS

    assert header == expected["header"]
    assert line == expected["line"] - {"line_no"}
    assert shipment == expected["shipment"]


def test_outline_never_carries_line_items():
    """OUTLINE 은 품목을 1줄도 받지 않는다 — 출력 토큰의 병목이 품목이다 (design §3.3.1)."""
    for include_shipments in (True, False):
        props = build_outline_schema(include_shipments=include_shipments)["properties"]
        assert "lines" not in props
        if include_shipments:
            assert "lines" not in props["shipments"]["items"]["properties"]


def test_outline_shipments_xor_line_range():
    """`split.by` 가 none 이 아니면 블록마다 구간, none 이면 `line_range` 하나."""
    split = build_outline_schema(include_shipments=True)
    assert "shipments" in split["properties"] and "line_range" not in split["properties"]
    assert "shipments" in split["required"]

    single = build_outline_schema(include_shipments=False)
    assert "line_range" in single["properties"] and "shipments" not in single["properties"]
    assert "line_range" in single["required"]


def test_shipment_blocks_carry_a_required_span():
    """블록의 src~src_end(품목표 포함 구간)가 청크 경계가 된다."""
    block = build_outline_schema(include_shipments=True)["properties"]["shipments"]["items"]
    assert {"src", "src_end"} <= set(block["required"])
    assert block["properties"]["src"]["type"] == "integer"


def test_line_range_carries_a_required_span():
    rng = build_outline_schema()["properties"]["line_range"]
    assert set(rng["required"]) == {"src", "src_end"}


def test_header_and_shipment_values_are_wrapped_with_an_anchor():
    """§3.2-가 — `{value, src, src_end?, confidence}`. 필수는 value·src·confidence."""
    props = build_outline_schema(include_shipments=True)["properties"]
    for key, spec in props["header"]["properties"].items():
        if key == "extra":
            continue
        assert set(spec["properties"]) == VALUE_KEYS, key
        assert set(spec["required"]) == {"value", "src", "confidence"}, key
    for key, spec in props["shipments"]["items"]["properties"].items():
        if key in ANCHOR_KEYS:
            continue
        assert set(spec["properties"]) == VALUE_KEYS, key


def test_absent_fields_are_omitted_not_null():
    """없는 필드는 키를 생략한다 — 헤더 필드를 required 에 넣지 않는다 (§3.2)."""
    schema = build_outline_schema(include_shipments=True)
    assert "required" not in schema["properties"]["header"]
    for spec in schema["properties"]["header"]["properties"].values():
        assert "null" not in str(spec["properties"]["value"]["type"])


def test_line_items_are_flat_scalars_with_one_anchor_per_line():
    """§3.2-나 — 평평한 스칼라 + 줄 단위 src·confidence. 값마다 4종 세트로 싸지 않는다."""
    item = build_lines_schema()["properties"]["lines"]["items"]
    for key, spec in item["properties"].items():
        if key in ANCHOR_KEYS:
            continue
        assert spec == {"type": "string", "description": spec["description"]}, key
    assert set(item["required"]) == {"src", "confidence"}      # 나머지는 전부 생략 가능
    assert "line_no" not in item["properties"]                 # 병합 후 엔진이 매긴다


def test_lines_schema_wraps_only_the_lines_array():
    schema = build_lines_schema()
    assert set(schema["properties"]) == {"lines"}              # 헤더·합계는 다시 받지 않는다
    assert schema["required"] == ["lines"]


def test_extra_fields_land_in_both_namespaces():
    """extra 는 header 쪽(OUTLINE)과 line 쪽(LINES)에 각각 생긴다."""
    extra = [{"name": "contract_no", "description": "계약번호"}]
    header_extra = build_outline_schema(extra)["properties"]["header"]["properties"]["extra"]
    assert "contract_no" in header_extra["properties"]
    assert set(header_extra["properties"]["contract_no"]["properties"]) == VALUE_KEYS

    line_extra = (
        build_lines_schema(extra)["properties"]["lines"]["items"]["properties"]["extra"]
    )
    assert line_extra["properties"]["contract_no"]["type"] == "string"    # 평평한 스칼라


def test_no_extra_namespace_without_extra_fields():
    assert "extra" not in build_outline_schema()["properties"]["header"]["properties"]
    assert "extra" not in build_lines_schema()["properties"]["lines"]["items"]["properties"]


def test_tool_wrappers():
    outline = build_outline_tool(include_shipments=True)
    assert outline["name"] == OUTLINE_TOOL_NAME
    assert outline["input_schema"]["type"] == "object"

    lines = build_lines_tool()
    assert lines["name"] == LINES_TOOL_NAME
    assert lines["input_schema"]["type"] == "object"
    assert outline["name"] != lines["name"]


def test_single_tool_is_composed_from_the_two_builders():
    """단일 툴(스캔본용)은 새 키를 만들지 않고 두 빌더의 결과를 잇는다 (design §3.3.6)."""
    split = build_single_tool(None, include_shipments=True, src_required=True)["input_schema"]
    block = split["properties"]["shipments"]["items"]
    assert "lines" in block["properties"] and "lines" in block["required"]
    assert "line_range" not in split["properties"] and "lines" not in split["properties"]

    single = build_single_tool(None, include_shipments=False, src_required=True)["input_schema"]
    assert "lines" in single["properties"] and "lines" in single["required"]
    assert "line_range" not in single["properties"] and "shipments" not in single["properties"]


def _walk(node):
    """스키마의 모든 하위 노드."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_scan_tool_has_no_src_anywhere_and_asks_the_model_for_the_page():
    """스캔본은 줄 번호가 없다 — `src` 를 요구하면 모델이 지어낸다. 위치는 `page` 로 받는다."""
    tool = build_single_tool([{"name": "contract_no", "description": "d"}],
                             include_shipments=True)          # src_required 기본값 = 스캔본
    assert tool["name"] == SINGLE_TOOL_NAME
    schema = tool["input_schema"]

    for node in _walk(schema):
        props = node.get("properties") if isinstance(node, dict) else None
        if not isinstance(props, dict):
            continue
        assert "src" not in props and "src_end" not in props
        assert "src" not in node.get("required", []) and "src_end" not in node.get("required", [])
        if "confidence" in props:                              # 값 · 품목 = 근거를 갖는 자리
            assert "page" in props and "page" in node["required"]

    lines = schema["properties"]["shipments"]["items"]["properties"]["lines"]["items"]
    assert lines["required"] == ["confidence", "page"]
    assert "lines" in schema["properties"]["shipments"]["items"]["required"]


def test_text_tool_keeps_src_required_and_has_no_page():
    schema = build_single_tool(None, include_shipments=False, src_required=True)["input_schema"]
    item = schema["properties"]["lines"]["items"]
    assert "src" in item["required"] and "page" not in item["properties"]


def test_building_the_scan_tool_does_not_disturb_the_text_schemas():
    """스캔 변형은 복사본에서 만든다 — 텍스트용 스키마가 오염되면 앵커가 사라진다."""
    before = build_lines_schema()
    build_single_tool(None, include_shipments=True)
    assert build_lines_schema() == before
