"""파생 필드 — 다른 필드의 **최종 값**(`field.*`)으로만 정해지는 필드 (SCHEMA §3 · §4.7).

예: YGJP 의 ZSHCO = `if(in(field.ZBRAND, ["471", "507"]), "A", "L")`.

파생 필드는 `field.*` 와 상수만 쓴다(검증기가 막는다). 그래서 원문 없이도 다시
계산할 수 있고, 검수 화면에서 사람이 ZBRAND 를 바꾸면 저장할 때 ZSHCO 가 따라간다
(`batch_service.merge_edits`). 사람이 파생 필드를 **직접** 고쳤으면 덮어쓰지 않는다(P5).
"""

from __future__ import annotations

from typing import Any

from . import expr as expr_mod
from .context import EvalContext
from .primitives import FormatError, apply_format

__all__ = ["NAMESPACE", "derived_fields", "recompute"]

NAMESPACE = "field"


def _field_refs(spec: Any) -> list[str] | None:
    """`from: expr` 이고 `field.*` 를 참조하면 그 필드 이름들, 아니면 None."""
    if not isinstance(spec, dict) or spec.get("from") != "expr":
        return None
    try:
        info = expr_mod.analyze(str(spec.get("expr") or ""))
    except expr_mod.ExprError:
        return None
    if not info.ok:
        return None
    refs = [p.parts[1] for p in expr_mod.paths(info.ast) if p.root == NAMESPACE and len(p.parts) == 2]
    return refs or None


def derived_fields(fields: dict[str, Any], field_order: list[str]) -> list[str]:
    """파생 필드 이름 — 전송 필드 순서대로."""
    return [name for name in field_order if _field_refs(fields.get(name))]


def recompute(
    values: dict[str, str],
    fields: dict[str, Any],
    field_order: list[str],
    *,
    keep: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    """파생 필드를 다시 계산해 `values` 를 고친다. 바뀐 것만 돌려준다.

    `keep` 에 든 필드(사람이 직접 고친 것)는 건드리지 않는다. 계산이 실패하면
    (형식 변환 오류 등) 지금 값을 그대로 둔다 — 검증이 빈 값·형식을 따로 본다.
    """
    changed: dict[str, str] = {}
    for name in derived_fields(fields, field_order):
        if name in keep:
            continue
        spec = fields[name]
        ctx = EvalContext(fields=values)
        try:
            value = expr_mod.run(str(spec["expr"]), ctx.resolve)
            if value and spec.get("format"):
                value = apply_format(str(spec["format"]), value)
        except (expr_mod.EvalError, FormatError):
            continue
        if values.get(name, "") != value:
            values[name] = value
            changed[name] = value
    return changed
