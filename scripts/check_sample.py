"""실물 발주서 사전 점검 — **LLM 을 호출하지 않는다. 비용 0.**

거래처 YAML 의 `extraction.hints` 는 "이 라벨 아래 이 값이 있다"고 주장한다.
그 주장이 **실제 문서와 맞는지**를 파싱 전에 확인한다. 안 맞으면 Claude 를
불러봐야 헛돈만 쓴다.

    python scripts/check_sample.py samples/MSC/raw/P7988114.HTM --customer MSC
    python scripts/check_sample.py <파일> --customer KL --text     # 원문도 출력

hints 안의 따옴표 친 문자열을 앵커로 뽑아 전처리된 텍스트에서 찾는다.
예시값이 섞인 앵커("Purchase Order ID:  10972")는 숫자를 떼고 라벨만 다시 찾는다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()   # 윈도우(cp949)에서 파이프로 넘길 때 한글·— 가 죽지 않게

from app.config import get_settings  # noqa: E402
from app.extraction.preprocess import load_document, normalize_ws  # noqa: E402
from app.masters import MasterError, load_customer  # noqa: E402

# hints 는 라벨을 "..." 로 감싸 적는다. 3자 미만은 우연히 맞을 수 있어 버린다.
_QUOTED = re.compile(r'"([^"\n]{3,80})"')
_TRAILING_VALUE = re.compile(r"[\s:：]*[-\d.,/]+\s*$")

# `예: "..."` 줄에 적힌 것은 **값의 예시**다 (브랜드명·PO 번호 등).
# 문서마다 달라서 없는 게 정상인데, 못 찾았다고 띄우면 현업이 헛고생한다.
_EXAMPLE_LINE = re.compile(r"^\s*(예시?|e\.?g\.?|ex)\s*[:)：]")


def anchors(hints: str) -> tuple[list[str], list[str]]:
    """hints 에서 앵커를 뽑아 (라벨, 예시값) 으로 나눈다.

    라벨은 양식에 **반드시** 있어야 하는 문구라 못 찾으면 경고한다.
    예시값은 그 자리에 들어갈 값을 보여준 것뿐이라 없어도 정상이다.
    """
    labels: list[str] = []
    examples: list[str] = []
    for line in (hints or "").splitlines():
        bucket = examples if _EXAMPLE_LINE.match(line) else labels
        for raw in _QUOTED.findall(line):
            text = raw.strip()
            if text and text not in labels and text not in examples:
                bucket.append(text)
    return labels, examples


def label_only(anchor: str) -> str:
    """예시값을 떼고 라벨만 남긴다. `Purchase Order ID:  10972` → `Purchase Order ID`."""
    return _TRAILING_VALUE.sub("", anchor).strip(" :：")


# 라벨만으로 다시 찾을 때의 최소 길이. `PO#` 같은 3자짜리도 살린다
# (따옴표 앵커 자체의 최소 길이와 같은 기준이다).
_MIN_LABEL = 3


def main() -> int:
    ap = argparse.ArgumentParser(description="실물 발주서 사전 점검 (LLM 호출 없음)")
    ap.add_argument("file", help="발주서 파일 경로")
    ap.add_argument("--customer", "-c", required=True, help="거래처 코드 (예: MSC)")
    ap.add_argument("--text", action="store_true", help="전처리된 원문도 출력")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[실패] 파일이 없습니다: {path}", file=sys.stderr)
        return 1

    try:
        master = load_customer(args.customer, get_settings().masters_dir)
    except MasterError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    try:
        doc = load_document(path)
    except Exception as exc:  # noqa: BLE001 — 사용자에게 원인을 그대로 보여준다
        print(f"[실패] 파일을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 1

    expected = [t.lower() for t in master.file_types]
    print("═" * 72)
    print(f"  {master.name} ({master.code})   {path.name}")
    print("═" * 72)
    print(f"  형식        : .{doc.ext}" + (
        f"   ※ 이 거래처는 보통 {'/'.join(expected).upper()} 입니다"
        if expected and doc.ext not in expected else "   (예상과 일치)"
    ))
    print(f"  페이지      : {doc.page_count}")
    print(f"  텍스트레이어: {'있음' if doc.has_text_layer else '없음 — 스캔본. 원본 PDF 를 그대로 판독시킵니다'}")
    print(f"  총 문자수   : {len(doc.full_text):,}")

    if not doc.has_text_layer:
        print("\n  스캔본이라 앵커를 대조할 수 없습니다. 거래처에 텍스트 PDF 를 요청하거나,")
        print("  그대로 파싱해 결과를 눈으로 확인해야 합니다.")
        return 0

    haystack = normalize_ws(doc.full_text).casefold()
    labels, examples = anchors(master.extraction.get("hints") or "")
    found, partial, missing = [], [], []

    for anchor in labels:
        if normalize_ws(anchor).casefold() in haystack:
            found.append(anchor)
            continue
        label = label_only(anchor)
        if len(label) >= _MIN_LABEL and normalize_ws(label).casefold() in haystack:
            partial.append((anchor, label))
        else:
            missing.append(anchor)

    total = len(found) + len(partial) + len(missing)
    print(f"\n  ── hints 앵커 대조 ({total}개) " + "─" * 40)
    if not total and not examples:
        print("  hints 에 따옴표로 적힌 라벨이 없습니다. 대조할 것이 없습니다.")
        return 0

    for anchor in found:
        print(f"    ✓ {anchor}")
    for anchor, label in partial:
        print(f"    ~ {anchor}")
        print(f"        → 예시값을 뺀 '{label}' 로는 찾았습니다 (정상)")
    for anchor in missing:
        print(f"    ✗ {anchor}")

    print(f"\n  찾음 {len(found)} / 라벨만 {len(partial)} / 못 찾음 {len(missing)}")

    # 예시값은 문서마다 달라서 없는 게 정상이다. 집계에 넣지 않고 참고로만 보여준다.
    if examples:
        hit = [e for e in examples if normalize_ws(e).casefold() in haystack]
        print(f"\n  ── hints 의 예시값 ({len(examples)}개) — 없어도 정상 " + "─" * 22)
        for anchor in examples:
            print(f"    {'✓' if anchor in hit else '·'} {anchor}")

    if not found and not partial:
        print("\n  ⛔ 하나도 찾지 못했습니다.")
        print("     거래처를 잘못 지정했거나, hints 가 이 문서 양식과 다릅니다.")
        print("     이대로 파싱하면 비용만 나갑니다. hints 를 먼저 고치세요.")
        return 1

    if missing:
        print("\n  ⚠ 못 찾은 라벨이 있습니다. 둘 중 하나입니다:")
        print("     · 이 문서에만 없는 항목 (다른 발주서로도 확인해 보세요)")
        print("     · hints 가 실제 양식과 어긋남 → masters/customers/"
              f"{master.code.lower()}.yaml 의 hints 수정")
        print("     --text 로 원문을 보면 실제 라벨을 확인할 수 있습니다.")
    else:
        print("\n  ✅ hints 의 라벨이 전부 문서에 있습니다. 파싱을 진행해도 좋습니다:")
        print(f"     python scripts/parse_one.py {path} --customer {master.code} --rows")

    if args.text:
        print("\n" + "─" * 72)
        print(doc.numbered_text()[:6000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
