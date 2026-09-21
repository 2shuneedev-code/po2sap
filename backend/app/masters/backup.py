"""마스터 파일을 덮어쓰기 **전에** 사본을 남긴다.

`brand_keys.csv` 는 현업이 몇 달에 걸쳐 채우는 값이고, 되돌리기 버튼이 없다.
잃는 경로가 화면에만 있는 게 아니다 — 서버에서 `git checkout .` 이나 GUI 의
"변경 취소" 한 번이면 통째로 날아간다 (CLAUDE.md §6 에 실제로 겪은 기록이 있다).

그래서 **네트워크·계정·Git 과 무관하게** 로컬에 시간 도장 사본을 남긴다.
Git 동기화(gitsync)는 그 위에 얹는 것이고, 이건 아무것도 필요 없이 항상 돈다.

사본은 `storage/master_backups/` 에 쌓인다 (Git 제외).
`git clean -xdf` 는 이 디렉터리까지 지우므로 서버에서 쓰지 않는다.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

DIR_NAME = "master_backups"


def backup_dir(storage_dir: Path) -> Path:
    return storage_dir / DIR_NAME


def snapshot(path: Path, storage_dir: Path, *, keep: int = 30) -> Path | None:
    """`path` 의 현재 내용을 사본으로 남기고 그 경로를 돌려준다.

    파일이 아직 없으면(첫 저장) 남길 것이 없으므로 `None`.
    사본을 못 남기는 상황이라면 **저장 자체를 막는다** — 되돌릴 수 없는 쓰기를
    안전망 없이 진행하는 것보다, 디스크·권한 문제를 그 자리에서 아는 편이 낫다.
    """
    if not path.exists():
        return None

    dest_dir = backup_dir(storage_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 마이크로초까지 찍는다. **모든 사본의 이름 구조가 같아야** 이름 정렬이
    # 곧 시간 정렬이 된다 — 겹칠 때만 `-1` 을 덧붙이는 식으로 하면 `-` 가 `.`
    # 보다 작아서 정렬이 뒤집히고, prune 이 최신 사본을 지운다.
    for _ in range(1000):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = dest_dir / f"{path.stem}.{stamp}{path.suffix}"
        if not dest.exists():
            break
    else:                                          # pragma: no cover
        raise OSError(f"사본 이름을 정하지 못했습니다: {dest_dir}")

    shutil.copy2(path, dest)
    prune(path, storage_dir, keep=keep)
    return dest


def history(path: Path, storage_dir: Path) -> list[Path]:
    """그 파일의 사본을 **최신순**으로. 이름의 시간 도장이 곧 정렬 키다."""
    dest_dir = backup_dir(storage_dir)
    if not dest_dir.exists():
        return []
    return sorted(
        dest_dir.glob(f"{path.stem}.*{path.suffix}"),
        key=lambda p: p.name, reverse=True,
    )


def prune(path: Path, storage_dir: Path, *, keep: int = 30) -> int:
    """오래된 사본을 지운다. `keep` 이 0 이하면 지우지 않는다."""
    if keep <= 0:
        return 0
    old = history(path, storage_dir)[keep:]
    for p in old:
        p.unlink(missing_ok=True)
    return len(old)
