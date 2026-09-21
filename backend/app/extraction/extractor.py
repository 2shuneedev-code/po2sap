"""추출 오케스트레이터: 파일 → RawPO + 검증 이슈.

책임 경계를 지킨다.
  · 이 모듈은 "원문에서 값 읽기"까지만 한다.
  · SAP 코드 결정(ZBRAND/KUNNR2/ZPKRE2…)은 rules 엔진(D2)의 몫이다.

**문서 1건 ≠ 호출 1회다** (design.md §3.3). 출력 토큰이 병목이라 큰 문서는 나눠 읽는다.

    문서 단위 픽스처 ── 있으면 그대로 (호출 없음 · 청크 로직에 들어가지 않는다)
    스캔본(텍스트 레이어 없음) ── 나누지 않는다. 단일 호출 + 한도 초과 시 명시적 거부 (§3.3.6)
    텍스트 문서
        ① OUTLINE  호출 1회   header · 블록 경계 · 합계. 품목은 받지 않는다
        ② plan     블록을 청크로 균등 분할                       (chunking.py)
        ③ LINES    청크마다 1회 · 병렬                           (스레드 풀)
        ④ merge    (shipment, chunk) 순으로 이어 붙임             (merge.py)
        ⑤ verify   앵커 대조 · 합계 교차검증                      (grounding.py)

저장된 응답 조회 · 캐시 · 재시도 · 절단 시 쪼개기는 전부 `_invoke` / `_read_range` 한 곳에서만
한다 — 프로바이더별로 경로가 갈라지면 한쪽만 고쳐 조용히 어긋난다.

**진행 콜백은 반드시 이 함수를 부른 스레드(메인)에서만 불린다.** 워커 스레드에서 부르면
스트림릿이 경고를 내거나 화면이 오동작한다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
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
from . import chunking, grounding
from . import merge as merge_mod
from .preprocess import SourceDoc, load_document
from .prompt import (
    SYSTEM_PROMPT,
    build_lines_prompt,
    build_outline_prompt,
    build_scan_prompt,
)
from .providers import DocumentInput, LLMProvider, create_provider
from .providers import cache as llm_cache
from .providers.base import (
    LLMError,
    LLMTransientError,
    LLMTruncatedError,
    ToolCallResult,
)
from .schema_builder import build_lines_tool, build_outline_tool, build_single_tool

log = logging.getLogger(__name__)

# 진행 콜백 `(단계, 완료, 전체, 라벨)`. 단계는 화면에 그대로 보이는 한글 문구다.
ProgressCallback = Callable[[str, int, int, str], None]

STAGE_OUTLINE = "골격 파악"
STAGE_LINES = "품목 읽기"
STAGE_SCAN = "스캔 판독"

SCAN_REFUSED = (
    "품목이 많은 스캔 발주서는 처리할 수 없습니다. 거래처에 텍스트 PDF 를 요청하세요."
)


class ScanNotSupportedError(ValueError):
    """스캔본을 읽을 수 없다 — 나눌 수단이 없어 조용히 잘린 결과를 내보내는 대신 거부한다.

    `ValueError` 라 배치 서비스가 그 파일만 FAILED 로 두고 나머지는 계속 간다.
    """


class _BudgetExceeded(LLMError):
    """문서 1건의 LLM 작업 시간 상한(`LLM_DOC_BUDGET_SEC`)을 넘었다."""


def splits_by_shipment(master: CustomerMaster) -> bool:
    """`split.by` 가 none 이 아니면 추출 스키마에 shipments 블록을 넣는다.

    거래처 이름으로 분기하지 않는다 (SCHEMA.md §0-1). YAML 이 정한다.
    """
    return str((master.split or {}).get("by") or "none").strip().lower() != "none"


@dataclass
class Extraction:
    """LLM 단계의 산출물 — 병합이 끝난 문서 단위 페이로드 + 그 과정에서 생긴 이슈."""

    payload: dict[str, Any]
    model: str = ""
    provider: str = ""
    cached: bool = False
    issues: list[GroundingIssue] = field(default_factory=list)
    anchored: bool = True           # 줄 번호(src)로 읽었는가 — 스캔 경로는 False
    stamp_pages: bool = True        # `src` 로 페이지를 계산해 채울 수 있는가


@dataclass
class _Run:
    """문서 1건을 읽는 동안 바뀌지 않는 것들 — 워커 스레드가 읽기만 한다."""

    doc: SourceDoc
    master: CustomerMaster
    policy: dict[str, Any]
    deadline: float | None
    split: bool
    extra_fields: list[dict[str, str]] | None
    label: str


@dataclass
class _ChunkOutcome:
    """청크 1개를 읽은 결과. 절단으로 쪼갰다면 조각들이 `parts` 에 위치 순으로 든다."""

    parts: list[tuple[chunking.Chunk, dict[str, Any] | None]] = field(default_factory=list)
    cached: bool = True
    reason: str = ""


class Extractor:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        provider: LLMProvider | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`provider` · `clock` · `sleep` 은 테스트가 갈아끼우는 자리다 (실제 호출 없이 시험)."""
        self._settings = settings or get_settings()
        self._provider = provider if provider is not None else create_provider(self._settings)
        self._cache_dir = self._settings.llm_cache_dir
        self._fixtures_dir = self._settings.llm_fixtures_dir
        self._clock = clock
        self._sleep = sleep

    # ── 진입점 ─────────────────────────────────────────────────────────
    def parse_file(
        self,
        path: str | Path,
        customer_code: str,
        *,
        display_name: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ParseResult:
        """`display_name` 은 저장 경로가 원본 파일명과 다를 때 쓴다.

        업로드는 `{file_id}__{원본명}` 으로 저장되는데, 픽스처는 원본명으로 찾고
        화면도 원본명을 보여줘야 한다. 저장 방식이 재생과 표시를 흔들면 안 된다.

        `on_progress(단계, 완료, 전체, 라벨)` 은 **이 함수를 부른 스레드에서만** 불린다.
        """
        master = load_customer(customer_code, self._settings.masters_dir)
        doc = load_document(path)
        if display_name:
            doc = replace(doc, filename=display_name)
        type_issue = self._check_file_type(doc, master)

        # 1) 문서 단위 픽스처 — 있으면 그대로 쓰고 청크 로직에 들어가지 않는다.
        #    픽스처는 Git 에 있으므로 새 클론에서도 곧바로 재생된다(CI 비용 0).
        fixture = llm_cache.load_fixture(self._fixtures_dir, master.code, doc.filename)
        if fixture is not None:
            extraction = Extraction(
                payload=fixture.payload, model=fixture.model, provider=fixture.provider,
                cached=True, stamp_pages=doc.has_text_layer,
            )
        else:
            extraction = self.extract_payload(doc, master, on_progress=on_progress)

        raw = _to_raw_po(extraction.payload, customer_code=master.code, source_file=doc.filename)
        if extraction.stamp_pages and doc.has_text_layer:
            _stamp_pages(raw, doc)

        issues = [*extraction.issues, *grounding.verify(raw, doc, anchored=extraction.anchored)]
        if type_issue:
            issues.insert(0, type_issue)

        return ParseResult(
            raw=raw,
            issues=issues,
            model_used=extraction.model,
            provider=extraction.provider,
            cached=extraction.cached,
        )

    def extract_payload(
        self,
        doc: SourceDoc,
        master: CustomerMaster,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> Extraction:
        """문서 단위 픽스처가 **없을 때의** LLM 단계 — 스캔 분기 또는 OUTLINE → LINES → 병합.

        `pin_fixture.py` 가 이 함수로 캐시에서 문서 단위 응답을 다시 조립한다.
        """
        use_text = _wants_text(doc, master)

        # `input: text` 인데 텍스트가 없는 문서. 예전에는 use_text 가 무조건 참이 되어
        # **거의 빈 텍스트를 보내고 빈 결과를 받았다** — 아무도 모르게 (design §3.3.6).
        if use_text and not doc.has_text_layer:
            raise ScanNotSupportedError(
                "이 파일에서 글자를 읽지 못했습니다 (텍스트 레이어가 없는 스캔 문서일 수 있습니다). "
                "이 거래처는 텍스트 문서만 읽도록 설정되어 있습니다. "
                "거래처에 원본(텍스트) PDF 를 요청하세요."
            )

        # 스캔본은 줄 번호가 없어 나눌 수 없다 — 청크 로직 앞에서 갈라진다 (D13).
        if not use_text:
            return self._parse_single(doc, master, on_progress)

        return self._parse_chunked(doc, master, on_progress)

    # ── 스캔본 — 나누지 않는다 (design.md §3.3.6) ──────────────────────
    def _parse_single(
        self, doc: SourceDoc, master: CustomerMaster, on_progress: ProgressCallback | None
    ) -> Extraction:
        """단일 호출. 앵커 대조·품번 백스톱은 건너뛴다 (대조할 원문이 없다).

        페이지 수가 `page_limit` 을 넘거나 출력이 잘리면 **재귀 없이 즉시** 거부한다.
        쪼갤 수단이 없는데 잘린 결과를 내보내면 품목이 조용히 빠진다.
        """
        if doc.ext != "pdf" or not doc.raw_bytes:
            raise ValueError(
                "문자 정보가 없는 파일입니다. 거래처에 원본(텍스트) PDF를 요청하세요."
            )
        page_limit = _positive_int(master.extraction.get("page_limit"))
        if page_limit is not None and doc.page_count > page_limit:
            raise ScanNotSupportedError(
                f"{SCAN_REFUSED} (스캔 문서 {doc.page_count}쪽 > 한도 {page_limit}쪽)"
            )

        label = doc.filename
        _notify(on_progress, STAGE_SCAN, 0, 1, label)

        tool = build_single_tool(
            master.extraction.get("extra_fields"),
            include_shipments=splits_by_shipment(master),
            src_required=False,
        )
        prompt = build_scan_prompt(
            customer_name=master.name, hints=master.extraction.get("hints")
        )
        document = DocumentInput(pdf_bytes=doc.raw_bytes, filename=doc.filename)
        try:
            result, cached = self._invoke(
                master, pass_kind="single", tool=tool, prompt=prompt,
                document=document, deadline=None,
            )
        except LLMTruncatedError as exc:
            raise ScanNotSupportedError(SCAN_REFUSED) from exc

        _notify(on_progress, STAGE_SCAN, 1, 1, label)
        return Extraction(
            payload=result.payload, model=result.model, provider=result.provider,
            cached=cached, anchored=False, stamp_pages=False,
        )

    # ── 텍스트 문서 — OUTLINE → LINES(병렬) → 병합 ─────────────────────
    def _parse_chunked(
        self, doc: SourceDoc, master: CustomerMaster, on_progress: ProgressCallback | None
    ) -> Extraction:
        run = self._new_run(doc, master)

        # ① OUTLINE — 실패하면 파일 전체 실패다. 경계를 모르면 나눌 수도 없다.
        _notify(on_progress, STAGE_OUTLINE, 0, 1, run.label)
        outline, outline_cached = self._call_outline(run)
        _notify(on_progress, STAGE_OUTLINE, 1, 1, run.label)

        # ② 청크 계획 — 블록 구간이 어긋나 있으면 여기서 명확한 오류가 난다.
        chunks = chunking.plan(
            outline.payload, doc, run.policy, self._settings.llm_max_tokens
        )

        # ③ LINES — 청크마다 1회, 병렬
        results, reasons, lines_cached = self._read_chunks(run, chunks, on_progress)

        # ④ 병합
        payload, issues = merge_mod.merge(outline.payload, results, doc, reasons=reasons)

        return Extraction(
            payload=payload, model=outline.model, provider=outline.provider,
            cached=outline_cached and lines_cached, issues=issues,
        )

    def _new_run(self, doc: SourceDoc, master: CustomerMaster) -> _Run:
        budget = int(self._settings.llm_doc_budget_sec)
        run = _Run(
            doc=doc,
            master=master,
            policy=chunking.chunk_policy(master, self._settings),
            deadline=self._clock() + budget if budget > 0 else None,
            split=splits_by_shipment(master),
            extra_fields=master.extraction.get("extra_fields"),
            label=doc.filename,
        )
        _ = doc.line_count      # 줄 번호 캐시를 워커가 갈라서 만들지 않게 미리 데운다
        return run

    def read_outline(
        self, doc: SourceDoc, master: CustomerMaster
    ) -> tuple[ToolCallResult, dict[str, Any], list[chunking.Chunk], bool]:
        """OUTLINE **1회만** 부르고 청크 계획까지 돌려준다 — `(응답, 정책, 청크, 재생 여부)`.

        `parse_one.py --outline-only` 가 실물 검증 1단계로 쓴다 (호출 1회, 품목은 읽지 않는다).
        픽스처·캐시는 본 경로와 **같은 자리**(`_call_outline`)를 지나므로 같은 응답이 재사용된다.
        """
        if not (_wants_text(doc, master) and doc.has_text_layer):
            raise ScanNotSupportedError(
                "골격(OUTLINE)은 텍스트 문서에만 있습니다. 스캔본은 나누지 않고 한 번에 읽습니다."
            )
        run = self._new_run(doc, master)
        outline, cached = self._call_outline(run)
        chunks = chunking.plan(outline.payload, doc, run.policy, self._settings.llm_max_tokens)
        return outline, run.policy, chunks, cached

    def _read_chunks(
        self, run: _Run, chunks: list[chunking.Chunk], on_progress: ProgressCallback | None
    ) -> tuple[list[tuple[chunking.Chunk, dict[str, Any] | None]], dict[int, str], bool]:
        """청크를 병렬로 읽는다. **진행 콜백은 여기 이 루프(메인 스레드)에서만 부른다.**

        시간 상한을 넘으면 남은 작업을 취소하고 미완 청크는 `None`(실패)로 돌려준다.
        이미 도착한 결과는 버리지 않는다.
        """
        total = len(chunks)
        results: list[tuple[chunking.Chunk, dict[str, Any] | None]] = []
        reasons: dict[int, str] = {}
        all_cached = True
        _notify(on_progress, STAGE_LINES, 0, total, run.label)
        if not chunks:
            return results, reasons, all_cached

        def take(chunk: chunking.Chunk, outcome: _ChunkOutcome) -> None:
            nonlocal all_cached
            results.extend(outcome.parts)
            all_cached = all_cached and outcome.cached
            if outcome.reason:
                reasons[chunk.chunk_index] = outcome.reason

        workers = max(1, int(self._settings.llm_max_concurrency))
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="po2sap-chunk")
        futures: dict[Future[_ChunkOutcome], chunking.Chunk] = {
            pool.submit(self._read_chunk, run, chunk): chunk for chunk in chunks
        }
        pending = set(futures)
        done_count = 0
        try:
            while pending:
                timeout = None if run.deadline is None else run.deadline - self._clock()
                if timeout is not None and timeout <= 0:
                    break
                finished, pending = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                for fut in finished:
                    chunk = futures[fut]
                    take(chunk, _outcome_of(fut, chunk))
                    done_count += 1
                    _notify(on_progress, STAGE_LINES, done_count, total, run.label)

            # 시간 상한 — 아직 안 끝난 것은 취소한다. 실행 중인 호출은 멈출 수 없으므로
            # 기다리지 않고(wait=False) 버린다. 그 호출이 나중에 끝나도 결과는 캐시에만 남는다.
            for fut in pending:
                chunk = futures[fut]
                if fut.done():
                    take(chunk, _outcome_of(fut, chunk))
                    continue
                fut.cancel()
                results.append((chunk, None))
                reasons[chunk.chunk_index] = (
                    f"문서 처리 시간 상한({self._settings.llm_doc_budget_sec}초)을 넘겨 취소했습니다"
                )
                all_cached = False
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return results, reasons, all_cached

    def _read_chunk(self, run: _Run, chunk: chunking.Chunk) -> _ChunkOutcome:
        """워커 스레드에서 도는 함수 — **콜백을 부르지 않는다.**"""
        outcome = _ChunkOutcome()
        self._read_range(run, chunk, chunk.start, chunk.end, 0, outcome)
        return outcome

    def _read_range(
        self, run: _Run, base: chunking.Chunk, start: int, end: int, depth: int,
        outcome: _ChunkOutcome,
    ) -> None:
        """구간 하나를 읽는다. 출력이 잘리면 **절반으로 쪼개** 다시 부른다 (design §3.3.4).

        부분 결과는 쓰지 않는다. 쪼갤 깊이(`LLM_CHUNK_SPLIT_DEPTH`)를 다 쓰고도 잘리면 **그
        조각만** 실패로 두고, 함께 쪼개진 다른 조각의 결과는 살린다.
        """
        part = replace(base, start=start, end=end)
        try:
            result, cached = self._call_lines(run, base, start, end, depth)
        except LLMTruncatedError as exc:
            if depth < int(self._settings.llm_chunk_split_depth) and end > start:
                mid = (start + end) // 2
                self._read_range(run, base, start, mid, depth + 1, outcome)
                self._read_range(run, base, mid + 1, end, depth + 1, outcome)
                return
            outcome.parts.append((part, None))
            outcome.reason = outcome.reason or f"출력이 잘려 더 쪼갤 수 없었습니다: {exc}"
            outcome.cached = False
            return
        except LLMError as exc:
            outcome.parts.append((part, None))
            outcome.reason = outcome.reason or str(exc).splitlines()[0]
            outcome.cached = False
            return

        outcome.parts.append((part, result.payload))
        outcome.cached = outcome.cached and cached

    # ── 호출 1회 — 픽스처 · 캐시 · 재시도가 **여기서만** 일어난다 ────────
    def _call_outline(self, run: _Run) -> tuple[ToolCallResult, bool]:
        doc, master = run.doc, run.master
        text = doc.numbered_text()
        return self._invoke(
            master,
            pass_kind="outline",
            tool=build_outline_tool(run.extra_fields, include_shipments=run.split),
            prompt=build_outline_prompt(
                master.name, master.extraction.get("hints"), text,
                include_shipments=run.split,
            ),
            document=DocumentInput(text=text, filename=doc.filename),
            deadline=run.deadline,
            fixture=llm_cache.load_named_fixture(
                self._fixtures_dir, llm_cache.outline_fixture_name(master.code, doc.filename)
            ),
        )

    def _call_lines(
        self, run: _Run, chunk: chunking.Chunk, start: int, end: int, depth: int
    ) -> tuple[ToolCallResult, bool]:
        doc, master = run.doc, run.master
        excerpt, body = lines_text(doc, start, end, int(run.policy["header_context_lines"]))
        # 청크 픽스처는 **계획대로의 청크**(depth 0)만 가리킨다. 절단으로 쪼갠 조각은
        # 이름으로 지정할 수 없다.
        fixture = None
        if depth == 0:
            fixture = llm_cache.load_named_fixture(
                self._fixtures_dir,
                llm_cache.chunk_fixture_name(master.code, doc.filename, chunk.chunk_index),
            )
        return self._invoke(
            master,
            pass_kind="lines",
            tool=build_lines_tool(run.extra_fields),
            prompt=build_lines_prompt(
                master.name, master.extraction.get("hints"), excerpt, body, start, end
            ),
            # 캐시 키의 재료는 **그 호출에 실제로 보낸 텍스트**다 (읽을 구간 + 발췌 + 본문).
            # 구간을 넣는 것이 중요하다 — 발췌(앞머리)와 본문이 이어져 있으면 구간이 달라도
            # 텍스트가 같아질 수 있고(절반으로 쪼갠 뒤쪽 조각 = 통째 호출), 그러면 캐시가
            # 다른 질문의 답을 돌려준다.
            document=DocumentInput(
                text=f"# 읽을 구간: L{start:06d} ~ L{end:06d}\n{excerpt}\n{body}",
                filename=doc.filename,
            ),
            deadline=run.deadline,
            fixture=fixture,
        )

    def _invoke(
        self,
        master: CustomerMaster,
        *,
        pass_kind: str,
        tool: dict[str, Any],
        prompt: str,
        document: DocumentInput,
        deadline: float | None,
        fixture: ToolCallResult | None = None,
    ) -> tuple[ToolCallResult, bool]:
        """저장된 응답을 먼저 찾고, 없을 때만 실제로 호출한다. `(결과, 재생 여부)`.

        조회 순서는 픽스처 → 런타임 캐시 → 호출이다. 출력이 잘린 응답은 **저장하지 않는다.**
        """
        if fixture is not None:
            return fixture, True

        key = llm_cache.cache_key(
            document=document,
            prompt_version=self._settings.llm_prompt_version,
            customer=master.code,
            model=self._settings.model_id("extract"),
            pass_kind=pass_kind,
        )
        cached = llm_cache.load(self._cache_dir, key)
        if cached is not None:
            return cached, True

        result = self._call_provider(
            master, tool=tool, prompt=prompt, document=document, deadline=deadline
        )
        if result.stop_reason == "max_tokens":
            # 절단을 예외로 알리지 않고 결과에 담아 돌려주는 프로바이더도 같이 받는다.
            raise LLMTruncatedError("모델 출력이 max_tokens 에서 잘렸습니다.")

        # 실제 호출 결과를 저장해 두면 이후 mock 으로 무료 재생이 가능하다.
        llm_cache.save(self._cache_dir, key, result)
        return result, False

    def _call_provider(
        self,
        master: CustomerMaster,
        *,
        tool: dict[str, Any],
        prompt: str,
        document: DocumentInput,
        deadline: float | None,
    ) -> ToolCallResult:
        """5xx·타임아웃·429(`LLMTransientError`)만 `LLM_CHUNK_RETRIES` 회 다시 부른다.

        4xx 는 같은 요청이 또 거부되므로 재시도하지 않는다. 절단(`LLMTruncatedError`)도
        같은 요청을 되풀이해 봐야 또 잘리므로 여기서 재시도하지 않는다 — 쪼개는 것은 호출자다.
        """
        attempts = 1 + max(0, int(self._settings.llm_chunk_retries))
        for attempt in range(1, attempts + 1):
            if deadline is not None and self._clock() >= deadline:
                raise _BudgetExceeded(
                    f"문서 처리 시간 상한({self._settings.llm_doc_budget_sec}초)을 넘겼습니다."
                )
            try:
                return self._provider.extract(
                    system=SYSTEM_PROMPT,
                    tool=tool,
                    user_prompt=prompt,
                    document=document,
                    model_alias="extract",
                    max_tokens=self._settings.llm_max_tokens,
                    customer=master.code,
                )
            except LLMTransientError:
                if attempt >= attempts:
                    raise
                self._sleep(min(2.0 * attempt, 10.0))
        raise AssertionError("unreachable")     # pragma: no cover

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

    def health(self):
        return self._provider.health()


# ── 청크 텍스트 ────────────────────────────────────────────────────────
def lines_text(doc: SourceDoc, start: int, end: int, header_lines: int) -> tuple[str, str]:
    """LINES 호출에 보낼 `(앞머리 발췌, 구간 본문)`.

    구간만 보내면 표 머리글이 없어 컬럼을 오인하므로 문서 앞머리를 함께 붙인다. 구간이 이미
    앞머리에 걸쳐 있으면 **겹치는 줄은 발췌에서 뺀다** — 같은 줄이 두 번 나가면 모델이
    품목을 두 번 읽는다. 번호는 문서 통번호 그대로다 (`SourceDoc.numbered_text`).

    캐시 키의 재료가 되는 텍스트이므로 프롬프트에 들어가는 것과 반드시 같은 함수에서 나온다.
    """
    excerpt_end = min(header_lines, start - 1)
    excerpt = doc.numbered_text(1, excerpt_end) if excerpt_end >= 1 else ""
    return excerpt, doc.numbered_text(start, end)


def _wants_text(doc: SourceDoc, master: CustomerMaster) -> bool:
    """거래처 설정(`extraction.input`)이 텍스트 경로를 원하는가.

    `auto` 는 문서에 텍스트 레이어가 있는지 보고, `text` 는 있든 없든 텍스트를 원한다
    (없으면 호출자가 명시적으로 거부한다), `image` 는 텍스트가 있어도 이미지로 읽힌다.
    """
    mode = (master.extraction.get("input") or "auto").lower()
    return doc.has_text_layer if mode == "auto" else (mode == "text")


def _positive_int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _notify(
    callback: ProgressCallback | None, stage: str, done: int, total: int, label: str
) -> None:
    if callback is not None:
        callback(stage, done, total, label)


def _outcome_of(fut: Future[_ChunkOutcome], chunk: chunking.Chunk) -> _ChunkOutcome:
    """워커가 예상 밖의 예외로 죽어도 **그 청크만** 실패로 두고 나머지를 살린다."""
    try:
        return fut.result()
    except Exception as exc:  # noqa: BLE001
        log.exception("청크 %s 처리 중 예상하지 못한 오류", chunk.label())
        return _ChunkOutcome(
            parts=[(chunk, None)], cached=False,
            reason=f"내부 오류 {type(exc).__name__}: {exc}",
        )


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
    page: int | None = None,
    confidence: float | None = None,
) -> ExtractedValue:
    """LLM 응답의 값 1개를 ExtractedValue 로 변환 (SCHEMA.md §3.2).

    두 모양을 읽는다.
      · `{value, src, src_end?, confidence}` — header · shipment 값. **이 모양이 진짜다.**
      · 스칼라 — 품목의 평평한 값. 줄 단위 앵커(src·src_end·page·confidence)를 인자로 받아
        값마다 물려 준다 — 그래야 그라운딩이 값 단위로 그 줄을 대조한다.

    **구 형태(`evidence` · 모델이 준 `page`)는 값만 읽고 근거로 삼지 않는다.** 원문 인용에는
    줄 번호가 없어서 앵커를 만들 수 없다 — 그대로 두면 그라운딩이 🔴 로 올린다.
    `page` 는 텍스트 경로에서 `src` 로부터 `_stamp_pages` 가 채운다. 모델이 준 `page` 를
    읽어 두는 것은 **스캔 경로(줄 번호가 없는 문서)** 를 위해서다 (design §3.3.6).

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
            page=_int(data.get("page")) if data.get("page") is not None else page,
            confidence=_float(data.get("confidence")) if data.get("confidence") is not None
            else confidence,
        )
    return ExtractedValue(
        value=str(data).strip(), src=src, src_end=src_end, page=page, confidence=confidence
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
    anchor = {
        "src": src,
        "src_end": src_end,
        "page": _int(item.get("page")),
        "confidence": _float(item.get("confidence")),
    }

    def v(key: str) -> ExtractedValue:
        return _val(item.get(key), **anchor)

    return POLine(
        line_no=fallback_no,
        src=src,
        src_end=src_end,
        chunk_range=_chunk_range(item.get("chunk")),
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


def _chunk_range(data: Any) -> tuple[int, int] | None:
    """병합이 품목에 실어 보낸 읽기 구간 `[시작, 끝]` (merge.CHUNK_KEY)."""
    if not isinstance(data, list | tuple) or len(data) != 2:
        return None
    lo, hi = _int(data[0]), _int(data[1])
    return (lo, hi) if lo is not None and hi is not None else None


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
