"""스트림릿 화면이 쓰는 서비스 계층.

화면은 **백엔드 모듈을 직접 부른다.** HTTP 를 거치지 않는다 — 사내 서버에
`streamlit run` 하나만 띄우면 되고, 포트·CORS·프록시 설정이 없다.
FastAPI(`backend/app/main.py`)는 외부 연동용으로 그대로 남아 있고,
전송 같은 되돌릴 수 없는 동작은 양쪽이 **같은 함수**를 부른다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:      # `streamlit run app/main.py` 로도 임포트되게
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from backend.app.batch_service import merge_edits, parse_batch, summary  # noqa: E402
from backend.app.catalog import CatalogEntry, load_catalog  # noqa: E402
from backend.app.config import Settings, get_settings  # noqa: E402
from backend.app.domain.models import Batch, BatchFile  # noqa: E402
from backend.app.extraction import Extractor  # noqa: E402
from backend.app.masters import MasterError, load_customer  # noqa: E402
from backend.app.masters import brands as brand_store  # noqa: E402
from backend.app.preview import build_preview, field_specs  # noqa: E402
from backend.app.send_service import SendBlocked, send_batch  # noqa: E402
from backend.app.storage import BatchRepo  # noqa: E402

__all__ = [
    "Batch", "CatalogEntry", "MasterError", "SendBlocked", "Settings",
    "brand_store", "catalog", "customer_master", "field_specs_for", "health",
    "merge_edits", "preview_for", "repo", "send_batch", "settings",
    "start_batch", "summary",
]

# 업로드 안전장치 — 계약 §4 와 같은 값. 없으면 디스크가 채워지거나 파싱이 멈춘다.
MAX_FILES = 50
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def settings() -> Settings:
    return get_settings()


def repo() -> BatchRepo:
    return BatchRepo(settings().storage_dir)


@st.cache_data(ttl=30, show_spinner=False)
def catalog(q: str = "", scope: str = "all", sort: str = "name") -> list[CatalogEntry]:
    """고객 목록. 30초 캐시 — 430행을 타이핑마다 다시 훑지 않는다.

    브랜드를 저장하면 `catalog.clear()` 로 즉시 무효화한다.
    """
    return load_catalog(settings(), q=q, scope=scope, sort=sort)


def customer_master(code: str):
    return load_customer(code.lower(), settings().masters_dir)


def start_batch(code: str, uploads: list) -> Batch:
    """업로드 → 저장 → 파싱. 파싱은 여기서 **동기로** 돈다.

    FastAPI 쪽은 배경 작업으로 돌리고 화면이 폴링하지만, 스트림릿은 스크립트가
    위에서 아래로 한 번 도는 모델이라 폴링이 더 복잡하다. 진행 표시는
    호출하는 쪽이 `st.status` 로 감싼다.
    """
    _check_uploads(uploads)

    store = repo()
    batch = Batch(batch_id=store.new_id(), customer=code, status="PARSING",
                  created_at=store.now())
    for index, up in enumerate(uploads, start=1):
        file_id = f"f{index}"
        batch.files.append(BatchFile(file_id=file_id, name=up.name, status="PARSING"))
        store.save_upload(batch.batch_id, file_id, up.name, up.getvalue())
    store.save(batch)

    parse_batch(batch.batch_id, settings())
    return store.load(batch.batch_id)


def _check_uploads(uploads: list) -> None:
    if not uploads:
        raise ValueError("업로드할 파일이 없습니다.")
    if len(uploads) > MAX_FILES:
        raise ValueError(f"파일은 한 번에 {MAX_FILES}개까지입니다 ({len(uploads)}개).")
    total = 0
    for up in uploads:
        size = len(up.getvalue())
        total += size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"{up.name} 이 {MAX_FILE_BYTES // 1024 // 1024}MB 를 넘습니다.")
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f"합계가 {MAX_TOTAL_BYTES // 1024 // 1024}MB 를 넘습니다.")


def health() -> dict:
    """마스터 · LLM · EAI 주소를 한 번에 본다 (계약 §8)."""
    cfg = settings()
    out: dict = {"eai_endpoint": cfg.eai_endpoint}
    try:
        from backend.app.masters import list_customers
        codes = [c.code for c in list_customers(cfg.masters_dir)]
        out["masters"] = (True, f"{len(codes)}개 거래처: {', '.join(codes)}")
    except Exception as exc:  # noqa: BLE001
        out["masters"] = (False, str(exc))
    try:
        llm = Extractor(cfg).health()
        out["llm"] = (llm.ok, f"{llm.provider} {llm.detail}".strip())
    except Exception as exc:  # noqa: BLE001
        out["llm"] = (False, str(exc))
    return out


@st.cache_data(ttl=30, show_spinner=False)
def preview_for(code: str) -> dict:
    """규칙 카드 (계약 §2). 라우트와 **같은 함수**를 쓴다."""
    return build_preview(code, settings())


@st.cache_data(ttl=30, show_spinner=False)
def field_specs_for(code: str) -> dict:
    """전송 필드 스펙 — `_base` 가 원천이다. 개수를 세지 않는다."""
    return dict(field_specs(customer_master(code)))
