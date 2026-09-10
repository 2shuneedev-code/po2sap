"""LLM 프로바이더 인터페이스.

바뀔 수 있는 축(API 키, 엔드포인트, 모델 ID 체계, 프록시)을 전부 이 뒤에 숨긴다.
개발용 키 → 사내 전용 계정 전환 시 **코드 변경 0줄, .env 교체만**으로 끝내는 것이 목적.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class DocumentInput:
    """LLM에 넘길 문서. 텍스트 경로와 원본(PDF) 경로 중 하나를 쓴다."""

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
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    ok: bool
    provider: str
    detail: str = ""


class LLMError(RuntimeError):
    """프로바이더 호출 실패. 사용자에게 보여줄 수 있는 메시지를 담는다."""


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
    ) -> ToolCallResult:
        """Tool Use 로 구조화 출력을 강제해 추출 결과를 반환한다."""
        ...

    def health(self) -> ProviderHealth:
        ...
