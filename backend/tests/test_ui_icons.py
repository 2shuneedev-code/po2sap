"""스트림릿 `icon=` 값은 전부 유효한 이모지여야 한다.

`st.info(..., icon="⑂")` 처럼 이모지가 아닌 글자를 주면 스트림릿이 예외를
던지고 **화면 전체가 트레이스백으로 바뀐다.** 규칙 카드 하나 때문에 검수
화면을 못 쓰게 되는 식이라, 눈으로 보기 전에 여기서 잡는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "ui"


def icon_literals() -> list[tuple[str, int, str]]:
    """`ui/` 안의 모든 `icon="..."` 리터럴을 모은다."""
    found = []
    for path in sorted(UI.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (kw.arg == "icon" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    found.append((path.name, kw.lineno, kw.value.value))
    return found


def test_ui_directory_exists():
    assert UI.is_dir(), "ui/ 가 없다 — 스트림릿 화면이 사라졌거나 경로가 바뀌었다"


def test_every_icon_is_a_valid_emoji():
    validate = pytest.importorskip("streamlit.string_util").validate_icon_or_emoji

    bad = []
    for name, line, value in icon_literals():
        try:
            validate(value)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{name}:{line} icon={value!r} — {exc}")

    assert not bad, "유효하지 않은 아이콘:\n" + "\n".join(bad)


def test_there_are_icons_to_check():
    """검사가 0건을 통과하고 있지 않은지 — 파서가 망가지면 조용히 통과한다."""
    assert len(icon_literals()) >= 5
