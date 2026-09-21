"""분할 추출 테스트용 가짜 프로바이더와 합성 문서.

**실제 LLM 을 부르지 않는다.** 프로바이더가 받은 프롬프트에서 읽을 구간(`L000010 ~ L000020`)을
꺼내, 그 구간에 든 품목 줄을 그대로 응답으로 돌려준다 — 진짜 모델이 성실하게 읽었을 때의
응답을 흉내 낸 것이라, 청크 분할·병합·그라운딩이 끝까지 이어지는지 볼 수 있다.

문서의 품목 줄은 `ITEM-0007 | 10` 모양이다. 품번이 그 줄에 있어 앵커 대조와 품번 백스톱을
통과한다.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.extraction.preprocess import SourceDoc
from app.extraction.providers.base import (
    DocumentInput,
    LLMError,
    ProviderHealth,
    ToolCallResult,
)

_RANGE = re.compile(r"읽을 구간: L(\d{6}) ~ L(\d{6})")
ITEM = re.compile(r"^(ITEM-\d+) \| (\d+)$")


def make_doc(item_counts: list[int], *, filename: str = "synthetic.htm") -> tuple[SourceDoc, list[tuple[int, int]]]:
    """블록마다 `item_counts[i]` 개의 품목 줄이 있는 문서.

    돌려주는 것은 `(문서, 블록 구간 목록)` 이다. 구간은 그 블록의 첫 줄(블록 제목)부터
    마지막 품목 줄까지이고, 블록 사이에는 서식 줄이 하나씩 낀다 (빈틈은 정상이다).
    """
    lines = ["PO 1234", "Purchase order header"]
    blocks: list[tuple[int, int]] = []
    number = 0
    for b, count in enumerate(item_counts, start=1):
        first = len(lines) + 2                      # +1 = PAGE 머리글, +1 = 1-기준
        lines.append(f"BLOCK {b:03d}")
        for _ in range(count):
            number += 1
            lines.append(f"ITEM-{number:04d} | {10 + number}")
        blocks.append((first, len(lines) + 1))
        lines.append("--- block end ---")
    doc = SourceDoc(filename=filename, ext="htm", pages=["\n".join(lines)], has_text_layer=True)
    return doc, blocks


def item_rows(doc: SourceDoc) -> dict[int, tuple[str, str]]:
    """줄 번호 → (품번, 수량)."""
    out = {}
    for n in range(1, doc.line_count + 1):
        m = ITEM.match(doc.line_at(n) or "")
        if m:
            out[n] = (m[1], m[2])
    return out


def value(text: str, src: int, confidence: float = 0.99) -> dict[str, Any]:
    return {"value": text, "src": src, "confidence": confidence}


def outline_payload(
    doc: SourceDoc, blocks: list[tuple[int, int]] | None, *, totals: bool = True
) -> dict[str, Any]:
    """OUTLINE 응답 — `blocks` 가 None 이면 품목표 구간(`line_range`) 하나."""
    rows = item_rows(doc)
    payload: dict[str, Any] = {"header": {"po_number": value("1234", 2)}}
    if blocks is None:
        first, last = min(rows), max(rows)
        payload["line_range"] = {"src": first, "src_end": last}
    else:
        payload["shipments"] = [
            {"src": lo, "src_end": hi, "shipment_no": value(f"{i:03d}", lo)}
            for i, (lo, hi) in enumerate(blocks, start=1)
        ]
    payload["totals"] = (
        {"line_count": len(rows), "total_qty": str(sum(int(q) for _, q in rows.values()))}
        if totals else {}
    )
    return payload


def lines_payload(doc: SourceDoc, start: int, end: int) -> dict[str, Any]:
    """구간 안의 품목 줄을 성실하게 읽은 응답."""
    return {"lines": [
        {"src": n, "confidence": 0.99, "item_code": code, "quantity": qty}
        for n, (code, qty) in item_rows(doc).items() if start <= n <= end
    ]}


@dataclass
class Call:
    kind: str                       # outline_purchase_order | extract_lines | extract_purchase_order
    start: int | None
    end: int | None
    thread: str
    doc_text: str | None = None


@dataclass
class FakeProvider:
    """호출을 기록하고, 종류별 핸들러로 응답을 만든다.

    lines_handler(start, end) → 응답 dict 를 돌려주거나 예외(`LLMTruncatedError` 등)를 올린다.
    """

    doc: SourceDoc
    outline: dict[str, Any] | None = None
    lines_handler: Callable[[int, int], dict[str, Any]] | None = None
    single: dict[str, Any] | None = None
    outline_error: Exception | None = None
    delay: Callable[[int, int], float] | None = None
    stop_reason: str = "tool_use"
    name: str = "fake"
    calls: list[Call] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def extract(self, *, system, tool, user_prompt, document: DocumentInput,
                model_alias="extract", max_tokens=16000, customer="") -> ToolCallResult:
        kind = tool["name"]
        m = _RANGE.search(user_prompt)
        start, end = (int(m[1]), int(m[2])) if m else (None, None)
        with self._lock:
            self.calls.append(Call(kind, start, end, threading.current_thread().name,
                                   document.text))
            self.tools.append(tool)

        if kind == "outline_purchase_order":
            if self.outline_error is not None:
                raise self.outline_error
            payload = self.outline
        elif kind == "extract_lines":
            if self.delay is not None:
                time.sleep(self.delay(start, end))
            handler = self.lines_handler or (lambda s, e: lines_payload(self.doc, s, e))
            payload = handler(start, end)
        else:
            payload = self.single
        if payload is None:
            raise LLMError(f"가짜 프로바이더에 {kind} 응답이 없다")
        return ToolCallResult(payload=payload, model="fake-model", provider="fake",
                              stop_reason=self.stop_reason)

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name)

    # ── 조회 ──────────────────────────────────────────────────────────
    def of(self, kind: str) -> list[Call]:
        return [c for c in self.calls if c.kind == kind]

    @property
    def line_ranges(self) -> list[tuple[int, int]]:
        return sorted((c.start, c.end) for c in self.of("extract_lines"))


class BoomProvider:
    """불리면 실패한다 — '이 경로에서는 호출이 없어야 한다'를 확인한다."""

    name = "boom"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, **_kwargs):
        self.calls += 1
        raise AssertionError("프로바이더가 불리면 안 되는 경로다")

    def health(self) -> ProviderHealth:  # pragma: no cover
        return ProviderHealth(ok=True, provider=self.name)
