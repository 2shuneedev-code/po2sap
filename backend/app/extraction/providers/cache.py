"""LLM 응답 캐시 + 테스트 픽스처 저장소.

주소 지정 방식이 두 가지다. **성질이 다르므로 일부러 나눴다.**

  1. 런타임 캐시  `storage/llm_cache/{sha256}.json`
     같은 문서를 다시 파싱할 때 비용·시간을 0으로 만든다.
     **호출 1회 단위**다 — 키 = 그 호출에 **실제로 보낸 텍스트** + 패스 종류 +
     프롬프트 버전 + 거래처 + 모델 ID (design.md §3.3).
     청크마다 텍스트가 달라 청크마다 키가 다르다. 그래서 청크 크기를 바꾸면
     바뀐 청크만 다시 부르고, 나머지는 캐시에서 나온다.
     **거래처 hints 는 키에 넣지 않는다** — hints 를 한 글자 고칠 때마다
     캐시가 전량 무효화되면 규칙 튜닝이 매번 유료가 된다. 프롬프트나 추출
     스키마가 바뀌었을 때는 `LLM_PROMPT_VERSION` 을 올려 무효화한다.

  2. 테스트 픽스처  `backend/tests/fixtures/llm_cache/{거래처}__{파일명}.json`
     **해시가 아니라 이름으로 찾는다.** 해시로 주소를 정하면 프롬프트·모델·
     스키마가 바뀔 때마다 골든 픽스처가 전부 미아가 된다. 이름으로 두면
     그런 변경과 무관하게 계속 재생된다 (CI 비용 0의 전제).

     픽스처는 세 종류다.
       · 문서 단위  `{거래처}__{파일명}.json`            병합이 끝난 응답 전체 — **우선한다**
       · 골격       `{거래처}__{파일명}__outline.json`   OUTLINE 호출 1회분
       · 청크       `{거래처}__{파일명}__c{n}.json`      LINES 호출 1회분 (n = 청크 통번호, 1부터)
     **문서 단위가 있으면 골격·청크 픽스처는 읽지 않는다.** 청크 크기를 바꿔도 문서 단위
     픽스처가 미아가 되지 않게 하려는 것이고, 골격·청크 픽스처는 문서 단위 응답이 없을 때
     호출 경로 전체를 재생하기 위한 보조 수단이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .base import DocumentInput, ToolCallResult


def cache_key(
    *,
    document: DocumentInput,
    prompt_version: str,
    customer: str,
    model: str,
    pass_kind: str = "",
) -> str:
    """런타임 캐시 키 — design.md §3.3.

    `pass_kind` 는 `outline` · `lines` · `single` 중 하나다. 같은 텍스트라도 어느 패스로
    불렀는지에 따라 응답의 모양이 달라 섞이면 안 된다. `document.text` 는 **그 호출에
    실제로 보낸 텍스트**여야 한다(청크면 그 구간). hints 는 넣지 않는다.
    """
    h = hashlib.sha256()
    if document.text is not None:
        h.update(document.text.encode("utf-8", errors="replace"))
    elif document.pdf_bytes:
        h.update(document.pdf_bytes)
    for part in (pass_kind, prompt_version, customer, model):
        h.update(b"\x00")
        h.update(str(part).encode("utf-8", errors="replace"))
    return h.hexdigest()


def cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def fixture_name(customer: str, filename: str, part: str = "") -> str:
    """`{거래처}__{파일명}[__{part}]` — 경로 구분자와 특수문자를 걷어낸다."""
    stem = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    suffix = f"__{part}" if part else ""
    return f"{customer.lower()}__{safe}{suffix}.json"


def outline_fixture_name(customer: str, filename: str) -> str:
    """골격(OUTLINE) 호출 1회분 픽스처 — `{거래처}__{파일명}__outline.json`."""
    return fixture_name(customer, filename, "outline")


def chunk_fixture_name(customer: str, filename: str, chunk_index: int) -> str:
    """청크(LINES) 호출 1회분 픽스처 — `{거래처}__{파일명}__c{n}.json`.

    **문서 단위 픽스처가 있으면 이 파일은 읽히지 않는다.** 문서 단위가 없을 때만 쓰는
    보조 수단이다 (모듈 docstring).
    """
    return fixture_name(customer, filename, f"c{chunk_index}")


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
        stop_reason=data.get("stop_reason", ""),
    )


def load(cache_dir: Path, key: str) -> ToolCallResult | None:
    return _read(cache_path(cache_dir, key))


def load_fixture(
    fixtures_dir: Path, customer: str, filename: str
) -> ToolCallResult | None:
    """문서 단위 픽스처."""
    return _read(fixture_path(fixtures_dir, customer, filename))


def load_named_fixture(fixtures_dir: Path, name: str) -> ToolCallResult | None:
    """이름으로 직접 — 골격·청크 픽스처. (`outline_fixture_name` · `chunk_fixture_name`)"""
    return _read(fixtures_dir / name)


def count(dirs: Iterable[Path]) -> int:
    total = 0
    for d in dirs:
        if d.exists():
            total += len(list(d.glob("*.json")))
    return total


def save(cache_dir: Path, key: str, result: ToolCallResult) -> None:
    """임시 파일에 쓴 뒤 바꿔치기한다 — 청크가 병렬로 저장되므로 읽는 쪽이
    쓰다 만 JSON 을 만나지 않게 한다."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_path(cache_dir, key)
    body = json.dumps(
        {
            "payload": result.payload,
            "model": result.model,
            "provider": result.provider,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "stop_reason": result.stop_reason,
        },
        ensure_ascii=False,
        indent=2,
    )
    fd, tmp = tempfile.mkstemp(dir=str(cache_dir), prefix=".cache.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
