"""참조표(CSV) 로더 — masters/refs/*.csv.

파일이 바뀌면 자동으로 다시 읽는다(mtime 을 캐시 키에 포함). 규칙을 고치는 동안
서버를 재시작하지 않아도 되고, 운영 중에는 사실상 메모리 조회다.

**예외 하나 — 브랜드 마스터.** `refs/brand_master.csv` 를 달라는 요청은 SAP 원본에
사람이 얹은 보정(`refs/brand_master_manual.csv`)을 합친 결과를 돌려받는다
(SCHEMA §4.5-A). 브랜드만 SAP·수동 두 원천을 갖는 참조표라서다. 병합은 여기
한 곳에만 둔다 — 규칙엔진·화면·검증기가 같은 후보를 본다.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

__all__ = ["RefTableError", "load", "merge_brand_overlay"]

BRAND_MASTER = "refs/brand_master.csv"
BRAND_MANUAL = "refs/brand_master_manual.csv"
SOURCE_COLUMN = "_source"          # 병합 결과에만 붙는다: sap | add | override


class RefTableError(ValueError):
    pass


def not_utf8(path: Path | str, exc: UnicodeDecodeError) -> RefTableError:
    """엑셀의 "CSV (쉼표로 분리)" 저장은 cp949 다 — 트레이스백 대신 고칠 방법을 준다."""
    return RefTableError(
        f"{Path(path).name} 이(가) UTF-8 이 아닙니다 ({exc.start}번째 바이트). "
        "엑셀에서 저장했다면 **'CSV UTF-8(쉼표로 분리)'** 형식으로 다시 저장하세요. "
        "ü·한글 같은 글자가 ? 로 바뀌었는지도 확인하세요."
    )


@lru_cache(maxsize=64)
def _read(path_str: str, mtime: float) -> tuple[dict[str, str], ...]:
    try:
        with Path(path_str).open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise RefTableError(f"참조표에 머리글이 없습니다: {path_str}")
            return tuple(
                {(k or ""): (v or "").strip() for k, v in row.items()} for row in reader
            )
    except UnicodeDecodeError as exc:
        raise not_utf8(path_str, exc) from exc


def load(masters_dir: Path, rel_path: str, *, optional: bool = False) -> list[dict[str, str]]:
    """참조표를 읽는다. `optional` 이면 파일이 없어도 빈 목록으로 동작한다."""
    path = Path(masters_dir) / rel_path
    if not path.exists():
        if optional:
            return []
        raise RefTableError(f"참조표 파일이 없습니다: {rel_path}")
    rows = list(_read(str(path), path.stat().st_mtime))
    if Path(rel_path).as_posix() == BRAND_MASTER:
        overlay_path = Path(masters_dir) / BRAND_MANUAL
        overlay = (
            list(_read(str(overlay_path), overlay_path.stat().st_mtime))
            if overlay_path.exists() else []
        )
        return merge_brand_overlay(rows, overlay)
    return rows


def merge_brand_overlay(
    sap: list[dict[str, str]], overlay: list[dict[str, str]]
) -> list[dict[str, str]]:
    """SAP ∪ 오버레이 (SCHEMA §4.5-A 병합 규칙 1~4).

    1. SAP 전 행을 파일 순서대로  2. suppress 조합을 뺀다
    3. override 는 같은 자리에서 zbrant(와 name1)만 바꾼다
    4. add 는 그 고객 블록 끝에 덧붙인다 (블록이 없으면 맨 끝)
    """
    def key(r: dict[str, str]) -> tuple[str, str]:
        return (r.get("kunnr", ""), r.get("zbrand", ""))

    suppress = {key(o) for o in overlay if o.get("action") == "suppress"}
    override = {key(o): o for o in overlay if o.get("action") == "override"}

    merged: list[dict[str, str]] = []
    for r in sap:
        k = key(r)
        if k in suppress:
            continue
        row = {**r, SOURCE_COLUMN: "sap"}
        if k in override:
            o = override[k]
            row["zbrant"] = o.get("zbrant") or row.get("zbrant", "")
            row["name1"] = o.get("name1") or row.get("name1", "")
            row[SOURCE_COLUMN] = "override"
        merged.append(row)

    for o in overlay:
        if o.get("action") != "add" or not o.get("kunnr"):
            continue
        row = {"kunnr": o["kunnr"], "name1": o.get("name1", ""),
               "zbrand": o.get("zbrand", ""), "zbrant": o.get("zbrant", ""),
               SOURCE_COLUMN: "add"}
        last = max((i for i, r in enumerate(merged) if r.get("kunnr") == o["kunnr"]), default=None)
        if last is None:
            merged.append(row)
        else:
            merged.insert(last + 1, row)
    return merged
