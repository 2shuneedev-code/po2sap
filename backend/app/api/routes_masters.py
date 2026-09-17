"""마스터 조회 API — contracts/api-contract.md §1·§2·§3.

규칙 카드를 만드는 일은 `app/preview.py` 가 한다 — 스트림릿 화면도 같은 함수를
부르므로 두 화면의 규칙 표시가 어긋날 자리가 없다. 여기는 HTTP 껍데기다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..catalog import load_catalog
from ..config import Settings, get_settings
from ..masters import MasterError, list_customers
from ..preview import PreviewError, build_preview, field_list

router = APIRouter(prefix="/api/masters", tags=["masters"])

# 라우트가 get_settings() 를 직접 부르면 테스트가 실제 masters/ 를 덮어쓴다.
Injected = Annotated[Settings, Depends(get_settings)]


@router.get("/customers")
def customers(settings: Injected) -> list[dict]:
    """업로드 화면의 거래처 선택 목록 — 규칙이 설정된 곳만.

    SAP 브랜드 마스터의 전 고객은 §10.1 이 준다 (`/api/brands/customers`).
    """
    try:
        return [
            {
                "code": c.code,
                "name": c.name,
                "customer_no": c.customer_no,
                "file_types": c.file_types,
            }
            for c in list_customers(settings.masters_dir)
        ]
    except MasterError as exc:
        raise HTTPException(500, f"거래처 설정을 읽지 못했습니다: {exc}") from exc


@router.get("/catalog")
def catalog(
    settings: Injected, q: str = "", scope: str = "all", sort: str = "name",
) -> dict:
    """SAP 브랜드 마스터의 **전 고객** + 규칙 설정 여부. 검색·정렬 포함.

    규칙이 없는 고객은 `code` 가 `""` 다 — 화면은 업로드를 막아야 한다.
    """
    rows = load_catalog(settings, q=q, scope=scope, sort=sort)
    return {"total": str(len(rows)), "customers": [r.as_dict() for r in rows]}


@router.get("/fields")
def fields(settings: Injected) -> dict:
    """그리드 컬럼 정의. `_base` 순서 그대로, 개수를 세지 않는다."""
    try:
        masters = list_customers(settings.masters_dir)
    except MasterError as exc:
        raise HTTPException(500, f"거래처 설정을 읽지 못했습니다: {exc}") from exc
    if not masters:
        raise HTTPException(500, "설정된 거래처가 없습니다")
    try:
        # field_specs 는 `_base` 가 원천이라 어느 거래처로 읽어도 같다.
        return {"fields": field_list(masters[0])}
    except PreviewError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/customers/{code}/preview")
def preview(code: str, settings: Injected) -> dict:
    try:
        return build_preview(code, settings)
    except PreviewError as exc:
        raise HTTPException(404, str(exc)) from exc
