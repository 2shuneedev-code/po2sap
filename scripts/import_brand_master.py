#!/usr/bin/env python
"""브랜드 마스터 재추출본 → masters/refs/brand_master.csv

    python scripts/import_brand_master.py <SAP추출.csv>            # 계획 보고 확인
    python scripts/import_brand_master.py <SAP추출.csv> --dry-run  # 계획만
    python scripts/import_brand_master.py <SAP추출.csv> --yes      # 확인 없이

이 파일은 **브랜드 마스터 원본**이다. 사람이 손으로 고치지 않고 재추출본으로
통째로 갈아끼운다. 사람이 얹은 보정(`brand_master_manual.csv`)은 **건드리지
않는다** — 대신 새 추출과 대조해 보고한다 (SCHEMA §4.5-A):

  override  대상 코드가 새 추출에 없음  → 고칠 원본이 사라졌다 (★ 막는다)
  suppress  대상 코드가 새 추출에 없음  → 보정 행을 지워도 된다 (안내)
  add       같은 코드가 새 추출에 등록됨 → SAP 정식 등록, 보정 행을 지워도 된다 (안내)

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()   # 윈도우(cp949)에서 파이프로 넘길 때 한글·— 가 죽지 않게

MASTERS = ROOT / "masters"        # --masters 로 바꾼다 (테스트가 실물을 안 건드리게)
TARGET = MASTERS / "refs" / "brand_master.csv"

# 우리 스키마 — masters/refs/brand_master.csv 와 같은 4컬럼(SCHEMA.md §4.5-A).
# vkorg·vtweg 는 SAP 마스터가 고객·브랜드 단위로만 등록돼 있어 항상 비거나
# 무의미했다 — 코드 어디서도 참조하지 않으므로 뺀다.
SCHEMA = ["kunnr", "name1", "zbrand", "zbrant"]
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


def read_manual() -> list[dict[str, str]]:
    path = MASTERS / "refs" / "brand_master_manual.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def report(new: list[dict], current: list[dict], manual: list[dict]) -> list[str]:
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

    def pair(m: dict) -> tuple[str, str]:
        return (m.get("kunnr", ""), m.get("zbrand", ""))

    broken = [m for m in manual if m.get("action") == "override" and pair(m) not in new_pairs]
    stale = [m for m in manual if m.get("action") == "suppress" and pair(m) not in new_pairs]
    landed = [m for m in manual if m.get("action") == "add" and pair(m) in new_pairs]

    if broken:
        print(f"\n★ 이름 보정(override) {len(broken)}건의 대상이 새 추출에 없습니다 — 고칠 원본이 사라졌습니다:")
        for m in broken[:20]:
            print(f"    고객 {m.get('kunnr')} 코드 {m.get('zbrand')} — {m.get('zbrant')!r}")
    for m in stale:
        print(f"  안내: suppress {m.get('kunnr')}/{m.get('zbrand')} — 이미 빠졌으니 보정 행을 지워도 됩니다")
    for m in landed:
        print(f"  안내: add {m.get('kunnr')}/{m.get('zbrand')} — SAP 에 정식 등록됐습니다. 보정 행을 지워도 됩니다")
    if not (broken or stale or landed):
        print(f"\n  보정표와 충돌 없음 (보정 {len(manual)}건)")
    return [f"{m.get('kunnr')}/{m.get('zbrand')}" for m in broken]


def write(rows: list[dict[str, str]]) -> None:
    """원자적으로 교체한다 — 쓰다 만 참조표가 남으면 전 거래처가 멈춘다."""
    tmp = TARGET.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, TARGET)


def main() -> int:
    parser = argparse.ArgumentParser(description="브랜드 마스터 재추출본 반영")
    parser.add_argument("export", help="SAP 에서 뽑은 CSV")
    parser.add_argument("--dry-run", action="store_true", help="계획만 보고 쓰지 않는다")
    parser.add_argument("--masters", default="",
                        help="마스터 폴더 (기본 masters/). 테스트가 사본을 가리킬 때 쓴다")
    parser.add_argument("--yes", action="store_true", help="확인 없이 반영")
    parser.add_argument(
        "--force", action="store_true",
        help="이름 보정(override) 대상이 사라져도 반영한다. "
             "brand_master_manual.csv 를 먼저 정리하는 편이 낫다",
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

    broken = report(new, read_current(), read_manual())

    if broken and not args.force:
        print("\n반영하지 않았습니다. brand_master_manual.csv 에서 위 보정을 먼저 정리하거나, "
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
