"""파싱 결과 도메인 모델.

핵심 원칙(P1): 이 단계에는 **원문에서 읽은 값만** 담긴다.
SAP 코드(ZBRAND, KUNNR2, ZPKRE2 …)는 여기 없다. 규칙엔진이 다음 단계에서 결정한다.

필드 이름은 `masters/SCHEMA.md` §3.1 표준 키를 따른다. 키를 바꾸려면 §3.1 을 먼저 고친다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedValue(BaseModel):
    """LLM이 추출한 값 1개 + 근거.

    evidence 는 원문에서 그대로 복사한 문자열이어야 하며,
    grounding 검증에서 실제 원문에 존재하는지 대조한다(환각 차단).
    """

    value: str | None = None
    evidence: str | None = None
    page: int | None = None
    confidence: float | None = None

    def is_empty(self) -> bool:
        return self.value is None or str(self.value).strip() == ""


def _ev() -> ExtractedValue:
    return ExtractedValue()


class POHeader(BaseModel):
    po_number: ExtractedValue = Field(default_factory=_ev)
    po_date: ExtractedValue = Field(default_factory=_ev)
    requested_date: ExtractedValue = Field(default_factory=_ev)
    brand_text: ExtractedValue = Field(default_factory=_ev)
    order_text: ExtractedValue = Field(default_factory=_ev)
    ship_to_text: ExtractedValue = Field(default_factory=_ev)
    bill_to_text: ExtractedValue = Field(default_factory=_ev)
    currency_text: ExtractedValue = Field(default_factory=_ev)
    incoterms_text: ExtractedValue = Field(default_factory=_ev)
    payment_terms_text: ExtractedValue = Field(default_factory=_ev)
    packing_spec: ExtractedValue = Field(default_factory=_ev)
    remark_default: ExtractedValue = Field(default_factory=_ev)
    extra: dict[str, ExtractedValue] = Field(default_factory=dict)


class POLine(BaseModel):
    """품목 1건.

    ship_to_text / brand_text / delivery_date 를 라인에도 두는 이유:
    품목마다 출하처·브랜드·납기가 다른 발주서가 존재하기 때문(검수 화면을
    평면 그리드로 설계한 이유와 동일). 비어 있으면 헤더 값으로 폴백한다.

    posex 는 **문서에 인쇄된 번호**만 담는다. 비어 있으면 규칙엔진이 ⑥ FIELDS 에서
    오더 단위마다 다시 매긴다 (SCHEMA.md §2.1).
    """

    line_no: int
    posex: ExtractedValue = Field(default_factory=_ev)
    our_item: ExtractedValue = Field(default_factory=_ev)
    item_code: ExtractedValue = Field(default_factory=_ev)
    description: ExtractedValue = Field(default_factory=_ev)
    quantity: ExtractedValue = Field(default_factory=_ev)
    unit: ExtractedValue = Field(default_factory=_ev)
    unit_price: ExtractedValue = Field(default_factory=_ev)
    net_value: ExtractedValue = Field(default_factory=_ev)
    delivery_date: ExtractedValue = Field(default_factory=_ev)
    ship_to_text: ExtractedValue = Field(default_factory=_ev)
    brand_text: ExtractedValue = Field(default_factory=_ev)
    remark: ExtractedValue = Field(default_factory=_ev)
    extra: dict[str, ExtractedValue] = Field(default_factory=dict)


class POShipment(BaseModel):
    """출하처(Shipment) 블록 1건 = 오더 1건.

    `split.by: shipment` 인 거래처에서만 채워진다. 한 발주서에 출하처가 여럿이면
    블록마다 별도 오더가 생기고 BSTKD·KUNNR2 가 달라진다 (SCHEMA.md §2.1).
    """

    shipment_no: ExtractedValue = Field(default_factory=_ev)
    receiving_loc: ExtractedValue = Field(default_factory=_ev)
    ship_to_text: ExtractedValue = Field(default_factory=_ev)
    ship_by_text: ExtractedValue = Field(default_factory=_ev)
    remark: ExtractedValue = Field(default_factory=_ev)
    lines: list[POLine] = Field(default_factory=list)


class POTotals(BaseModel):
    """발주서에 인쇄된 합계. 추출 결과와 대조해 라인 누락을 탐지한다."""

    line_count: int | None = None
    total_qty: str | None = None
    total_amount: str | None = None


class RawPO(BaseModel):
    """추출 결과 1문서.

    `shipments` 가 비어 있지 않으면 **오더 단위는 shipment** 이고, 이때 `lines` 는
    문서 상단 요약표다(합계 대조용, 오더 생성에 쓰지 않는다). `shipments` 가 비어
    있으면 `lines` 가 곧 그 문서 1건짜리 오더의 품목이다. — SCHEMA.md §2.1
    """

    customer_code: str
    source_file: str
    header: POHeader = Field(default_factory=POHeader)
    lines: list[POLine] = Field(default_factory=list)
    shipments: list[POShipment] = Field(default_factory=list)
    totals: POTotals = Field(default_factory=POTotals)
    notes: list[str] = Field(default_factory=list)

    @property
    def is_split(self) -> bool:
        return bool(self.shipments)

    @property
    def all_lines(self) -> list[POLine]:
        """오더 생성에 실제로 쓰이는 전 품목 (분할 여부 무관)."""
        if self.shipments:
            return [ln for s in self.shipments for ln in s.lines]
        return list(self.lines)


class GroundingIssue(BaseModel):
    level: str          # "error" | "warn"
    field: str          # "header.po_number" | "lines[2].quantity"
    code: str           # EVIDENCE_NOT_FOUND | LOW_CONFIDENCE | TOTAL_MISMATCH
    message: str


class ParseResult(BaseModel):
    """추출 + 검증 결과 묶음."""

    raw: RawPO
    issues: list[GroundingIssue] = Field(default_factory=list)
    model_used: str = ""
    provider: str = ""
    cached: bool = False

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warn")
