"""참조표 스프레드시트 편집의 공통 규칙 — 범위 교체.

화면은 고객 한 곳을 골라 그 행만 고치거나, 아무도 안 고르고 파일 전체를 고친다.
한 곳만 고칠 때는 **그 고객 블록이 있던 자리를 지킨다** — 행 순서가 판정
우선순위이고(CLAUDE.md §5), 순서가 흔들리면 Git diff 가 읽히지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

__all__ = ["replace_scope"]


def replace_scope(
    current: list[T],
    new: list[T],
    kunnr: str | None,
    key: Callable[[T], str] = lambda r: r.kunnr,     # type: ignore[attr-defined]
) -> list[T]:
    """`kunnr` 가 없으면 `new` 가 전체다. 있으면 그 고객 행만 `new` 로 바꾼다."""
    if kunnr is None:
        return list(new)
    first = next((i for i, r in enumerate(current) if key(r) == kunnr), None)
    kept = [r for r in current if key(r) != kunnr]
    # first 앞의 행은 전부 다른 고객이라 kept 에서도 같은 자리다.
    at = len(kept) if first is None else first
    return kept[:at] + list(new) + kept[at:]
