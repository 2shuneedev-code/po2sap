"""테스트 공통 설정.

전 테스트가 LLM 을 호출하지 않는다. 실제 호출이 필요한 테스트는 없다 —
추출 결과는 backend/tests/fixtures/llm_cache/ 의 픽스처로 재생한다 (비용 0).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))          # 스트림릿 화면(app/) 테스트용

# 실수로라도 실제 API 를 때리지 않도록 못을 박는다.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.pop("LLM_API_KEY", None)


@pytest.fixture(autouse=True, scope="session")
def _ignore_local_env_file():
    """테스트가 개발자의 `.env` 를 읽지 않게 한다.

    `Settings` 는 `_PROJECT_ROOT/.env` 를 읽는다. 그대로 두면 **내 체크아웃에
    `.env` 가 없어서 통과하고, `.env` 가 있는 사람 환경에서는 깨진다** — CI 는
    초록인데 사용자만 빨간, 가장 찾기 어려운 부류다 (2026-09-20 에 실제로 그랬다:
    `.env.example` 의 `LLM_BASE_URL=` 이 `None` 이 아니라 `""` 로 들어왔다).

    테스트는 기본값과 명시적으로 넘긴 값만 본다.
    """
    from app.config import Settings

    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def masters_dir() -> Path:
    return ROOT / "masters"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def validate_masters():
    """scripts/validate_masters.py 를 모듈로 불러온다 (문서에 적힌 경로를 유지)."""
    path = ROOT / "scripts" / "validate_masters.py"
    spec = importlib.util.spec_from_file_location("validate_masters", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # exec 전에 등록해야 한다 — 모듈 안의 @dataclass 가 sys.modules 를 되짚는다.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
