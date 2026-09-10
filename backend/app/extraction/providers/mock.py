"""Mock 프로바이더 — API 호출 없이 저장된 응답을 재생한다.

용도
  · API 키가 아직 없을 때 개발 착수
  · 프론트엔드 개발 (LLM 키 불필요)
  · CI/골든 테스트 (비용 0, 결과 고정)

응답 파일은 문서 내용 해시로 찾는다:
    storage/llm_cache/{sha256}.json
실제 호출 결과는 자동으로 이 경로에 저장되므로, 한 번 실제 파싱을 돌려두면
그 뒤로는 무료로 반복 재생할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import DocumentInput, LLMError, ProviderHealth, ToolCallResult
from .cache import cache_key, cache_path


class MockProvider:
    name = "mock"

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

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
        key = cache_key(document=document, prompt=user_prompt)
        path = cache_path(self._cache_dir, key)

        if not path.exists():
            raise LLMError(
                "mock 프로바이더에 저장된 응답이 없습니다.\n"
                f"  찾은 경로: {path}\n"
                "해결 방법:\n"
                "  1) .env 에서 LLM_PROVIDER=anthropic 으로 바꾸고 실제 파싱을 1회 실행\n"
                "     (결과가 자동 저장되어 이후 mock 으로 무료 재생 가능)\n"
                "  2) 또는 위 경로에 기대 결과 JSON 을 직접 넣기"
            )

        data = json.loads(path.read_text(encoding="utf-8"))
        return ToolCallResult(
            payload=data.get("payload", data),
            model=data.get("model", "mock"),
            provider=self.name,
        )

    def health(self) -> ProviderHealth:
        count = len(list(self._cache_dir.glob("*.json"))) if self._cache_dir.exists() else 0
        return ProviderHealth(ok=True, provider=self.name, detail=f"저장된 응답 {count}건")
