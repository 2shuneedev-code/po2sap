"""파싱 결과 도메인 모델.

핵심 원칙(P1): 이 단계에는 **원문에서 읽은 값만** 담긴다.
SAP 코드(ZBRAND, KUNNR2, ZPKRE2 …)는 여기 없다. 규칙엔진이 다음 단계에서 결정한다.
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


class POHeader(BaseModel):
    po_number: ExtractedValue = Field(default_factory=ExtractedValue)
    po_date: ExtractedValue = Field(default_factory=ExtractedValue)
    requested_date: ExtractedValue = Field(default_factory=ExtractedValue)
    ship_to_text: ExtractedValue = Field(default_factory=ExtractedValue)
    bill_to_text: ExtractedValue = Field(default_factory=ExtractedValue)
    brand_text: ExtractedValue = Field(default_factory=ExtractedValue)
    incoterms: ExtractedValue = Field(default_factory=ExtractedValue)
    payment_terms: ExtractedValue = Field(default_factory=ExtractedValue)
    currency: ExtractedValue = Field(default_factory=ExtractedValue)
    order_text: ExtractedValue = Field(default_factory=ExtractedValue)
    extra: dict[str, ExtractedValue] = Field(default_factory=dict)


class POLine(BaseModel):
    """품목 1건.

    ship_to_text / brand_text / req_date 를 라인에도 두는 이유:
    품목마다 출하처·브랜드·납기가 다른 발주서가 존재하기 때문(검수 화면을
    평면 33컬럼으로 설계한 이유와 동일). 비어 있으면 헤더 값으로 폴백한다.
    """

    line_no: int
    our_item: ExtractedValue = Field(default_factory=ExtractedValue)
    item_code: ExtractedValue = Field(default_factory=ExtractedValue)
    description: ExtractedValue = Field(default_factory=ExtractedValue)
    quantity: ExtractedValue = Field(default_factory=ExtractedValue)
    unit: ExtractedValue = Field(default_factory=ExtractedValue)
    unit_price: ExtractedValue = Field(default_factory=ExtractedValue)
    req_date: ExtractedValue = Field(default_factory=ExtractedValue)
    ship_to_text: ExtractedValue = Field(default_factory=ExtractedValue)
    brand_text: ExtractedValue = Field(default_factory=ExtractedValue)
    extra: dict[str, ExtractedValue] = Field(default_factory=dict)


class POTotals(BaseModel):
    """발주서에 인쇄된 합계. 추출 결과와 대조해 라인 누락을 탐지한다."""

    line_count: int | None = None
    total_qty: str | None = None
    total_amount: str | None = None


class RawPO(BaseModel):
    customer_code: str
    source_file: str
    header: POHeader = Field(default_factory=POHeader)
    lines: list[POLine] = Field(default_factory=list)
    totals: POTotals = Field(default_factory=POTotals)
    notes: list[str] = Field(default_factory=list)


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
