#!/usr/bin/env python
"""SAP 브랜드 마스터 재추출본 → masters/refs/brand_master.csv

    python scripts/import_brand_master.py <SAP추출.csv>            # 계획 보고 확인
    python scripts/import_brand_master.py <SAP추출.csv> --dry-run  # 계획만
    python scripts/import_brand_master.py <SAP추출.csv> --yes      # 확인 없이

이 파일은 **SAP 원본이라 읽기 전용**이다. 사람이 손으로 고치지 않고 재추출본으로
통째로 갈아끼운다. 다만 그냥 덮어쓰면 안 된다 — 지금 `brand_keys.csv` 가
매핑해 둔 코드가 새 목록에서 빠지면, 그 거래처 발주서는 브랜드 판정에 실패한다.
**깨지는 매핑이 하나라도 있으면 쓰지 않는다.**

SAP 추출기가 컬럼 이름을 `A~KUNNR` 처럼 테이블 별칭과 함께 뱉는다. 별칭은
추출 조건에 따라 달라지므로 접두를 떼고 이름만 본다.

LLM 호출 없음 = 비용 0.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

MASTERS = ROOT / "masters"        # --masters 로 바꾼다 (테스트가 실물을 안 건드리게)
TARGET = MASTERS / "refs" / "brand_master.csv"

# 우리 스키마. 없는 컬럼은 빈 값으로 채운다 (vkorg·vtweg 는 코드가 쓰지 않는다).
SCHEMA = ["kunnr", "zbrand", "zbrant", "name1", "vkorg", "vtweg"]
REQUIRED = ["kunnr", "zbrand", "zbrant", "name1"]


def normalize(name: str) -> str:
    """`A~KUNNR` · `B~NAME1` → `kunnr` · `name1`. 별칭은 추출 조건마다 달라진다."""
    return name.split("~")[-1].strip().lstrip("﻿").lower()


def read_export(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"빈 파일입니다: {path}")
        mapping = {raw: normalize(raw) for raw in reader.fieldnames}
        missing = [c for c in REQUIRED if c not in mapping.values()]
        if missing:
            raise SystemExit(
                f"필요한 컬럼이 없습니다: {', '.join(missing)}\n"
                f"  파일의 컬럼: {', '.join(reader.fieldnames)}\n"
                f"  (테이블 별칭 `A~` 는 떼고 봅니다)"
            )
        rows = []
        for raw in reader:
            row = {mapping[k]: (v or "").strip() for k, v in raw.items() if k in mapping}
            if not (row.get("kunnr") and row.get("zbrand")):
                continue                      # 꼬리의 빈 줄
            rows.append({c: row.get(c, "") for c in SCHEMA})
        return rows


def read_current() -> list[dict[str, str]]:
    if not TARGET.exists():
        return []
    with TARGET.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_keys() -> list[dict[str, str]]:
    path = MASTERS / "refs" / "brand_keys.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def report(new: list[dict], current: list[dict], keys: list[dict]) -> list[str]:
    """무엇이 달라지는지, 그래서 무엇이 깨지는지."""
    new_pairs = {(r["kunnr"], r["zbrand"]) for r in new}
    cur_pairs = {(r["kunnr"], r["zbrand"]) for r in current}
    new_cust = {r["kunnr"] for r in new}
    cur_cust = {r["kunnr"] for r in current}

    print(f"현재  {len(current):5}행 · 고객 {len(cur_cust)}곳")
    print(f"신규  {len(new):5}행 · 고객 {len(new_cust)}곳")
    print(f"  고객 추가 {len(new_cust - cur_cust):4}곳 · 빠짐 {len(cur_cust - new_cust):4}곳")
    print(f"  코드 추가 {len(new_pairs - cur_pairs):4}건 · 빠짐 {len(cur_pairs - new_pairs):4}건")

    renamed = 0
    cur_names = {(r["kunnr"], r["zbrand"]): r.get("zbrant", "") for r in current}
    for row in new:
        pair = (row["kunnr"], row["zbrand"])
        if pair in cur_names and cur_names[pair] != row["zbrant"]:
            renamed += 1
    if renamed:
        print(f"  브랜드명 변경 {renamed}건")

    broken = [k for k in keys if (k.get("kunnr"), k.get("zbrand")) not in new_pairs]
    if broken:
        print(f"\n★ 지금 매핑된 {len(broken)}건이 새 목록에 없습니다 — 그 발주서는 브랜드 판정에 실패합니다:")
        for k in broken[:20]:
            print(f"    고객 {k.get('kunnr')} 코드 {k.get('zbrand')} — {k.get('text')!r}")
        if len(broken) > 20:
            print(f"    … 외 {len(broken) - 20}건")
    else:
        print(f"\n  깨지는 매핑 없음 (현재 {len(keys)}건 전부 유효)")
    return [f"{k.get('kunnr')}/{k.get('zbrand')}" for k in broken]


def write(rows: list[dict[str, str]]) -> None:
    """원자적으로 교체한다 — 쓰다 만 참조표가 남으면 전 거래처가 멈춘다."""
    tmp = TARGET.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, TARGET)


def main() -> int:
    parser = argparse.ArgumentParser(description="SAP 브랜드 마스터 재추출본 반영")
    parser.add_argument("export", help="SAP 에서 뽑은 CSV")
    parser.add_argument("--dry-run", action="store_true", help="계획만 보고 쓰지 않는다")
    parser.add_argument("--masters", default="",
                        help="마스터 폴더 (기본 masters/). 테스트가 사본을 가리킬 때 쓴다")
    parser.add_argument("--yes", action="store_true", help="확인 없이 반영")
    parser.add_argument(
        "--force", action="store_true",
        help="매핑이 깨져도 반영한다. 깨진 거래처는 브랜드 판정에 실패하므로 "
             "brand_keys.csv 를 먼저 고치는 편이 낫다",
    )
    args = parser.parse_args()

    global MASTERS, TARGET
    if args.masters:
        MASTERS = Path(args.masters)
        TARGET = MASTERS / "refs" / "brand_master.csv"

    path = Path(args.export)
    if not path.exists():
        print(f"파일이 없습니다: {path}")
        return 2

    new = read_export(path)
    if not new:
        print("읽어낸 행이 없습니다. 컬럼 이름을 확인하세요.")
        return 1

    broken = report(new, read_current(), read_keys())

    if broken and not args.force:
        print("\n반영하지 않았습니다. brand_keys.csv 에서 위 매핑을 먼저 정리하거나, "
              "정말 괜찮다면 --force 를 쓰세요.")
        return 1
    if args.dry_run:
        print("\n--dry-run 이라 쓰지 않았습니다.")
        return 0
    if not args.yes:
        answer = input("\n위 내용으로 교체할까요? [y/N] ").strip().lower()
        if answer != "y":
            print("취소했습니다.")
            return 0

    write(new)
    print(f"\n교체했습니다: {TARGET.relative_to(ROOT)} ({len(new)}행)")
    print("이어서:  python scripts/validate_masters.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
