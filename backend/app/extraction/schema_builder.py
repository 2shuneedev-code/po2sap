"""LLM 구조화 출력 스키마 (Tool Use 입력 스키마) 생성.

Tool Use 로 출력을 강제하면 스키마를 벗어난 응답이 원천 차단된다.
툴은 **패스마다 둘로 나뉜다** (design.md §3.3.2).

  OUTLINE  header · shipments[] (또는 line_range) · totals · notes.  품목은 받지 않는다.
  LINES    구간 하나의 품목만.  헤더·합계는 다시 받지 않는다.
  SINGLE   문서 1건을 한 번에. **스캔본(텍스트 레이어 없음) 전용** — 줄 번호가 없어 나눌 수 없다
           (design.md §3.3.6). `src` 대신 모델이 `page` 를 준다.

**값의 포장은 `masters/SCHEMA.md` §3.2 가 단일 원천이다.**
  · header · shipment 값 : `{value, src, src_end?, confidence}` — 값마다 따로
  · line(품목)           : 평평한 스칼라 + 줄 단위 `src`·`confidence` 1개
  · 없는 필드는 **키를 생략**한다 (null 을 채우지 않는다) — 출력 토큰을 줄이는 핵심이다
  · `line_no` 는 받지 않는다 (병합 후 엔진이 매긴다, §2.1-6)

**키 이름은 `masters/SCHEMA.md` §3.1 표준 키가 단일 원천이다.**
여기에 키를 추가·변경하기 전에 §3.1 을 먼저 고친다. 거꾸로 하지 않는다.
"""

from __future__ import annotations

import copy
from typing import Any

OUTLINE_TOOL_NAME = "outline_purchase_order"
LINES_TOOL_NAME = "extract_lines"
SINGLE_TOOL_NAME = "extract_purchase_order"

# 앵커·신뢰도 키. 표준 키(§3.1)가 아니라 **포장**이므로 키 목록 비교에서 뺀다.
ANCHOR_KEYS = frozenset({"src", "src_end", "confidence"})

_SRC = {
    "type": "integer",
    "minimum": 1,
    "description": (
        "근거가 있는 원문 줄 번호. 각 줄 앞의 `L000123|` 의 숫자를 **그대로 복사**할 것. "
        "직접 세지 말 것."
    ),
}
_SRC_END = {
    "type": "integer",
    "minimum": 1,
    "description": "값이 여러 줄에 걸칠 때만 마지막 줄 번호 (주소 블록 등). 한 줄이면 생략.",
}
_CONFIDENCE = {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "확신도 0.0~1.0. 애매하면 낮게 줄 것.",
}


def _value_schema(description: str) -> dict[str, Any]:
    """header · shipment 값 1개 — SCHEMA.md §3.2(가)."""
    return {
        "type": "object",
        "description": description,
        "properties": {
            "value": {
                "type": "string",
                "description": "추출한 값. 임의로 추측하지 말 것.",
            },
            "src": _SRC,
            "src_end": _SRC_END,
            "confidence": _CONFIDENCE,
        },
        "required": ["value", "src", "confidence"],
    }


# ── SCHEMA.md §3.1 표준 키 ─────────────────────────────────────────────
# 설명 끝의 "없으면 생략" 은 **그 키를 응답에서 빼라**는 뜻이다 (null 을 넣지 않는다).
_HEADER_FIELDS: dict[str, str] = {
    "po_number": (
        "거래처 발주번호. 문서가 'Purchase Order ID' 등 다른 이름을 쓰더라도 "
        "발주를 식별하는 번호를 여기에 담을 것"
    ),
    "po_date": "발주일. YYYY-MM-DD 형식으로 변환해서 넣을 것",
    "requested_date": "납품요청일/납기일 (문서 전체 기준). YYYY-MM-DD 형식",
    "brand_text": "발주서에 표기된 브랜드 문구 원문 (코드로 변환하지 말 것)",
    "order_text": (
        "브랜드·특기사항이 적힌 원문 블록. 헤더 부근의 설명 텍스트를 "
        "그대로 담을 것 (브랜드 키워드 탐색에 사용)"
    ),
    "ship_to_text": "출하처(Ship To) 주소 블록 전체를 원문 그대로",
    "bill_to_text": "청구처(Bill To) 주소 블록 전체를 원문 그대로",
    "currency_text": "통화 표기 원문 (USD, JPY, 'United States Dollars' 등)",
    "incoterms_text": "인도조건 원문 (FCA, FOB, EXW 등)",
    "payment_terms_text": "지급조건 원문 (NET 30 등)",
    "packing_spec": "포장 지시 원문 (예: 'S-Y,B-Y'). 없으면 생략",
    "remark_default": "특정 라인에 묶이지 않은 공통 비고 원문. 없으면 생략",
}

_LINE_FIELDS: dict[str, str] = {
    "posex": (
        "발주서에 인쇄된 품목 번호 원문 (예: '00001'). "
        "인쇄된 번호가 없으면 생략 — 임의로 만들지 말 것"
    ),
    "our_item": "거래처(고객) 품번 — 고객사 자재번호",
    "item_code": "자사 품번 — 공급사(우리) 자재번호. 없으면 생략",
    "description": "품명/규격",
    "quantity": "수량. 숫자만 (쉼표 제거). 예: '25' 또는 '25.000'",
    "unit": "단위 (EA, PCS 등)",
    "unit_price": "단가. 합계금액(Extended/Amount/Net Value)이 아니라 **단가**임에 주의",
    "net_value": "이 라인의 합계금액 (Net Value / Extended / Amount). 단가가 아님",
    "delivery_date": "이 품목의 납기일. 라인별 납기가 없으면 생략. YYYY-MM-DD",
    "ship_to_text": "이 품목의 출하처가 헤더와 다를 경우에만 채울 것. 같으면 생략",
    "brand_text": "이 품목의 브랜드 문구 원문. 라인별 브랜드가 없으면 생략",
    "remark": "이 품목 전용 비고 원문 (예: '#1 QNCT stock'). 없으면 생략",
}

_SHIPMENT_FIELDS: dict[str, str] = {
    "shipment_no": "출하 블록 번호 원문 (예: '001'). 없으면 생략",
    "receiving_loc": "입고처 코드 원문 (예: 'ELK'). 없으면 생략",
    "ship_to_text": (
        "이 출하 블록의 출하처 주소 블록 전체를 원문 그대로. "
        "창고명 줄을 반드시 포함할 것"
    ),
    "ship_by_text": "이 출하 블록의 출하 기한/방법 원문. 없으면 생략",
    "remark": "이 출하 블록의 비고 원문. 없으면 생략",
}

_SHIPMENTS_DESCRIPTION = (
    "출하처(Shipment) 블록 목록. **오더는 이 블록 단위로 나뉜다.**\n"
    "- 출하처가 하나뿐인 문서여도 반드시 1건을 만들 것.\n"
    "- 각 블록의 src·src_end 는 **그 블록의 품목표까지 포함한 구간**이다. "
    "블록끼리 겹치지 않게, 빠진 줄이 없게 이어 붙일 것.\n"
    "- 품목은 여기서 읽지 않는다. 문서 상단의 전체 요약 품목표도 읽지 않는다."
)

_LINE_RANGE_DESCRIPTION = (
    "품목표가 있는 구간. src 는 첫 품목 줄(또는 표 머리글), src_end 는 마지막 품목 줄. "
    "품목은 여기서 읽지 않는다."
)


def _range_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {"src": _SRC, "src_end": _SRC_END},
        "required": ["src", "src_end"],
    }


def _extra_value_props(extra_fields: list[dict[str, str]] | None) -> dict[str, Any]:
    return {f["name"]: _value_schema(f.get("description", f["name"])) for f in extra_fields or []}


# ── OUTLINE ────────────────────────────────────────────────────────────
def build_outline_schema(
    extra_fields: list[dict[str, str]] | None = None,
    *,
    include_shipments: bool = False,
) -> dict[str, Any]:
    """OUTLINE 툴 스키마. **품목은 1줄도 받지 않는다** (design.md §3.3.2).

    extra_fields      거래처별 추가 필드 (SCHEMA.md §4.2). header 에 생성된다.
                      line 쪽은 `build_lines_schema` 가 만든다.
    include_shipments `split.by` 가 none 이 아닐 때만 True. True 면 블록마다
                      `src`~`src_end`(품목표 포함 구간)를 받고, False 면
                      `line_range` 하나를 받는다. 두 경우 모두 이 구간이 청크 경계가 된다.
    """
    header_props: dict[str, Any] = {k: _value_schema(v) for k, v in _HEADER_FIELDS.items()}
    extra_props = _extra_value_props(extra_fields)
    if extra_props:
        header_props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드",
            "properties": extra_props,
        }

    properties: dict[str, Any] = {
        "header": {
            "type": "object",
            "description": "발주서 헤더 정보. 원문에 없는 필드는 키를 생략할 것.",
            "properties": header_props,
        },
    }
    required = ["header"]

    if include_shipments:
        properties["shipments"] = {
            "type": "array",
            "description": _SHIPMENTS_DESCRIPTION,
            "items": {
                "type": "object",
                "properties": {
                    **{k: _value_schema(v) for k, v in _SHIPMENT_FIELDS.items()},
                    "src": {**_SRC, "description": "블록의 첫 줄 번호 (`L000123|` 의 숫자 복사)"},
                    "src_end": {**_SRC, "description": "블록의 마지막 줄 번호 (품목표 끝까지)"},
                },
                "required": ["src", "src_end"],
            },
        }
        required.append("shipments")
    else:
        properties["line_range"] = _range_schema(_LINE_RANGE_DESCRIPTION)
        required.append("line_range")

    properties["totals"] = {
        "type": "object",
        "description": "발주서에 인쇄된 합계 (라인 누락 검증에 사용). 인쇄돼 있지 않으면 키를 생략.",
        "properties": {
            "line_count": {"type": "integer", "description": "총 품목 수"},
            "total_qty": {"type": "string", "description": "총 수량"},
            "total_amount": {"type": "string", "description": "총 금액"},
        },
    }
    properties["notes"] = {
        "type": "array",
        "description": "특이사항 (수기 메모, 판독 불가 영역 등). 없으면 생략.",
        "items": {"type": "string"},
    }
    required.append("totals")

    return {"type": "object", "properties": properties, "required": required}


def build_outline_tool(
    extra_fields: list[dict[str, str]] | None = None,
    *,
    include_shipments: bool = False,
) -> dict[str, Any]:
    return {
        "name": OUTLINE_TOOL_NAME,
        "description": (
            "발주서의 골격을 반환한다: 헤더, 출하처 블록(또는 품목표 구간), 합계. "
            "품목은 반환하지 않는다."
        ),
        "input_schema": build_outline_schema(extra_fields, include_shipments=include_shipments),
    }


# ── LINES ──────────────────────────────────────────────────────────────
def build_lines_schema(extra_fields: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """LINES 툴 스키마. 품목은 **평평한 스칼라 + 줄 단위 앵커 1개** (SCHEMA.md §3.2-나).

    필수는 `src`·`confidence` 둘뿐이다. 없는 필드는 키를 생략한다 — 빈 필드 하나가
    네 줄의 null 이 되던 것이 0줄이 된다. `line_no` 는 받지 않는다.
    """
    item_props: dict[str, Any] = {
        "src": {**_SRC, "description": _SRC["description"].replace("근거가 있는", "이 품목이 있는")},
        "src_end": {**_SRC_END, "description": "품목이 두 줄 이상에 걸칠 때만 마지막 줄 번호"},
        "confidence": _CONFIDENCE,
        **{k: {"type": "string", "description": v} for k, v in _LINE_FIELDS.items()},
    }
    if extra_fields:
        item_props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드 (라인). 없는 것은 키를 생략.",
            "properties": {
                f["name"]: {"type": "string", "description": f.get("description", f["name"])}
                for f in extra_fields
            },
        }

    return {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "description": (
                    "이 구간의 모든 품목을 빠짐없이. 구간에 품목이 없으면 빈 배열. "
                    "구간 밖의 줄은 참조하지 말 것."
                ),
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": ["src", "confidence"],
                },
            },
        },
        "required": ["lines"],
    }


def build_lines_tool(extra_fields: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "name": LINES_TOOL_NAME,
        "description": "주어진 구간의 품목을 구조화해 반환한다. 헤더·합계는 반환하지 않는다.",
        "input_schema": build_lines_schema(extra_fields),
    }


# ── SINGLE — 스캔본 (design.md §3.3.6) ────────────────────────────────
_PAGE = {
    "type": "integer",
    "minimum": 1,
    "description": (
        "이 값이 있는 **PDF 페이지 번호**(1부터). 이 문서에는 줄 번호가 없으므로 "
        "줄 번호 대신 페이지로 위치를 알려 줄 것."
    ),
}


def build_single_tool(
    extra_fields: list[dict[str, str]] | None = None,
    *,
    include_shipments: bool = False,
    src_required: bool = False,
) -> dict[str, Any]:
    """문서 1건을 한 번에 읽는 툴 — OUTLINE 과 LINES 를 한 스키마로 합친 것이다.

    새 키를 만들지 않는다. 두 빌더가 만든 스키마를 **그대로** 이어 붙일 뿐이라 스키마의
    원천은 계속 이 모듈의 두 빌더 하나다.

    src_required  True 면 줄 번호(`src`)가 필수인 텍스트 문서용이다 (앵커 대조를 쓴다).
                  False(기본)면 **스캔본용**이다 — 줄 번호가 존재하지 않으므로 `src`·`src_end`
                  를 스키마에서 빼고, 그 자리에 `page` 를 넣어 **모델이** 페이지를 알려 준다.
                  §3.1 의 "페이지는 코드가 계산한다"에 대한 명시적 예외다 (§3.3.6).
    """
    outline = build_outline_schema(extra_fields, include_shipments=include_shipments)
    lines = build_lines_schema(extra_fields)["properties"]["lines"]

    props = dict(outline["properties"])
    required = [r for r in outline["required"] if r != "line_range"]
    props.pop("line_range", None)

    if include_shipments:
        block = props["shipments"]["items"]
        block["properties"] = {**block["properties"], "lines": lines}
        block["required"] = [*block["required"], "lines"]
    else:
        props["lines"] = lines
        required.append("lines")

    schema: dict[str, Any] = {"type": "object", "properties": props, "required": required}
    if not src_required:
        schema = _to_page_anchor(copy.deepcopy(schema))

    return {
        "name": SINGLE_TOOL_NAME,
        "description": "발주서에서 추출한 정보를 구조화해 반환한다.",
        "input_schema": schema,
    }


def _to_page_anchor(node: Any) -> Any:
    """`src`·`src_end` 를 걷어내고, 값·품목(=`confidence` 가 있는 객체)에는 `page` 를 넣는다.

    출하처 블록의 `src`~`src_end` 는 청크 경계용이라 그냥 빠진다 — 스캔본은 나누지 않는다.
    """
    if isinstance(node, list):
        return [_to_page_anchor(n) for n in node]
    if not isinstance(node, dict):
        return node

    out = {k: _to_page_anchor(v) for k, v in node.items()}
    props = out.get("properties")
    if isinstance(props, dict) and "src" in props:
        anchored_value = "confidence" in props
        props.pop("src", None)
        props.pop("src_end", None)
        required = [r for r in out.get("required", []) if r not in ("src", "src_end")]
        if anchored_value:
            props["page"] = dict(_PAGE)
            required.append("page")
        out["required"] = required
    return out
