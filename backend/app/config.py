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

    # 역할 별칭 → 실제 모델 ID. 사내 계정에서 쓸 수 있는 모델로 .env 에서 바꾼다.
    llm_model_extract: str = "claude-opus-5"
    llm_model_fallback: str = "claude-sonnet-5"

    llm_max_tokens: int = 16000
    llm_timeout_sec: int = 120
    llm_max_concurrency: int = 4

    # 사내망 프록시 · SSL 검사 장비. **`.env` 에 `HTTPS_PROXY` 를 적는 것으로는
    # 안 된다** — pydantic-settings 는 `.env` 를 이 객체로만 읽고 `os.environ`
    # 으로 내보내지 않아서, HTTP 클라이언트가 그 값을 영영 못 본다.
    # 여기 선언해야 클라이언트에 실제로 전달된다 (anthropic_direct.py).
    llm_proxy: str = ""                 # 예: http://proxy.사내:8080
    llm_ca_bundle: str = ""             # 사내 CA 인증서 번들(.pem) 경로
    # 캐시 키에 들어간다. **Tool 스키마(schema_builder)나 SYSTEM_PROMPT 를 고치면 올린다.**
    # 안 올리면 구 스키마로 받은 캐시가 그대로 재생돼 값이 조용히 빈다.
    llm_prompt_version: str = "v2"

    # ── EAI ────────────────────────────────────────────────
    # 개발  https://eai-dev.yg1.solutions:5443/po2sap/order
    # 운영  https://eai-prd... (이관 시 .env 만 교체한다 — 코드는 그대로)
    # 기본값을 실제 서버로 두지 않는다. .env 를 깜빡한 채 돌렸다가 진짜 오더가
    # 나가면 되돌릴 수 없다. 비어 있으면 전송 단계가 명시적으로 거부한다.
    eai_endpoint: str = ""
    eai_auth_mode: str = "none"         # none | apikey | basic
    eai_api_key: str = ""
    eai_api_key_header: str = "X-API-Key"
    eai_basic_user: str = ""
    eai_basic_password: str = ""
    eai_timeout_sec: int = 60
    eai_retries: int = 3                # 5xx·타임아웃만. 4xx 는 재시도하지 않는다
    eai_max_rows_per_request: int = 0   # 0 = 무제한
    eai_verify_tls: bool = True         # 끄지 않는다. 사내 CA 는 아래로 지정
    eai_ca_bundle: str = ""             # 사내 SSL 검사 장비용 인증서 번들 경로
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

    def require_eai_endpoint(self) -> str:
        """전송 직전에 부른다. 형식이 틀리면 **보내기 전에** 막는다.

        평문 HTTP 는 루프백(모의 서버)에서만 허용한다. 사내망이라도 발주 데이터가
        평문으로 흐르면 안 되고, 요구사항도 HTTPS 다.
        """
        from urllib.parse import urlparse

        endpoint = (self.eai_endpoint or "").strip()
        if not endpoint:
            raise ValueError(
                "EAI_ENDPOINT 가 설정되지 않았습니다. .env 에 전송 주소를 넣으세요 "
                "(개발: https://eai-dev.yg1.solutions:5443/po2sap/order)."
            )

        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"EAI_ENDPOINT 형식이 올바르지 않습니다: {endpoint}")
        if parsed.scheme == "http" and (parsed.hostname or "") not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError(
                f"EAI_ENDPOINT 는 HTTPS 여야 합니다: {endpoint} "
                "(평문 http 는 로컬 모의 서버에서만 허용합니다)."
            )
        return endpoint

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
