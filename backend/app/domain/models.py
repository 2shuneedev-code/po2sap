"""파싱 결과 도메인 모델.

핵심 원칙(P1): 이 단계에는 **원문에서 읽은 값만** 담긴다.
SAP 코드(ZBRAND, KUNNR2, ZPKRE2 …)는 여기 없다. 규칙엔진이 다음 단계에서 결정한다.

필드 이름은 `masters/SCHEMA.md` §3.1 표준 키를 따른다. 키를 바꾸려면 §3.1 을 먼저 고친다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedValue(BaseModel):
    """LLM이 추출한 값 1개 + 근거 앵커.

    근거는 원문 인용이 아니라 **줄 번호**(`src`~`src_end`, 문서 통번호 1-기준)다.
    grounding 이 그 줄의 원문에서 `value` 를 실제로 찾는다 (design.md §3.4).

    `page` 는 모델이 준 값이 아니다. `src` 로부터 코드가 채운다 (SCHEMA.md §3.2).
    """

    value: str | None = None
    src: int | None = None
    src_end: int | None = None
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
    src: int | None = None          # 이 품목이 있는 원문 줄 (줄 단위 앵커 1개, SCHEMA §3.2-나)
    src_end: int | None = None      # 여러 줄에 걸칠 때의 마지막 줄
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

    src: int | None = None          # 이 블록의 시작 줄 (품목표 포함 구간, design §3.3.2)
    src_end: int | None = None      # 이 블록의 끝 줄 — 청크 경계가 된다
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
    비어 있다 — 문서 상단 요약표는 품목으로 추출하지 않는다(합계는 `totals` 로만 받는다).
    `shipments` 가 비어 있으면 `lines` 가 곧 그 문서 1건짜리 오더의 품목이다.
    — SCHEMA.md §2.1
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


class IssueCode:
    """`GroundingIssue.code` 의 값. 문자열 그대로 API·화면에 나간다."""

    # 앵커 대조 (design.md §3.4)
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"   # 🔴 src 없음·범위 밖·값이 그 줄에 없음
    EVIDENCE_WEAK = "EVIDENCE_WEAK"             # 🟡 그 줄에 비슷하게만 있음
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    NO_LINES = "NO_LINES"
    # 청크 분할·병합 (design.md §3.3.4) — 발행은 다음 단계의 오케스트레이터가 한다
    CHUNK_FAILED = "CHUNK_FAILED"               # 🔴 그 구간을 못 읽음 → 전송 차단
    EMPTY_CHUNK = "EMPTY_CHUNK"                 # 🟡 구간에서 품목 0건
    DUPLICATE_LINE = "DUPLICATE_LINE"           # 🟡 인접 청크에서 같은 src 가 두 번


class GroundingIssue(BaseModel):
    level: str          # "error" | "warn"
    field: str          # "header.po_number" | "lines[2].quantity"
    code: str           # IssueCode 의 값
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


# ── 규칙엔진 산출물 (SCHEMA.md §2 의 ⑥~⑦) ─────────────────────────────
class RowIssue(BaseModel):
    """행 단위 문제. severity 가 error 면 전송이 막힌다."""

    field: str = ""
    severity: str = "warn"      # "error" | "warn"
    code: str = ""              # REQUIRED_MISSING | MAX_LEN | FORMAT_ERROR | NO_MATCH …
    message: str = ""


class SapRow(BaseModel):
    """전송 필드 1행 = 품목 1건.

    `fields` 는 `_base/sap_defaults.yaml` 의 전송 필드를 **전량** 담는다 —
    값이 없어도 키는 있고 값은 "" 다 (계약 §4·5 규약).
    `_` 로 시작하는 것들은 화면 전용이며 전송 페이로드에 들어가지 않는다.
    """

    row_id: str = ""
    file: str = ""              # → _file
    group: str = ""             # → _group (분할 단위 라벨. 분할 없으면 "")
    line_no: int = 0            # → _line_no (오더 단위 안에서의 순번)
    fields: dict[str, str] = Field(default_factory=dict)
    issues: list[RowIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")


class BuildResult(BaseModel):
    """한 문서를 규칙엔진에 통과시킨 결과."""

    rows: list[SapRow] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    grid: dict[str, object] = Field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(r.error_count for r in self.rows)

    @property
    def warn_count(self) -> int:
        return sum(len(r.issues) - r.error_count for r in self.rows)


# ── 배치 (계약 §4~§7) ──────────────────────────────────────────────────
class BatchFile(BaseModel):
    file_id: str
    name: str
    status: str = "PARSING"     # PARSING | DONE | FAILED
    error: str = ""
    row_count: int = 0


class BatchRow(BaseModel):
    """검수 그리드의 한 행.

    `original` 은 **파싱 직후 값**이고 클라이언트가 바꿀 수 없다. 검수 중 올라온
    값은 `fields` 에만 반영된다. 둘을 나눠 두어야 "무엇이 사람 손을 탔는가"를
    서버가 판단할 수 있고(`edited`), 위조된 행을 걸러낼 수 있다.
    """

    row_id: str
    file_id: str = ""
    file: str = ""
    group: str = ""
    line_no: int = 0
    original: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    issues: list[RowIssue] = Field(default_factory=list)
    edited: list[str] = Field(default_factory=list)
    deleted: bool = False

    @property
    def error_count(self) -> int:
        return 0 if self.deleted else sum(1 for i in self.issues if i.severity == "error")


class Batch(BaseModel):
    batch_id: str
    customer: str
    status: str = "PARSING"     # PARSING | NEEDS_REVIEW | READY | SENDING | SENT | SEND_FAILED
    created_at: str = ""
    files: list[BatchFile] = Field(default_factory=list)
    rows: list[BatchRow] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    grid: dict[str, object] = Field(default_factory=dict)

    @property
    def live_rows(self) -> list[BatchRow]:
        return [r for r in self.rows if not r.deleted]

    def recompute_status(self) -> str:
        if any(f.status == "PARSING" for f in self.files):
            return "PARSING"
        if self.status in {"SENDING", "SENT", "SEND_FAILED"}:
            return self.status
        blocked = any(r.error_count for r in self.live_rows)
        return "NEEDS_REVIEW" if blocked or not self.live_rows else "READY"
