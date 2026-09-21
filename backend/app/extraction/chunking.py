"""청크 경계 계산 — design.md §3.3.3.

OUTLINE 이 돌려준 블록(출하처 구간 또는 품목표 구간)을 **LINES 호출 1회분**으로 나눈다.

  블록 먼저, 그 다음 줄 수.
    · 블록 경계를 넘는 청크는 만들지 않는다 — 한 청크의 결과가 두 오더로 갈리면 병합이 추측이 된다
    · 블록 하나를 `limit` 줄로 **균등 분할**한다. 겹침 0 · 빈틈 0. 마지막 청크만 짧아지지 않는다
    · `limit = min(max_lines_per_chunk, floor(max_tokens × safety_ratio / tokens_per_line))`

**이 모듈은 거래처를 모른다** (P2). 블록이 어디서 오는지는 OUTLINE 응답의 모양
(`shipments` 가 있는가 · `line_range` 인가)이 말해 주고, 크기는 정책 dict 가 정한다.
정책의 원천은 `masters/_base/sap_defaults.yaml` 의 `extraction_defaults.chunking` 이고
거래처가 바꾼 키는 `extraction.chunking` 에서 온다 — 합치는 곳은 `masters/loader.py` 다.

OUTLINE 은 LLM 이 만든 값이다. 블록 구간(`src`~`src_end`)은 **여기서 처음 검증된다** —
문서 밖이거나 뒤집혔거나 서로 겹치면 청크를 만들 수 없으므로 `ChunkPlanError` 를 올린다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..masters.loader import CustomerMaster, MasterError
from .preprocess import SourceDoc

__all__ = ["Chunk", "ChunkPlanError", "CHUNKING_KEYS", "chunk_policy", "plan"]

# SCHEMA.md §4.2 — 허용되는 키의 전부. validate_masters 가 같은 목록으로 검사한다.
CHUNKING_KEYS = (
    "enabled",
    "max_lines_per_chunk",
    "tokens_per_line",
    "safety_ratio",
    "header_context_lines",
)


class ChunkPlanError(ValueError):
    """OUTLINE 이 준 블록 구간을 믿을 수 없어 청크를 만들 수 없다.

    파일 하나의 실패다 (design.md §3.3.4 — 경계를 모르면 나눌 수도 없다).
    `ValueError` 라 배치 서비스가 그 파일만 FAILED 로 두고 나머지는 계속 간다.
    """


@dataclass(frozen=True)
class Chunk:
    """LINES 호출 1회분의 구간. `start`·`end` 는 문서 통번호(1-기준, 양끝 포함)다.

    shipment_index  OUTLINE 의 `shipments` 목록에서의 위치(0-기준). `line_range` 면 None
    chunk_index     문서 안 통번호(1부터). 골격·청크 픽스처의 `__c{n}` 이 이 값이다
    """

    shipment_index: int | None
    chunk_index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    def label(self) -> str:
        return f"L{self.start:06d}~L{self.end:06d}"


def chunk_policy(master: CustomerMaster, settings: Any = None) -> dict[str, Any]:
    """이 거래처의 청크 정책 — `_base` 기본값 ← 거래처 override, **키 단위 병합**.

    보통은 로더가 이미 합쳐 둔 `master.extraction["chunking"]` 을 그대로 쓴다. 이 마스터가
    `_base` 를 상속하지 않아 키가 비어 있으면 `settings.masters_dir` 의 `_base` 에서 채운다.
    그래도 없으면 **코드에 든 기본값으로 얼버무리지 않고** 실패한다 (design §3.3.3).
    """
    override = dict((master.extraction or {}).get("chunking") or {})
    missing = [k for k in CHUNKING_KEYS if k not in override]

    if missing:
        defaults = _base_defaults(settings)
        override = {**defaults, **override}
        missing = [k for k in CHUNKING_KEYS if k not in override]
    if missing:
        raise MasterError(
            "청크 정책을 알 수 없습니다: "
            f"{', '.join(missing)} — masters/_base/sap_defaults.yaml 의 "
            "extraction_defaults.chunking 에 있어야 합니다."
        )
    return {k: override[k] for k in CHUNKING_KEYS}


def _base_defaults(settings: Any) -> dict[str, Any]:
    masters_dir = getattr(settings, "masters_dir", None)
    if masters_dir is None:
        return {}
    path = Path(masters_dir) / "_base" / "sap_defaults.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict((data.get("extraction_defaults") or {}).get("chunking") or {})


def line_limit(policy: dict[str, Any], max_tokens: int) -> int:
    """청크 하나에 담을 줄 수 상한 — 줄 수 상한과 출력 토큰 상한 중 작은 쪽."""
    by_lines = int(policy["max_lines_per_chunk"])
    by_tokens = math.floor(
        max_tokens * float(policy["safety_ratio"]) / float(policy["tokens_per_line"])
    )
    return max(1, min(by_lines, by_tokens))


def plan(
    outline: dict[str, Any], doc: SourceDoc, policy: dict[str, Any], max_tokens: int
) -> list[Chunk]:
    """OUTLINE 응답 → LINES 호출 계획. 문서 순서(블록 순서 → 블록 안 위치)로 돌려준다.

    블록 목록은 `outline["shipments"]` 가 있으면 그것, 아니면 `[outline["line_range"]]` 다.
    `enabled: false` 면 블록당 청크 1개로 나누지 않는다.
    """
    blocks = _validate(_blocks(outline), doc)

    limit = line_limit(policy, max_tokens)
    enabled = bool(policy.get("enabled", True))

    chunks: list[Chunk] = []
    for shipment_index, src, end in blocks:
        length = end - src + 1
        parts = 1 if not enabled else math.ceil(length / limit)
        # 균등 분할 — 앞쪽 청크가 1줄씩 더 가져간다. 마지막만 짧아지지 않는다.
        size, extra = divmod(length, parts)
        start = src
        for i in range(parts):
            stop = start + size + (1 if i < extra else 0) - 1
            chunks.append(Chunk(shipment_index, len(chunks) + 1, start, stop))
            start = stop + 1
    return chunks


# ── 블록 추출 · 검증 ───────────────────────────────────────────────────
def _blocks(outline: dict[str, Any]) -> list[tuple[int | None, tuple[Any, Any]]]:
    shipments = outline.get("shipments")
    if shipments:
        out = []
        for i, block in enumerate(shipments):
            block = block if isinstance(block, dict) else {}
            out.append((i, (block.get("src"), block.get("src_end"))))
        return out
    rng = outline.get("line_range")
    if isinstance(rng, dict):
        return [(None, (rng.get("src"), rng.get("src_end")))]
    return []


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate(
    blocks: list[tuple[int | None, tuple[Any, Any]]], doc: SourceDoc
) -> list[tuple[int | None, int, int]]:
    """블록 구간이 문서 안이고, 뒤집히지 않았고, 서로 겹치지 않는지 본다.

    통과하면 `(shipment_index, src, end)` 정수 목록을 OUTLINE 순서 그대로 돌려준다.

    빈틈은 허용한다 — 블록 사이에 요약표·서식 줄이 있는 것이 정상이다.
    여러 문제가 있어도 한 번에 다 알려 준다 (하나 고치고 다시 돌려 또 걸리는 일을 줄인다).
    """
    problems: list[str] = []
    ranges: list[tuple[str, int, int]] = []
    clean: list[tuple[int | None, int, int]] = []

    for shipment_index, (raw_src, raw_end) in blocks:
        name = "품목표 구간(line_range)" if shipment_index is None else f"출하처 블록 {shipment_index + 1}"
        src, end = _as_int(raw_src), _as_int(raw_end)
        if src is None or end is None:
            problems.append(f"{name}: 시작·끝 줄 번호가 없습니다 (src={raw_src!r}, src_end={raw_end!r})")
            continue
        if src > end:
            problems.append(f"{name}: 시작({src})이 끝({end})보다 뒤입니다")
            continue
        if src < 1 or end > doc.line_count:
            problems.append(
                f"{name}: 구간 L{src:06d}~L{end:06d} 이 문서 범위(1~{doc.line_count}) 밖입니다"
            )
            continue
        ranges.append((name, src, end))
        clean.append((shipment_index, src, end))

    ordered = sorted(ranges, key=lambda r: (r[1], r[2]))
    for (a_name, _a_src, a_end), (b_name, b_src, _b_end) in zip(ordered, ordered[1:], strict=False):
        if b_src <= a_end:
            problems.append(f"{a_name} 과 {b_name} 의 구간이 겹칩니다 (L{b_src:06d} 이 양쪽에 있습니다)")

    if problems:
        raise ChunkPlanError(
            "골격(OUTLINE) 판독 결과의 구간을 쓸 수 없습니다 — 다시 변환해 보세요.\n  · "
            + "\n  · ".join(problems)
        )
    return clean
