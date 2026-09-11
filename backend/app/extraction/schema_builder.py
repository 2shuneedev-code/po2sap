"""LLM 구조화 출력 스키마 (Tool Use 입력 스키마) 생성.

Tool Use 로 출력을 강제하면 스키마를 벗어난 응답이 원천 차단된다.
모든 값은 {value, evidence, page, confidence} 4종 세트로 받는다 — evidence 가
있어야 환각을 코드로 검증할 수 있다.
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


_HEADER_FIELDS: dict[str, str] = {
    "po_number": "고객 발주번호 (Purchase Order No.)",
    "po_date": "발주일. YYYYMMDD(구분자 없는 8자리 숫자 문자열)로 변환해서 넣을 것",
    "requested_date": "납품요청일/납기일. YYYYMMDD(구분자 없는 8자리 숫자 문자열)로 변환해서 넣을 것",
    "ship_to_text": "출하처(Ship To) 주소 블록 전체를 원문 그대로",
    "bill_to_text": "청구처(Bill To) 주소 블록 전체를 원문 그대로",
    "brand_text": "발주서에 표기된 브랜드 문구 원문 (코드로 변환하지 말 것)",
    "incoterms": "인도조건 (FCA, FOB, EXW 등)",
    "payment_terms": "지급조건 (NET 30 등)",
    "currency": "통화 코드 (USD, JPY, KRW 등)",
    "order_text": (
        "브랜드·특기사항이 적힌 원문 블록. 헤더 부근의 설명 텍스트를 "
        "그대로 담을 것 (브랜드 키워드 탐색에 사용)"
    ),
}

_LINE_FIELDS: dict[str, str] = {
    "our_item": "거래처(고객) 품번 — 고객사 자재번호",
    "item_code": "자사 품번 — 공급사(우리) 자재번호. 없으면 null",
    "description": "품명/규격",
    "quantity": "수량. 숫자만 (쉼표 제거). 예: '25' 또는 '25.000'",
    "unit": "단위 (EA, PCS 등)",
    "unit_price": "단가. 합계금액(Extended/Amount)이 아니라 **단가**임에 주의",
    "req_date": "이 품목의 납기일. 라인별 납기가 없으면 null. YYYYMMDD(구분자 없는 8자리 숫자 문자열)로 변환해서 넣을 것",
    "ship_to_text": "이 품목의 출하처가 헤더와 다를 경우에만 채울 것. 같으면 null",
    "brand_text": "이 품목의 브랜드 문구 원문. 라인별 브랜드가 없으면 null",
}


def build_tool_schema(extra_fields: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """거래처별 추가 필드(extra_fields)를 병합한 Tool 스키마를 만든다."""
    header_props = {k: _value_schema(v) for k, v in _HEADER_FIELDS.items()}
    line_props = {k: _value_schema(v) for k, v in _LINE_FIELDS.items()}
    line_props["line_no"] = {
        "type": "integer",
        "description": "품목 순번 (1부터, 발주서에 나타난 순서대로)",
    }

    extra_props: dict[str, Any] = {}
    for f in extra_fields or []:
        extra_props[f["name"]] = _value_schema(f.get("description", f["name"]))

    if extra_props:
        header_props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드",
            "properties": dict(extra_props),
        }
        line_props["extra"] = {
            "type": "object",
            "description": "거래처 고유 추가 필드 (라인)",
            "properties": dict(extra_props),
        }

    return {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "description": "발주서 헤더 정보",
                "properties": header_props,
                "required": list(_HEADER_FIELDS.keys()),
            },
            "lines": {
                "type": "array",
                "description": "품목 목록. 발주서의 모든 품목을 빠짐없이 포함할 것.",
                "items": {
                    "type": "object",
                    "properties": line_props,
                    "required": ["line_no", *_LINE_FIELDS.keys()],
                },
            },
            "totals": {
                "type": "object",
                "description": "발주서에 인쇄된 합계 (라인 누락 검증에 사용)",
                "properties": {
                    "line_count": {"type": ["integer", "null"], "description": "총 품목 수"},
                    "total_qty": {"type": ["string", "null"], "description": "총 수량"},
                    "total_amount": {"type": ["string", "null"], "description": "총 금액"},
                },
                "required": ["line_count", "total_qty", "total_amount"],
            },
            "notes": {
                "type": "array",
                "description": "특이사항 (수기 메모, 판독 불가 영역 등)",
                "items": {"type": "string"},
            },
        },
        "required": ["header", "lines", "totals", "notes"],
    }


def build_tool(extra_fields: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "발주서에서 추출한 정보를 구조화해 반환한다.",
        "input_schema": build_tool_schema(extra_fields),
    }
