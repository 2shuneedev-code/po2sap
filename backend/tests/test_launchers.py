"""사내 서버용 .bat 런처 — 리눅스 CI 는 실행해 볼 수 없으니 형식만이라도 지킨다.

여기서 잡으려는 것은 두 가지다.

  1. **인코딩** — UTF-8 로 저장하면 한국어 윈도우(cp949) cmd 에서 한글이 깨진다.
     깨진 안내문은 없는 것만 못하다.
  2. **줄바꿈** — LF 만 있는 배치 파일은 구문이 어긋날 수 있다. CRLF 여야 한다.

파일이 실제로 도는지는 윈도우에서 사람이 확인한다 (README 참조).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = ["setup.bat", "run.bat", "check.bat", "run-mock-eai.bat"]


def batch_files() -> list[Path]:
    return sorted(ROOT.glob("*.bat"))


def test_the_launchers_exist() -> None:
    assert [p.name for p in batch_files()] == sorted(EXPECTED)


@pytest.mark.parametrize("name", EXPECTED)
def test_is_readable_on_korean_windows(name: str) -> None:
    """cp949 로 읽혀야 한다 — UTF-8 로 저장하면 안내문이 깨진다."""
    raw = (ROOT / name).read_bytes()
    raw.decode("cp949")          # 못 읽으면 여기서 깨진다


@pytest.mark.parametrize("name", EXPECTED)
def test_uses_crlf_line_endings(name: str) -> None:
    raw = (ROOT / name).read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n"), "LF 만인 줄이 있습니다"


@pytest.mark.parametrize("name", EXPECTED)
def test_runs_from_its_own_folder(name: str) -> None:
    """더블클릭하면 작업 디렉터리가 어디일지 모른다. `cd /d "%~dp0"` 로 못 박는다."""
    text = (ROOT / name).read_bytes().decode("cp949")
    assert 'cd /d "%~dp0"' in text


@pytest.mark.parametrize("name", EXPECTED)
def test_uses_the_venv_python_not_the_system_one(name: str) -> None:
    """서버에서 가장 많이 나는 사고다 — 전역 파이썬에는 라이브러리가 없다."""
    text = (ROOT / name).read_bytes().decode("cp949")
    runs = [ln for ln in text.splitlines()
            if ln.strip().startswith(".venv\\Scripts\\python.exe")]
    if name == "setup.bat":
        assert runs                      # 설치도 가상환경 파이썬으로 한다
        return
    assert runs, "가상환경 파이썬을 쓰지 않습니다"
    assert "python -m" not in text.replace(".venv\\Scripts\\python.exe -m", "")


@pytest.mark.parametrize("name", [n for n in EXPECTED if n != "setup.bat"])
def test_says_what_to_do_when_setup_is_missing(name: str) -> None:
    """가상환경 없이 눌렀을 때 창이 그냥 닫히면 원인을 알 수 없다."""
    text = (ROOT / name).read_bytes().decode("cp949")
    assert "setup.bat" in text
    assert "pause" in text               # 오류를 읽을 시간을 준다


def test_gitattributes_keeps_git_from_rewriting_them() -> None:
    """Git 이 줄바꿈을 정규화하면 위 두 검사가 통과해도 체크아웃에서 깨진다."""
    assert "*.bat -text" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
