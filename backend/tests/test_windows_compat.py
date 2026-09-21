"""윈도우에서만 나는 것들 — 리눅스 CI 는 이걸 못 잡는다.

2026-09-21 에 사용자 PC(윈도우 한국어)에서 7개가 깨졌다. 둘 다 리눅스에서는
증상이 없어서 여기까지 통과하고 나갔다.

  1. `cp949` — 출력을 파이프로 넘기면 `—`(em dash) 에서 UnicodeEncodeError.
     테스트뿐 아니라 `python scripts\\... > 결과.txt` 도 죽었다
  2. 경로 구분자 — `git ls-files` 는 `a/b.py`, 윈도우 `relative_to` 는 `a\\b.py`.
     그대로 비교하면 멀쩡한 저장소에 대고 "46개 파일이 커밋 안 됨"이라고 한다
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def scripts() -> list[Path]:
    """**직접 실행되는** 스크립트만. 공용 정의 모듈(master_sheets 등)은 출력이 없다."""
    return sorted(
        p for p in SCRIPTS.glob("*.py")
        if not p.name.startswith("_")
        and '__main__' in p.read_text(encoding="utf-8")
    )


def test_there_are_scripts_to_check():
    """검사가 0건을 통과하고 있지 않은지."""
    assert len(scripts()) >= 5


@pytest.mark.parametrize("script", scripts(), ids=lambda p: p.name)
def test_script_survives_a_cp949_pipe(script):
    """★ 윈도우 한국어 환경에서 출력을 파이프로 넘겨도 죽지 않아야 한다.

    `--help` 만으로도 한글이 나온다. 인코딩이 안 맞으면 여기서 바로 터진다.
    """
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT, capture_output=True,
        env={**_clean_env(), "PYTHONIOENCODING": "cp949"},
    )
    stderr = result.stderr.decode("utf-8", "replace")
    assert "UnicodeEncodeError" not in stderr, (
        f"{script.name} 이 cp949 파이프에서 죽는다 — scripts/_console.py 의 "
        f"use_utf8() 을 부르고 있는지 확인:\n{stderr[-400:]}"
    )
    assert result.returncode == 0, stderr[-400:]


def _clean_env() -> dict[str, str]:
    import os

    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")
    return {k: v for k, v in os.environ.items() if k in keep}


def test_every_script_sets_up_console_encoding():
    """새 스크립트를 만들 때 빠뜨리기 쉬운 자리라, 파일 내용으로도 본다."""
    missing = [
        p.name for p in scripts()
        if "use_utf8()" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "이 스크립트들이 콘솔 인코딩을 맞추지 않는다 — 윈도우에서 파이프로 "
        f"넘길 때 죽는다: {', '.join(missing)}\n"
        "  from _console import use_utf8  /  use_utf8()"
    )


def test_git_paths_and_disk_paths_are_compared_in_one_shape():
    """경로 비교는 `/` 로 맞춘 뒤에 한다 — 윈도우는 `\\` 를 준다."""
    from test_repo_completeness import on_disk, tracked

    disk = on_disk("scripts")
    assert disk, "scripts 아래 .py 가 없다 — 검사가 헛돌고 있다"
    assert all("\\\\" not in path for path in disk), "디스크 경로에 역슬래시가 남아 있다"
    assert all("\\\\" not in path for path in tracked("scripts"))
