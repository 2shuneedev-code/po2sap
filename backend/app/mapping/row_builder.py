"""⑥ FIELDS — 전송 필드 전부를 렌더해 행 하나를 만든다 (SCHEMA.md §4.6).

**필드 목록과 순서는 `_base/sap_defaults.yaml` 이 정한다.** 여기에 필드 이름을
적지 않는다 — 36이 34가 되어도 이 코드는 그대로여야 한다.
"""

from __future__ import annotations

from typing import Any

from ..domain.models import RowIssue
from ..rules import expr as expr_mod
from ..rules.context import EvalContext
from ..rules.primitives import FormatError, apply_format

__all__ = ["build_row", "GENERATORS"]

# `gen:` 생성기. 새 생성기가 필요하면 여기와 SCHEMA §4.6 에 함께 추가한다.
GENERATORS = {
    # 품목 순번 × 10 을 6자리로 (010 → "000010"). 앞자리 0 을 보존해야 하므로 문자열이다.
    "line_no_x10": lambda ctx: f"{int(ctx.line.get('line_no') or 0) * 10:06d}",
}


def build_row(
    field_order: list[str],
    fields: dict[str, Any],
    ctx: EvalContext,
    *,
    base_defaults: dict[str, str],
    table_assignments: dict[str, str],
) -> tuple[dict[str, str], list[RowIssue]]:
    values: dict[str, str] = {}
    issues: list[RowIssue] = []

    for name in field_order:
        spec = fields.get(name)
        if not isinstance(spec, dict):
            values[name] = ""
            issues.append(RowIssue(
                field=name, severity="error", code="FIELD_NOT_DECLARED",
                message=f"{name} 매핑이 선언되지 않았습니다.",
            ))
            continue

        value, issue = _render(name, spec, ctx, base_defaults, table_assignments)
        values[name] = value
        if issue:
            issues.append(issue)

    return values, issues


def _render(
    name: str,
    spec: dict[str, Any],
    ctx: EvalContext,
    base_defaults: dict[str, str],
    table_assignments: dict[str, str],
) -> tuple[str, RowIssue | None]:
    source = spec.get("from")

    try:
        raw = _raw_value(name, source, spec, ctx, base_defaults, table_assignments)
    except expr_mod.EvalError as exc:
        return "", RowIssue(field=name, severity="error", code="EXPR_ERROR", message=str(exc))

    text = "" if raw is None else str(raw)

    if not text and spec.get("fallback"):
        fallback = ctx.resolve(str(spec["fallback"]))
        text = "" if fallback is None else str(fallback)

    if text and spec.get("format"):
        try:
            text = apply_format(str(spec["format"]), text)
        except FormatError as exc:
            return text, RowIssue(
                field=name, severity="error", code="FORMAT_ERROR", message=str(exc)
            )

    if not text and spec.get("default") is not None:
        text = str(spec["default"])

    return text, None


def _raw_value(
    name: str,
    source: Any,
    spec: dict[str, Any],
    ctx: EvalContext,
    base_defaults: dict[str, str],
    table_assignments: dict[str, str],
) -> Any:
    if source == "const":
        return spec.get("value", "")
    if source == "base":
        return base_defaults.get(name, "")
    if source == "doc":
        return ctx.resolve(str(spec.get("path") or ""))
    if source == "table":
        return table_assignments.get(name, "")
    if source == "rule":
        result = ctx.rules.get(str(spec.get("rule") or ""))
        return "" if isinstance(result, dict) else result
    if source == "expr":
        return expr_mod.run(str(spec.get("expr") or ""), ctx.resolve)
    if source == "gen":
        generator = GENERATORS.get(str(spec.get("generator") or ""))
        if generator is None:
            raise expr_mod.EvalError(f"없는 생성기입니다: {spec.get('generator')}")
        return generator(ctx)
    raise expr_mod.EvalError(f"알 수 없는 from 입니다: {source}")
