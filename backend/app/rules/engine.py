"""규칙엔진 — masters/SCHEMA.md §2 의 7단계 중 ②~⑦.

    ① EXTRACT   extraction/ 가 끝내고 RawPO 를 넘겨준다
    ② SPLIT     RawPO → 오더 단위 목록                      ← split
    ③ CONTEXT   meta / header / shipment / line 조립         ← 엔진 고정
    ④ TABLES    결정표 → 파생변수(_xxx) + 전송 필드 일부      ← tables
    ⑤ RULES     매핑 규칙 → 규칙 결과                         ← rules
    ⑥ FIELDS    전송 필드 전량 렌더 → 행                      ← fields
    ⑦ VALIDATE  필수값·길이·checks                           ← fields.required, checks

거래처 이름은 이 파일 어디에도 없다(원칙 P2). 분기는 전부 마스터가 시킨다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.models import (
    BuildResult,
    ExtractedValue,
    IssueCode,
    POLine,
    POShipment,
    RawPO,
    RowIssue,
    SapRow,
)
from ..mapping.row_builder import build_row
from ..masters.loader import CustomerMaster
from ..validation.validator import validate_batch, validate_row
from . import expr as expr_mod
from .context import EvalContext
from .decision_table import evaluate_table
from .derived import recompute
from .expr import ExprError
from .mapping_rules import evaluate_rule

__all__ = ["build"]


# ── ③ CONTEXT 조립 헬퍼 ────────────────────────────────────────────────
def _flatten(model: Any) -> dict[str, str]:
    """ExtractedValue 묶음을 평평한 문자열 사전으로. 없는 값은 ''."""
    if model is None:
        return {}
    out: dict[str, str] = {}
    for name, value in model:
        if isinstance(value, ExtractedValue):
            out[name] = value.value or ""
        elif name == "extra" and isinstance(value, dict):
            for key, extra in value.items():
                out[f"extra.{key}"] = (extra.value or "") if isinstance(extra, ExtractedValue) else ""
        elif isinstance(value, (str, int)):
            out[name] = str(value)
    return out


def _order_units(raw: RawPO) -> list[tuple[POShipment | None, list[POLine]]]:
    """② SPLIT (SCHEMA §2.1).

    shipments 가 있으면 블록 하나가 오더 하나다. 이때 최상위 lines 는 문서 상단
    요약표이므로 **오더를 만들지 않는다** — 쓰면 수량이 두 배가 된다.
    """
    if raw.shipments:
        return [(s, list(s.lines)) for s in raw.shipments]
    return [(None, list(raw.lines))]


def build(
    raw: RawPO,
    master: CustomerMaster,
    masters_dir: Path,
    *,
    file_name: str = "",
) -> BuildResult:
    base = master.raw.get("sap_defaults") or {}
    field_specs = master.raw.get("field_specs") or {}
    field_order = list(field_specs)
    split = master.split or {}
    group_path = str(split.get("group_label") or "")

    meta_ns = {
        "code": master.code,
        "customer_no": master.customer_no,
        "name": master.name,
    }
    header_ns = _flatten(raw.header)

    rows: list[SapRow] = []
    counter = 0

    for shipment, lines in _order_units(raw):
        shipment_ns = _flatten(shipment)
        for line in lines:
            counter += 1
            ctx = EvalContext(
                meta=dict(meta_ns),
                header=dict(header_ns),
                shipment=dict(shipment_ns),
                line=_flatten(line),
            )

            issues: list[RowIssue] = []
            assignments = _run_tables(master, ctx, issues)      # ④
            _run_rules(master, ctx, masters_dir, issues)        # ⑤

            values, field_issues = build_row(                   # ⑥
                field_order, master.fields or {}, ctx,
                base_defaults={k: str(v) for k, v in base.items()},
                table_assignments=assignments,
            )
            issues += field_issues
            # 파생 필드(field.*)는 다른 필드가 다 정해진 뒤에 — 검수 저장 때도 같은 함수가 돈다
            recompute(values, master.fields or {}, field_order)
            issues += validate_row(values, master.fields or {}, field_specs)  # ⑦

            group = ""
            if group_path:
                resolved = ctx.resolve(group_path)
                group = "" if resolved is None else str(resolved)
            elif shipment is not None:
                group = shipment_ns.get("receiving_loc") or shipment_ns.get("shipment_no") or ""

            rows.append(SapRow(
                row_id=f"r_{counter:04d}",
                file=file_name or raw.source_file,
                group=group,
                line_no=line.line_no,
                fields=values,
                issues=issues,
            ))

    batch_issues = validate_batch(                              # ⑦ (행 가로지르기)
        rows,
        master.raw.get("checks") or [],
        {"summary_qty": raw.totals.total_qty if raw.is_split else None},
    )
    for issue in batch_issues:
        for row in rows:
            row.issues.append(issue)
    _flag_likely_missed(rows, master, field_specs)

    # `send_only` 필드는 행에 값이 들어가 전송되지만 검수 표에는 그리지 않는다.
    send_only = [n for n, s in field_specs.items() if isinstance(s, dict) and s.get("send_only")]
    grid = {**(master.grid or {}), "send_only": send_only}
    return BuildResult(rows=rows, columns=field_order, grid=grid)


def _flag_likely_missed(rows: list[SapRow], master: CustomerMaster, field_specs: dict) -> None:
    """거래처 전용 로직 필드가 **다른 행엔 다 들어갔는데** 이 행만 비면 🟡.

    원문은 같은 모양인데 한 행만 비는 것은 대개 Claude 가 그 줄을 놓친 것이다
    (예: 나눠 읽는 경계에 걸린 품목). 빈 행이 소수일 때만 — 값이 든 행이 더 많아야
    "다른 건 다 들어갔다"고 볼 수 있다. 그 칸에 이미 다른 경고가 있으면 겹쳐 달지 않는다.
    대상은 거래처 파일에 직접 적은 필드 중 고정값(const)이 아닌 것.
    """
    targets = [
        name for name in master.own_fields
        if isinstance((master.fields or {}).get(name), dict)
        and master.fields[name].get("from") != "const"
    ]
    for name in targets:
        empty = [r for r in rows if not r.fields.get(name)]
        if not empty or len(rows) - len(empty) <= len(empty):
            continue
        spec = field_specs.get(name) or {}
        label = f"{spec.get('label') or name}({spec.get('code') or name})"
        for row in empty:
            if any(i.field == name for i in row.issues):
                continue
            row.issues.append(RowIssue(
                field=name, severity="warn", code=IssueCode.LIKELY_MISSED,
                message=(
                    f"다른 행은 {label} 이 들어갔는데 이 행만 비었습니다 — "
                    "Claude 가 원문을 놓쳤을 수 있습니다. 원문을 확인하세요."
                ),
            ))


def _run_tables(master: CustomerMaster, ctx: EvalContext, issues: list[RowIssue]) -> dict[str, str]:
    """④ TABLES — 파생변수는 컨텍스트로, 전송 필드명은 렌더 단계로 넘긴다."""
    assignments: dict[str, str] = {}
    for name, table in (master.tables or {}).items():
        outcome = evaluate_table(name, table, ctx)
        for column, value in outcome.assignments.items():
            if column.startswith("_"):
                ctx.derived[column] = value
            else:
                assignments[column] = value
        if outcome.severity:
            issues.append(RowIssue(
                field=_first_field(table), severity=outcome.severity,
                code="TABLE_NO_MATCH", message=outcome.message,
            ))
    return assignments


def _first_field(table: dict[str, Any]) -> str:
    for column in table.get("then") or []:
        if not str(column).startswith("_"):
            return str(column)
    return ""


def _rules_used_as_values(master: CustomerMaster) -> set[str]:
    """필드 값에 쓰이는 규칙 — `from: rule` 이 가리키거나 식(`expr`)이 참조하는 것."""
    rules = set(master.rules or {})
    used: set[str] = set()
    for spec in (master.fields or {}).values():
        if not isinstance(spec, dict):
            continue
        if spec.get("from") == "rule":
            used.add(str(spec.get("rule") or ""))
        elif spec.get("from") == "expr":
            try:
                info = expr_mod.analyze(str(spec.get("expr") or ""))
            except ExprError:
                continue
            if info.ok:
                used.update(p.root for p in expr_mod.paths(info.ast) if p.root in rules)
    return used


def _run_rules(
    master: CustomerMaster, ctx: EvalContext, masters_dir: Path, issues: list[RowIssue]
) -> None:
    """⑤ RULES — 규칙끼리는 서로 참조할 수 없다. 조합이 필요하면 expr 에서 한다.

    경고는 **값으로 쓰이는 규칙**만 낸다. 드롭다운 후보만 주는 규칙(`choices`)이
    "후보가 7개입니다"를 내면, 전용 규칙이 이미 값을 채운 행에도 고르라는 말이 붙는다.
    """
    used = _rules_used_as_values(master)
    for name, rule in (master.rules or {}).items():
        outcome = evaluate_rule(name, rule, ctx, masters_dir)
        ctx.rules[name] = outcome.value
        if outcome.severity and name in used:
            issues.append(RowIssue(
                field="", severity=outcome.severity,
                code="RULE_NO_MATCH", message=outcome.message,
            ))
