"""콘솔 출력 인코딩 — 한국어·em dash 가 윈도우에서 죽지 않게.

윈도우 한국어 환경의 기본 인코딩은 `cp949` 다. 파이썬은 출력이 **파이프로
넘어갈 때** 그 로케일 인코딩을 쓰는데, `cp949` 에는 `—`(em dash) 같은 글자가
없어서 `UnicodeEncodeError` 로 죽는다.

    python scripts\\master_import.py ... > 결과.txt     ← 여기서 죽었다
    subprocess.run(..., capture_output=True)            ← 테스트도 여기서 죽었다

콘솔에 직접 찍을 때는 건드리지 않는다. 파이썬이 윈도우 콘솔 API 로 제대로
넘기고 있고, 거기에 UTF-8 을 강제하면 오히려 옛 conhost 에서 깨져 보인다.
"""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """출력이 콘솔이 아니면(파이프·파일·캡처) UTF-8 로 맞춘다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if not stream.isatty():
                reconfigure(encoding="utf-8")
        except (OSError, ValueError):      # 닫힌 스트림 등 — 출력 때문에 죽지 않는다
            pass
