"""Git 동기화 — 되돌릴 수 없는 일을 하지 않는가.

이 모듈은 서버 PC 에서 현업의 값을 다룬다. 가장 나쁜 실패는 "조용히 되돌리는
것"이라, 여기서 확인하는 것은 기능보다 **하지 않는 일**이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from app import gitsync


def _run(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                         text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "masters" / "refs").mkdir(parents=True)
    _run(r.parent, "init", "-q", "-b", "main", str(r))
    _run(r, "config", "user.email", "t@example.com")
    _run(r, "config", "user.name", "t")
    keys = r / "masters" / "refs" / "brand_keys.csv"
    keys.write_text("kunnr,zbrand,match,text,note\n", encoding="utf-8")
    _run(r, "add", "-A")
    _run(r, "commit", "-qm", "init")
    return r


def _keys(repo: Path) -> Path:
    return repo / "masters" / "refs" / "brand_keys.csv"


def test_clean_repo_reads_as_synced(repo: Path) -> None:
    st = gitsync.status(repo, [_keys(repo)])
    assert st.repo and st.tracked
    assert st.synced and not st.dirty


def test_edit_shows_up_as_dirty(repo: Path) -> None:
    _keys(repo).write_text("kunnr,zbrand,match,text,note\n100249,B1,contains,x,\n",
                           encoding="utf-8")
    st = gitsync.status(repo, [_keys(repo)])
    assert st.dirty and not st.synced


def test_commit_stages_only_the_given_path(repo: Path) -> None:
    """**핵심.** 옆에 있던 다른 변경을 같이 커밋해 가면 안 된다."""
    _keys(repo).write_text("kunnr,zbrand,match,text,note\n100249,B1,contains,x,\n",
                           encoding="utf-8")
    stray = repo / "손대면_안되는것.txt"
    stray.write_text("작업 중", encoding="utf-8")

    result = gitsync.commit_and_push(repo, [_keys(repo)], "rules: 매핑", push=False)

    assert result.ok, result.detail
    committed = _run(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["masters/refs/brand_keys.csv"]
    assert stray.exists()                     # 남의 파일은 건드리지 않는다


def test_nothing_to_commit_is_not_an_error(repo: Path) -> None:
    result = gitsync.commit_and_push(repo, [_keys(repo)], "rules: 매핑", push=False)
    assert result.ok and "없습니다" in result.detail


def test_push_failure_says_the_commit_survived(repo: Path) -> None:
    """원격이 없으면 푸시는 실패한다. 그때 **커밋은 됐다**고 말해야 한다 —
    값이 어디에 있는지 알아야 다음 행동이 정해진다."""
    _keys(repo).write_text("kunnr,zbrand,match,text,note\n100249,B1,contains,x,\n",
                           encoding="utf-8")
    result = gitsync.commit_and_push(repo, [_keys(repo)], "rules: 매핑")

    assert not result.ok
    assert "커밋은 됐" in result.detail
    assert _run(repo, "log", "--oneline").count("\n") == 2    # 커밋은 남았다


def test_outside_a_repo_is_reported_not_raised(tmp_path: Path) -> None:
    """Git 이 없거나 저장소가 아니어도 화면은 떠야 한다."""
    st = gitsync.status(tmp_path, [tmp_path / "x.csv"])
    assert not st.repo and st.synced          # 갈릴 일이 없으면 문제 없음이다


def test_path_outside_the_repo_is_refused(repo: Path, tmp_path: Path) -> None:
    result = gitsync.commit_and_push(repo, [tmp_path / "밖에있는.csv"], "rules: x")
    assert not result.ok and "저장소 밖" in result.detail


def test_module_never_calls_destructive_git(tmp_path: Path) -> None:
    """소스에 pull·reset·checkout·clean 이 아예 없어야 한다.

    사람이 판단할 일을 화면이 대신 하면, 그 판단이 틀렸을 때 되돌릴 수 없다.
    """
    src = Path(gitsync.__file__).read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#") and "·" not in line
    )
    for forbidden in ('"pull"', '"reset"', '"checkout"', '"clean"', '"rebase"', '"-A"'):
        assert forbidden not in body, f"파괴적 git 인자가 들어갔다: {forbidden}"
