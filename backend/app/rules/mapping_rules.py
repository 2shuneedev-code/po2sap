"""⑤ RULES — 매핑 규칙 평가 (SCHEMA.md §4.5).

규칙끼리는 서로 참조할 수 없다(순환 방지). 필요하면 `expr` 에서 조합한다.
`lookup` 과 `csv_map` 은 방향이 반대다 — 전자는 키로 찾고, 후자는 원문을 훑는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import reftable
from .context import EvalContext
from .matching import normalize

__all__ = ["RuleOutcome", "evaluate_rule"]


@dataclass
class RuleOutcome:
    value: Any = None                       # str | dict[str, str] | None
    matched: bool = False
    severity: str = ""
    message: str = ""
    extras: dict[str, str] = field(default_factory=dict)


def _source(rule: dict[str, Any], ctx: EvalContext) -> str:
    value = ctx.resolve(str(rule.get("source") or ""))
    if (value is None or value == "") and rule.get("fallback_source"):
        value = ctx.resolve(str(rule["fallback_source"]))
    return normalize("" if value is None else str(value), rule.get("normalize"))


def evaluate_rule(
    name: str, rule: dict[str, Any], ctx: EvalContext, masters_dir: Path
) -> RuleOutcome:
    kind = str(rule.get("kind") or "")

    if kind == "fixed":
        return RuleOutcome(value=str(rule.get("value", "")), matched=True)
    if kind in {"keyword_map", "value_map"}:
        return _entries_map(name, rule, ctx, kind)
    if kind == "csv_map":
        return _csv_map(name, rule, ctx, masters_dir)
    if kind == "csv_choice":
        return _csv_choice(name, rule, ctx, masters_dir)
    if kind == "lookup":
        return _lookup(name, rule, ctx, masters_dir)
    if kind == "regex_extract":
        return _regex(name, rule, ctx)

    return RuleOutcome(severity="error", message=f"규칙 {name}: 알 수 없는 kind 입니다: {kind}")


def _fold(text: str, insensitive: bool) -> str:
    return text.casefold() if insensitive else text


def _entries_map(name: str, rule: dict[str, Any], ctx: EvalContext, kind: str) -> RuleOutcome:
    source = _source(rule, ctx)
    insensitive = bool(rule.get("case_insensitive"))
    key = "contains" if kind == "keyword_map" else "equals"

    for entry in rule.get("entries") or []:
        if key not in entry:
            continue
        needle = str(entry[key])
        hit = (
            _fold(needle, insensitive) in _fold(source, insensitive)
            if kind == "keyword_map"
            else _fold(source, insensitive) == _fold(needle, insensitive)
        )
        if hit:
            return RuleOutcome(value=str(entry.get("value", "")), matched=True)

    return _no_match(name, rule, ctx)


def _csv_map(
    name: str, rule: dict[str, Any], ctx: EvalContext, masters_dir: Path
) -> RuleOutcome:
    source = _source(rule, ctx)
    insensitive = bool(rule.get("case_insensitive"))
    rows = reftable.load(masters_dir, str(rule.get("table_file") or ""), optional=True)

    filter_col = rule.get("filter_column")
    if filter_col:
        mine = ctx.meta.get("customer_no", "")
        rows = [r for r in rows if r.get(filter_col, "") == mine]

    key_col = str(rule.get("key_column") or "")
    value_col = str(rule.get("value_column") or "")
    mode_col = rule.get("mode_column")

    for row in rows:                       # 파일 순서 = 우선순위 (SCHEMA §4.5)
        needle = row.get(key_col, "")
        if not needle:
            continue
        mode = (row.get(mode_col) or "contains") if mode_col else "contains"
        hit = (
            _fold(source, insensitive) == _fold(needle, insensitive)
            if mode == "equals"
            else _fold(needle, insensitive) in _fold(source, insensitive)
        )
        if hit:
            return RuleOutcome(value=row.get(value_col, ""), matched=True)

    return _no_match(name, rule, ctx)


def _csv_choice(
    name: str, rule: dict[str, Any], ctx: EvalContext, masters_dir: Path
) -> RuleOutcome:
    """`csv_choice` — 원문을 보지 않고 이 고객의 후보 수로 판정한다 (SCHEMA §4.5).

    후보 1개면 자동으로 채우고, 0개나 2개 이상이면 비워 둔다. 여럿 중 하나를
    마스터가 짐작해 고르지 않는다 — 그건 검수 화면(사람)이 할 일이다.
    """
    rows = reftable.load(masters_dir, str(rule.get("table_file") or ""), optional=True)

    filter_col = str(rule.get("filter_column") or "")
    mine = ctx.meta.get("customer_no", "")
    rows = [r for r in rows if r.get(filter_col, "") == mine]

    value_col = str(rule.get("value_column") or "")
    label_col = rule.get("label_column")

    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    for row in rows:                       # 파일 순서 = 후보 순서 (SCHEMA §4.5)
        value = row.get(value_col, "")
        if value in seen:
            continue
        seen.add(value)
        candidates.append(row)

    count = len(candidates)
    if count == 1:
        row = candidates[0]
        extras = {}
        if label_col:
            extras["label"] = row.get(str(label_col), "")
        return RuleOutcome(value=row.get(value_col, ""), matched=True, extras=extras)

    return _choice_no_match(name, rule, ctx, "on_no_match" if count == 0 else "on_many", count)


def _choice_no_match(
    name: str, rule: dict[str, Any], ctx: EvalContext, key: str, count: int
) -> RuleOutcome:
    spec = rule.get(key) or {}
    action = str(spec.get("action") or "warn")
    raw_message = str(spec.get("message") or f"규칙 {name}: 후보가 {count}개입니다")
    message = (
        raw_message.replace("{count}", str(count))
        if key == "on_many"
        else ctx.render_message(raw_message)
    )

    if action == "empty":
        return RuleOutcome(value="", matched=False)
    return RuleOutcome(
        value="", matched=False,
        severity="error" if action == "error" else "warn",
        message=message,
    )


def _lookup(
    name: str, rule: dict[str, Any], ctx: EvalContext, masters_dir: Path
) -> RuleOutcome:
    optional = bool(rule.get("optional"))
    rows = reftable.load(masters_dir, str(rule.get("table_file") or ""), optional=optional)
    columns = [str(c) for c in (rule.get("return") or [])]

    key_value = ctx.resolve(str(rule.get("key") or ""))
    key_value = "" if key_value is None else str(key_value)
    key_col = str(rule.get("key_column") or "")

    if key_value:
        for row in rows:
            if row.get(key_col, "") == key_value:
                return RuleOutcome(value={c: row.get(c, "") for c in columns}, matched=True)

    outcome = _no_match(name, rule, ctx)
    # 참조표 규칙은 미매칭이어도 반환 키가 존재해야 한다 — expr 이 ref.b_code 를 읽는다.
    if not isinstance(outcome.value, dict):
        outcome.value = dict.fromkeys(columns, "")
    return outcome


def _regex(name: str, rule: dict[str, Any], ctx: EvalContext) -> RuleOutcome:
    source = _source(rule, ctx)
    try:
        match = re.search(str(rule.get("pattern") or ""), source)
    except re.error as exc:
        return RuleOutcome(severity="error", message=f"규칙 {name}: 정규식이 잘못됐습니다 ({exc})")

    if match:
        group = rule.get("group", 0)
        try:
            return RuleOutcome(value=match.group(group) or "", matched=True)
        except IndexError as exc:
            return RuleOutcome(
                severity="error", message=f"규칙 {name}: 없는 group 입니다: {group} ({exc})"
            )
    return _no_match(name, rule, ctx)


def _no_match(name: str, rule: dict[str, Any], ctx: EvalContext) -> RuleOutcome:
    spec = rule.get("on_no_match") or {}
    action = str(spec.get("action") or "warn")
    message = ctx.render_message(
        str(spec.get("message") or f"규칙 {name} 에서 일치하는 값을 찾지 못했습니다")
    )

    if action == "default":
        return RuleOutcome(value=spec.get("value", ""), matched=False)
    if action == "empty":
        return RuleOutcome(value="", matched=False)
    return RuleOutcome(
        value="", matched=False,
        severity="error" if action == "error" else "warn",
        message=message,
    )
