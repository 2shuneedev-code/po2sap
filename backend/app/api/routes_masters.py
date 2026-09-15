"""마스터 조회 API — contracts/api-contract.md §1·§2·§3.

화면이 거래처를 고르면 **그 거래처의 규칙이 YAML 그대로 카드로 그려진다.**
여기서 만드는 응답은 전부 `masters/` 에서 파생된 것이고, 이 모듈에는
거래처 이름도 필드 이름도 하드코딩돼 있지 않다 (CLAUDE.md P2).

프론트는 `rules[].kind` 로 아이콘만 고르고 `columns`/`rows` 는 모양 그대로 그린다.
규칙이 바뀌면 코드를 고치지 않아도 화면이 따라온다.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings, get_settings
from ..masters import CustomerMaster, MasterError, list_customers, load_customer
from ..rules import EvalContext, EvalError, ExprError, reftable
from ..rules import expr as expr_mod

router = APIRouter(prefix="/api/masters", tags=["masters"])

# 라우트가 get_settings() 를 직접 부르면 테스트가 실제 masters/ 를 덮어쓴다.
Injected = Annotated[Settings, Depends(get_settings)]


# ── §1 거래처 목록 ────────────────────────────────────────────────────
@router.get("/customers")
def customers(settings: Injected) -> list[dict]:
    """업로드 화면의 거래처 선택 목록."""
    return [
        {
            "code": c.code,
            "name": c.name,
            "customer_no": c.customer_no,
            "file_types": c.file_types,
        }
        for c in _all(settings)
    ]


# ── §3 그리드 컬럼 정의 ───────────────────────────────────────────────
@router.get("/fields")
def fields(settings: Injected) -> dict:
    """`_base/sap_defaults.yaml` 의 `field_specs` 순서 그대로.

    개수를 세지 않는다 — 36이 34가 되어도 이 응답과 화면은 그대로 동작한다.
    """
    specs = _field_specs(_any_master(settings))
    out = []
    for name, spec in specs.items():
        item: dict[str, Any] = {"name": name, "label": str(spec.get("label") or name)}
        for key in ("sheet", "type", "max_len"):
            if spec.get(key) not in (None, ""):
                item[key] = spec[key]
        out.append(item)
    return {"fields": out}


# ── §2 규칙 카드 ──────────────────────────────────────────────────────
@router.get("/customers/{code}/preview")
def preview(code: str, settings: Injected) -> dict:
    master = _one(code, settings)
    specs = _field_specs(master)

    return {
        "code": master.code,
        "name": master.name,
        "customer_no": master.customer_no,
        "fixed": _fixed(master, specs),
        "rules": _tables(master) + _rules(master, settings),
        "split": _split(master),
        "todos": _todos(master, specs),
        "footer": "나머지 항목은 발주서에서 읽어옵니다.",
    }


# ── 조회 헬퍼 ─────────────────────────────────────────────────────────
def _all(settings: Settings) -> list[CustomerMaster]:
    try:
        return list_customers(settings.masters_dir)
    except MasterError as exc:
        raise HTTPException(500, f"거래처 설정을 읽지 못했습니다: {exc}") from exc


def _one(code: str, settings: Settings) -> CustomerMaster:
    try:
        return load_customer(code.lower(), settings.masters_dir)
    except MasterError as exc:
        raise HTTPException(404, f"거래처를 찾을 수 없습니다: {code}") from exc


def _any_master(settings: Settings) -> CustomerMaster:
    """`field_specs` 는 `_base` 가 원천이라 어느 거래처로 읽어도 같다."""
    masters = _all(settings)
    if not masters:
        raise HTTPException(500, "설정된 거래처가 없습니다")
    return masters[0]


def _field_specs(master: CustomerMaster) -> dict[str, Any]:
    specs = master.raw.get("field_specs") or {}
    if not specs:
        raise HTTPException(500, "전송 필드 스펙(_base/sap_defaults.yaml)을 읽지 못했습니다")
    return specs


def _label(specs: dict[str, Any], name: str) -> str:
    return str((specs.get(name) or {}).get("label") or name)


# ── fixed: 발주서를 읽지 않고도 이미 정해지는 값 ──────────────────────
def _fixed(master: CustomerMaster, specs: dict[str, Any]) -> list[dict]:
    """`const` · `base` · `meta` 만으로 결정되는 필드.

    `expr` 은 **참조하는 경로를 먼저 본다.** `meta.*` 만 쓰는 식이라야 고정값이다.
    평가 결과로 판단하면 안 된다 — `join("-", ["01", header.po_date, ...])` 는
    문서 값이 비어도 `"01--"` 를 내놓아서, 확정되지 않은 값이 화면에 확정된 것처럼
    찍힌다. 검수자가 그걸 믿으면 틀린 발주번호가 그대로 나간다.
    """
    defaults = master.raw.get("sap_defaults") or {}
    ctx = EvalContext(meta={"code": master.code, "customer_no": master.customer_no})

    out = []
    for name, rule in (master.fields or {}).items():
        if not isinstance(rule, dict):
            continue
        source, value = rule.get("from"), None

        if source == "const":
            value = rule.get("value")
        elif source == "base":
            value = defaults.get(name)
        elif source == "expr":
            value = _meta_only_expr(str(rule.get("expr") or ""), ctx)

        if value not in (None, ""):
            item = {"field": name, "label": _label(specs, name), "value": str(value)}
            if rule.get("explain"):
                item["note"] = str(rule["explain"])
            out.append(item)
    return out


def _meta_only_expr(source: str, ctx: EvalContext) -> str | None:
    """`meta.*` 만 참조하는 식이면 평가해 값을, 아니면 `None`.

    문서·규칙·결정표 값을 하나라도 참조하면 그 필드는 발주서를 읽어야 정해진다.
    """
    try:
        info = expr_mod.analyze(source)
        if not info.ok:
            return None
        if not all(p.dotted.startswith("meta.") for p in expr_mod.paths(info.ast)):
            return None
        return expr_mod.run(source, ctx.resolve)
    except (ExprError, EvalError):
        return None


# ── rules[]: 결정표 ───────────────────────────────────────────────────
def _tables(master: CustomerMaster) -> list[dict]:
    """`tables` 는 조건 → 결과 행렬이다. 그대로 표로 그린다."""
    out = []
    for table_id, table in (master.tables or {}).items():
        if not isinstance(table, dict):
            continue
        conds = [c for c in (table.get("when") or []) if isinstance(c, dict)]
        columns = [str(c.get("label") or c.get("source") or "") for c in conds]
        columns += [f"→ {name}" for name in (table.get("then") or [])]

        rows = []
        for row in table.get("rows") or []:
            if isinstance(row, dict):
                rows.append([str(v) for v in (row.get("when") or [])]
                            + [str(v) for v in (row.get("then") or [])])

        out.append(_card(table_id, "table", table, columns, rows))
    return out


# ── rules[]: 매핑 규칙 ────────────────────────────────────────────────
def _rules(master: CustomerMaster, settings: Settings) -> list[dict]:
    out = []
    for rule_id, rule in (master.rules or {}).items():
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("kind") or "rule")

        if kind == "csv_map":
            columns, rows = _csv_map_rows(rule, master, settings)
        elif kind in ("value_map", "keyword_map"):
            columns, rows = _entry_rows(rule)
        else:  # lookup 등 — 참조표 내용을 화면에 펼치지 않는다
            columns, rows = [], []

        out.append(_card(rule_id, kind, rule, columns, rows))
    return out


def _card(rule_id: str, kind: str, spec: dict, columns: list, rows: list) -> dict:
    card = {
        "id": rule_id,
        "kind": kind,
        "label": str(spec.get("label") or rule_id),
        "columns": columns,
        "rows": rows,
    }
    note = spec.get("note") or spec.get("description")
    if note:
        card["note"] = str(note).strip()
    return card


def _entry_rows(rule: dict) -> tuple[list[str], list[list[str]]]:
    """`entries` 를 (조건, → 값) 두 컬럼으로."""
    rows = []
    for entry in rule.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("equals") or entry.get("contains") or ""
        row = [str(key), str(entry.get("value") or "")]
        if entry.get("todo"):
            row.append(f"※ {entry['todo']}")
        rows.append(row)
    has_todo = any(len(r) > 2 for r in rows)
    columns = ["원문", "→ 코드"] + (["확인 필요"] if has_todo else [])
    return columns, [r + [""] * (len(columns) - len(r)) for r in rows]


def _csv_map_rows(
    rule: dict, master: CustomerMaster, settings: Settings
) -> tuple[list[str], list[list[str]]]:
    """참조표에서 **이 거래처 행만** 뽑아 보여준다.

    브랜드 매핑이 여기 걸린다 — 거래처를 고르면 그 거래처 브랜드가 바로 보인다.
    참조표가 없어도 화면은 떠야 하므로 실패는 빈 표로 처리한다.
    """
    key_col = str(rule.get("key_column") or "")
    value_col = str(rule.get("value_column") or "")
    mode_col = str(rule.get("mode_column") or "")
    filter_col = str(rule.get("filter_column") or "")

    try:
        table = reftable.load(settings.masters_dir, str(rule.get("table_file") or ""),
                              optional=True)
    except reftable.RefTableError:
        return [], []

    rows = []
    for entry in table:
        if filter_col and entry.get(filter_col) != master.customer_no:
            continue
        row = [entry.get(key_col, ""), entry.get(value_col, "")]
        if mode_col:
            row.append(entry.get(mode_col, ""))
        if entry.get("note"):
            row.append(entry["note"])
        rows.append(row)

    width = max((len(r) for r in rows), default=2)
    columns = (["원문", "→ 코드"] + (["비교"] if mode_col else []) + ["비고"])[:width]
    return columns, [r + [""] * (width - len(r)) for r in rows]


# ── split · todos ────────────────────────────────────────────────────
def _split(master: CustomerMaster) -> dict:
    split = master.split or {}
    by = str(split.get("by") or "none")
    return {"by": by, "label": str(split.get("label") or "")}


def _todos(master: CustomerMaster, specs: dict[str, Any]) -> list[dict]:
    """`todo:` 가 달린 곳을 모아 화면 상단에 띄운다 (CLAUDE.md P4).

    미확정 값이 있어도 개발과 파싱은 멈추지 않지만, 검수자는 알아야 한다.
    """
    out = []
    for name, rule in (master.fields or {}).items():
        if isinstance(rule, dict) and rule.get("todo"):
            out.append({"field": name, "label": _label(specs, name),
                        "note": str(rule["todo"])})
    for rule_id, rule in (master.rules or {}).items():
        if not isinstance(rule, dict):
            continue
        for entry in rule.get("entries") or []:
            if isinstance(entry, dict) and entry.get("todo"):
                out.append({"field": rule_id,
                            "label": str(rule.get("label") or rule_id),
                            "note": f"{entry.get('value', '')}: {entry['todo']}"})
    return out
