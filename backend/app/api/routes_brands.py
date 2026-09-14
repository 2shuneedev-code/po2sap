"""브랜드 매핑 콘솔 API — contracts/api-contract.md §10.

화면의 일은 하나다: **발주서 원문 문구 → SAP 브랜드 코드** 를 잇는 것.
SAP 이 주는 것은 `코드 → 이름`뿐이고 원문 키는 어디에도 없다. 사람이 채운다.
그래서 이 라우터는 brand_master 를 읽기만 하고 brand_keys 만 쓴다.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..masters import CustomerMaster, MasterError, list_customers
from ..masters import brands as brand_store

router = APIRouter(prefix="/api/brands", tags=["brands"])

# 라우트가 get_settings() 를 직접 부르면 테스트가 실제 masters/ 를 덮어쓴다.
# 주입해 두면 테스트에서 사본을 가리키게 갈아끼울 수 있다.
Injected = Annotated[Settings, Depends(get_settings)]

MAX_LIMIT = 500


# ── 요청 본문 ──────────────────────────────────────────────────────────
class KeyIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    match: Literal["contains", "equals"] = "contains"
    note: str = ""


class KeysIn(BaseModel):
    keys: list[KeyIn] = Field(default_factory=list, max_length=100)


# ── 조회 헬퍼 ──────────────────────────────────────────────────────────
def _customers_by_no(settings: Settings) -> dict[str, CustomerMaster]:
    """고객코드 → 규칙이 설정된 거래처. 규칙이 없는 고객은 여기 없다."""
    try:
        return {c.customer_no: c for c in list_customers(settings.masters_dir) if c.customer_no}
    except MasterError as exc:
        raise HTTPException(500, f"거래처 설정을 읽지 못했습니다: {exc}") from exc


def _index(settings: Settings) -> tuple[dict[str, list], dict[str, str], dict[str, list]]:
    master = brand_store.load_master(settings.masters_dir)
    keys = brand_store.load_keys(settings.masters_dir)

    by_customer: dict[str, list] = {}
    names: dict[str, str] = {}
    for b in master:
        by_customer.setdefault(b.kunnr, []).append(b)
        if b.customer_name:
            names[b.kunnr] = b.customer_name

    keys_by: dict[str, list] = {}
    for k in keys:
        keys_by.setdefault(f"{k.kunnr}:{k.zbrand}", []).append(k)
    return by_customer, names, keys_by


# ── 목록 ───────────────────────────────────────────────────────────────
@router.get("/customers")
def list_brand_customers(
    settings: Injected,
    q: str = Query("", description="고객명·고객코드·거래처코드 부분 일치"),
    filter: Literal["all", "configured", "unconfigured"] = "all",
    limit: int = Query(200, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """좌측 고객 목록. 규칙이 없는 고객도 **전부** 나온다 — 브랜드부터 채워두면
    나중에 규칙을 만들 때 그대로 쓰인다."""
    by_customer, names, keys_by = _index(settings)
    configured = _customers_by_no(settings)

    rows = []
    needle = q.strip().lower()
    for kunnr in sorted(by_customer, key=lambda k: k.zfill(12)):
        cfg = configured.get(kunnr)
        if filter == "configured" and not cfg:
            continue
        if filter == "unconfigured" and cfg:
            continue

        # SAP 의 name1 이 축약형인 경우가 있다 (107525 = "KL").
        # 사람이 아는 이름은 거래처 마스터 쪽이므로 둘 다 검색 대상으로 둔다.
        sap_name = names.get(kunnr, "")
        name = cfg.name if cfg and cfg.name else sap_name
        if needle and not any(
            needle in field.lower()
            for field in (name, sap_name, kunnr, cfg.code if cfg else "")
            if field
        ):
            continue

        brands = by_customer[kunnr]
        rows.append({
            "kunnr": kunnr,
            "name": name,
            "sap_name": sap_name,
            "code": cfg.code if cfg else "",
            "file_types": cfg.file_types if cfg else [],
            "brand_count": str(len(brands)),
            "mapped_count": str(sum(1 for b in brands if keys_by.get(f"{kunnr}:{b.zbrand}"))),
        })

    return {
        "total": str(len(rows)),
        "limit": str(limit),
        "offset": str(offset),
        "customers": rows[offset : offset + limit],
    }


# ── 상세 ───────────────────────────────────────────────────────────────
@router.get("/customers/{kunnr}")
def get_brand_customer(kunnr: str, settings: Injected) -> dict[str, Any]:
    by_customer, names, keys_by = _index(settings)
    if kunnr not in by_customer:
        raise HTTPException(404, f"브랜드 마스터에 없는 고객입니다: {kunnr}")

    cfg = _customers_by_no(settings).get(kunnr)
    brands = []
    for b in by_customer[kunnr]:
        found = keys_by.get(f"{kunnr}:{b.zbrand}", [])
        brands.append({
            "zbrand": b.zbrand,
            "name": b.name,
            "keys": [
                {"text": k.text, "match": k.match, "note": k.note} for k in found
            ],
            "status": "mapped" if found else "unmapped",
        })

    sap_name = names.get(kunnr, "")
    return {
        "kunnr": kunnr,
        "name": cfg.name if cfg and cfg.name else sap_name,
        "sap_name": sap_name,
        "code": cfg.code if cfg else "",
        "file_types": cfg.file_types if cfg else [],
        "owner": (cfg.raw.get("meta", {}).get("owner", "") if cfg else ""),
        "configured": "true" if cfg else "false",
        "brands": brands,
        "logic": _logic(cfg) if cfg else None,
    }


def _logic(master: CustomerMaster) -> dict[str, Any]:
    """규칙 카드 (계약 §2 와 같은 모양: 전부 문자열의 columns/rows)."""
    split = master.split or {}
    tables = []
    for name, t in (master.tables or {}).items():
        conds = t.get("when") or []
        tables.append({
            "id": name,
            "label": str(t.get("label") or name),
            "scope": str(t.get("scope") or "header"),
            "description": str(t.get("description") or "").strip(),
            "columns": [str(c.get("label") or c.get("source") or "") for c in conds]
            + [f"→ {c}" for c in (t.get("then") or [])],
            "rows": [
                [str(v) for v in (r.get("when") or [])] + [str(v) for v in (r.get("then") or [])]
                for r in (t.get("rows") or [])
            ],
            "on_no_match": _no_match(t),
        })

    rules = []
    for name, r in (master.rules or {}).items():
        kind = str(r.get("kind") or "")
        columns: list[str] = []
        rows: list[list[str]] = []
        note = str(r.get("description") or "").strip()

        if kind in {"keyword_map", "value_map"}:
            mk = "contains" if kind == "keyword_map" else "equals"
            columns = ["원문 포함" if mk == "contains" else "원문 완전일치", "→ 값"]
            rows = [[str(e.get(mk, "")), str(e.get("value", ""))] for e in (r.get("entries") or [])]
        elif kind == "csv_map":
            # 같은 화면의 브랜드 표가 이 규칙의 내용이다 — 여기서 다시 그리지 않는다.
            note = note or f"참조표 {r.get('table_file')} 의 이 거래처 행으로 판정합니다"
        elif kind == "lookup":
            columns = ["참조표", "키", "→ 반환"]
            rows = [[
                str(r.get("table_file", "")), str(r.get("key", "")),
                ", ".join(str(x) for x in (r.get("return") or [])),
            ]]

        rules.append({
            "id": name, "kind": kind,
            "label": str(r.get("label") or name),
            "source": str(r.get("source") or ""),
            "note": note, "columns": columns, "rows": rows,
            "on_no_match": _no_match(r),
        })

    specs = master.raw.get("field_specs") or {}
    fields = []
    for name, spec in (master.fields or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("from") == "const" and not spec.get("todo") and not spec.get("explain"):
            continue                      # 고정 빈값은 화면에서 접는다
        meta = specs.get(name) or {}
        fields.append({
            "field": name,
            "label": str(meta.get("label") or ""),
            "max_len": str(meta.get("max_len") or ""),
            "source": _source(spec),
            "explain": str(spec.get("explain") or ""),
            "todo": str(spec.get("todo") or ""),
        })

    return {
        "split": {"by": str(split.get("by") or "none"),
                  "label": str(split.get("description") or split.get("label") or "").strip()},
        "tables": tables,
        "rules": rules,
        "fields": fields,
        "checks": [
            {"id": str(c.get("id", "")), "label": str(c.get("label", "")),
             "severity": str(c.get("severity", "")), "description": str(c.get("description", ""))}
            for c in (master.raw.get("checks") or [])
        ],
    }


def _no_match(spec: dict[str, Any]) -> dict[str, str]:
    nm = spec.get("on_no_match") or {}
    return {"action": str(nm.get("action") or ""), "message": str(nm.get("message") or "")}


def _source(spec: dict[str, Any]) -> str:
    kind = spec.get("from")
    if kind == "doc":
        base = f"doc · {spec.get('path')}"
        return base + (f" ← {spec['fallback']}" if spec.get("fallback") else "")
    if kind == "table":
        return f"table · {spec.get('table')}"
    if kind == "rule":
        return f"rule · {spec.get('rule')}"
    if kind == "expr":
        return str(spec.get("expr") or "")
    if kind == "gen":
        return f"gen · {spec.get('generator')}"
    if kind == "base":
        return "base · 공통 고정값"
    value = spec.get("value")
    return f"const · {'(빈값)' if value == '' else value}"


# ── 저장 ───────────────────────────────────────────────────────────────
@router.put("/customers/{kunnr}/{zbrand}")
def put_brand_keys(
    kunnr: str, zbrand: str, body: KeysIn, settings: Injected
) -> dict[str, Any]:
    """원문 키 한 묶음을 통째로 교체한다. 빈 목록이면 매핑을 지운다."""
    keys = [
        brand_store.BrandKey(kunnr=kunnr, zbrand=zbrand, match=k.match,
                             text=k.text, note=k.note)
        for k in body.keys
    ]
    try:
        saved = brand_store.set_keys(settings.masters_dir, kunnr, zbrand, keys)
    except brand_store.BrandError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "kunnr": kunnr,
        "zbrand": zbrand,
        "keys": [{"text": k.text, "match": k.match, "note": k.note} for k in saved],
        "status": "mapped" if saved else "unmapped",
    }
