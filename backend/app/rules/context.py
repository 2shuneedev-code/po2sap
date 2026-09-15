"""평가 컨텍스트 — SCHEMA.md §3 네임스페이스.

`fields` / `rules` / `tables` 가 참조할 수 있는 이름은 여기 담긴 것이 전부다.
없는 경로는 예외가 아니라 `None` 이다 — 발주서마다 비는 값이 다르고, 비었다는
사실은 `required` 가 판단할 몫이지 참조 자체가 실패할 일은 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["EvalContext"]

_NAMESPACES = ("meta", "header", "shipment", "line")


@dataclass
class EvalContext:
    meta: dict[str, str] = field(default_factory=dict)
    header: dict[str, str] = field(default_factory=dict)
    shipment: dict[str, str] = field(default_factory=dict)
    line: dict[str, str] = field(default_factory=dict)
    derived: dict[str, str] = field(default_factory=dict)      # 결정표가 만든 _xxx
    rules: dict[str, Any] = field(default_factory=dict)        # 규칙 결과

    def resolve(self, path: str) -> Any:
        parts = path.split(".")
        head = parts[0]

        if head in _NAMESPACES:
            source = getattr(self, head)
            if len(parts) == 2:
                return source.get(parts[1])
            if len(parts) == 3 and parts[1] == "extra":
                return source.get(f"extra.{parts[2]}")
            return None

        if head.startswith("_"):
            return self.derived.get(head)

        result = self.rules.get(head)
        if len(parts) == 1:
            return result
        if isinstance(result, dict):
            return result.get(parts[1])
        return None

    def leaves(self) -> dict[str, str]:
        """`{our_item}` 같은 메시지 플레이스홀더용 — 경로의 마지막 조각."""
        out: dict[str, str] = {}
        for ns in _NAMESPACES:
            for key, value in getattr(self, ns).items():
                out.setdefault(key.split(".")[-1], "" if value is None else str(value))
        for key, value in self.derived.items():
            out.setdefault(key.lstrip("_"), "" if value is None else str(value))
        return out

    def render_message(self, message: str) -> str:
        out = message
        for name, value in self.leaves().items():
            out = out.replace("{" + name + "}", value)
        return out
