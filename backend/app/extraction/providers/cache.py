"""LLM 응답 캐시.

같은 문서를 다시 파싱할 때 비용과 시간을 0으로 만든다.
동시에 mock 프로바이더의 응답 저장소 역할을 한다(골든 테스트 기반).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .base import DocumentInput, ToolCallResult


def cache_key(*, document: DocumentInput, prompt: str) -> str:
    """문서 내용 + 프롬프트가 같으면 같은 키.

    프롬프트에는 거래처 힌트와 프롬프트 버전이 포함되므로,
    규칙이나 프롬프트가 바뀌면 자동으로 캐시가 무효화된다.
    """
    h = hashlib.sha256()
    if document.text is not None:
        h.update(document.text.encode("utf-8", errors="replace"))
    elif document.pdf_bytes:
        h.update(document.pdf_bytes)
    h.update(b"\x00")
    h.update(prompt.encode("utf-8", errors="replace"))
    return h.hexdigest()


def cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def load(cache_dir: Path, key: str) -> ToolCallResult | None:
    path = cache_path(cache_dir, key)
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return ToolCallResult(
        payload=data.get("payload", {}),
        model=data.get("model", ""),
        provider=data.get("provider", ""),
    )


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
