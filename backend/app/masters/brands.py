"""브랜드 참조표 읽기·쓰기 — masters/refs/*.csv.

두 파일의 성격이 다르다 (SCHEMA §1).

  brand_master.csv  SAP 원본. **이 모듈은 읽기만 한다.** 재추출로 통째 교체된다.
  brand_keys.csv    발주서 원문 → 코드. 사람이 채우는 값이라 화면에서 편집한다.

쓰기는 brand_keys.csv 에만, 그것도 (거래처, 코드) 한 묶음씩 일어난다.
쓰기 전에 **그 코드가 SAP 에 등록돼 있는지 확인한다** — 등록되지 않은 코드를
저장하면 나중에 SAP 이 오더를 거부하고, 원인을 찾기 어려워진다.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import backup

MASTER_FILE = "refs/brand_master.csv"
KEYS_FILE = "refs/brand_keys.csv"
KEY_COLUMNS = ["kunnr", "zbrand", "match", "text", "note"]
MATCH_MODES = ("contains", "equals")


class BrandError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


@dataclass(frozen=True)
class Brand:
    kunnr: str
    zbrand: str
    name: str
    customer_name: str


@dataclass(frozen=True)
class BrandKey:
    kunnr: str
    zbrand: str
    match: str
    text: str
    note: str = ""


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def load_master(masters_dir: Path) -> list[Brand]:
    """SAP 브랜드 마스터 전량. 순서는 파일 순서를 따른다."""
    return [
        Brand(
            kunnr=r["kunnr"], zbrand=r["zbrand"],
            name=r.get("zbrant", ""), customer_name=r.get("name1", ""),
        )
        for r in _read(masters_dir / MASTER_FILE)
        if r.get("kunnr")
    ]


def load_keys(masters_dir: Path) -> list[BrandKey]:
    return [
        BrandKey(
            kunnr=r["kunnr"], zbrand=r["zbrand"],
            match=r.get("match") or "contains",
            text=r.get("text", ""), note=r.get("note", ""),
        )
        for r in _read(masters_dir / KEYS_FILE)
        if r.get("kunnr")
    ]


def registered_codes(masters_dir: Path, kunnr: str) -> set[str]:
    return {b.zbrand for b in load_master(masters_dir) if b.kunnr == kunnr}


def validate_keys(masters_dir: Path, kunnr: str, zbrand: str, keys: list[BrandKey]) -> None:
    """저장 전 검사. 통과하지 못하면 파일을 건드리지 않는다."""
    known = registered_codes(masters_dir, kunnr)
    if not known:
        raise BrandError(f"고객 {kunnr} 이 브랜드 마스터에 없습니다.")
    if zbrand not in known:
        raise BrandError(
            f"브랜드 코드 {zbrand} 는 고객 {kunnr} 에 등록돼 있지 않습니다. "
            "SAP 이 거부할 코드라 저장하지 않습니다."
        )

    seen: set[str] = set()
    for key in keys:
        if not key.text.strip():
            raise BrandError("원문 키가 비어 있습니다.")
        if key.match not in MATCH_MODES:
            raise BrandError(
                f"판정 방식이 올바르지 않습니다: {key.match} "
                f"({' 또는 '.join(MATCH_MODES)})"
            )
        folded = key.text.strip().casefold()
        if folded in seen:
            raise BrandError(f"같은 원문 키가 두 번 있습니다: {key.text}")
        seen.add(folded)

    # 다른 코드가 이미 쓰고 있는 문구면 어느 쪽으로 판정될지 알 수 없다.
    for other in load_keys(masters_dir):
        if other.kunnr != kunnr or other.zbrand == zbrand:
            continue
        if other.text.strip().casefold() in seen:
            raise BrandError(
                f"원문 키 {other.text!r} 는 이미 브랜드 코드 {other.zbrand} 가 쓰고 있습니다. "
                "같은 문구를 두 코드에 둘 수 없습니다."
            )


def set_keys(
    masters_dir: Path,
    kunnr: str,
    zbrand: str,
    keys: list[BrandKey],
    *,
    storage_dir: Path | None = None,
    backup_keep: int = 30,
) -> list[BrandKey]:
    """(거래처, 코드) 한 묶음을 통째로 교체한다. 빈 목록이면 매핑을 지운다.

    같은 묶음이 있던 자리를 지켜 파일 순서를 보존한다 — 행 순서가 곧
    판정 우선순위이므로(SCHEMA §4.5) 저장할 때마다 순서가 흔들리면 안 된다.

    `storage_dir` 을 주면 **덮어쓰기 전에 사본을 남긴다**
    (`storage/master_backups/`). 운영 경로(화면·API)는 반드시 넘긴다 —
    현업이 몇 달 채운 값이라 되돌릴 수단이 있어야 한다. 테스트처럼 사본이
    필요 없는 자리에서만 생략한다.
    """
    validate_keys(masters_dir, kunnr, zbrand, keys)

    rows = load_keys(masters_dir)
    target = [i for i, r in enumerate(rows) if r.kunnr == kunnr and r.zbrand == zbrand]
    replacement = [
        BrandKey(kunnr=kunnr, zbrand=zbrand, match=k.match, text=k.text.strip(), note=k.note)
        for k in keys
    ]

    if target:
        at = target[0]
        rows = [r for i, r in enumerate(rows) if i not in set(target)]
        rows[at:at] = replacement
    else:
        same_customer = [i for i, r in enumerate(rows) if r.kunnr == kunnr]
        at = same_customer[-1] + 1 if same_customer else len(rows)
        rows[at:at] = replacement

    path = masters_dir / KEYS_FILE
    if storage_dir is not None:
        backup.snapshot(path, storage_dir, keep=backup_keep)
    _write(path, rows)
    return replacement


def _write(path: Path, rows: list[BrandKey]) -> None:
    """임시 파일에 쓰고 원자적으로 바꾼다 — 쓰다 죽어도 반쪽 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".brand_keys.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=KEY_COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "kunnr": r.kunnr, "zbrand": r.zbrand,
                    "match": r.match, "text": r.text, "note": r.note,
                })
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
