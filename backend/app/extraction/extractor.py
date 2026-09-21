"""추출 오케스트레이터: 파일 → RawPO + 검증 이슈.

책임 경계를 지킨다.
  · 이 모듈은 "원문에서 값 읽기"까지만 한다.
  · SAP 코드 결정(ZBRAND/KUNNR2/ZPKRE2…)은 rules 엔진(D2)의 몫이다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..domain.models import (
    ExtractedValue,
    GroundingIssue,
    ParseResult,
    POHeader,
    POLine,
    POShipment,
    POTotals,
    RawPO,
)
from ..masters.loader import CustomerMaster, load_customer
from . import grounding
from .preprocess import SourceDoc, load_document
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .providers import DocumentInput, create_provider
from .providers import cache as llm_cache
from .schema_builder import build_lines_schema, build_outline_schema

# 과도기 단일 호출 툴의 이름 (아래 `_single_shot_tool`)
_SINGLE_SHOT_TOOL = "extract_purchase_order"


def splits_by_shipment(master: CustomerMaster) -> bool:
    """`split.by` 가 none 이 아니면 추출 스키마에 shipments 블록을 넣는다.

    거래처 이름으로 분기하지 않는다 (SCHEMA.md §0-1). YAML 이 정한다.
    """
    return str((master.split or {}).get("by") or "none").strip().lower() != "none"


def _single_shot_tool(
    extra_fields: list[dict[str, str]] | None, *, include_shipments: bool
) -> dict[str, Any]:
    """**과도기** — OUTLINE 과 LINES 스키마를 한 툴로 합쳐 문서 1건을 한 번에 읽힌다.

    오케스트레이터가 OUTLINE 1회 + LINES N회로 바뀌면(design.md §3.3.2) 이 함수는
    지워진다. 그때까지 기존 "문서 1건 = 호출 1회" 흐름이 새 스키마 모양으로 계속 돌게
    하는 얇은 접착제다. 두 빌더가 만든 스키마를 **그대로** 이어 붙일 뿐 새 키를 만들지
    않는다 — 스키마의 원천은 `schema_builder` 하나다.
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

    return {
        "name": _SINGLE_SHOT_TOOL,
        "description": "발주서에서 추출한 정보를 구조화해 반환한다.",
        "input_schema": {"type": "object", "properties": props, "required": required},
    }


class Extractor:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = create_provider(self._settings)
        self._cache_dir = self._settings.llm_cache_dir
        self._fixtures_dir = self._settings.llm_fixtures_dir

    def parse_file(
        self, path: str | Path, customer_code: str, *, display_name: str | None = None
    ) -> ParseResult:
        """`display_name` 은 저장 경로가 원본 파일명과 다를 때 쓴다.

        업로드는 `{file_id}__{원본명}` 으로 저장되는데, 픽스처는 원본명으로 찾고
        화면도 원본명을 보여줘야 한다. 저장 방식이 재생과 표시를 흔들면 안 된다.
        """
        master = load_customer(customer_code, self._settings.masters_dir)
        doc = load_document(path)
        if display_name:
            doc = replace(doc, filename=display_name)
        type_issue = self._check_file_type(doc, master)

        document, prompt = self._build_request(doc, master)
        result, cached = self._call(document, prompt, master)

        raw = _to_raw_po(result.payload, customer_code=master.code, source_file=doc.filename)
        if doc.has_text_layer:
            _stamp_pages(raw, doc)
        issues = grounding.verify(raw, doc)
        if type_issue:
            issues.insert(0, type_issue)

        return ParseResult(
            raw=raw,
            issues=issues,
            model_used=result.model,
            provider=result.provider,
            cached=cached,
        )

    # ── 내부 ───────────────────────────────────────────────────────────
    @staticmethod
    def _check_file_type(doc: SourceDoc, master: CustomerMaster) -> GroundingIssue | None:
        """`meta.file_types` 는 **안내용이다. 차단하지 않는다.**

        거래처가 평소와 다른 형식으로 한 번 보내는 일은 실제로 일어난다. 그때
        업로드 자체를 막으면 사람이 할 수 있는 일이 없어진다 — 읽어보고 안 되면
        그때 실패해도 늦지 않다. 계약 §1·process.md·NEXT.md 가 정한 방침이다.
        """
        allowed = {t.lower() for t in master.file_types}
        if not allowed or doc.ext in allowed:
            return None
        return GroundingIssue(
            level="warn",
            field="file",
            code="UNEXPECTED_FILE_TYPE",
            message=(
                f"{master.name} 발주서는 보통 {'/'.join(sorted(allowed)).upper()} 형식인데 "
                f".{doc.ext} 파일입니다. 판독 결과를 특히 주의해서 확인하세요."
            ),
        )

    def _build_request(
        self, doc: SourceDoc, master: CustomerMaster
    ) -> tuple[DocumentInput, str]:
        mode = (master.extraction.get("input") or "auto").lower()
        use_text = doc.has_text_layer if mode == "auto" else (mode == "text")

        if use_text:
            document = DocumentInput(text=doc.numbered_text(), filename=doc.filename)
            body: str | None = doc.numbered_text()
        else:
            # 스캔본: 원본 PDF를 그대로 넘겨 판독시킨다(별도 OCR 불필요).
            if not doc.raw_bytes or doc.ext != "pdf":
                raise ValueError(
                    "문자 정보가 없는 파일입니다. 거래처에 원본(텍스트) PDF를 요청하세요."
                )
            document = DocumentInput(pdf_bytes=doc.raw_bytes, filename=doc.filename)
            body = None

        prompt = build_user_prompt(
            customer_name=master.name,
            hints=master.extraction.get("hints"),
            document_text=body,
        )
        return document, prompt

    def _call(self, document: DocumentInput, prompt: str, master: CustomerMaster):
        """저장된 응답을 먼저 찾고, 없을 때만 실제로 호출한다.

        조회 순서는 픽스처 → 런타임 캐시다. 픽스처는 Git 에 있으므로 새 클론에서도
        곧바로 재생된다(CI 비용 0). 조회를 여기 한 곳에서만 하므로 프로바이더별로
        경로가 갈리지 않는다.
        """
        fixture = llm_cache.load_fixture(
            self._fixtures_dir, master.code, document.filename
        )
        if fixture is not None:
            return fixture, True

        key = llm_cache.cache_key(
            document=document,
            prompt_version=self._settings.llm_prompt_version,
            customer=master.code,
            model=self._settings.model_id("extract"),
        )
        cached = llm_cache.load(self._cache_dir, key)
        if cached is not None:
            return cached, True

        tool = _single_shot_tool(
            master.extraction.get("extra_fields"),
            include_shipments=splits_by_shipment(master),
        )
        result = self._provider.extract(
            system=SYSTEM_PROMPT,
            tool=tool,
            user_prompt=prompt,
            document=document,
            model_alias="extract",
            max_tokens=self._settings.llm_max_tokens,
            customer=master.code,
        )

        # 실제 호출 결과를 저장해 두면 이후 mock 으로 무료 재생이 가능하다.
        llm_cache.save(self._cache_dir, key, result)
        return result, False

    def health(self):
        return self._provider.health()


# ── 응답 → 도메인 모델 ─────────────────────────────────────────────────
def _int(data: Any) -> int | None:
    """줄 번호 · 페이지. 모델이 `"412"` 나 `412.0` 을 줘도 정수로 읽는다."""
    if isinstance(data, bool) or data is None:
        return None
    try:
        return int(data)
    except (TypeError, ValueError):
        return None


def _float(data: Any) -> float | None:
    if isinstance(data, bool) or data is None:
        return None
    try:
        return float(data)
    except (TypeError, ValueError):
        return None


def _val(
    data: Any,
    *,
    src: int | None = None,
    src_end: int | None = None,
    confidence: float | None = None,
) -> ExtractedValue:
    """LLM 응답의 값 1개를 ExtractedValue 로 변환 (SCHEMA.md §3.2).

    두 모양을 읽는다.
      · `{value, src, src_end?, confidence}` — header · shipment 값. **이 모양이 진짜다.**
      · 스칼라 — 품목의 평평한 값. 줄 단위 앵커(src·src_end·confidence)를 인자로 받아
        값마다 물려 준다 — 그래야 그라운딩이 값 단위로 그 줄을 대조한다.

    **구 형태(`evidence` · 모델이 준 `page`)는 값만 읽고 근거로 삼지 않는다.** 원문 인용에는
    줄 번호가 없어서 앵커를 만들 수 없다 — 그대로 두면 그라운딩이 🔴 로 올린다.
    `page` 는 여기서 채우지 않는다. `src` 로부터 `_stamp_pages` 가 채운다.

    모델이 스키마를 벗어나 문자열만 반환하는 경우도 방어적으로 흡수한다.
    """
    if data is None:
        return ExtractedValue()
    if isinstance(data, dict):
        value = data.get("value")
        return ExtractedValue(
            value=None if value is None else str(value).strip(),
            src=_int(data.get("src")) if data.get("src") is not None else src,
            src_end=_int(data.get("src_end")) if data.get("src_end") is not None else src_end,
            page=_int(data.get("page")),
            confidence=_float(data.get("confidence")) if data.get("confidence") is not None
            else confidence,
        )
    return ExtractedValue(
        value=str(data).strip(), src=src, src_end=src_end, confidence=confidence
    )


def _extra(data: Any, **anchor: Any) -> dict[str, ExtractedValue]:
    if not isinstance(data, dict):
        return {}
    return {k: _val(v, **anchor) for k, v in data.items()}


def _to_line(item: Any, fallback_no: int) -> POLine:
    """품목 1건 (SCHEMA.md §3.2-나) — 평평한 스칼라 + 줄 단위 앵커 1개.

    `line_no` 는 받지 않는다. 모델이 준 번호는 청크 안에서만 센 값이라 쓰지 않고,
    오더 단위 안의 순번(`fallback_no`)을 매긴다 (SCHEMA.md §2.1-6).
    """
    item = item if isinstance(item, dict) else {}
    src, src_end = _int(item.get("src")), _int(item.get("src_end"))
    anchor = {"src": src, "src_end": src_end, "confidence": _float(item.get("confidence"))}

    def v(key: str) -> ExtractedValue:
        return _val(item.get(key), **anchor)

    return POLine(
        line_no=fallback_no,
        src=src,
        src_end=src_end,
        posex=v("posex"),
        our_item=v("our_item"),
        item_code=v("item_code"),
        description=v("description"),
        quantity=v("quantity"),
        unit=v("unit"),
        unit_price=v("unit_price"),
        net_value=v("net_value"),
        delivery_date=v("delivery_date"),
        ship_to_text=v("ship_to_text"),
        brand_text=v("brand_text"),
        remark=v("remark"),
        extra=_extra(item.get("extra"), **anchor),
    )


def _to_lines(data: Any) -> list[POLine]:
    """line_no 는 오더 단위 안에서 1부터 센다 (SCHEMA.md §2.1-6)."""
    return [_to_line(item, idx) for idx, item in enumerate(data or [], start=1)]


def _to_shipments(data: Any) -> list[POShipment]:
    out: list[POShipment] = []
    for block in data or []:
        block = block if isinstance(block, dict) else {}
        out.append(
            POShipment(
                src=_int(block.get("src")),
                src_end=_int(block.get("src_end")),
                shipment_no=_val(block.get("shipment_no")),
                receiving_loc=_val(block.get("receiving_loc")),
                ship_to_text=_val(block.get("ship_to_text")),
                ship_by_text=_val(block.get("ship_by_text")),
                remark=_val(block.get("remark")),
                lines=_to_lines(block.get("lines")),
            )
        )
    return out


def _to_raw_po(payload: dict[str, Any], *, customer_code: str, source_file: str) -> RawPO:
    h = payload.get("header") or {}
    header = POHeader(
        po_number=_val(h.get("po_number")),
        po_date=_val(h.get("po_date")),
        requested_date=_val(h.get("requested_date")),
        brand_text=_val(h.get("brand_text")),
        order_text=_val(h.get("order_text")),
        ship_to_text=_val(h.get("ship_to_text")),
        bill_to_text=_val(h.get("bill_to_text")),
        currency_text=_val(h.get("currency_text")),
        incoterms_text=_val(h.get("incoterms_text")),
        payment_terms_text=_val(h.get("payment_terms_text")),
        packing_spec=_val(h.get("packing_spec")),
        remark_default=_val(h.get("remark_default")),
        extra=_extra(h.get("extra")),
    )

    t = payload.get("totals") or {}
    totals = POTotals(
        line_count=t.get("line_count"),
        total_qty=None if t.get("total_qty") is None else str(t["total_qty"]),
        total_amount=None if t.get("total_amount") is None else str(t["total_amount"]),
    )

    return RawPO(
        customer_code=customer_code,
        source_file=source_file,
        header=header,
        lines=_to_lines(payload.get("lines")),
        shipments=_to_shipments(payload.get("shipments")),
        totals=totals,
        notes=[str(n) for n in (payload.get("notes") or [])],
    )


def _stamp_pages(raw: RawPO, doc: SourceDoc) -> None:
    """모델이 준 값이 아니라 **`src` 로부터 계산한** 페이지를 채운다 (SCHEMA.md §3.2).

    페이지는 파생 사실이다. LLM 에게 시키면 틀릴 수 있고 값도 든다(원칙 P1).
    """
    def walk(obj: Any) -> None:
        for name in type(obj).model_fields:
            member = getattr(obj, name)
            members = member.values() if isinstance(member, dict) else [member]
            for m in members:
                if isinstance(m, ExtractedValue):
                    m.page = doc.page_of(m.src) if m.src is not None else None

    walk(raw.header)
    for line in raw.lines:
        walk(line)
    for shipment in raw.shipments:
        walk(shipment)
        for line in shipment.lines:
            walk(line)
