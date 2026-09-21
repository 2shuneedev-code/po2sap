"""청크 결과 병합 — design.md §3.3.4.

OUTLINE 응답(골격)에 LINES 청크 응답(품목)을 이어 붙여 **문서 단위 페이로드**를 만든다.
결과의 모양은 예전 "문서 1건 = 호출 1회" 응답과 같다 — `_to_raw_po` 가 그대로 읽는다.

규약 (SCHEMA.md §2.1 · design §3.3.4)
  1. shipment 순서 = OUTLINE 이 준 순서. 청크는 `(shipment_index, chunk_index)` 오름차순으로
     그 shipment 의 `lines` 에 이어 붙인다. **도착 순서(병렬 완료 순서)는 결과에 영향이 없다**
  2. `line_no` 는 병합 후에 오더 단위 안에서 1부터 다시 매긴다. 모델이 준 번호는 쓰지 않는다
  3. `POSEX` 는 건드리지 않는다 — 생성은 ⑥ FIELDS 의 몫이다
  4. 같은 `src` 가 두 번 오면 앞의 것만 남기고 🟡 `DUPLICATE_LINE`
  5. `page` 는 모델에게 묻지 않는다. `src` 로 **코드가** 계산한다 (P1)

실패한 청크(`None`)를 전체 실패로 만들지 않는다. 나머지를 살리고 🔴 `CHUNK_FAILED` 를 남긴다 —
검수 화면에는 보이고 전송은 막힌다. **메시지에 빠진 줄 범위를 적는다.**
"""

from __future__ import annotations

import copy
from typing import Any

from ..domain.models import GroundingIssue, IssueCode
from .chunking import Chunk
from .preprocess import SourceDoc

__all__ = ["merge"]

# 라인 항목에 실려 가는 **읽기 구간** — 그 줄을 어느 호출이 읽었는가.
# 그라운딩이 `src` 가 이 구간을 벗어나면 🔴 로 잡는다 (design §3.4-0).
CHUNK_KEY = "chunk"


def merge(
    outline_payload: dict[str, Any],
    chunk_results: list[tuple[Chunk, dict[str, Any] | None]],
    doc: SourceDoc,
    *,
    reasons: dict[int, str] | None = None,
) -> tuple[dict[str, Any], list[GroundingIssue]]:
    """`chunk_results` 는 `(청크, 그 응답 | 실패면 None)` 목록이다. 순서는 상관없다.

    reasons  청크 통번호 → 실패 사유. 있으면 `CHUNK_FAILED` 메시지에 덧붙인다.
    """
    payload = copy.deepcopy(outline_payload)
    payload.pop("line_range", None)
    split = bool(payload.get("shipments"))

    # 대상 리스트 — shipment 별, 또는 문서 단위 하나
    targets: dict[int | None, list[dict[str, Any]]] = {}
    if split:
        for i, block in enumerate(payload["shipments"]):
            block["lines"] = targets.setdefault(i, [])
    else:
        payload["lines"] = targets.setdefault(None, [])

    issues: list[GroundingIssue] = []
    seen: dict[int | None, set[int]] = {key: set() for key in targets}

    # 같은 청크에서 쪼개져 나온 조각(절단 재귀)도 위치 순서로 이어 붙는다 → start 가 셋째 키다.
    ordered = sorted(
        chunk_results,
        key=lambda pair: (
            -1 if pair[0].shipment_index is None else pair[0].shipment_index,
            pair[0].chunk_index,
            pair[0].start,
        ),
    )

    for chunk, result in ordered:
        target = targets.get(chunk.shipment_index)
        if target is None:
            # OUTLINE 에 없는 블록을 가리키는 청크 — 만든 쪽의 버그다. 조용히 버리지 않는다.
            raise ValueError(
                f"청크 {chunk.label()} 의 대상 블록(shipment_index={chunk.shipment_index}) 이 "
                "골격에 없습니다"
            )
        field = _field(chunk)

        if result is None:
            reason = (reasons or {}).get(chunk.chunk_index)
            issues.append(GroundingIssue(
                level="error",
                field=field,
                code=IssueCode.CHUNK_FAILED,
                message=(
                    f"{chunk.label()} 구간을 읽지 못해 이 구간의 품목이 빠졌습니다"
                    + (f" ({reason})" if reason else "")
                    + ". 다시 변환하거나 원본과 대조해 채워야 전송할 수 있습니다."
                ),
            ))
            continue

        items = [it for it in (result.get("lines") or []) if isinstance(it, dict)]
        if not items:
            issues.append(GroundingIssue(
                level="warn",
                field=field,
                code=IssueCode.EMPTY_CHUNK,
                message=(
                    f"{chunk.label()} 구간에서 품목이 하나도 나오지 않았습니다. "
                    "진짜 품목이 없는 구간이면 무시해도 됩니다."
                ),
            ))
            continue

        for item in items:
            src = _int(item.get("src"))
            if src is not None and src in seen[chunk.shipment_index]:
                issues.append(GroundingIssue(
                    level="warn",
                    field=field,
                    code=IssueCode.DUPLICATE_LINE,
                    message=(
                        f"L{src:06d} 줄이 두 번 읽혔습니다 (구간 {chunk.label()}). "
                        "뒤의 것은 버렸습니다."
                    ),
                ))
                continue
            if src is not None:
                seen[chunk.shipment_index].add(src)

            kept = dict(item)
            kept[CHUNK_KEY] = [chunk.start, chunk.end]
            kept["page"] = doc.page_of(src) if src is not None else None
            target.append(kept)

    # line_no 는 병합이 끝난 뒤 위치 순서로 — 모델이 준 번호는 청크 안에서만 센 값이다.
    for lines in targets.values():
        for number, item in enumerate(lines, start=1):
            item["line_no"] = number

    return payload, issues


def _field(chunk: Chunk) -> str:
    """그 오더 전 행에 붙도록 오더 단위 경로로 둔다 (`batch_service._grounding_by_row`).

    경로 표기는 grounding 과 같다 — 1-기준 `shipments[i].lines`.
    """
    if chunk.shipment_index is None:
        return "lines"
    return f"shipments[{chunk.shipment_index + 1}].lines"


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
