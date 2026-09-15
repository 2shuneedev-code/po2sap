"""원문 대조 — 결정표 `op` 와 규칙 `kind` 가 공유한다 (SCHEMA §4.4 · §4.5)."""

from __future__ import annotations

import re

__all__ = ["OPS", "normalize", "compare"]

_SPACES = re.compile(r"\s+")

NORMALIZERS = {
    "trim": str.strip,
    "collapse_spaces": lambda s: _SPACES.sub(" ", s),
    "upper": str.upper,
    "lower": str.lower,
}

OPS = ("contains_ci", "equals", "equals_ci", "regex", "starts_with")


def normalize(text: str | None, ops: list[str] | None = None) -> str:
    out = text or ""
    for name in ops or []:
        fn = NORMALIZERS.get(name)
        if fn is None:
            raise ValueError(f"알 수 없는 normalize 입니다: {name}")
        out = fn(out)
    return out


def compare(op: str, source: str, needle: str) -> bool:
    if op == "contains_ci":
        return needle.casefold() in source.casefold()
    if op == "equals":
        return source == needle
    if op == "equals_ci":
        return source.casefold() == needle.casefold()
    if op == "starts_with":
        return source.startswith(needle)
    if op == "regex":
        return re.search(needle, source) is not None
    raise ValueError(f"알 수 없는 op 입니다: {op}")
