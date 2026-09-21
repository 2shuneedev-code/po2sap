"""거래처 마스터(YAML) 로더.

D1 범위에서는 meta / extraction / split 만 사용한다.
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
    split: dict[str, Any] = field(default_factory=dict)
    # D2 확장 지점
    tables: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    grid: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def customers_dir(masters_dir: Path) -> Path:
    return Path(masters_dir) / "customers"


def list_customers(masters_dir: Path) -> list[CustomerMaster]:
    """거래처 파일을 전부 읽는다. `_` 로 시작하는 파일은 거래처가 아니다.

    `_template.yaml` 은 새 거래처를 만들 때 복사하는 서식이다. 그것까지 읽으면
    화면 거래처 목록에 `XXX` 가 뜨고, 고르면 빈 규칙으로 파싱이 돌아간다.
    """
    out = []
    for path in sorted(customers_dir(masters_dir).glob("*.yaml")):
        if path.stem.startswith("_"):
            continue
        out.append(load_customer(path.stem, masters_dir))
    return out


@lru_cache(maxsize=64)
def _load_yaml(path_str: str, mtime: float) -> dict[str, Any]:
    """mtime 을 캐시 키에 포함 → 파일을 고치면 자동으로 다시 읽는다."""
    data = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise MasterError(f"마스터 형식이 올바르지 않습니다: {path_str}")
    return data


# 전용 규칙이 없는 거래처가 쓰는 공용 프로필. 브랜드까지는 뽑아낸다.
GENERIC_EXTENDS = ["_base/sap_defaults", "profiles/standard", "profiles/generic"]


def load_customer(code: str, masters_dir: Path) -> CustomerMaster:
    path = customers_dir(masters_dir) / f"{code.lower()}.yaml"
    if not path.exists():
        return _generic_customer(code, masters_dir)

    data = _load_yaml(str(path), path.stat().st_mtime)
    data = _apply_extends(data, masters_dir)
    data = _resolve_chunking(data)

    meta = data.get("meta") or {}
    if not meta.get("code"):
        raise MasterError(f"{path.name}: meta.code 가 없습니다")

    return CustomerMaster(
        code=str(meta["code"]),
        name=str(meta.get("name") or meta["code"]),
        customer_no=str(meta.get("customer_no") or ""),
        file_types=[str(t).lower() for t in (meta.get("file_types") or [])],
        extraction=data.get("extraction") or {},
        split=data.get("split") or {},
        tables=data.get("tables") or {},
        rules=data.get("rules") or {},
        fields=data.get("fields") or {},
        grid=data.get("grid") or {},
        raw=data,
    )


def _generic_customer(code: str, masters_dir: Path) -> CustomerMaster:
    """전용 YAML 이 없는 거래처를 **공용 프로필로** 세운다.

    SAP 브랜드 마스터에 브랜드가 등록된 고객이면 전용 규칙 없이도 발주서를
    올려 브랜드까지 뽑아볼 수 있어야 한다 — 전 거래처 테스트 배포가 그래야
    가능하다. 브랜드 마스터에도 없는 코드는 그대로 오류다.

    `generic` 표시를 달아 화면이 "이 거래처는 전용 규칙이 없다"를 감추지 못하게 한다.
    """
    from .brands import load_master  # 순환 임포트 방지 — 호출 시점에 가져온다

    kunnr = str(code).strip()
    try:
        brands = [b for b in load_master(masters_dir) if b.kunnr == kunnr]
    except Exception:                        # noqa: BLE001 — 참조표가 없으면 없는 대로
        brands = []

    if not brands:
        available = [p.stem for p in customers_dir(masters_dir).glob("*.yaml")
                     if not p.stem.startswith("_")]
        raise MasterError(
            f"거래처 설정을 찾을 수 없습니다: {code} "
            f"(규칙 있음: {', '.join(available) or '없음'} · "
            f"브랜드 마스터에도 이 고객코드가 없습니다)"
        )

    name = next((b.customer_name for b in brands if b.customer_name), kunnr)
    data = _apply_extends({
        "meta": {
            "code": kunnr,
            "name": name,
            "customer_no": kunnr,
            "status": "active",
            "file_types": [],        # 안내용일 뿐이라 비워 둔다 (계약 §1)
            "generic": True,
        },
        "extends": GENERIC_EXTENDS,
    }, masters_dir)
    data = _resolve_chunking(data)

    meta = data["meta"]
    return CustomerMaster(
        code=kunnr,
        name=str(meta.get("name") or kunnr),
        customer_no=kunnr,
        file_types=[],
        extraction=data.get("extraction") or {},
        split=data.get("split") or {},
        tables=data.get("tables") or {},
        rules=data.get("rules") or {},
        fields=data.get("fields") or {},
        grid=data.get("grid") or {},
        raw=data,
    )


def _resolve_chunking(data: dict[str, Any]) -> dict[str, Any]:
    """`extraction.chunking` 을 **키 단위로** 합친다 — SCHEMA §1 의 통째 교체 규칙의 유일한 예외.

    `_base` 의 기본값(`extraction_defaults.chunking`) 위에 거래처가 적은 키만 덮는다.
    성능 손잡이라 거래처가 한 값만 조절하는 일이 흔한데, 나머지를 다시 적게 하면
    `_base` 의 기본값을 올려도 그 거래처만 낡은 값에 묶인다 (SCHEMA §4.2).

    합친 결과는 `extraction.chunking` 에 들어간다. 기본값이 없고 거래처도 안 적었으면
    아무것도 만들지 않는다 (그때는 `chunking.chunk_policy` 가 명시적으로 실패한다).
    """
    defaults = (data.get("extraction_defaults") or {}).get("chunking") or {}
    extraction = data.get("extraction") or {}
    override = extraction.get("chunking") or {}
    if not isinstance(defaults, dict) or not isinstance(override, dict):
        return data                      # 형식 오류는 validate_masters 가 잡는다
    merged = {**defaults, **override}
    if not merged:
        return data
    return {**data, "extraction": {**extraction, "chunking": merged}}


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


# 이 섹션들은 **항목 하나가 원자 단위**다. 거래처가 fields.KUNNR2 를 다시 쓰면
# 프로필의 KUNNR2 는 통째로 교체된다 — 깊게 합치면 프로필의 todo/value 가
# 거래처의 재정의에 섞여 들어가 "from: table 인데 value 도 있는" 스펙이 만들어진다.
_ATOMIC_SECTIONS = {"fields", "tables", "rules", "field_specs"}


def _deep_merge(
    base: dict[str, Any], override: dict[str, Any], depth: int = 0
) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if not (k in out and isinstance(out[k], dict) and isinstance(v, dict)):
            # 리스트(결정표 rows, grid.hidden 등)는 병합하지 않고 교체한다.
            out[k] = v
        elif depth == 0 and k in _ATOMIC_SECTIONS:
            out[k] = {**out[k], **v}          # 항목 단위로 합치고, 항목은 통째로 교체
        else:
            out[k] = _deep_merge(out[k], v, depth + 1)
    return out
