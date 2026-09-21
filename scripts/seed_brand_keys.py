#!/usr/bin/env python
"""브랜드 매핑 초벌 채우기 — SAP 브랜드명을 발주서 원문 문구로 쓴다.

    python scripts/seed_brand_keys.py --dry-run   # 무엇이 채워지는지
    python scripts/seed_brand_keys.py             # 확인 후 채움

SAP 의 브랜드명(`ZBRANT`)이 대개 발주서에 그대로 찍힌다 — MSC 의 `HERTEL → 38`
도 브랜드명 `HERTEL BRAND` 에서 온 것이다. 그래서 브랜드 마스터만 있으면
매핑의 **초벌**은 기계가 채울 수 있다. 사람이 처음부터 78곳 300건을 치지 않는다.

초벌일 뿐이다. 실제 발주서 문구가 다르면(`ACCUPRO-CARBIDE DRILL MILL (AP`)
현업이 화면에서 고친다. 그래서
  · **이미 사람이 채운 것은 건드리지 않는다** (같은 코드에 키가 있으면 통째로 건너뜀)
  · 채운 행에 `note` 로 "자동 초벌"임을 남긴다 — 확인 안 된 값임을 숨기지 않는다
  · 한 고객 안에서 브랜드명이 겹치는 코드는 **채우지 않는다** (어느 쪽인지 모른다)

LLM 호출 없음 = 비용 0.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()   # 윈도우(cp949)에서 파이프로 넘길 때 한글·— 가 죽지 않게

MASTERS = ROOT / "masters"        # --masters 로 바꾼다 (테스트가 실물을 안 건드리게)

NOTE = "자동 초벌 (SAP 브랜드명) — 실제 발주서 문구 확인 필요"


def plan(masters: Path) -> tuple[dict, list[str]]:
    """채울 것과, 건너뛴 이유."""
    from app.masters import brands as store

    master = store.load_master(masters)
    keys = store.load_keys(masters)

    mapped = {(k.kunnr, k.zbrand) for k in keys}

    # 한 고객 안에서 브랜드명이 겹치면 어느 코드로 갈지 알 수 없다.
    by_text: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for b in master:
        if b.name.strip():
            by_text[(b.kunnr, b.name.strip().upper())].append(b.zbrand)
    ambiguous = {k for k, v in by_text.items() if len(v) > 1}

    grouped: dict[tuple[str, str], list] = {}
    skipped: list[str] = []
    for b in master:
        text = b.name.strip()
        if not text:
            skipped.append(f"{b.kunnr}/{b.zbrand} — 브랜드명이 비어 있음")
            continue
        if (b.kunnr, b.zbrand) in mapped:
            continue                       # 사람이 채운 것은 건드리지 않는다
        if (b.kunnr, text.upper()) in ambiguous:
            skipped.append(f"{b.kunnr}/{b.zbrand} — '{text}' 가 이 고객 안에서 중복")
            continue
        grouped[(b.kunnr, b.zbrand)] = [
            store.BrandKey(kunnr=b.kunnr, zbrand=b.zbrand, match="contains",
                           text=text, note=NOTE)
        ]
    return grouped, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="브랜드 매핑 초벌 채우기")
    ap.add_argument("--dry-run", action="store_true", help="계획만 보고 쓰지 않는다")
    ap.add_argument("--yes", action="store_true", help="확인 없이 채움")
    ap.add_argument("--masters", default="", help="마스터 폴더 (기본 masters/)")
    args = ap.parse_args()

    masters = Path(args.masters) if args.masters else MASTERS
    from app.masters import brands as store

    grouped, skipped = plan(masters)
    before = len(store.load_keys(masters))

    print(f"기존 매핑 {before}건")
    print(f"채울 것   {len(grouped)}건 ({len({k for k, _ in grouped})}곳)")
    if skipped:
        print(f"건너뜀    {len(skipped)}건")
        for line in skipped[:10]:
            print(f"    {line}")
        if len(skipped) > 10:
            print(f"    … 외 {len(skipped) - 10}건")

    if not grouped:
        print("\n채울 것이 없습니다.")
        return 0
    if args.dry_run:
        print("\n--dry-run 이라 쓰지 않았습니다.")
        return 0
    if not args.yes:
        answer = input("\n채울까요? (기존 매핑은 그대로 둡니다) [y/N] ").strip().lower()
        if answer != "y":
            print("취소했습니다.")
            return 0

    failed = 0
    for (kunnr, zbrand), rows in grouped.items():
        try:
            store.set_keys(masters, kunnr, zbrand, rows)
        except (store.BrandError, ValueError) as exc:
            print(f"  ⛔ {kunnr}/{zbrand} — {exc}")
            failed += 1

    after = len(store.load_keys(masters))
    print(f"\n채웠습니다: {before} → {after}건" + (f" (거부 {failed}건)" if failed else ""))
    print("화면의 **브랜드 매핑** 탭에서 실제 발주서 문구로 고칠 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
