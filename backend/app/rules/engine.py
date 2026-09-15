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
    POLine,
    POShipment,
    RawPO,
    RowIssue,
    SapRow,
)
from ..mapping.row_builder import build_row
from ..masters.loader import CustomerMaster
from ..validation.validator import validate_batch, validate_row
from .context import EvalContext
from .decision_table import evaluate_table
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

    return BuildResult(rows=rows, columns=field_order, grid=master.grid or {})


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


def _run_rules(
    master: CustomerMaster, ctx: EvalContext, masters_dir: Path, issues: list[RowIssue]
) -> None:
    """⑤ RULES — 규칙끼리는 서로 참조할 수 없다. 조합이 필요하면 expr 에서 한다."""
    for name, rule in (master.rules or {}).items():
        outcome = evaluate_rule(name, rule, ctx, masters_dir)
        ctx.rules[name] = outcome.value
        if outcome.severity:
            issues.append(RowIssue(
                field="", severity=outcome.severity,
                code="RULE_NO_MATCH", message=outcome.message,
            ))
