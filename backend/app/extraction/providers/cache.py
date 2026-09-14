"""LLM 응답 캐시 + 테스트 픽스처 저장소.

주소 지정 방식이 두 가지다. **성질이 다르므로 일부러 나눴다.**

  1. 런타임 캐시  `storage/llm_cache/{sha256}.json`
     같은 문서를 다시 파싱할 때 비용·시간을 0으로 만든다.
     키 = 문서 내용 + 프롬프트 버전 + 거래처 + 모델 ID (design.md §3.3).
     **거래처 hints 는 키에 넣지 않는다** — hints 를 한 글자 고칠 때마다
     캐시가 전량 무효화되면 규칙 튜닝이 매번 유료가 된다. 프롬프트나 추출
     스키마가 바뀌었을 때는 `LLM_PROMPT_VERSION` 을 올려 무효화한다.

  2. 테스트 픽스처  `backend/tests/fixtures/llm_cache/{거래처}__{파일명}.json`
     **해시가 아니라 이름으로 찾는다.** 해시로 주소를 정하면 프롬프트·모델·
     스키마가 바뀔 때마다 골든 픽스처가 전부 미아가 된다. 이름으로 두면
     그런 변경과 무관하게 계속 재생된다 (CI 비용 0의 전제).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .base import DocumentInput, ToolCallResult


def cache_key(
    *, document: DocumentInput, prompt_version: str, customer: str, model: str
) -> str:
    """런타임 캐시 키 — design.md §3.3."""
    h = hashlib.sha256()
    if document.text is not None:
        h.update(document.text.encode("utf-8", errors="replace"))
    elif document.pdf_bytes:
        h.update(document.pdf_bytes)
    for part in (prompt_version, customer, model):
        h.update(b"\x00")
        h.update(str(part).encode("utf-8", errors="replace"))
    return h.hexdigest()


def cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def fixture_name(customer: str, filename: str) -> str:
    """`{거래처}__{파일명}` — 경로 구분자와 특수문자를 걷어낸다."""
    stem = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    return f"{customer.lower()}__{safe}.json"


def fixture_path(fixtures_dir: Path, customer: str, filename: str) -> Path:
    return fixtures_dir / fixture_name(customer, filename)


def _read(path: Path) -> ToolCallResult | None:
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return ToolCallResult(
        payload=data.get("payload", {}),
        model=data.get("model", ""),
        provider=data.get("provider", ""),
    )


def load(cache_dir: Path, key: str) -> ToolCallResult | None:
    return _read(cache_path(cache_dir, key))


def load_fixture(
    fixtures_dir: Path, customer: str, filename: str
) -> ToolCallResult | None:
    return _read(fixture_path(fixtures_dir, customer, filename))


def count(dirs: Iterable[Path]) -> int:
    total = 0
    for d in dirs:
        if d.exists():
            total += len(list(d.glob("*.json")))
    return total


def save(cache_dir: Path, key: str, result: ToolCallResult) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path(cache_dir, key).write_text(
        json.dumps(
            {
                "payload": result.payload,
                "model": result.model,
                "provider": result.provider,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
