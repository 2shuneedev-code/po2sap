"""전송 감사 로그 — storage/audit/{YYYY-MM}/send.jsonl.

design.md §8: 구조화 JSON, **원문·단가는 기록하지 않는다.** 보존 5년.
남기는 것은 "무엇을 언제 어디로 보냈고 어떻게 됐는가"다. 오더를 되짚을 수 있도록
BSTKD 목록과 페이로드 해시를 남기고, 값 자체는 남기지 않는다.

한 줄 = 전송 시도 1회. 재시도로 성공해도 시도 횟수가 그대로 보인다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["record_send", "payload_digest", "read_month"]

# 금액·단가·품명처럼 값 자체가 대외비인 필드는 감사 로그에 남기지 않는다.
_KEYS_LOGGED = ("BSTKD",)


def payload_digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def record_send(storage_dir: Path, entry: dict[str, Any]) -> Path:
    now = datetime.now().astimezone()
    directory = Path(storage_dir) / "audit" / now.strftime("%Y-%m")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "send.jsonl"

    line = {"ts": now.isoformat(timespec="seconds"), **entry}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def order_keys(rows: list[dict[str, str]]) -> list[str]:
    """되짚기용 키. 값 자체가 아니라 오더 식별자만 남긴다."""
    seen: list[str] = []
    for row in rows:
        for key in _KEYS_LOGGED:
            value = row.get(key, "")
            if value and value not in seen:
                seen.append(value)
    return seen


def read_month(storage_dir: Path, month: str) -> list[dict[str, Any]]:
    path = Path(storage_dir) / "audit" / month / "send.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
