"""Anthropic API 직접 호출 프로바이더.

사내 게이트웨이를 쓰는 경우에도 base_url 만 바꾸면 동일하게 동작한다.
"""

from __future__ import annotations

import base64
from typing import Any

from ...config import Settings
from .base import DocumentInput, LLMError, ProviderHealth, ToolCallResult

# PDF 원본을 그대로 넘길 때의 상한 (대략치, 초과 시 텍스트 경로 권장)
_MAX_PDF_BYTES = 30 * 1024 * 1024


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if not settings.llm_api_key:
            raise LLMError(
                "LLM_API_KEY 가 설정되지 않았습니다. "
                ".env 에 키를 넣거나 LLM_PROVIDER=mock 으로 개발하세요."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("anthropic 패키지가 설치되지 않았습니다: pip install anthropic") from exc

        kwargs: dict[str, Any] = {
            "api_key": settings.llm_api_key,
            "timeout": float(settings.llm_timeout_sec),
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        self._client = Anthropic(**kwargs)

    # ── 호출 ───────────────────────────────────────────────────────────
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
        model = self._settings.model_id(model_alias)
        content = self._build_content(user_prompt, document)

        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0,
                # 공통 시스템 프롬프트는 캐시 대상 (거래처 힌트는 user 쪽에 둔다)
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # noqa: BLE001 - SDK 예외를 사용자 메시지로 변환
            raise LLMError(f"Claude API 호출 실패: {exc}") from exc

        payload = self._extract_tool_input(resp, tool["name"])
        usage = getattr(resp, "usage", None)
        return ToolCallResult(
            payload=payload,
            model=model,
            provider=self.name,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )

    # ── 내부 ───────────────────────────────────────────────────────────
    @staticmethod
    def _build_content(user_prompt: str, document: DocumentInput) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []

        # 텍스트 레이어가 없는 스캔본은 PDF 원본을 그대로 넘겨 판독시킨다.
        if document.text is None and document.pdf_bytes:
            if len(document.pdf_bytes) > _MAX_PDF_BYTES:
                raise LLMError("PDF 용량이 너무 큽니다. 페이지를 분할해 주세요.")
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(document.pdf_bytes).decode(),
                    },
                }
            )

        blocks.append({"type": "text", "text": user_prompt})
        return blocks

    @staticmethod
    def _extract_tool_input(resp: Any, tool_name: str) -> dict[str, Any]:
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool_name:
                return dict(getattr(block, "input", {}) or {})
        stop = getattr(resp, "stop_reason", "?")
        raise LLMError(
            f"모델이 구조화 결과를 반환하지 않았습니다 (stop_reason={stop}). "
            "문서가 발주서가 아니거나 판독이 불가능할 수 있습니다."
        )

    def health(self) -> ProviderHealth:
        try:
            self._client.messages.create(
                model=self._settings.model_id("extract"),
                max_tokens=8,
                messages=[{"role": "user", "content": "ping"}],
            )
            return ProviderHealth(ok=True, provider=self.name, detail="연결 정상")
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(ok=False, provider=self.name, detail=str(exc))
