"""출력 절단 감지와 그 대응 — design.md §3.3.4. **LLM 호출 없이** 가짜 프로바이더로 본다.

  · 프로바이더는 `stop_reason == "max_tokens"` 를 (tool_use 가 있어도) 예외로 올린다
  · 추출기는 부분 결과를 쓰지 않고 그 청크를 **절반으로 쪼개** 다시 부른다
  · 쪼갤 깊이를 다 쓰면 **그 조각만** 실패하고 나머지는 산다
  · 문서 시간 상한을 넘기면 남은 청크를 취소한다
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.config import Settings
from app.extraction import Extractor
from app.extraction.providers.base import (
    LLMError,
    LLMTransientError,
    LLMTruncatedError,
    ToolCallResult,
)
from app.masters.loader import load_customer
from llm_fakes import FakeProvider, lines_payload, make_doc, outline_payload

anthropic = pytest.importorskip("anthropic")

from app.extraction.providers.anthropic_direct import (  # noqa: E402
    AnthropicProvider,
    _is_transient,
)


# ── 프로바이더 ─────────────────────────────────────────────────────────
def response(stop_reason: str, *, with_tool: bool = True):
    block = SimpleNamespace(type="tool_use", name="extract_lines", input={"lines": [{"src": 1}]})
    return SimpleNamespace(
        stop_reason=stop_reason, content=[block] if with_tool else [],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


def test_max_tokens_raises_truncated_even_when_a_tool_use_block_is_present():
    """잘린 tool_use 는 마지막 품목이 반쪽일 수 있다 — 있어도 쓰지 않는다."""
    with pytest.raises(LLMTruncatedError):
        AnthropicProvider._extract_tool_input(response("max_tokens"), "extract_lines")
    with pytest.raises(LLMTruncatedError):
        AnthropicProvider._extract_tool_input(response("max_tokens", with_tool=False), "extract_lines")


def test_a_truncation_is_an_llm_error_so_existing_handlers_still_catch_it():
    assert issubclass(LLMTruncatedError, LLMError)
    assert issubclass(LLMTransientError, LLMError)
    assert not issubclass(LLMTruncatedError, LLMTransientError)     # 같은 요청을 되풀이해도 또 잘린다


def test_a_normal_stop_returns_the_tool_input():
    out = AnthropicProvider._extract_tool_input(response("tool_use"), "extract_lines")
    assert out == {"lines": [{"src": 1}]}


def test_no_tool_use_without_truncation_is_a_plain_error():
    with pytest.raises(LLMError) as info:
        AnthropicProvider._extract_tool_input(response("end_turn", with_tool=False), "extract_lines")
    assert not isinstance(info.value, LLMTruncatedError)


class SpyAnthropic:
    """`anthropic.Anthropic` 대역 — 생성 인자를 기록하고 정해진 응답을 돌려준다."""

    kwargs: dict = {}
    reply = None

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs
        self.messages = SimpleNamespace(create=lambda **_kw: type(self).reply)


@pytest.fixture
def spy(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", SpyAnthropic)
    SpyAnthropic.kwargs, SpyAnthropic.reply = {}, response("tool_use")
    return SpyAnthropic


def provider(**over) -> AnthropicProvider:
    return AnthropicProvider(Settings(llm_provider="anthropic", llm_api_key="k", **over))


def test_the_sdk_retry_count_is_explicit_not_the_sdk_default(spy):
    """SDK 기본(2회)에 맡기면 타임아웃과 곱해져 최악 ~6분이 된다 — 설정이 그대로 전달돼야 한다."""
    provider(llm_max_retries=5, llm_timeout_sec=33)
    assert spy.kwargs["max_retries"] == 5
    assert spy.kwargs["timeout"] == 33.0
    provider()
    assert spy.kwargs["max_retries"] == Settings().llm_max_retries == 2


def test_the_stop_reason_is_carried_up_to_the_result(spy):
    result = provider().extract(
        system="s", tool={"name": "extract_lines"}, user_prompt="p",
        document=SimpleNamespace(text="t", pdf_bytes=None, filename="f"),
    )
    assert result.stop_reason == "tool_use"
    assert result.payload == {"lines": [{"src": 1}]}


def test_truncation_surfaces_from_extract(spy):
    spy.reply = response("max_tokens")
    with pytest.raises(LLMTruncatedError):
        provider().extract(
            system="s", tool={"name": "extract_lines"}, user_prompt="p",
            document=SimpleNamespace(text="t", pdf_bytes=None, filename="f"),
        )


@pytest.mark.parametrize("status,transient", [(500, True), (503, True), (429, True),
                                              (400, False), (401, False), (404, False)])
def test_only_5xx_and_429_are_transient(status, transient):
    exc = SimpleNamespace(status_code=status)
    assert _is_transient(exc) is transient          # type: ignore[arg-type]


def test_timeouts_and_connection_errors_are_transient():
    class APITimeoutError(Exception): ...
    class APIConnectionError(Exception): ...
    assert _is_transient(APITimeoutError()) and _is_transient(APIConnectionError())
    assert not _is_transient(ValueError("x"))


# ── 추출기: 절단 → 절반으로 쪼개 다시 ───────────────────────────────────
def settings(tmp_path, masters_dir, **over) -> Settings:
    base = {"llm_provider": "mock", "masters_dir": masters_dir, "storage_dir": tmp_path,
            "llm_max_concurrency": 1,           # 호출 순서를 고정해 본다
            "llm_max_tokens": 1120}             # 1120×0.7/80 = 9 줄
    return Settings(**{**base, **over})


def extractor(tmp_path, masters_dir, fake, **over) -> Extractor:
    return Extractor(settings(tmp_path, masters_dir, **over), provider=fake,
                     sleep=lambda _s: None)


def truncating(doc, limit: int):
    """`limit` 줄보다 넓은 구간이면 출력이 잘리는 모델."""
    def handler(start: int, end: int):
        if end - start + 1 > limit:
            raise LLMTruncatedError("잘림")
        return lines_payload(doc, start, end)
    return handler


def test_a_truncated_chunk_is_split_in_half_and_read_again(tmp_path, masters_dir):
    doc, blocks = make_doc([8])                     # 한 블록 · 9 줄 이하 → 청크 1개 (품목 8줄 + 제목)
    fake = FakeProvider(doc, outline_payload(doc, blocks), truncating(doc, limit=5))
    master = load_customer("msc", masters_dir)

    ex = extractor(tmp_path, masters_dir, fake).extract_payload(doc, master)

    lo, hi = blocks[0]                              # 9줄 구간 (제목 1 + 품목 8)
    # 통째로 한 번(잘림) → 절반씩 (5 · 4 줄 → 5줄은 통과)
    assert fake.line_ranges == sorted([(lo, hi), (lo, lo + 4), (lo + 5, hi)])
    assert [ln["src"] for ln in ex.payload["shipments"][0]["lines"]] == list(range(lo + 1, hi + 1))
    assert ex.issues == []


def test_no_partial_result_is_used_from_the_truncated_call(tmp_path, masters_dir):
    """잘린 호출이 품목을 돌려줬어도(일부라도) 버린다 — 쪼갠 뒤의 결과만 쓴다."""
    doc, blocks = make_doc([8])
    lo, hi = blocks[0]
    calls = []

    def handler(start, end):
        calls.append((start, end))
        if (start, end) == (lo, hi):
            raise LLMTruncatedError("잘림")           # 이 호출의 부분 결과는 존재하지 않는 것으로 친다
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = extractor(tmp_path, masters_dir, fake).extract_payload(doc, load_customer("msc", masters_dir))
    srcs = [ln["src"] for ln in ex.payload["shipments"][0]["lines"]]
    assert srcs == sorted(set(srcs)) == list(range(lo + 1, hi + 1))     # 중복도 누락도 없다


def test_depth_is_exhausted_then_only_that_piece_fails(tmp_path, masters_dir):
    """쪼갤 깊이를 다 쓰고도 잘리면 그 조각만 실패한다. 함께 쪼개진 조각·다른 청크는 산다."""
    doc, blocks = make_doc([8, 3])                  # 블록1 = 9줄(청크 1) · 블록2 = 4줄(청크 1)
    lo, hi = blocks[0]
    calls = []

    def handler(start, end):
        calls.append((start, end))
        if lo <= start <= hi and start <= lo + 1:     # 블록1 의 **앞머리**(제목 줄 근처)는 언제나 잘린다
            raise LLMTruncatedError("잘림")
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = extractor(tmp_path, masters_dir, fake, llm_chunk_split_depth=1).extract_payload(
        doc, load_customer("msc", masters_dir))

    failed = [i for i in ex.issues if i.code == "CHUNK_FAILED"]
    assert len(failed) == 1                          # 앞쪽 조각 하나만
    assert failed[0].field == "shipments[1].lines"
    assert f"L{lo:06d}~" in failed[0].message
    first, second = ex.payload["shipments"]
    assert len(first["lines"]) > 0                   # 같은 청크의 뒤쪽 조각은 살았다
    assert len(second["lines"]) == 3                 # 다른 청크는 온전하다


def test_depth_zero_means_never_split(tmp_path, masters_dir):
    doc, blocks = make_doc([8])
    fake = FakeProvider(doc, outline_payload(doc, blocks), truncating(doc, limit=2))
    ex = extractor(tmp_path, masters_dir, fake, llm_chunk_split_depth=0).extract_payload(
        doc, load_customer("msc", masters_dir))
    assert len(fake.of("extract_lines")) == 1
    assert [i.code for i in ex.issues] == ["CHUNK_FAILED"]
    assert "잘려" in ex.issues[0].message


def test_a_result_that_reports_max_tokens_without_raising_is_also_a_truncation(tmp_path, masters_dir):
    """프로바이더가 예외 대신 결과에 stop_reason 만 담아 돌려줘도 같은 취급이다."""
    doc, blocks = make_doc([4])
    lo, hi = blocks[0]

    class Reporting(FakeProvider):
        def extract(self, **kw):
            result = super().extract(**kw)
            span = kw["user_prompt"]
            if kw["tool"]["name"] == "extract_lines" and f"L{lo:06d} ~ L{hi:06d}" in span:
                return ToolCallResult(payload={"lines": []}, stop_reason="max_tokens",
                                      model="m", provider="fake")
            return result

    fake = Reporting(doc, outline_payload(doc, blocks))
    ex = extractor(tmp_path, masters_dir, fake).extract_payload(doc, load_customer("msc", masters_dir))
    assert (lo, hi) in fake.line_ranges and len(fake.line_ranges) > 1      # 쪼개서 다시 불렸다
    assert ex.issues == []


def test_a_truncated_response_is_never_written_to_the_cache(tmp_path, masters_dir):
    """캐시에는 골격 1개 + 잘리지 않은 절반 2개만 있다 — 잘린 통째 호출은 저장되지 않는다."""
    doc, blocks = make_doc([8])
    fake = FakeProvider(doc, outline_payload(doc, blocks), truncating(doc, limit=5))
    extractor(tmp_path, masters_dir, fake).extract_payload(doc, load_customer("msc", masters_dir))
    assert len(fake.of("extract_lines")) == 3                      # 통째(잘림) + 절반 둘
    assert len(list((tmp_path / "llm_cache").glob("*.json"))) == 1 + 2

    # 같은 캐시로 다시 — 절반들은 캐시에서 나오고, 잘리는 통째 호출을 다시 부르지도 않는다
    again = FakeProvider(doc, outline_payload(doc, blocks), truncating(doc, limit=5))
    extractor(tmp_path, masters_dir, again).extract_payload(doc, load_customer("msc", masters_dir))
    assert [c.kind for c in again.calls] == ["extract_lines"]      # 통째 1번만 (다시 잘려 쪼갠다)


# ── 재시도: 5xx·타임아웃만 ─────────────────────────────────────────────
def test_transient_errors_are_retried_a_configured_number_of_times(tmp_path, masters_dir):
    doc, blocks = make_doc([3])
    attempts = []

    def handler(start, end):
        attempts.append((start, end))
        if len(attempts) < 2:
            raise LLMTransientError("503")
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = extractor(tmp_path, masters_dir, fake, llm_chunk_retries=1).extract_payload(
        doc, load_customer("msc", masters_dir))
    assert len(attempts) == 2 and ex.issues == []


def test_retries_run_out_and_the_chunk_fails(tmp_path, masters_dir):
    doc, blocks = make_doc([3])

    def handler(start, end):
        raise LLMTransientError("503")

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = extractor(tmp_path, masters_dir, fake, llm_chunk_retries=2).extract_payload(
        doc, load_customer("msc", masters_dir))
    assert len(fake.of("extract_lines")) == 3                    # 1 + 재시도 2
    assert [i.code for i in ex.issues] == ["CHUNK_FAILED"]


def test_a_client_error_is_not_retried(tmp_path, masters_dir):
    """4xx 는 같은 요청이 또 거부된다."""
    doc, blocks = make_doc([3])

    def handler(start, end):
        raise LLMError("400 bad request")

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = extractor(tmp_path, masters_dir, fake, llm_chunk_retries=5).extract_payload(
        doc, load_customer("msc", masters_dir))
    assert len(fake.of("extract_lines")) == 1
    assert "400" in ex.issues[0].message


# ── 문서 시간 상한 ─────────────────────────────────────────────────────
class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_nothing_is_called_once_the_budget_is_spent(tmp_path, masters_dir):
    """골격을 읽느라 시간을 다 썼다면 품목 호출은 하나도 하지 않는다."""
    doc, blocks = make_doc([8, 8, 8])
    clock = Clock()
    fake = FakeProvider(doc, outline_payload(doc, blocks))
    original = fake.extract

    def outline_is_slow(**kw):
        result = original(**kw)
        clock.now += 1000                            # 골격 호출이 예산을 다 먹었다 (메인 스레드)
        return result

    fake.extract = outline_is_slow                   # type: ignore[method-assign]
    ex = Extractor(settings(tmp_path, masters_dir, llm_doc_budget_sec=15), provider=fake,
                   clock=clock, sleep=lambda _s: None).extract_payload(
        doc, load_customer("msc", masters_dir))

    assert fake.of("extract_lines") == []
    failed = [i for i in ex.issues if i.code == "CHUNK_FAILED"]
    assert len(failed) == 3 and all("시간 상한" in i.message for i in failed)
    assert [len(s["lines"]) for s in ex.payload["shipments"]] == [0, 0, 0]


def test_the_budget_cancels_calls_still_in_flight_and_keeps_what_arrived(tmp_path, masters_dir):
    """끝난 청크는 산다. 아직 응답이 없는 호출은 기다리지 않고 취소한다 (멈춘 호출에 묶이지 않는다)."""
    import threading
    import time

    doc, blocks = make_doc([8, 8, 8, 8])            # 청크 4개
    release = threading.Event()
    firsts = {blocks[0][0], blocks[1][0]}

    def handler(start, end):
        if start not in firsts:
            release.wait(30)                         # 셋째·넷째는 응답이 오지 않는다
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    started = time.monotonic()
    try:
        ex = Extractor(settings(tmp_path, masters_dir, llm_max_concurrency=4, llm_doc_budget_sec=1),
                       provider=fake, sleep=lambda _s: None).extract_payload(
            doc, load_customer("msc", masters_dir))
        elapsed = time.monotonic() - started
    finally:
        release.set()                                # 남은 스레드를 풀어 준다

    assert elapsed < 10                              # 멈춘 호출(30초)을 기다리지 않았다
    assert [len(s["lines"]) for s in ex.payload["shipments"]] == [8, 8, 0, 0]
    failed = [i for i in ex.issues if i.code == "CHUNK_FAILED"]
    assert [i.field for i in failed] == ["shipments[3].lines", "shipments[4].lines"]
    assert all("시간 상한" in i.message for i in failed)


def test_a_zero_budget_means_no_limit(tmp_path, masters_dir):
    doc, blocks = make_doc([3, 3])
    clock = Clock()

    def handler(start, end):
        clock.now += 10_000
        return lines_payload(doc, start, end)

    fake = FakeProvider(doc, outline_payload(doc, blocks), handler)
    ex = Extractor(settings(tmp_path, masters_dir, llm_doc_budget_sec=0), provider=fake,
                   clock=clock, sleep=lambda _s: None).extract_payload(
        doc, load_customer("msc", masters_dir))
    assert ex.issues == []
