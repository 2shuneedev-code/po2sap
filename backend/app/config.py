"""애플리케이션 설정 — 환경 전환의 단일 창구.

개발 PC → 사내 서버 이관 시 코드가 아니라 이 설정(.env)만 교체한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────
    llm_provider: str = "mock"          # mock | anthropic | gateway
    llm_api_key: str = ""
    llm_base_url: str | None = None

    # 역할 별칭 → 실제 모델 ID
    llm_model_extract: str = "claude-sonnet-4-5"
    llm_model_fallback: str = "claude-opus-4-1"

    llm_max_tokens: int = 16000
    llm_timeout_sec: int = 120
    llm_max_concurrency: int = 4
    # 캐시 키에 들어간다. **Tool 스키마(schema_builder)나 SYSTEM_PROMPT 를 고치면 올린다.**
    # 안 올리면 구 스키마로 받은 캐시가 그대로 재생돼 값이 조용히 빈다.
    llm_prompt_version: str = "v2"

    # ── EAI ────────────────────────────────────────────────
    eai_endpoint: str = "http://127.0.0.1:9000/api/po2sap/salesorder"
    eai_auth_mode: str = "none"         # none | apikey | basic
    eai_api_key: str = ""
    eai_timeout_sec: int = 60
    payload_root: str = "rows"          # rows | array

    # ── 경로 ───────────────────────────────────────────────
    masters_dir: Path = _PROJECT_ROOT / "masters"
    storage_dir: Path = _PROJECT_ROOT / "storage"

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT

    @property
    def llm_cache_dir(self) -> Path:
        """실제 호출 결과가 쌓이는 런타임 캐시 (Git 제외)."""
        return self.storage_dir / "llm_cache"

    @property
    def llm_fixtures_dir(self) -> Path:
        """Git 에 커밋되는 재생용 픽스처. 새 클론에서도 mock 이 돈다."""
        return _PROJECT_ROOT / "backend" / "tests" / "fixtures" / "llm_cache"

    def model_id(self, alias: str) -> str:
        """역할 별칭('extract'/'fallback')을 실제 모델 ID로 해석."""
        mapping = {
            "extract": self.llm_model_extract,
            "fallback": self.llm_model_fallback,
        }
        if alias not in mapping:
            raise ValueError(f"알 수 없는 모델 별칭: {alias}")
        return mapping[alias]


@lru_cache
def get_settings() -> Settings:
    return Settings()
