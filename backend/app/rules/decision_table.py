"""④ TABLES — 결정표 평가 (SCHEMA.md §4.4).

행은 **위에서부터** 보고 첫 일치에서 멈춘다. 작성 순서가 곧 우선순위다.
`then` 의 `_` 접두는 파생변수로만 남고, 그 밖의 이름은 전송 필드를 바로 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import EvalContext
from .matching import compare

__all__ = ["TableOutcome", "evaluate_table"]


@dataclass
class TableOutcome:
    assignments: dict[str, str] = field(default_factory=dict)
    matched: bool = False
    severity: str = ""          # "" | "error" | "warn"
    message: str = ""


def _source_value(cond: dict[str, Any], ctx: EvalContext) -> str:
    value = ctx.resolve(str(cond.get("source") or ""))
    if (value is None or value == "") and cond.get("fallback_source"):
        value = ctx.resolve(str(cond["fallback_source"]))
    return "" if value is None else str(value)


def evaluate_table(name: str, table: dict[str, Any], ctx: EvalContext) -> TableOutcome:
    conditions = table.get("when") or []
    columns = [str(c) for c in (table.get("then") or [])]
    sources = [_source_value(c, ctx) for c in conditions]

    for row in table.get("rows") or []:
        needles = [str(x) for x in (row.get("when") or [])]
        if len(needles) != len(conditions):
            continue
        if all(
            compare(str(cond.get("op") or "equals"), source, needle)
            for cond, source, needle in zip(conditions, sources, needles, strict=True)
        ):
            values = [str(v) for v in (row.get("then") or [])]
            return TableOutcome(
                assignments=dict(zip(columns, values, strict=False)), matched=True
            )

    return _no_match(name, table, columns, ctx)


def _no_match(
    name: str, table: dict[str, Any], columns: list[str], ctx: EvalContext
) -> TableOutcome:
    spec = table.get("on_no_match") or {}
    action = str(spec.get("action") or "warn")
    message = ctx.render_message(str(spec.get("message") or f"결정표 {name} 에서 일치하는 행을 찾지 못했습니다"))

    if action == "default":
        values = [str(v) for v in (spec.get("value") or [])]
        return TableOutcome(assignments=dict(zip(columns, values, strict=False)), matched=False)
    if action == "empty":
        return TableOutcome(assignments=dict.fromkeys(columns, ""), matched=False)
    return TableOutcome(
        assignments=dict.fromkeys(columns, ""),
        matched=False,
        severity="error" if action == "error" else "warn",
        message=message,
    )
