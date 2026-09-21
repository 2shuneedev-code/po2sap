"""저장소에 소스가 빠져 있지 않은지.

`.gitignore` 에 `storage/` 라고만 쓰면 **모든 깊이**의 storage 폴더가 걸려서
소스인 `backend/app/storage/` 까지 커밋에서 빠진다. 2026-09-17 에 실제로
그랬고, 새 클론에서 앱이 아예 뜨지 않았다. 내 작업 폴더에는 파일이 있으니
눈으로는 안 보인다 — git 에게 물어봐야 보인다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# 실행에 반드시 필요한데 무시 규칙에 걸리기 쉬운 곳들.
SOURCE_DIRS = ["backend/app", "ui", "scripts", "masters"]


def tracked(path: str) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", path], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    return {line for line in out.stdout.splitlines() if line}


def on_disk(path: str) -> set[str]:
    """디스크의 `.py` 목록. **경로를 `/` 로 맞춘다.**

    `git ls-files` 는 언제나 `backend/app/x.py` 를 돌려주지만 윈도우의
    `Path.relative_to` 는 `backend\\app\\x.py` 를 준다. 그대로 빼면 전부
    "커밋 안 됨"으로 보여서, 멀쩡한 저장소에 대고 46개 파일이 없다고 한다.
    """
    base = ROOT / path
    return {
        p.relative_to(ROOT).as_posix()
        for p in base.rglob("*.py")
        if "__pycache__" not in p.parts
    }


@pytest.mark.parametrize("folder", SOURCE_DIRS)
def test_every_python_source_is_committed(folder):
    if not (ROOT / folder).is_dir():
        pytest.skip(f"{folder} 없음")
    missing = on_disk(folder) - tracked(folder)
    assert not missing, (
        f"{folder} 아래 파일이 git 에 없다 — 새 클론에서 앱이 안 뜬다:\n  "
        + "\n  ".join(sorted(missing))
        + "\n`git check-ignore -v <파일>` 로 어느 규칙에 걸렸는지 확인할 것."
    )


def test_runtime_storage_is_still_ignored():
    """루트의 런타임 산출물은 계속 무시돼야 한다 — 고치다가 반대로 가지 않게."""
    out = subprocess.run(
        ["git", "check-ignore", "-v", "storage/batches/x.json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, "루트 storage/ 가 더 이상 무시되지 않는다"


def test_samples_stay_out_of_git():
    """실물 발주서는 대외비다. `.gitignore` 와 `README.md` 둘뿐이어야 한다."""
    assert tracked("samples") == {"samples/.gitignore", "samples/README.md"}
