"""환각 차단 장치.

LLM 파싱을 업무에 쓰려면 "그럴듯하지만 틀린 값"을 코드로 걸러야 한다.
사람 검수가 최종 안전망이지만, 그 앞에 자동 방어선을 세 겹 둔다 (design.md §3.4).

  1) 앵커 대조    : 모델이 준 **줄 번호(`src`)의 원문**에 그 값이 실제로 있는가
  2) 합계 교차검증 : 발주서에 인쇄된 합계와 추출 결과가 산술적으로 맞는가
  3) 신뢰도 임계   : 모델이 스스로 낮게 매긴 값을 사람에게 올린다

앵커 대조의 판정 순서(사다리)는 `anchor.py` 에 있다. 이 모듈은 그 결과를 이슈로 올린다.

  ① `src` 없음·문서 범위 밖                        🔴 EVIDENCE_NOT_FOUND
  ② 청크 응답인데 그 청크 구간 밖                   🔴 EVIDENCE_NOT_FOUND
  ③ `src` 줄에서 값을 못 찾음(MISS) / 비슷하게만(FUZZY)  🔴 / 🟡 EVIDENCE_WEAK
  ④ 품번 백스톱 — 앵커를 통과해도 문서 전체에 없으면       🔴 EVIDENCE_NOT_FOUND
  ⑤ 신뢰도 임계

스캔본(텍스트 레이어 없음)은 대조할 원문이 없어 ①~④ 를 건너뛴다.

**`GroundingIssue.field` 의 경로 표기는 바꾸지 않는다.** `batch_service.py` 가 그 문자열을
정규식으로 읽어 행에 배분한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..domain.models import ExtractedValue, GroundingIssue, IssueCode, RawPO
from .anchor import AnchorResult, locate
from .preprocess import SourceDoc, normalize_ws

# 필수 필드는 신뢰도 기준을 더 엄격하게 본다
_REQUIRED_PATHS = {"header.po_number", "quantity", "item_code", "our_item"}

_CONF_WARN = 0.9
_CONF_ERROR = 0.7

# 품번 백스톱 대상 — 값을 지어내는 사고가 가장 비싼 자리다 (design.md §3.4)
_PART_LEAVES = {"item_code", "our_item"}
_PART_MIN_ALNUM = 4


@dataclass
class _Ctx:
    doc: SourceDoc
    check_anchor: bool
    full_text: str                              # normalize_ws + lower — 품번 백스톱용
    allowed_range: tuple[int, int] | None       # 청크 응답이면 그 구간 (양끝 포함)


def verify(
    raw: RawPO,
    doc: SourceDoc,
    *,
    allowed_range: tuple[int, int] | None = None,
) -> list[GroundingIssue]:
    """`allowed_range` 는 **청크 응답을 검증할 때** 그 청크의 줄 구간이다.

    `src` 가 구간 밖이면 🔴 — 프롬프트가 "구간 밖을 참조하지 말 것"을 지시했는데도
    벗어난 것이므로 그 값은 믿을 수 없다. 청크 호출자는 다음 단계에서 붙인다.
    """
    # 스캔본(텍스트 레이어 없음)은 대조할 원문이 없으므로 앵커 검증을 건너뛴다.
    check_anchor = doc.has_text_layer
    ctx = _Ctx(
        doc=doc,
        check_anchor=check_anchor,
        full_text=normalize_ws(doc.full_text).lower() if check_anchor else "",
        allowed_range=allowed_range,
    )
    issues: list[GroundingIssue] = []

    for name, val in _iter_header(raw):
        issues += _check_value(f"header.{name}", val, ctx)

    for idx, line in enumerate(raw.lines, start=1):
        for name, val in _iter_line(line):
            issues += _check_value(f"lines[{idx}].{name}", val, ctx)

    for s_idx, shipment in enumerate(raw.shipments, start=1):
        prefix = f"shipments[{s_idx}]"
        for name, val in _iter_shipment(shipment):
            issues += _check_value(f"{prefix}.{name}", val, ctx)
        for idx, line in enumerate(shipment.lines, start=1):
            for name, val in _iter_line(line):
                issues += _check_value(f"{prefix}.lines[{idx}].{name}", val, ctx)

    issues += _check_totals(raw)

    if not raw.all_lines:
        issues.append(
            GroundingIssue(
                level="error",
                field="lines",
                code=IssueCode.NO_LINES,
                message="품목을 하나도 추출하지 못했습니다. 발주서 양식을 확인하세요.",
            )
        )

    for s_idx, shipment in enumerate(raw.shipments, start=1):
        if not shipment.lines:
            issues.append(
                GroundingIssue(
                    level="error",
                    field=f"shipments[{s_idx}].lines",
                    code=IssueCode.NO_LINES,
                    message=(
                        f"{s_idx}번 출하처 블록에서 품목을 하나도 추출하지 못했습니다. "
                        "블록 전용 품목표를 찾지 못했을 수 있습니다."
                    ),
                )
            )

    return issues


# ── 개별 값 검증 ───────────────────────────────────────────────────────
def _check_value(path: str, val: ExtractedValue, ctx: _Ctx) -> list[GroundingIssue]:
    if val is None or val.is_empty():
        return []

    out: list[GroundingIssue] = []
    leaf = path.split(".")[-1]
    is_required = leaf in _REQUIRED_PATHS or path in _REQUIRED_PATHS

    if ctx.check_anchor:
        out += _check_anchor(path, leaf, val, ctx)

    # 5) 신뢰도 임계
    conf = val.confidence
    if conf is not None:
        if is_required and conf < _CONF_ERROR:
            out.append(
                GroundingIssue(
                    level="error",
                    field=path,
                    code=IssueCode.LOW_CONFIDENCE,
                    message=f"판독 신뢰도가 낮습니다 ({conf:.2f}). 확인이 필요합니다.",
                )
            )
        elif conf < _CONF_WARN:
            out.append(
                GroundingIssue(
                    level="warn",
                    field=path,
                    code=IssueCode.LOW_CONFIDENCE,
                    message=f"판독 신뢰도가 낮습니다 ({conf:.2f}).",
                )
            )

    return out


def _check_anchor(
    path: str, leaf: str, val: ExtractedValue, ctx: _Ctx
) -> list[GroundingIssue]:
    """①~④ — 앵커 존재 · 청크 구간 · 줄 대조 · 품번 백스톱."""
    doc = ctx.doc
    src = val.src
    end = val.src_end if val.src_end is not None else src

    def error(message: str) -> list[GroundingIssue]:
        return [GroundingIssue(
            level="error", field=path, code=IssueCode.EVIDENCE_NOT_FOUND, message=message
        )]

    # ① 앵커 존재 — 없거나 문서 밖이면 그 자체로 환각이 확정된다 (검사는 공짜다)
    if src is None or end is None or not (1 <= src <= end <= doc.line_count):
        return error(
            f"근거 줄 번호(src)가 없거나 문서 범위 밖입니다 (값: {val.value}). "
            "잘못 읽었을 수 있으니 반드시 확인하세요."
        )

    # ② 청크 응답이면 그 청크 구간 밖의 줄을 가리킬 수 없다
    if ctx.allowed_range is not None:
        lo, hi = ctx.allowed_range
        if src < lo or end > hi:
            return error(
                f"근거 줄({src})이 읽기로 지정된 구간({lo}~{hi}) 밖입니다 (값: {val.value}). "
                "잘못 읽었을 수 있으니 반드시 확인하세요."
            )

    out: list[GroundingIssue] = []

    # ③ 앵커 대조 — 그 줄의 원문에서 값을 찾는다
    verdict = locate(val.value, doc.slice_text(src, end))
    if verdict is AnchorResult.MISS:
        return error(
            f"근거 줄({src})에서 값을 찾지 못했습니다 (값: {val.value}). "
            "잘못 읽었을 수 있으니 반드시 확인하세요."
        )
    weak = verdict is AnchorResult.FUZZY
    if weak:
        out.append(GroundingIssue(
            level="warn",
            field=path,
            code=IssueCode.EVIDENCE_WEAK,
            message=(
                f"근거 줄({src})에 비슷한 표기만 있습니다 (값: {val.value}). "
                "원문과 대조하세요."
            ),
        ))

    # ④ 품번 백스톱 — 앵커를 통과했어도 문서 전체에 없는 품번은 지어낸 것이다
    if leaf in _PART_LEAVES:
        code = normalize_ws(val.value or "")
        if (
            sum(ch.isalnum() and ch.isascii() for ch in code) >= _PART_MIN_ALNUM
            and code.lower() not in ctx.full_text
        ):
            # 경고(비슷함)와 오류(문서에 없음)를 겹쳐 두지 않는다 — 오류 하나로 충분하다.
            return error(
                f"품번이 문서 어디에도 없습니다 (값: {val.value}). "
                "지어낸 값일 수 있으니 반드시 확인하세요."
            )

    return out


# ── 2) 합계 교차검증 ───────────────────────────────────────────────────
def _check_totals(raw: RawPO) -> list[GroundingIssue]:
    out: list[GroundingIssue] = []
    totals = raw.totals

    lines = raw.all_lines

    if totals.line_count is not None and totals.line_count != len(lines):
        out.append(
            GroundingIssue(
                level="error",
                field="totals.line_count",
                code=IssueCode.TOTAL_MISMATCH,
                message=(
                    f"발주서에 적힌 품목 수({totals.line_count})와 "
                    f"추출한 품목 수({len(lines)})가 다릅니다. 라인 누락 가능성이 있습니다."
                ),
            )
        )

    stated = _to_decimal(totals.total_qty)
    if stated is not None:
        extracted = Decimal(0)
        ok = True
        for line in lines:
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
                    code=IssueCode.TOTAL_MISMATCH,
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
_HEADER_KEYS = (
    "po_number", "po_date", "requested_date", "brand_text", "order_text",
    "ship_to_text", "bill_to_text", "currency_text", "incoterms_text",
    "payment_terms_text", "packing_spec", "remark_default",
)

_SHIPMENT_KEYS = (
    "shipment_no", "receiving_loc", "ship_to_text", "ship_by_text", "remark",
)

_LINE_KEYS = (
    "posex", "our_item", "item_code", "description", "quantity", "unit",
    "unit_price", "net_value", "delivery_date", "ship_to_text", "brand_text",
    "remark",
)


def _iter_header(raw: RawPO):
    h = raw.header
    for name in _HEADER_KEYS:
        yield name, getattr(h, name)
    for name, val in (h.extra or {}).items():
        yield f"extra.{name}", val


def _iter_shipment(shipment):
    for name in _SHIPMENT_KEYS:
        yield name, getattr(shipment, name)


def _iter_line(line):
    for name in _LINE_KEYS:
        yield name, getattr(line, name)
    for name, val in (line.extra or {}).items():
        yield f"extra.{name}", val
