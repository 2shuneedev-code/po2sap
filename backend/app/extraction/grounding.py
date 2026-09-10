"""환각 차단 장치.

LLM 파싱을 업무에 쓰려면 "그럴듯하지만 틀린 값"을 코드로 걸러야 한다.
사람 검수가 최종 안전망이지만, 그 앞에 자동 방어선을 세 겹 둔다.

  1) 근거 그라운딩 : evidence 문자열이 실제 원문에 존재하는가
  2) 합계 교차검증 : 발주서에 인쇄된 합계와 추출 결과가 산술적으로 맞는가
  3) 신뢰도 임계   : 모델이 스스로 낮게 매긴 값을 사람에게 올린다
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..domain.models import ExtractedValue, GroundingIssue, RawPO
from .preprocess import SourceDoc, normalize_ws

# 필수 필드는 신뢰도 기준을 더 엄격하게 본다
_REQUIRED_PATHS = {"header.po_number", "quantity", "item_code", "our_item"}

_CONF_WARN = 0.9
_CONF_ERROR = 0.7

# 근거 문자열이 이보다 짧으면 우연히 일치할 수 있어 검증에서 제외
_MIN_EVIDENCE_LEN = 4


def verify(raw: RawPO, doc: SourceDoc) -> list[GroundingIssue]:
    issues: list[GroundingIssue] = []

    # 스캔본(텍스트 레이어 없음)은 대조할 원문이 없으므로 근거 검증을 건너뛴다.
    check_evidence = doc.has_text_layer
    haystack = normalize_ws(doc.full_text).lower() if check_evidence else ""

    for name, val in _iter_header(raw):
        issues += _check_value(f"header.{name}", val, haystack, check_evidence)

    for idx, line in enumerate(raw.lines, start=1):
        for name, val in _iter_line(line):
            issues += _check_value(f"lines[{idx}].{name}", val, haystack, check_evidence)

    issues += _check_totals(raw)

    if not raw.lines:
        issues.append(
            GroundingIssue(
                level="error",
                field="lines",
                code="NO_LINES",
                message="품목을 하나도 추출하지 못했습니다. 발주서 양식을 확인하세요.",
            )
        )

    return issues


# ── 개별 값 검증 ───────────────────────────────────────────────────────
def _check_value(
    path: str, val: ExtractedValue, haystack: str, check_evidence: bool
) -> list[GroundingIssue]:
    if val is None or val.is_empty():
        return []

    out: list[GroundingIssue] = []
    leaf = path.split(".")[-1]
    is_required = leaf in _REQUIRED_PATHS or path in _REQUIRED_PATHS

    # 1) 근거 그라운딩
    if check_evidence:
        ev = normalize_ws(val.evidence or "")
        if not ev:
            out.append(
                GroundingIssue(
                    level="warn",
                    field=path,
                    code="NO_EVIDENCE",
                    message=f"근거가 제시되지 않았습니다 (값: {val.value}). 원문과 대조하세요.",
                )
            )
        elif len(ev) >= _MIN_EVIDENCE_LEN and ev.lower() not in haystack:
            out.append(
                GroundingIssue(
                    level="error",
                    field=path,
                    code="EVIDENCE_NOT_FOUND",
                    message=(
                        f"근거를 원문에서 찾지 못했습니다 (값: {val.value}). "
                        "잘못 읽었을 수 있으니 반드시 확인하세요."
                    ),
                )
            )

    # 3) 신뢰도 임계
    conf = val.confidence
    if conf is not None:
        if is_required and conf < _CONF_ERROR:
            out.append(
                GroundingIssue(
                    level="error",
                    field=path,
                    code="LOW_CONFIDENCE",
                    message=f"판독 신뢰도가 낮습니다 ({conf:.2f}). 확인이 필요합니다.",
                )
            )
        elif conf < _CONF_WARN:
            out.append(
                GroundingIssue(
                    level="warn",
                    field=path,
                    code="LOW_CONFIDENCE",
                    message=f"판독 신뢰도가 낮습니다 ({conf:.2f}).",
                )
            )

    return out


# ── 2) 합계 교차검증 ───────────────────────────────────────────────────
def _check_totals(raw: RawPO) -> list[GroundingIssue]:
    out: list[GroundingIssue] = []
    totals = raw.totals

    if totals.line_count is not None and totals.line_count != len(raw.lines):
        out.append(
            GroundingIssue(
                level="error",
                field="totals.line_count",
                code="TOTAL_MISMATCH",
                message=(
                    f"발주서에 적힌 품목 수({totals.line_count})와 "
                    f"추출한 품목 수({len(raw.lines)})가 다릅니다. 라인 누락 가능성이 있습니다."
                ),
            )
        )

    stated = _to_decimal(totals.total_qty)
    if stated is not None:
        extracted = Decimal(0)
        ok = True
        for line in raw.lines:
            q = _to_decimal(line.quantity.value)
            if q is None:
                ok = False
                break
            extracted += q
        if ok and stated != extracted:
            out.append(
                GroundingIssue(
                    level="error",
                    field="totals.total_qty",
                    code="TOTAL_MISMATCH",
                    message=(
                        f"발주서 총 수량({stated})과 추출 합계({extracted})가 다릅니다. "
                        "라인 누락 또는 수량 오독 가능성이 있습니다."
                    ),
                )
            )

    return out


def _to_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(text))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ── 순회 헬퍼 ──────────────────────────────────────────────────────────
def _iter_header(raw: RawPO):
    h = raw.header
    for name in (
        "po_number", "po_date", "requested_date", "ship_to_text", "bill_to_text",
        "brand_text", "incoterms", "payment_terms", "currency", "order_text",
    ):
        yield name, getattr(h, name)
    for name, val in (h.extra or {}).items():
        yield f"extra.{name}", val


def _iter_line(line):
    for name in (
        "our_item", "item_code", "description", "quantity", "unit",
        "unit_price", "req_date", "ship_to_text", "brand_text",
    ):
        yield name, getattr(line, name)
    for name, val in (line.extra or {}).items():
        yield f"extra.{name}", val
