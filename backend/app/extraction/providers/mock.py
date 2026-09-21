"""Mock 프로바이더 — API 호출 없이 저장된 응답을 재생한다.

용도
  · API 키가 아직 없을 때 개발 착수
  · 프론트엔드 개발 (LLM 키 불필요)
  · CI/골든 테스트 (비용 0, 결과 고정)

**저장된 응답을 찾는 일은 Extractor 가 한다.** 예전에는 이 클래스가 캐시 경로를
직접 뒤져서 Extractor 와 조회 경로가 둘로 갈렸는데, 한쪽만 고치면 조용히
어긋나므로 일원화했다. 여기까지 호출이 왔다는 것은 **재생할 응답이 없다**는 뜻이라,
무엇을 어디에 두면 되는지 알려주고 실패한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import DocumentInput, LLMError, ProviderHealth, ToolCallResult
from .cache import count, fixture_name, outline_fixture_name


class MockProvider:
    name = "mock"

    def __init__(self, cache_dir: Path, fixtures_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir
        self._fixtures_dir = fixtures_dir

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
        who = customer or "unknown"
        if self._fixtures_dir:
            doc_path = self._fixtures_dir / fixture_name(who, document.filename)
            outline_path = self._fixtures_dir / outline_fixture_name(who, document.filename)
            chunk_name = fixture_name(who, document.filename, "c{n}")
            where = (
                f"  픽스처 경로: {doc_path}\n"
                f"  (문서 단위가 없을 때만 호출 단위도 된다 — 골격 {outline_path.name} ·\n"
                f"   청크 {chunk_name}, n 은 1부터)\n"
            )
        else:
            where = ""
        raise LLMError(
            "mock 프로바이더에 재생할 응답이 없습니다.\n"
            f"  문서: {document.filename} (거래처 {customer or '?'})\n"
            f"  호출: {tool.get('name', '?')}\n"
            + where
            + f"  런타임 캐시: {self._cache_dir}/\n"
            "해결 방법:\n"
            "  1) .env 에서 LLM_PROVIDER=anthropic 으로 바꾸고 실제 파싱을 1회 실행\n"
            "     (호출마다 런타임 캐시에 저장되어 이후 mock 으로 무료 재생 가능)\n"
            "  2) 또는 위 픽스처 경로에 기대 결과 JSON 을 직접 넣기\n"
            "     형태: {\"payload\": {...추출 결과...}, \"model\": \"fixture\"}"
        )

    def health(self) -> ProviderHealth:
        dirs = [d for d in (self._cache_dir, self._fixtures_dir) if d is not None]
        return ProviderHealth(
            ok=True, provider=self.name, detail=f"재생 가능한 응답 {count(dirs)}건"
        )
