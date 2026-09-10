"""FastAPI 진입점 (D1: 헬스체크 + 거래처 목록까지).

업로드/검수/전송 엔드포인트는 D3~D4에서 추가한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .extraction import Extractor
from .masters import list_customers

app = FastAPI(title="PO2SAP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    """마스터 로딩 · LLM 프로바이더 상태를 한 번에 확인한다.

    사내 서버 이관 직후 가장 먼저 호출할 엔드포인트.
    """
    settings = get_settings()

    masters_ok, masters_detail = True, ""
    try:
        customers = [c.code for c in list_customers(settings.masters_dir)]
        masters_detail = f"{len(customers)}개 거래처: {', '.join(customers)}"
    except Exception as exc:  # noqa: BLE001
        masters_ok, masters_detail = False, str(exc)

    try:
        llm = Extractor(settings).health()
        llm_status = {"ok": llm.ok, "provider": llm.provider, "detail": llm.detail}
    except Exception as exc:  # noqa: BLE001
        llm_status = {"ok": False, "provider": settings.llm_provider, "detail": str(exc)}

    return {
        "status": "ok" if masters_ok and llm_status["ok"] else "degraded",
        "masters": {"ok": masters_ok, "detail": masters_detail},
        "llm": llm_status,
        "models": {
            "extract": settings.llm_model_extract,
            "fallback": settings.llm_model_fallback,
        },
        "eai_endpoint": settings.eai_endpoint,
    }


@app.get("/api/masters/customers")
def customers() -> list[dict]:
    """업로드 화면의 거래처 선택 목록."""
    settings = get_settings()
    return [
        {
            "code": c.code,
            "name": c.name,
            "customer_no": c.customer_no,
            "file_types": c.file_types,
        }
        for c in list_customers(settings.masters_dir)
    ]
