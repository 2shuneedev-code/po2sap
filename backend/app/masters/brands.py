"""브랜드 참조표 — SAP 원본 + 사람이 얹는 보정(오버레이). SCHEMA §4.5-A.

  brand_master.csv         SAP 원본. **이 모듈은 읽기만 한다.** 재추출로 통째 교체된다
                           (`scripts/import_brand_master.py`).
  brand_master_manual.csv  사람이 얹는 보정. 재추출 사이의 유일한 보정 창구다.
                           `add`(후보 추가) · `override`(브랜드명 교체) · `suppress`(후보 제외)

**판정에 쓰이는 것은 언제나 둘을 합친 목록이다.** 병합은 `rules/reftable.py` 한
곳에만 있고(`merge_brand_overlay`), 여기 `load_master()` 는 그걸 부르는 얇은
래퍼다 — 규칙엔진과 화면이 서로 다른 후보를 보는 일이 없게.

쓰기는 오버레이에만, 그것도 고객 한 곳의 행 묶음 단위로 일어난다.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..rules import reftable
from . import backup

MASTER_FILE = reftable.BRAND_MASTER
MANUAL_FILE = reftable.BRAND_MANUAL
MANUAL_COLUMNS = ["kunnr", "name1", "zbrand", "zbrant", "action", "note"]
ACTIONS = ("add", "override", "suppress")


class BrandError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


@dataclass(frozen=True)
class Brand:
    kunnr: str
    zbrand: str
    name: str
    customer_name: str
    source: str = "sap"            # sap | add | override — 화면이 출처를 보여준다


@dataclass(frozen=True)
class ManualRow:
    kunnr: str
    zbrand: str
    zbrant: str
    action: str
    note: str
    name1: str = ""


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]
    except UnicodeDecodeError as exc:
        raise reftable.not_utf8(path, exc) from exc


def _to_brand(r: dict[str, str]) -> Brand:
    return Brand(
        kunnr=r["kunnr"], zbrand=r["zbrand"],
        name=r.get("zbrant", ""), customer_name=r.get("name1", ""),
        source=r.get(reftable.SOURCE_COLUMN) or "sap",
    )


def load_sap(masters_dir: Path) -> list[Brand]:
    """SAP 원본만. 오버레이 검증(override/suppress 대상 확인)에 쓴다."""
    return [_to_brand(r) for r in _read(masters_dir / MASTER_FILE) if r.get("kunnr")]


def load_master(masters_dir: Path) -> list[Brand]:
    """판정에 쓰이는 후보 전량 = SAP ∪ 오버레이. 순서는 병합 결과를 따른다."""
    return [
        _to_brand(r)
        for r in reftable.load(masters_dir, MASTER_FILE, optional=True)
        if r.get("kunnr")
    ]


def load_manual(masters_dir: Path) -> list[ManualRow]:
    return [
        ManualRow(
            kunnr=r["kunnr"], zbrand=r.get("zbrand", ""), zbrant=r.get("zbrant", ""),
            action=r.get("action", ""), note=r.get("note", ""), name1=r.get("name1", ""),
        )
        for r in _read(masters_dir / MANUAL_FILE)
        if r.get("kunnr")
    ]


def registered_codes(masters_dir: Path, kunnr: str) -> set[str]:
    """이 고객의 판정 후보 코드 (병합 후)."""
    return {b.zbrand for b in load_master(masters_dir) if b.kunnr == kunnr}


def validate_manual(masters_dir: Path, kunnr: str, rows: list[ManualRow]) -> None:
    """저장 전 검사 (SCHEMA §4.5-A "저장 전 검증"). 통과 못 하면 파일을 건드리지 않는다."""
    sap = {b.zbrand: b for b in load_sap(masters_dir) if b.kunnr == kunnr}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        where = f"코드 {row.zbrand or '(빈값)'}"
        if not row.zbrand:
            raise BrandError("브랜드 코드가 비어 있습니다.")
        if row.action not in ACTIONS:
            raise BrandError(f"{where} — 동작은 {' · '.join(ACTIONS)} 중 하나여야 합니다: {row.action!r}")
        if not row.note.strip():
            raise BrandError(f"{where} — 비고(왜 고쳤는지)는 필수입니다.")
        if row.action in ("add", "override") and not row.zbrant.strip():
            raise BrandError(f"{where} — 브랜드명이 비어 있습니다.")
        pair = (row.zbrand, row.action)
        if pair in seen:
            raise BrandError(f"{where} — 같은 동작({row.action})이 두 번 있습니다.")
        seen.add(pair)

        if row.action in ("override", "suppress") and row.zbrand not in sap:
            raise BrandError(
                f"{where} — SAP 원본에 없는 코드는 {row.action} 할 수 없습니다. "
                "새 후보라면 add 를 쓰세요."
            )
        if row.action == "add" and row.zbrand in sap:
            raise BrandError(
                f"{where} — 이미 SAP 에 등록된 코드입니다. 이름을 고치려면 override 를 쓰세요."
            )


def set_manual(
    masters_dir: Path,
    kunnr: str,
    rows: list[ManualRow],
    *,
    storage_dir: Path | None = None,
    backup_keep: int = 30,
) -> list[ManualRow]:
    """고객 한 곳의 오버레이 행을 통째로 교체한다. 빈 목록이면 그 고객 보정을 지운다.

    그 고객 블록이 있던 자리를 지킨다 — 파일 순서가 흔들리면 diff 가 읽히지 않는다.
    `storage_dir` 을 주면 **덮어쓰기 전에 사본을 남긴다.** 운영 경로(화면·API)는
    반드시 넘긴다.
    """
    if not any(b.kunnr == kunnr for b in load_sap(masters_dir)) and any(
        r.action != "add" for r in rows
    ):
        raise BrandError(f"고객 {kunnr} 이 SAP 브랜드 마스터에 없습니다. add 만 쓸 수 있습니다.")
    validate_manual(masters_dir, kunnr, rows)

    customer_name = next(
        (b.customer_name for b in load_sap(masters_dir) if b.kunnr == kunnr and b.customer_name),
        "",
    )
    replacement = [
        ManualRow(
            kunnr=kunnr, zbrand=r.zbrand.strip(), zbrant=r.zbrant.strip(),
            action=r.action, note=r.note.strip(), name1=r.name1 or customer_name,
        )
        for r in rows
    ]

    current = load_manual(masters_dir)
    target = [i for i, r in enumerate(current) if r.kunnr == kunnr]
    kept = [r for r in current if r.kunnr != kunnr]
    at = target[0] if target else len(kept)
    kept[at:at] = replacement

    path = masters_dir / MANUAL_FILE
    if storage_dir is not None:
        backup.snapshot(path, storage_dir, keep=backup_keep)
    _write(path, kept)
    return replacement


def _write(path: Path, rows: list[ManualRow]) -> None:
    """임시 파일에 쓰고 원자적으로 바꾼다 — 쓰다 죽어도 반쪽 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".brand_manual.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANUAL_COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "kunnr": r.kunnr, "name1": r.name1, "zbrand": r.zbrand,
                    "zbrant": r.zbrant, "action": r.action, "note": r.note,
                })
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
