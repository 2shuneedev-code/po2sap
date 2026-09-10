"""추출 오케스트레이터: 파일 → RawPO + 검증 이슈.

책임 경계를 지킨다.
  · 이 모듈은 "원문에서 값 읽기"까지만 한다.
  · SAP 코드 결정(ZBRAND/KUNNR2/ZPKRE2…)은 rules 엔진(D2)의 몫이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..domain.models import (
    ExtractedValue,
    ParseResult,
    POHeader,
    POLine,
    POTotals,
    RawPO,
)
from ..masters.loader import CustomerMaster, load_customer
from . import grounding
from .preprocess import SourceDoc, load_document
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .providers import DocumentInput, create_provider
from .providers import cache as llm_cache
from .schema_builder import build_tool


class Extractor:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = create_provider(self._settings)
        self._cache_dir = self._settings.storage_dir / "llm_cache"

    def parse_file(self, path: str | Path, customer_code: str) -> ParseResult:
        master = load_customer(customer_code, self._settings.masters_dir)
        doc = load_document(path)
        self._check_file_type(doc, master)

        document, prompt = self._build_request(doc, master)
        result, cached = self._call(document, prompt, master)

        raw = _to_raw_po(result.payload, customer_code=master.code, source_file=doc.filename)
        issues = grounding.verify(raw, doc)

        return ParseResult(
            raw=raw,
            issues=issues,
            model_used=result.model,
            provider=result.provider,
            cached=cached,
        )

    # ── 내부 ───────────────────────────────────────────────────────────
    @staticmethod
    def _check_file_type(doc: SourceDoc, master: CustomerMaster) -> None:
        allowed = {t.lower() for t in master.file_types}
        if allowed and doc.ext not in allowed:
            raise ValueError(
                f"{master.name} 발주서는 {'/'.join(sorted(allowed)).upper()} 형식입니다 "
                f"(업로드한 파일: .{doc.ext})"
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
        # 프롬프트 버전을 캐시 키에 반영 (프롬프트가 바뀌면 캐시 무효화)
        prompt = f"<!-- prompt:{self._settings.llm_prompt_version} -->\n{prompt}"
        return document, prompt

    def _call(self, document: DocumentInput, prompt: str, master: CustomerMaster):
        key = llm_cache.cache_key(document=document, prompt=prompt)

        cached = llm_cache.load(self._cache_dir, key)
        if cached is not None and self._provider.name != "mock":
            return cached, True

        tool = build_tool(master.extraction.get("extra_fields"))
        result = self._provider.extract(
            system=SYSTEM_PROMPT,
            tool=tool,
            user_prompt=prompt,
            document=document,
            model_alias="extract",
            max_tokens=self._settings.llm_max_tokens,
        )

        if self._provider.name != "mock":
            # 실제 호출 결과를 저장해 두면 이후 mock 으로 무료 재생이 가능하다.
            llm_cache.save(self._cache_dir, key, result)

        return result, False

    def health(self):
        return self._provider.health()


# ── 응답 → 도메인 모델 ─────────────────────────────────────────────────
def _val(data: Any) -> ExtractedValue:
    """LLM 응답의 값 1개를 ExtractedValue 로 변환.

    모델이 스키마를 벗어나 문자열만 반환하는 경우도 방어적으로 흡수한다.
    """
    if data is None:
        return ExtractedValue()
    if isinstance(data, dict):
        value = data.get("value")
        return ExtractedValue(
            value=None if value is None else str(value).strip(),
            evidence=data.get("evidence"),
            page=data.get("page"),
            confidence=data.get("confidence"),
        )
    return ExtractedValue(value=str(data).strip())


def _extra(data: Any) -> dict[str, ExtractedValue]:
    if not isinstance(data, dict):
        return {}
    return {k: _val(v) for k, v in data.items()}


def _to_raw_po(payload: dict[str, Any], *, customer_code: str, source_file: str) -> RawPO:
    h = payload.get("header") or {}
    header = POHeader(
        po_number=_val(h.get("po_number")),
        po_date=_val(h.get("po_date")),
        requested_date=_val(h.get("requested_date")),
        ship_to_text=_val(h.get("ship_to_text")),
        bill_to_text=_val(h.get("bill_to_text")),
        brand_text=_val(h.get("brand_text")),
        incoterms=_val(h.get("incoterms")),
        payment_terms=_val(h.get("payment_terms")),
        currency=_val(h.get("currency")),
        order_text=_val(h.get("order_text")),
        extra=_extra(h.get("extra")),
    )

    lines: list[POLine] = []
    for idx, item in enumerate(payload.get("lines") or [], start=1):
        item = item or {}
        lines.append(
            POLine(
                line_no=int(item.get("line_no") or idx),
                our_item=_val(item.get("our_item")),
                item_code=_val(item.get("item_code")),
                description=_val(item.get("description")),
                quantity=_val(item.get("quantity")),
                unit=_val(item.get("unit")),
                unit_price=_val(item.get("unit_price")),
                req_date=_val(item.get("req_date")),
                ship_to_text=_val(item.get("ship_to_text")),
                brand_text=_val(item.get("brand_text")),
                extra=_extra(item.get("extra")),
            )
        )

    t = payload.get("totals") or {}
    totals = POTotals(
        line_count=t.get("line_count"),
        total_qty=None if t.get("total_qty") is None else str(t["total_qty"]),
        total_amount=None if t.get("total_amount") is None else str(t["total_amount"]),
    )

    notes = [str(n) for n in (payload.get("notes") or [])]

    return RawPO(
        customer_code=customer_code,
        source_file=source_file,
        header=header,
        lines=lines,
        totals=totals,
        notes=notes,
    )
