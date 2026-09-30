"""출하 참조표 — 고객별 출하조건(ZSHCO)·운송수단(VSART). `refs/shipping_master.csv`.

고객 1곳 = 행 1개(kunnr · name1 · zshco · vsart). 규칙엔진은 `profiles/standard.yaml`
의 `csv_choice` 로 이 표를 읽는다 — 행이 없으면 ZSHCO 는 비고(노랗게), VSART 는
전 거래처 기본값이 쓰인다. 여기는 **화면이 쓰는 읽기·쓰기**만 담당한다.

쓰기는 고객 한 곳 단위다. 그 고객 행이 있던 자리를 지킨다 — 파일 순서가
흔들리면 diff 가 읽히지 않는다.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..rules import reftable
from . import backup
from .tabular import replace_scope

FILE = "refs/shipping_master.csv"
COLUMNS = ["kunnr", "name1", "zshco", "vsart"]
VALUE_COLUMNS = ("zshco", "vsart")        # 전송 필드 이름 = 컬럼 이름의 대문자


class ShippingError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


@dataclass(frozen=True)
class ShippingRow:
    kunnr: str
    name1: str = ""
    zshco: str = ""
    vsart: str = ""


def load(masters_dir: Path) -> list[ShippingRow]:
    return [
        ShippingRow(**{c: r.get(c, "").strip() for c in COLUMNS})
        for r in reftable.load(masters_dir, FILE, optional=True)
        if r.get("kunnr", "").strip()
    ]


def get(masters_dir: Path, kunnr: str) -> ShippingRow | None:
    return next((r for r in load(masters_dir) if r.kunnr == kunnr), None)


def _max_lens(masters_dir: Path) -> dict[str, int]:
    """전송 필드 길이는 `_base` 가 유일한 원천이다 (CLAUDE.md §2)."""
    data = yaml.safe_load((masters_dir / "_base" / "sap_defaults.yaml").read_text("utf-8")) or {}
    specs = data.get("field_specs") or {}
    return {
        col: int(specs[col.upper()]["max_len"])
        for col in VALUE_COLUMNS
        if (specs.get(col.upper()) or {}).get("max_len")
    }


def set_row(
    masters_dir: Path,
    row: ShippingRow,
    *,
    storage_dir: Path | None = None,
    backup_keep: int = 30,
) -> ShippingRow | None:
    """고객 한 곳의 행을 교체한다. 값이 둘 다 비면 그 행을 지운다(→ 기본값으로).

    `storage_dir` 을 주면 **덮어쓰기 전에 사본을 남긴다.** 운영 경로(화면)는 반드시 넘긴다.
    """
    kunnr = row.kunnr.strip()
    if not kunnr:
        raise ShippingError("고객코드가 비어 있습니다.")
    clean = ShippingRow(
        kunnr=kunnr, name1=row.name1.strip(),
        zshco=row.zshco.strip(), vsart=row.vsart.strip(),
    )
    for col, limit in _max_lens(masters_dir).items():
        value = getattr(clean, col)
        if len(value) > limit:
            raise ShippingError(f"{col.upper()} 는 {limit}자까지입니다: {value!r}")

    current = load(masters_dir)
    at = next((i for i, r in enumerate(current) if r.kunnr == kunnr), None)
    kept = [r for r in current if r.kunnr != kunnr]
    keep_row = any(getattr(clean, c) for c in VALUE_COLUMNS)
    if keep_row:
        kept.insert(len(kept) if at is None else at, clean)

    path = masters_dir / FILE
    if storage_dir is not None:
        backup.snapshot(path, storage_dir, keep=backup_keep)
    _write(path, kept)
    return clean if keep_row else None


def set_rows(
    masters_dir: Path,
    rows: list[ShippingRow],
    *,
    kunnr: str | None = None,
    storage_dir: Path | None = None,
    backup_keep: int = 30,
) -> list[ShippingRow]:
    """화면 스프레드시트 저장 — **원본 CSV 를 직접** 고친다.

    `kunnr` 를 주면 그 고객 행만 `rows` 로 바꾸고(자리 유지), 없으면 파일 전체를
    `rows` 로 바꾼다. 값이 둘 다 빈 행은 버린다(→ 그 고객은 빈 칸). 검사를 하나라도
    통과 못 하면 파일을 건드리지 않는다.
    """
    limits = _max_lens(masters_dir)
    clean: list[ShippingRow] = []
    for index, row in enumerate(rows, start=1):
        r = ShippingRow(**{c: str(getattr(row, c) or "").strip() for c in COLUMNS})
        if not any(getattr(r, c) for c in (*COLUMNS,)):
            continue                                    # 빈 줄
        if not r.kunnr:
            raise ShippingError(f"{index}행 — 고객코드가 비어 있습니다.")
        if kunnr is not None and r.kunnr != kunnr:
            raise ShippingError(f"{index}행 — 이 화면은 고객 {kunnr} 행만 고칩니다: {r.kunnr}")
        for col, limit in limits.items():
            if len(getattr(r, col)) > limit:
                raise ShippingError(f"{index}행 — {col.upper()} 는 {limit}자까지입니다: {getattr(r, col)!r}")
        if any(getattr(r, c) for c in VALUE_COLUMNS):
            clean.append(r)

    result = replace_scope(load(masters_dir), clean, kunnr)
    dup = _first_duplicate([r.kunnr for r in result])
    if dup:
        raise ShippingError(f"고객 {dup} 행이 두 개입니다 — 고객 1곳 = 행 1개.")

    path = masters_dir / FILE
    if storage_dir is not None:
        backup.snapshot(path, storage_dir, keep=backup_keep)
    _write(path, result)
    return clean


def _first_duplicate(keys: list) -> object | None:
    seen: set = set()
    for key in keys:
        if key in seen:
            return key
        seen.add(key)
    return None


def _write(path: Path, rows: list[ShippingRow]) -> None:
    """임시 파일에 쓰고 원자적으로 바꾼다 — 쓰다 죽어도 반쪽 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".shipping.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({c: getattr(r, c) for c in COLUMNS})
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
