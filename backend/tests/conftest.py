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
