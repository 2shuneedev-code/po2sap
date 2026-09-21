"""마스터 파일의 Git 상태를 보고, 확인 후 커밋·푸시한다.

왜 필요한가 — 브랜드 매핑은 **서버 디스크의 CSV** 를 고친다. 그 파일은 Git 에
추적되고 있어서, 서버에서 고친 채로 두면 저장소 버전과 갈린다. 갈린 상태에서
`git pull` 을 하면 막히고, 막힌 것을 푼다고 `git checkout .` 을 누르는 순간
현업이 몇 달 채운 값이 사라진다.

**해법은 서버를 그 파일의 주인으로 두는 것이다.** 서버가 고칠 때마다 커밋·푸시하면
원격이 늘 서버와 같아서, 다음 `git pull` 이 그 파일을 건드릴 일이 없다.

안전 원칙 — 이 모듈은 **되돌릴 수 없는 일을 하지 않는다.**
  · `add` · `commit` · `push` 만 한다
  · `pull` · `reset` · `checkout` · `clean` 은 하지 않는다 (그건 사람이 판단할 일)
  · 지정한 경로만 스테이징한다. `git add -A` 는 쓰지 않는다
  · 실패하면 실패했다고 말한다. 저장 자체는 이미 끝나 있고 사본도 남아 있다
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 30          # 사내망에서 원격이 응답 없을 때 화면이 멎지 않게


@dataclass(frozen=True)
class GitResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class GitStatus:
    repo: bool          # Git 저장소 안인가
    tracked: bool       # 그 파일이 추적되고 있는가
    dirty: bool         # 커밋 안 된 변경이 있는가
    ahead: int          # 원격보다 앞선 커밋 수 (푸시 안 된 것)
    branch: str
    detail: str = ""

    @property
    def synced(self) -> bool:
        """저장소 밖이면 Git 과 갈릴 일 자체가 없다 — 그것도 '문제 없음'이다."""
        return not self.repo or (not self.dirty and self.ahead == 0)


def _git(root: Path, *args: str, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def _rel(root: Path, paths: list[Path]) -> list[str]:
    """Git 에 넘길 경로. 윈도우 `\\` 를 `/` 로 맞춘다."""
    out = []
    for p in paths:
        try:
            out.append(p.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue        # 저장소 밖의 경로는 넘기지 않는다
    return out


def status(root: Path, paths: list[Path]) -> GitStatus:
    """지정한 경로들의 Git 상태. 어떤 실패도 예외로 올리지 않는다 —
    Git 이 없거나 저장소가 아니어도 화면은 떠야 한다."""
    rel = _rel(root, paths)
    if not rel:
        return GitStatus(False, False, False, 0, "", "저장소 밖의 파일입니다")

    try:
        inside = _git(root, "rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0:
            return GitStatus(False, False, False, 0, "", "Git 저장소가 아닙니다")

        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        ls = _git(root, "ls-files", "--", *rel)
        tracked = bool(ls.stdout.strip())
        st = _git(root, "status", "--porcelain", "--", *rel)
        dirty = bool(st.stdout.strip())

        ahead = 0
        cnt = _git(root, "rev-list", "--count", "@{upstream}..HEAD")
        if cnt.returncode == 0 and cnt.stdout.strip().isdigit():
            ahead = int(cnt.stdout.strip())

        return GitStatus(True, tracked, dirty, ahead, branch)
    except (OSError, subprocess.SubprocessError) as exc:
        return GitStatus(False, False, False, 0, "", f"Git 을 실행하지 못했습니다: {exc}")


def commit_and_push(
    root: Path, paths: list[Path], message: str, *, push: bool = True
) -> GitResult:
    """지정한 경로만 스테이징해 커밋하고, 원하면 푸시한다.

    커밋은 됐는데 푸시가 막히는 경우(원격이 앞서 있음·네트워크·권한)가 흔하다.
    그때 **커밋까지는 된 것**을 분명히 말한다 — 값은 이미 이력에 들어가 있고,
    남은 일은 푸시뿐이라는 걸 알아야 다음 행동이 정해진다.
    """
    rel = _rel(root, paths)
    if not rel:
        return GitResult(False, "저장소 밖의 파일이라 커밋할 수 없습니다.")

    try:
        add = _git(root, "add", "--", *rel)
        if add.returncode != 0:
            return GitResult(False, f"git add 실패: {add.stderr.strip()}")

        staged = _git(root, "diff", "--cached", "--name-only", "--", *rel)
        if not staged.stdout.strip():
            return GitResult(True, "커밋할 변경이 없습니다 (이미 이력에 있습니다).")

        commit = _git(root, "commit", "-m", message, "--", *rel)
        if commit.returncode != 0:
            return GitResult(False, f"git commit 실패: {(commit.stderr or commit.stdout).strip()}")

        if not push:
            return GitResult(True, "커밋했습니다 (푸시는 하지 않았습니다).")

        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        pushed = _git(root, "push", "origin", branch, timeout=TIMEOUT * 2)
        if pushed.returncode != 0:
            return GitResult(
                False,
                "커밋은 됐지만 푸시가 실패했습니다 — 값은 로컬 이력에 안전합니다.\n"
                f"{(pushed.stderr or pushed.stdout).strip()}",
            )
        return GitResult(True, f"커밋하고 origin/{branch} 에 푸시했습니다.")
    except subprocess.TimeoutExpired:
        return GitResult(False, "Git 이 응답하지 않아 중단했습니다 (원격 연결 확인).")
    except (OSError, subprocess.SubprocessError) as exc:
        return GitResult(False, f"Git 실행 실패: {exc}")
