"""배치 처리 — 업로드 → 파싱 → 규칙엔진 → 검수 행.

추출(extraction)·규칙(rules)·저장(storage)을 잇는 얇은 층이다. 판단은 각 모듈이 하고
여기서는 순서와 실패 처리만 맡는다.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

from .config import Settings
from .domain.models import Batch, BatchRow, GroundingIssue, IssueCode, RowIssue
from .extraction import Extractor
from .extraction.extractor import ProgressCallback
from .extraction.providers.base import LLMError
from .masters import MasterError, load_customer
from .rules.engine import build
from .storage import BatchRepo

__all__ = ["parse_batch", "merge_edits"]

# grounding 이 쓰는 경로 표기 — "shipments[2].lines[1].quantity" / "lines[3].item_code"
_SHIPMENT_LINE = re.compile(r"^shipments\[(\d+)\]\.lines\[(\d+)\]\.(.+)$")
_LINE = re.compile(r"^lines\[(\d+)\]\.(.+)$")
# 오더 단위 경로 — 청크 실패(CHUNK_FAILED)·빈 청크·중복 품목이 이 모양으로 온다
_SHIPMENT_ONLY = re.compile(r"^shipments\[(\d+)\]\.lines$")


def parse_batch(
    batch_id: str, settings: Settings, *, on_progress: ProgressCallback | None = None
) -> None:
    """파일별로 파싱 → 행 생성. 한 파일이 실패해도 나머지는 계속 간다.

    `on_progress(단계, 완료, 전체, 라벨)` 은 **이 함수를 부른 스레드에서만** 불린다 —
    추출기가 워커 스레드에서는 부르지 않는다. 화면(스트림릿)이 안전하게 받을 수 있다.
    """
    repo = BatchRepo(settings.storage_dir, stale_after_sec=settings.parse_stale_sec)
    batch = repo.load(batch_id)

    try:
        master = load_customer(batch.customer, settings.masters_dir)
    except MasterError as exc:
        for f in batch.files:
            f.status, f.error = "FAILED", str(exc)
        batch.status = batch.recompute_status()
        repo.save(batch)
        return

    try:
        extractor = Extractor(settings)
    except LLMError as exc:                     # 키·설정 오류 — PARSING 으로 남기지 않는다
        for f in batch.files:
            f.status, f.error = "FAILED", str(exc)
        batch.status = batch.recompute_status()
        repo.save(batch)
        return
    counter = 0

    for entry in batch.files:
        path = repo.upload_path(batch_id, entry.file_id, entry.name)
        try:
            parsed = extractor.parse_file(
                path, batch.customer, display_name=entry.name, on_progress=on_progress
            )
            result = build(parsed.raw, master, settings.masters_dir, file_name=entry.name)
            batch.columns = result.columns
            batch.grid = result.grid

            by_row = _grounding_by_row(parsed.issues, parsed.raw)
            for index, row in enumerate(result.rows):
                counter += 1
                issues = list(row.issues) + by_row.get(index, [])
                batch.rows.append(BatchRow(
                    row_id=f"r_{counter:04d}",
                    file_id=entry.file_id, file=entry.name,
                    group=row.group, line_no=row.line_no,
                    original=dict(row.fields), fields=dict(row.fields),
                    issues=_dedupe(issues),
                ))
            entry.status, entry.row_count = "DONE", len(result.rows)
            if not result.rows:
                # 행이 없으면 이슈를 붙일 곳이 없다 — 이유(구간을 못 읽음 · 품목 없음 등)가
                # 사라지지 않게 파일의 실패 사유로 올린다.
                reasons = [i.message for i in parsed.issues if i.level == "error"]
                if reasons:
                    entry.status = "FAILED"
                    entry.error = " / ".join(reasons[:3]) + (
                        f" (외 {len(reasons) - 3}건)" if len(reasons) > 3 else ""
                    )

        except (LLMError, MasterError, ValueError, FileNotFoundError) as exc:
            entry.status, entry.error, entry.row_count = "FAILED", str(exc), 0

    batch.status = batch.recompute_status()
    repo.save(batch)


def _grounding_by_row(
    issues: list[GroundingIssue], raw: Any
) -> dict[int, list[RowIssue]]:
    """근거 검증 결과를 행에 배분한다.

    라인 단위 이슈는 그 행에만 붙인다. **헤더·합계 단위는 모든 행에 붙인다** —
    헤더 값은 전 행의 BSTKD·ZBRAND 등에 쓰이므로 실제로 모든 행이 영향을 받는다.
    """
    # 행 순서는 규칙엔진의 ② SPLIT 과 같다: 출하처 순 → 그 안의 라인 순.
    positions: dict[tuple[int, int], int] = {}
    index = 0
    if raw.shipments:
        for s_idx, shipment in enumerate(raw.shipments, start=1):
            for l_idx in range(1, len(shipment.lines) + 1):
                positions[(s_idx, l_idx)] = index
                index += 1
    else:
        for l_idx in range(1, len(raw.lines) + 1):
            positions[(0, l_idx)] = index
            index += 1

    total = index
    out: dict[int, list[RowIssue]] = {}

    def add(row_index: int, issue: GroundingIssue, field: str) -> None:
        out.setdefault(row_index, []).append(RowIssue(
            field=field, severity=issue.level, code=issue.code, message=issue.message
        ))

    for issue in issues:
        only = _SHIPMENT_ONLY.match(issue.field)
        if only:
            # 오더 단위 이슈 → 그 오더의 전 행. 그 오더에 행이 하나도 없으면(구간을 통째로
            # 못 읽은 경우) 붙일 행이 없으므로 아래에서 문서 전 행에 붙인다 — 막아야 하는
            # 이슈가 조용히 사라지면 안 된다.
            rows_of = [pos for (s_idx, _l), pos in positions.items() if s_idx == int(only[1])]
            if rows_of:
                for row_index in rows_of:
                    add(row_index, issue, "")
                continue
        m = _SHIPMENT_LINE.match(issue.field) or _LINE.match(issue.field)
        if m:
            groups = m.groups()
            key = (int(groups[0]), int(groups[1])) if len(groups) == 3 else (0, int(groups[0]))
            field = groups[-1]
            target = positions.get(key)
            if target is not None:
                add(target, issue, field)
                continue
        for row_index in range(total):          # 헤더·합계·문서 단위
            add(row_index, issue, "")

    return out


def _dedupe(issues: list[RowIssue]) -> list[RowIssue]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RowIssue] = []
    for issue in issues:
        key = (issue.field, issue.code, issue.message)
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return out


def merge_edits(
    batch: Batch, incoming: list[dict[str, Any]], settings: Settings
) -> list[str]:
    """검수 화면이 보낸 값을 **서버 스냅샷에 병합**한다.

    클라이언트가 보낸 것을 그대로 받아들이지 않는다. 서버가 아는 row_id 에만,
    서버가 아는 컬럼에만 반영한다 — 없는 행을 끼워 넣거나 컬럼을 새로 만들 수 없다.
    무엇이 바뀌었는지(`edited`)는 파싱 원본과 대조해 서버가 계산한다.

    돌려주는 값은 **거부된 row_id 목록**이다.
    """
    from .validation.validator import validate_row

    master = load_customer(batch.customer, settings.masters_dir)
    field_specs = master.raw.get("field_specs") or {}
    fields = master.fields or {}
    known = {row.row_id: row for row in batch.rows}
    columns = set(batch.columns)
    rejected: list[str] = []

    for item in incoming:
        row_id = str(item.get("row_id") or "")
        row = known.get(row_id)
        if row is None:
            rejected.append(row_id or "(빈 row_id)")
            continue

        if item.get("deleted") is not None:
            row.deleted = bool(item["deleted"])

        for name, value in (item.get("fields") or {}).items():
            if name in columns:
                row.fields[name] = "" if value is None else str(value)

        row.edited = sorted(n for n in columns if row.fields.get(n, "") != row.original.get(n, ""))
        if row.deleted:
            row.issues = []
        else:
            # 값 검증은 다시 하되, **읽지 못한 구간**(CHUNK_FAILED)은 값이 아니라 행 자체가
            # 없다는 뜻이라 화면에서 고칠 수 없다. 검증 버튼으로 지워지면 빠진 품목을 안고
            # 전송이 열린다 — 서버가 들고 있는 그 이슈는 그대로 둔다 (다시 변환해야 풀린다).
            carried = [i for i in row.issues if i.code == IssueCode.CHUNK_FAILED]
            row.issues = _dedupe(carried + validate_row(row.fields, fields, field_specs))

    batch.status = batch.recompute_status()
    return rejected


def summary(batch: Batch) -> dict[str, str]:
    rows = batch.live_rows
    total = 0
    for row in rows:
        with contextlib.suppress(ValueError):
            total += int(float(row.fields.get("KWMENG") or 0))
    errors = sum(r.error_count for r in rows)
    warns = sum(len(r.issues) - r.error_count for r in rows)
    return {
        "row_count": str(len(rows)),
        "total_qty": str(total),
        "error_count": str(errors),
        "warn_count": str(warns),
    }


def upload_dir(settings: Settings, batch_id: str) -> Path:
    return Path(settings.storage_dir) / "batches" / batch_id / "uploads"
