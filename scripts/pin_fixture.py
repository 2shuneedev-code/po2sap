"""실제 응답을 **고정 픽스처**로 박는다 — 시연·회귀용.

왜 필요한가. 라이브 호출은 매번 결과가 조금씩 다르고, 네트워크·키·요금이
걸려 있다. **사람 앞에서 보여줄 때 그 셋 중 하나라도 어긋나면 되돌릴 수 없다.**

픽스처로 박아 두면 `LLM_PROVIDER=mock` 이 그 파일을 그대로 재생한다.
오프라인·비용 0·매번 같은 결과다. 추출기는 **런타임 캐시보다 픽스처를 먼저**
보므로, 박아 두면 그 값이 이긴다.

찾는 이름은 `{거래처}__{파일명}.json` 이다 — 해시가 아니라서 프롬프트나 모델이
바뀌어도 계속 재생된다.

사용법
    # 1) 실제로 한 번 파싱한다 (LLM_PROVIDER=anthropic)
    python scripts/parse_one.py samples/발주서.htm --customer MSC --rows

    # 2) 그 결과를 픽스처로 박는다
    python scripts/pin_fixture.py samples/발주서.htm --customer MSC

    # 3) 값이 틀렸으면 픽스처 JSON 을 **손으로 고친다** (payload 안의 value)
    #    고친 내용이 다음 재생부터 그대로 나온다

    # 4) .env 를 LLM_PROVIDER=mock 으로 두고 시연한다

    --dry-run 무엇을 어디에 쓸지만 보여준다
    --force   이미 있는 픽스처를 덮어쓴다
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

use_utf8()

from app.config import get_settings  # noqa: E402
from app.extraction.preprocess import load_document  # noqa: E402
from app.extraction.providers import cache as llm_cache  # noqa: E402
from app.masters import MasterError, load_customer  # noqa: E402


def _document_input(path: Path, master):
    """추출기와 **같은 방식으로** 문서를 만든다 — 캐시 키가 맞아야 찾는다."""
    from app.extraction.providers.base import DocumentInput

    doc = load_document(path)
    mode = (master.extraction.get("input") or "auto").lower()
    use_text = doc.has_text_layer if mode == "auto" else (mode == "text")
    if use_text:
        return DocumentInput(text=doc.numbered_text(), filename=doc.filename)
    return DocumentInput(pdf_bytes=doc.raw_bytes, filename=doc.filename)


def main() -> int:
    ap = argparse.ArgumentParser(description="실제 응답을 고정 픽스처로 박는다")
    ap.add_argument("file", help="발주서 파일 경로")
    ap.add_argument("--customer", "-c", required=True, help="거래처 코드 또는 고객코드")
    ap.add_argument("--dry-run", action="store_true", help="계획만 출력")
    ap.add_argument("--force", action="store_true", help="이미 있는 픽스처를 덮어쓴다")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[실패] 파일이 없습니다: {path}", file=sys.stderr)
        return 1

    settings = get_settings()
    try:
        master = load_customer(args.customer, settings.masters_dir)
    except MasterError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    document = _document_input(path, master)
    dest = llm_cache.fixture_path(settings.llm_fixtures_dir, master.code, document.filename)

    print("═" * 66)
    print(f"  {master.name} ({master.code})   {document.filename}")
    print("═" * 66)

    if dest.exists() and not args.force:
        print(f"  이미 픽스처가 있습니다: {dest}")
        print("  이 파일이 이미 재생됩니다. 바꾸려면 직접 고치거나 --force 를 주세요.")
        return 0

    key = llm_cache.cache_key(
        document=document,
        prompt_version=settings.llm_prompt_version,
        customer=master.code,
        model=settings.model_id("extract"),
    )
    source = llm_cache.cache_path(settings.llm_cache_dir, key)
    if not source.exists():
        print("  [실패] 이 문서의 실제 응답이 캐시에 없습니다.")
        print(f"         찾은 곳: {source}")
        print("\n  먼저 실제로 한 번 파싱하세요 (.env 의 LLM_PROVIDER=anthropic):")
        print(f"    python scripts/parse_one.py {path} --customer {args.customer} --rows")
        print("\n  모델 ID 나 LLM_PROMPT_VERSION 을 그 뒤에 바꿨다면 키가 달라져")
        print("  못 찾습니다. 파싱할 때와 같은 .env 로 실행하세요.")
        return 1

    data = json.loads(source.read_text(encoding="utf-8"))
    data["_comment"] = (
        f"{master.code} / {document.filename} 의 실제 응답을 고정한 픽스처. "
        "mock 프로바이더가 이 파일을 그대로 재생한다 (오프라인·비용 0·결과 고정). "
        "값이 틀렸으면 payload 안의 value 를 손으로 고친다 — 고친 값이 그대로 재생된다."
    )

    print(f"  원본 캐시 : {source.name}")
    print(f"  픽스처    : {dest}")
    print(f"  모델      : {data.get('model') or '(기록 없음)'}")
    header = (data.get("payload") or {}).get("header") or {}
    if header:
        print("\n  헤더 값 (틀린 것이 있으면 픽스처를 고치세요)")
        for name, field in list(header.items())[:12]:
            value = field.get("value") if isinstance(field, dict) else field
            print(f"    {name:<16} {value}")
    payload = data.get("payload") or {}
    # 분할 문서는 품목이 shipments[].lines 에 있다 (상단 요약표는 품목으로 받지 않는다)
    count = len(payload.get("lines") or []) + sum(
        len(s.get("lines") or []) for s in payload.get("shipments") or [] if isinstance(s, dict)
    )
    print(f"\n  품목 {count}건")

    if args.dry_run:
        print("\n  --dry-run 이라 쓰지 않았습니다.")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n  ✅ 박았습니다. 이제 .env 를 LLM_PROVIDER=mock 으로 두면")
    print("     이 문서는 오프라인·비용 0 으로 같은 결과가 나옵니다.")
    print(f"\n  값을 고치려면: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
