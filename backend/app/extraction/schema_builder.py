"""LLM 구조화 출력 스키마 (Tool Use 입력 스키마) 생성.

Tool Use 로 출력을 강제하면 스키마를 벗어난 응답이 원천 차단된다.
모든 값은 {value, evidence, page, confidence} 4종 세트로 받는다 — evidence 가
있어야 환각을 코드로 검증할 수 있다.

**키 이름은 `masters/SCHEMA.md` §3.1 표준 키가 단일 원천이다.**
여기에 키를 추가·변경하기 전에 §3.1 을 먼저 고친다. 거꾸로 하지 않는다.
"""

from __future__ import annotations

from typing import Any

TOOL_NAME = "extract_purchase_order"


def _value_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "value": {
                "type": ["string", "null"],
                "description": "추출한 값. 찾지 못하면 null. 임의로 추측하지 말 것.",
            },
            "evidence": {
                "type": ["string", "null"],
                "description": (
                    "이 값의 근거가 된 원문 문자열을 **그대로 복사**. "
                    "요약·재작성 금지. 값을 찾지 못했으면 null."
                ),
            },
            "page": {"type": ["integer", "null"], "description": "근거가 있는 페이지 번호 (1부터)"},
            "confidence": {
                "type": ["number", "null"],
                "description": "확신도 0.0~1.0. 애매하면 낮게 줄 것.",
            },
        },
        "required": ["value", "evidence", "page", "confidence"],
    }


# ── SCHEMA.md §3.1 표준 키 ─────────────────────────────────────────────
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
    "packing_spec": "포장 지시 원문 (예: 'S-Y,B-Y'). 없으면 null",
    "remark_default": "특정 라인에 묶이지 않은 공통 비고 원문. 없으면 null",
}

_LINE_FIELDS: dict[str, str] = {
    "posex": (
        "발주서에 인쇄된 품목 번호 원문 (예: '00001'). "
        "인쇄된 번호가 없으면 null — 임의로 만들지 말 것"
    ),
    "our_item": "거래처(고객) 품번 — 고객사 자재번호",
    "item_code": "자사 품번 — 공급사(우리) 자재번호. 없으면 null",
    "description": "품명/규격",
    "quantity": "수량. 숫자만 (쉼표 제거). 예: '25' 또는 '25.000'",
    "unit": "단위 (EA, PCS 등)",
    "unit_price": "단가. 합계금액(Extended/Amount/Net Value)이 아니라 **단가**임에 주의",
    "net_value": "이 라인의 합계금액 (Net Value / Extended / Amount). 단가가 아님",
    "delivery_date": "이 품목의 납기일. 라인별 납기가 없으면 null. YYYY-MM-DD",
    "ship_to_text": "이 품목의 출하처가 헤더와 다를 경우에만 채울 것. 같으면 null",
    "brand_text": "이 품목의 브랜드 문구 원문. 라인별 브랜드가 없으면 null",
    "remark": "이 품목 전용 비고 원문 (예: '#1 QNCT stock'). 없으면 null",
}

_SHIPMENT_FIELDS: dict[str, str] = {
    "shipment_no": "출하 블록 번호 원문 (예: '001'). 없으면 null",
    "receiving_loc": "입고처 코드 원문 (예: 'ELK'). 없으면 null",
    "ship_to_text": (
        "이 출하 블록의 출하처 주소 블록 전체를 원문 그대로. "
        "창고명 줄을 반드시 포함할 것"
    ),
    "ship_by_text": "이 출하 블록의 출하 기한/방법 원문. 없으면 null",
    "remark": "이 출하 블록의 비고 원문. 없으면 null",
}

_LINES_DESCRIPTION = "품목 목록. 발주서의 모든 품목을 빠짐없이 포함할 것."

_SHIPMENTS_DESCRIPTION = (
    "출하처(Shipment) 블록 목록. **오더는 이 블록 단위로 나뉜다.**\n"
    "- 출하처가 하나뿐인 문서여도 반드시 1건을 만들 것.\n"
    "- 각 블록의 lines 에는 **그 블록에 딸린 품목표의 품목만** 담을 것.\n"
    "- 문서 상단의 전체 요약 품목표는 여기에 넣지 말고 최상위 lines 에 담을 것."
)


def _line_props(extra_props: dict[str, Any]) -> dict[str, Any]:
    props = {k: _value_schema(v) for k, v in _LINE_FIELDS.items()}
    props["line_no"] = {
        "type": "integer",
        "description": "품목 순번 (1부터, 발주서에 나타난 순서대로)",
    }
    if extra_props:
        props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드 (라인)",
            "properties": dict(extra_props),
        }
    return props


def _lines_schema(extra_props: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "items": {
            "type": "object",
            "properties": _line_props(extra_props),
            "required": ["line_no", *_LINE_FIELDS.keys()],
        },
    }


def build_tool_schema(
    extra_fields: list[dict[str, str]] | None = None,
    *,
    include_shipments: bool = False,
) -> dict[str, Any]:
    """Tool 스키마를 만든다.

    extra_fields      거래처별 추가 필드 (SCHEMA.md §4.2). header/line 양쪽에 생성된다.
    include_shipments `split.by` 가 none 이 아닐 때만 True.
                      분할하지 않는 거래처에 빈 블록을 물려 모델을 헷갈리게 하지 않는다.
    """
    header_props = {k: _value_schema(v) for k, v in _HEADER_FIELDS.items()}

    extra_props: dict[str, Any] = {}
    for f in extra_fields or []:
        extra_props[f["name"]] = _value_schema(f.get("description", f["name"]))

    if extra_props:
        header_props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드",
            "properties": dict(extra_props),
        }

    properties: dict[str, Any] = {
        "header": {
            "type": "object",
            "description": "발주서 헤더 정보",
            "properties": header_props,
            "required": list(_HEADER_FIELDS.keys()),
        },
        "lines": _lines_schema(extra_props, _LINES_DESCRIPTION),
    }
    required = ["header", "lines"]

    if include_shipments:
        properties["lines"] = _lines_schema(
            extra_props,
            "문서 상단의 전체 요약 품목표. 출하처별 품목은 여기가 아니라 "
            "shipments[].lines 에 담을 것. 요약표가 없으면 빈 배열.",
        )
        properties["shipments"] = {
            "type": "array",
            "description": _SHIPMENTS_DESCRIPTION,
            "items": {
                "type": "object",
                "properties": {
                    **{k: _value_schema(v) for k, v in _SHIPMENT_FIELDS.items()},
                    "lines": _lines_schema(
                        extra_props, "이 출하 블록에 딸린 품목표의 품목"
                    ),
                },
                "required": [*_SHIPMENT_FIELDS.keys(), "lines"],
            },
        }
        required.append("shipments")

    properties["totals"] = {
        "type": "object",
        "description": "발주서에 인쇄된 합계 (라인 누락 검증에 사용)",
        "properties": {
            "line_count": {"type": ["integer", "null"], "description": "총 품목 수"},
            "total_qty": {"type": ["string", "null"], "description": "총 수량"},
            "total_amount": {"type": ["string", "null"], "description": "총 금액"},
        },
        "required": ["line_count", "total_qty", "total_amount"],
    }
    properties["notes"] = {
        "type": "array",
        "description": "특이사항 (수기 메모, 판독 불가 영역 등)",
        "items": {"type": "string"},
    }
    required += ["totals", "notes"]

    return {"type": "object", "properties": properties, "required": required}


def build_tool(
    extra_fields: list[dict[str, str]] | None = None,
    *,
    include_shipments: bool = False,
) -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "발주서에서 추출한 정보를 구조화해 반환한다.",
        "input_schema": build_tool_schema(
            extra_fields, include_shipments=include_shipments
        ),
    }
