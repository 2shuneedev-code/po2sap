"""FastAPI 진입점.

헬스체크만 여기 있고, 나머지는 api/ 아래 라우터가 맡는다
(masters · brands · batches).

계약은 contracts/api-contract.md 가 원천이다. 오류 형태도 거기 §0 을 따른다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import batches_router, brands_router, masters_router
from .config import Settings, get_settings
from .extraction import Extractor
from .masters import list_customers

app = FastAPI(title="PO2SAP", version="0.1.0")

# 라우트가 get_settings() 를 직접 부르면 테스트가 실제 masters/ 를 덮어쓴다.
Injected = Annotated[Settings, Depends(get_settings)]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(brands_router)
app.include_router(batches_router)
app.include_router(masters_router)


# ── 오류 형태 (계약 §0) ────────────────────────────────────────────────
# 프론트가 항상 같은 모양을 받도록 FastAPI 기본 {"detail": ...} 을 감싼다.
_ERROR_CODES = {
    400: "BAD_REQUEST", 404: "NOT_FOUND", 409: "CONFLICT",
    422: "INVALID_INPUT", 500: "INTERNAL_ERROR",
}


def _error(status: int, message: str) -> JSONResponse:
    code = _ERROR_CODES.get(status, "ERROR")
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(HTTPException)
def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = (exc.errors() or [{}])[0]
    where = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
    return _error(422, f"입력값이 올바르지 않습니다: {where or '요청 본문'}")


@app.get("/api/health")
def health(settings: Injected) -> dict:
    """마스터 로딩 · LLM 프로바이더 상태를 한 번에 확인한다.

    사내 서버 이관 직후 가장 먼저 호출할 엔드포인트.
    """
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
