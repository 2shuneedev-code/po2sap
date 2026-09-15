"""전송 페이로드 조립 — design.md §5.

필드 목록도 순서도 `_base/sap_defaults.yaml` 이 정한다. 이 파일에 필드 이름이
등장하지 않는다 — 36이 34가 되어도 그대로 동작해야 한다.
"""

from __future__ import annotations

from typing import Any

from ..domain.models import BatchRow

__all__ = ["build_payload", "split_rows", "row_values"]


def row_values(row: BatchRow, columns: list[str]) -> dict[str, str]:
    """`columns` 순서대로 전량. `_` 접두(화면 전용)는 애초에 들어가지 않는다."""
    return {name: str(row.fields.get(name, "")) for name in columns}


def build_payload(
    rows: list[BatchRow], columns: list[str], *, root: str = "rows"
) -> dict[str, Any] | list[dict[str, str]]:
    """`PAYLOAD_ROOT` 로 최상위 형태를 바꾼다 (EAI 쪽 규격이 확정되면 한 줄 설정)."""
    payload = [row_values(r, columns) for r in rows if not r.deleted]
    return payload if root == "array" else {"rows": payload}


def split_rows(rows: list[BatchRow], max_rows: int) -> list[list[BatchRow]]:
    """대용량 분할. 0 이면 한 번에 보낸다."""
    live = [r for r in rows if not r.deleted]
    if max_rows <= 0 or len(live) <= max_rows:
        return [live] if live else []
    return [live[i : i + max_rows] for i in range(0, len(live), max_rows)]
