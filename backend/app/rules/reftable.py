"""참조표(CSV) 로더 — masters/refs/*.csv.

파일이 바뀌면 자동으로 다시 읽는다(mtime 을 캐시 키에 포함). 규칙을 고치는 동안
서버를 재시작하지 않아도 되고, 운영 중에는 사실상 메모리 조회다.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

__all__ = ["RefTableError", "load"]


class RefTableError(ValueError):
    pass


@lru_cache(maxsize=64)
def _read(path_str: str, mtime: float) -> tuple[dict[str, str], ...]:
    with Path(path_str).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RefTableError(f"참조표에 머리글이 없습니다: {path_str}")
        return tuple(
            {(k or ""): (v or "").strip() for k, v in row.items()} for row in reader
        )


def load(masters_dir: Path, rel_path: str, *, optional: bool = False) -> list[dict[str, str]]:
    """참조표를 읽는다. `optional` 이면 파일이 없어도 빈 목록으로 동작한다."""
    path = Path(masters_dir) / rel_path
    if not path.exists():
        if optional:
            return []
        raise RefTableError(f"참조표 파일이 없습니다: {rel_path}")
    return list(_read(str(path), path.stat().st_mtime))
