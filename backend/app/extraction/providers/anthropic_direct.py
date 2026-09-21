"""Anthropic API 직접 호출 프로바이더.

사내 게이트웨이를 쓰는 경우에도 base_url 만 바꾸면 동일하게 동작한다.
"""

from __future__ import annotations

import base64
import ssl
from pathlib import Path
from typing import Any

from ...config import Settings
from .base import (
    DocumentInput,
    LLMError,
    LLMTransientError,
    LLMTruncatedError,
    ProviderHealth,
    ToolCallResult,
)

# PDF 원본을 그대로 넘길 때의 상한 (대략치, 초과 시 텍스트 경로 권장)
_MAX_PDF_BYTES = 30 * 1024 * 1024


def _http_client(settings: Settings):
    """사내망 프록시 · SSL 검사 장비를 쓰는 경우의 HTTP 클라이언트.

    둘 다 없으면 `None` 을 돌려 SDK 기본 클라이언트를 그대로 쓴다.

    **`.env` 에 `HTTPS_PROXY` 를 적는 것으로는 안 된다.** pydantic-settings 는
    `.env` 를 Settings 객체로만 읽고 `os.environ` 으로 내보내지 않아서, httpx 가
    그 값을 영영 보지 못한다. 사내 이관에서 원인 모를 TLS/타임아웃으로 막히는
    자리라 설정을 명시적으로 받아 여기서 넘긴다.
    """
    if not (settings.llm_proxy or settings.llm_ca_bundle):
        return None

    try:
        from anthropic import DefaultHttpxClient
    except ImportError as exc:  # pragma: no cover
        raise LLMError("anthropic 패키지가 설치되지 않았습니다") from exc

    options: dict[str, Any] = {}
    if settings.llm_proxy:
        options["proxy"] = settings.llm_proxy
    if settings.llm_ca_bundle:
        bundle = Path(settings.llm_ca_bundle)
        if not bundle.exists():
            raise LLMError(
                f"LLM_CA_BUNDLE 파일이 없습니다: {bundle}\n"
                "사내 CA 인증서(.pem) 경로를 확인하세요."
            )
        # `verify=<경로 문자열>` 은 httpx2 에서 폐기됐다 — SSL 컨텍스트를 만들어 넘긴다.
        try:
            options["verify"] = ssl.create_default_context(cafile=str(bundle))
        except ssl.SSLError as exc:
            # 파일은 있는데 인증서가 아닌 경우. 원본 SSLError 만 올라가면
            # "왜 안 되지" 로 몇 시간이 간다.
            raise LLMError(
                f"LLM_CA_BUNDLE 을 인증서로 읽지 못했습니다: {bundle}\n"
                f"PEM 형식(.pem/.crt) 인지 확인하세요 — {exc}"
            ) from exc
    return DefaultHttpxClient(**options)


def _is_transient(exc: Exception) -> bool:
    """다시 시도해 볼 만한 실패인가 — 타임아웃 · 연결 끊김 · 429 · 5xx.

    SDK 예외 클래스를 임포트해 비교하지 않고 속성으로 본다. 게이트웨이가 다른 예외
    타입을 던져도 상태 코드가 있으면 같은 기준으로 판정된다.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    name = type(exc).__name__
    return "Timeout" in name or "Connection" in name


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
            # 호출 1회(청크 1개)의 상한이다. 문서 전체는 LLM_DOC_BUDGET_SEC 가 자른다.
            "timeout": float(settings.llm_timeout_sec),
            # SDK 기본(2회)에 맡기지 않고 명시한다. 기본값이 타임아웃과 곱해져
            # 최악 (1+2) × 120초 ≈ 6분이 되는 것을 눈에 보이게 하려는 것이다.
            "max_retries": int(settings.llm_max_retries),
        }
        # 사내 게이트웨이든 Anthropic 직접이든 코드는 같다. 주소만 다르다.
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url

        http_client = _http_client(settings)
        if http_client is not None:
            kwargs["http_client"] = http_client

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
        customer: str = "",
    ) -> ToolCallResult:
        model = self._settings.model_id(model_alias)
        content = self._build_content(user_prompt, document)

        try:
            # temperature 를 보내지 않는다. 현행 모델(Opus 5 · Sonnet 5 등)은
            # 샘플링 파라미터를 받지 않고 400 을 낸다. 재현성은 temperature 가 아니라
            # **응답 캐시**가 보장한다 — 같은 문서는 저장된 응답을 그대로 재생한다.
            resp = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
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
            message = f"Claude API 호출 실패: {exc}"
            if _is_transient(exc):
                raise LLMTransientError(message) from exc
            raise LLMError(message) from exc

        payload = self._extract_tool_input(resp, tool["name"])
        usage = getattr(resp, "usage", None)
        return ToolCallResult(
            payload=payload,
            model=model,
            provider=self.name,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            stop_reason=str(getattr(resp, "stop_reason", "") or ""),
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
        stop = getattr(resp, "stop_reason", "?")
        # 출력이 잘렸으면 tool_use 블록이 **있어도** 쓰지 않는다. 잘린 입력은 마지막 품목이
        # 반쪽이거나 배열이 닫히지 않은 채 SDK 가 복구한 것일 수 있다 (design.md §3.3.4).
        if stop == "max_tokens":
            raise LLMTruncatedError(
                "모델 출력이 max_tokens 에서 잘렸습니다 (stop_reason=max_tokens). "
                "부분 결과는 사용하지 않습니다."
            )
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool_name:
                return dict(getattr(block, "input", {}) or {})
        raise LLMError(
            f"모델이 구조화 결과를 반환하지 않았습니다 (stop_reason={stop}). "
            "문서가 발주서가 아니거나 판독이 불가능할 수 있습니다."
        )

    def health(self) -> ProviderHealth:
        """키와 모델 ID 가 유효한지만 본다.

        예전에는 실제 메시지를 보냈다. `/api/health` 는 화면과 모니터링이 주기적으로
        부르는 자리라 그때마다 과금됐다. 모델 조회는 토큰을 쓰지 않으면서
        **키·권한·모델 ID 세 가지를 한 번에** 확인해 준다.
        """
        model = self._settings.model_id("extract")
        try:
            info = self._client.models.retrieve(model)
            return ProviderHealth(
                ok=True, provider=self.name,
                detail=f"연결 정상 · {getattr(info, 'display_name', None) or model}",
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                ok=False, provider=self.name,
                detail=f"{exc}  (모델 ID: {model})",
            )
