"""LLM_PROVIDER 설정값으로 프로바이더를 고른다."""

from __future__ import annotations

from ...config import Settings
from .base import LLMError, LLMProvider


def create_provider(settings: Settings) -> LLMProvider:
    provider = (settings.llm_provider or "mock").strip().lower()
    cache_dir = settings.storage_dir / "llm_cache"

    if provider == "mock":
        from .mock import MockProvider

        return MockProvider(cache_dir)

    if provider in {"anthropic", "gateway"}:
        # gateway = 사내 LLM 게이트웨이. Anthropic 호환 엔드포인트를 전제로 하며
        # LLM_BASE_URL 만 다르다.
        from .anthropic_direct import AnthropicProvider

        return AnthropicProvider(settings)

    raise LLMError(
        f"알 수 없는 LLM_PROVIDER: {provider} (사용 가능: mock, anthropic, gateway)"
    )
