"""D1 확인용 CLI: 발주서 1부를 파싱해 결과를 콘솔에 출력한다.

사용법
    python scripts/parse_one.py <파일경로> --customer MSC
    python scripts/parse_one.py sample.pdf --customer MSC --json out.json
    python scripts/parse_one.py sample.pdf --customer MSC --text-only   # 전처리만 확인
    python scripts/parse_one.py sample.pdf --customer MSC --rows         # 전송 행까지
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()   # 윈도우(cp949)에서 파이프로 넘길 때 한글·— 가 죽지 않게

from app.config import get_settings  # noqa: E402
from app.extraction import Extractor, load_document  # noqa: E402
from app.extraction.providers.base import LLMError  # noqa: E402
from app.masters import MasterError, load_customer  # noqa: E402
from app.rules.engine import build  # noqa: E402


def _print_lines(lines, *, indent: int = 2, title: str | None = None) -> None:
    pad = " " * indent
    if title:
        print(f"\n{title}")
    print(f"{pad}{'#':>3} {'our_item':<14} {'item_code':<14} {'수량':>10} {'단가':>10}  품명")
    for line in lines:
        print(
            f"{pad}{line.line_no:>3} "
            f"{(line.our_item.value or '-'):<14} "
            f"{(line.item_code.value or '-'):<14} "
            f"{(line.quantity.value or '-'):>10} "
            f"{(line.unit_price.value or '-'):>10}  "
            f"{(line.description.value or '')[:36]}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="발주서 1부 파싱 (D1 확인용)")
    ap.add_argument("file", help="발주서 파일 경로 (PDF/HTM)")
    ap.add_argument("--customer", "-c", required=True, help="거래처 코드 (예: MSC)")
    ap.add_argument("--json", "-o", help="결과를 JSON 파일로 저장")
    ap.add_argument("--text-only", action="store_true", help="전처리 결과(원문 텍스트)만 출력")
    ap.add_argument("--rows", action="store_true", help="규칙엔진까지 돌려 전송 행을 출력")
    args = ap.parse_args()

    path = Path(args.file)

    # ── 전처리만 확인 (LLM 호출 없음 = 무료) ──────────────────
    if args.text_only:
        doc = load_document(path)
        print(f"파일       : {doc.filename}")
        print(f"형식       : {doc.ext}")
        print(f"페이지     : {doc.page_count}")
        print(f"텍스트레이어: {'있음' if doc.has_text_layer else '없음 (스캔본)'}")
        print(f"총 문자수  : {len(doc.full_text):,}")
        print("─" * 70)
        print(doc.numbered_text()[:4000])
        return 0

    # ── 파싱 ──────────────────────────────────────────────────
    try:
        result = Extractor().parse_file(path, args.customer)
    except (MasterError, LLMError, ValueError, FileNotFoundError) as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    raw = result.raw
    print("═" * 70)
    print(f"  거래처   : {raw.customer_code}")
    print(f"  파일     : {raw.source_file}")
    print(f"  프로바이더: {result.provider} / {result.model_used}"
          f"{'  (캐시 재사용)' if result.cached else ''}")
    print("═" * 70)

    h = raw.header
    print("\n[헤더]")
    for name in ("po_number", "po_date", "requested_date", "ship_to_text",
                 "brand_text", "incoterms_text", "currency_text",
                 "packing_spec", "remark_default"):
        v = getattr(h, name)
        conf = f"  (신뢰도 {v.confidence:.2f})" if v.confidence is not None else ""
        print(f"  {name:<18}: {v.value}{conf}")

    if raw.shipments:
        # split.by 가 none 이 아닌 거래처: 출하처 블록 = 오더 1건 (SCHEMA.md §2.1)
        print(f"\n[오더 분할] {len(raw.shipments)}건")
        for idx, shipment in enumerate(raw.shipments, start=1):
            head = " / ".join(
                x for x in (shipment.shipment_no.value, shipment.receiving_loc.value) if x
            )
            print(f"\n  ── 출하처 {idx}{f'  ({head})' if head else ''}")
            first = (shipment.ship_to_text.value or "").strip().splitlines()
            print(f"     ship_to: {first[0] if first else '-'}")
            _print_lines(shipment.lines, indent=5)
        if raw.lines:
            print(f"\n  ※ 상단 요약표 {len(raw.lines)}건은 합계 대조용이며 오더를 만들지 않는다")
    else:
        _print_lines(raw.lines, indent=2, title=f"[품목] {len(raw.lines)}건")

    t = raw.totals
    print(f"\n[발주서 기재 합계] 품목수={t.line_count}  수량={t.total_qty}  금액={t.total_amount}")

    # ── 검증 결과 ─────────────────────────────────────────────
    print(f"\n[검증] 오류 {result.error_count}건 / 경고 {result.warn_count}건")
    for issue in result.issues:
        mark = "⛔" if issue.level == "error" else "⚠"
        print(f"  {mark} [{issue.code}] {issue.field}")
        print(f"      {issue.message}")

    if raw.notes:
        print("\n[특이사항]")
        for n in raw.notes:
            print(f"  · {n}")

    # ── 규칙엔진 (SCHEMA.md §2 의 ②~⑦) ───────────────────────
    if args.rows:
        settings = get_settings()
        master = load_customer(args.customer, settings.masters_dir)
        result = build(raw, master, settings.masters_dir, file_name=raw.source_file)

        print(f"\n[전송 행] {len(result.rows)}건 × {len(result.columns)}필드"
              f"  (오류 {result.error_count} / 경고 {result.warn_count})")
        shown = [c for c in result.columns if c not in set(result.grid.get("hidden") or [])]
        for row in result.rows:
            head = f"  {row.row_id}"
            if row.group:
                head += f"  [{row.group}]"
            print(f"\n{head}")
            for name in shown:
                value = row.fields.get(name, "")
                if value:
                    print(f"      {name:<8} {value}")
            for issue in row.issues:
                mark = "⛔" if issue.severity == "error" else "⚠"
                print(f"      {mark} [{issue.code}] {issue.field}: {issue.message}")

    if args.json:
        out = Path(args.json)
        out.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n결과 저장: {out}")

    return 0 if result.error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
