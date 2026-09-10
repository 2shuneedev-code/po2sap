"""거래처 마스터(YAML) 로더.

D1 범위에서는 meta / extraction 만 사용한다.
tables / rules / fields / grid 는 D2(규칙엔진)에서 확장한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


class MasterError(RuntimeError):
    pass


@dataclass
class CustomerMaster:
    code: str
    name: str
    customer_no: str
    file_types: list[str] = field(default_factory=list)
    extraction: dict[str, Any] = field(default_factory=dict)
    # D2 확장 지점
    tables: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    grid: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def customers_dir(masters_dir: Path) -> Path:
    return Path(masters_dir) / "customers"


def list_customers(masters_dir: Path) -> list[CustomerMaster]:
    out = []
    for path in sorted(customers_dir(masters_dir).glob("*.yaml")):
        out.append(load_customer(path.stem, masters_dir))
    return out


@lru_cache(maxsize=64)
def _load_yaml(path_str: str, mtime: float) -> dict[str, Any]:
    """mtime 을 캐시 키에 포함 → 파일을 고치면 자동으로 다시 읽는다."""
    data = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise MasterError(f"마스터 형식이 올바르지 않습니다: {path_str}")
    return data


def load_customer(code: str, masters_dir: Path) -> CustomerMaster:
    path = customers_dir(masters_dir) / f"{code.lower()}.yaml"
    if not path.exists():
        available = [p.stem for p in customers_dir(masters_dir).glob("*.yaml")]
        raise MasterError(
            f"거래처 설정을 찾을 수 없습니다: {code} "
            f"(사용 가능: {', '.join(available) or '없음'})"
        )

    data = _load_yaml(str(path), path.stat().st_mtime)
    data = _apply_extends(data, masters_dir)

    meta = data.get("meta") or {}
    if not meta.get("code"):
        raise MasterError(f"{path.name}: meta.code 가 없습니다")

    return CustomerMaster(
        code=str(meta["code"]),
        name=str(meta.get("name") or meta["code"]),
        customer_no=str(meta.get("customer_no") or ""),
        file_types=[str(t).lower() for t in (meta.get("file_types") or [])],
        extraction=data.get("extraction") or {},
        tables=data.get("tables") or {},
        rules=data.get("rules") or {},
        fields=data.get("fields") or {},
        grid=data.get("grid") or {},
        raw=data,
    )


def _apply_extends(data: dict[str, Any], masters_dir: Path) -> dict[str, Any]:
    """_base 조각을 먼저 깔고 거래처 값으로 덮어쓴다 (거래처 우선)."""
    parents = data.get("extends") or []
    if not parents:
        return data

    merged: dict[str, Any] = {}
    for rel in parents:
        p = Path(masters_dir) / f"{rel}.yaml"
        if not p.exists():
            raise MasterError(f"상속 대상을 찾을 수 없습니다: {rel} ({p})")
        merged = _deep_merge(merged, _load_yaml(str(p), p.stat().st_mtime))

    return _deep_merge(merged, data)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            # 리스트(결정표 rows 등)는 병합하지 않고 교체한다.
            out[k] = v
    return out
