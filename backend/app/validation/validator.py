"""⑦ VALIDATE — 전송 차단 기준 (design.md §6 · SCHEMA.md §4.9).

🔴 error 가 하나라도 있으면 전송 버튼이 열리지 않는다. 사람이 고칠 수 있는
문구를 담는 것이 이 모듈의 일이다 — "무엇이 왜 안 되는지"가 화면에 그대로 나간다.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..domain.models import RowIssue, SapRow

__all__ = ["validate_row", "validate_batch", "CHECKS"]


def validate_row(
    values: dict[str, str], fields: dict[str, Any], field_specs: dict[str, Any]
) -> list[RowIssue]:
    issues: list[RowIssue] = []

    for name, value in values.items():
        spec = fields.get(name)
        if not isinstance(spec, dict):
            continue

        if spec.get("required") and not value:
            label = str((field_specs.get(name) or {}).get("label") or name)
            issues.append(RowIssue(
                field=name, severity="error", code="REQUIRED_MISSING",
                message=f"{label}({name}) 은 필수입니다. 값을 입력하세요.",
            ))

        max_len = (field_specs.get(name) or {}).get("max_len")
        if max_len and len(value) > int(max_len):
            issues.append(RowIssue(
                field=name, severity="error", code="MAX_LEN",
                message=f"{name} 은 {max_len}자를 넘을 수 없습니다 (현재 {len(value)}자).",
            ))

    return issues


# ── 거래처별 추가 검증 (SCHEMA §4.9) ───────────────────────────────────
def _shipment_total_match(rows: list[SapRow], context: dict[str, Any]) -> list[RowIssue]:
    """출하처별 수량 합계 = 문서 상단 요약표 합계.

    복수 출하처 문서에서 블록을 하나라도 놓치면 여기서 걸린다 — 놓친 오더는
    화면에 아예 나타나지 않으므로 사람 눈으로는 발견할 수 없다.
    """
    stated = _to_decimal(context.get("summary_qty"))
    if stated is None:
        return []

    total = Decimal(0)
    for row in rows:
        qty = _to_decimal(row.fields.get("KWMENG"))
        if qty is None:
            return []
        total += qty

    if total == stated:
        return []
    return [RowIssue(
        field="KWMENG", severity="error", code="TOTAL_MISMATCH",
        message=(
            f"출하처별 수량 합계({total})가 발주서 요약표 합계({stated})와 다릅니다. "
            "출하처 블록을 놓쳤을 수 있습니다."
        ),
    )]


CHECKS = {"shipment_total_match": _shipment_total_match}


def validate_batch(
    rows: list[SapRow], checks: list[dict[str, Any]], context: dict[str, Any]
) -> list[RowIssue]:
    """행 전체를 가로질러 보는 검증. 행 하나에 귀속되지 않는다."""
    issues: list[RowIssue] = []
    for check in checks or []:
        fn = CHECKS.get(str(check.get("id") or ""))
        if fn is None:
            continue
        found = fn(rows, context)
        severity = str(check.get("severity") or "error")
        for issue in found:
            issues.append(issue.model_copy(update={"severity": severity}))
    return issues


def _to_decimal(text: Any) -> Decimal | None:
    if text in (None, ""):
        return None
    try:
        return Decimal(str(text).replace(",", ""))
    except InvalidOperation:
        return None
