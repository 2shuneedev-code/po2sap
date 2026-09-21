"""LLM 프로바이더 인터페이스.

바뀔 수 있는 축(API 키, 엔드포인트, 모델 ID 체계, 프록시)을 전부 이 뒤에 숨긴다.
개발용 키 → 사내 전용 계정 전환 시 **코드 변경 0줄, .env 교체만**으로 끝내는 것이 목적.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class DocumentInput:
    """LLM에 넘길 문서. 텍스트 경로와 원본(PDF) 경로 중 하나를 쓴다.

    `text` 는 **그 호출에 실제로 보낸 텍스트**다 (캐시 키의 재료 — cache.py).
    청크 호출이면 문서 전체가 아니라 앞머리 발췌 + 그 구간만 담는다.
    """

    text: str | None = None
    pdf_bytes: bytes | None = None
    filename: str = ""


@dataclass
class ToolCallResult:
    payload: dict[str, Any]                  # 도구 입력 = 구조화된 추출 결과
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    # 모델이 멈춘 이유 (`end_turn` · `tool_use` · `max_tokens` …). 프로바이더가 삼키면
    # 오케스트레이터가 출력 절단을 알 방법이 없다 (design.md §3.5).
    stop_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    ok: bool
    provider: str
    detail: str = ""


class LLMError(RuntimeError):
    """프로바이더 호출 실패. 사용자에게 보여줄 수 있는 메시지를 담는다."""


class LLMTruncatedError(LLMError):
    """출력이 `max_tokens` 에서 잘렸다 (design.md §3.3.4).

    **부분 결과를 쓰지 않는다.** 잘린 JSON 은 마지막 품목이 반쪽일 수 있고, 어디까지
    믿을 수 있는지 알 방법이 없다. 호출자는 입력을 절반으로 쪼개 다시 부른다.
    """


class LLMTransientError(LLMError):
    """다시 시도하면 될 수도 있는 실패 — 5xx · 429 · 타임아웃 · 연결 끊김.

    4xx(잘못된 요청·인증)는 같은 요청이 또 거부되므로 여기 속하지 않는다.
    """


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def extract(
        self,
        *,
        system: str,
        tool: dict[str, Any],
        user_prompt: str,
        document: DocumentInput,
        model_alias: str = "extract",
        max_tokens: int = 16000,
        customer: str = "",
    ) -> ToolCallResult:
        """Tool Use 로 구조화 출력을 강제해 추출 결과를 반환한다.

        customer 는 로그·오류 메시지용 거래처 코드다. 호출 내용에는 영향을 주지 않는다.
        출력이 `max_tokens` 에서 잘리면 `LLMTruncatedError` 를 올린다.
        """
        ...

    def health(self) -> ProviderHealth:
        ...
