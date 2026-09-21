"""Claude API 연결 점검 — 메시지를 보내지 않으므로 비용 0.

실물 발주서를 돌리기 **전에** 이것부터 돌린다. 키·주소·모델 ID 중 하나만
틀려도 파싱은 첫 호출에서 죽는데, 그때는 이미 파일을 읽고 프롬프트를 만든
뒤라 원인이 한눈에 안 보인다. 여기서는 모델 조회(models.retrieve)만 하므로
토큰을 쓰지 않으면서 **키·권한·모델 ID 세 가지를 한 번에** 확인한다.

사용법
    python scripts/check_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()

from app.config import get_settings  # noqa: E402
from app.extraction.providers import LLMError, create_provider  # noqa: E402


def _masked(key: str) -> str:
    """키는 절대 그대로 찍지 않는다 — 터미널 기록·캡처가 그대로 유출이다."""
    key = (key or "").strip()
    if not key:
        return "(비어 있음)"
    return f"{key[:7]}…{key[-4:]}  (길이 {len(key)})"


def main() -> int:
    s = get_settings()
    provider_name = (s.llm_provider or "mock").strip().lower()

    print("═" * 64)
    print("  Claude API 연결 점검  (메시지 전송 없음 = 비용 0)")
    print("═" * 64)
    print(f"  LLM_PROVIDER   : {provider_name}")
    print(f"  LLM_BASE_URL   : {s.llm_base_url or '(기본 https://api.anthropic.com)'}")
    print(f"  LLM_API_KEY    : {_masked(s.llm_api_key)}")
    print(f"  추출 모델      : {s.model_id('extract')}")
    print(f"  예비 모델      : {s.model_id('fallback')}")
    print(f"  LLM_PROXY      : {s.llm_proxy or '(없음)'}")
    print(f"  LLM_CA_BUNDLE  : {s.llm_ca_bundle or '(없음)'}")
    print(f"  프롬프트 버전  : {s.llm_prompt_version}")
    print("─" * 64)

    if provider_name in {"anthropic", "gateway"} and not (s.llm_api_key or "").strip():
        print("  [실패] LLM_API_KEY 가 비어 있습니다.")
        print("         .env 에 키를 넣거나 LLM_PROVIDER=mock 으로 되돌리세요.")
        return 1

    if provider_name == "gateway" and not (s.llm_base_url or "").strip():
        print("  [실패] gateway 인데 LLM_BASE_URL 이 비어 있습니다.")
        return 1

    if (s.llm_base_url or "").rstrip("/").endswith("/v1"):
        print("  [주의] LLM_BASE_URL 끝의 /v1 은 SDK 가 붙입니다.")
        print("         그대로 두면 /v1/v1/messages 로 나가 404 가 납니다.")

    try:
        health = create_provider(s).health()
    except LLMError as exc:
        print(f"  [실패] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001  — 프록시·CA 설정 오류가 여기로 온다
        print(f"  [실패] 프로바이더를 만들지 못했습니다: {exc}")
        return 1

    mark = "정상" if health.ok else "실패"
    # gateway 도 내부적으로는 anthropic 클래스를 쓴다. 설정값 쪽 이름을 보여준다.
    print(f"  [{mark}] {provider_name} — {health.detail}")
    print("─" * 64)

    if not health.ok:
        print("  흔한 원인")
        print("   · 키 오타·폐기      → 콘솔에서 재발급")
        print("   · 모델 ID 미허용    → 계정이 쓸 수 있는 ID 로 LLM_MODEL_EXTRACT 수정")
        print("   · 사내 SSL 검사     → LLM_CA_BUNDLE 에 사내 CA(.pem) 경로")
        print("   · 사내 프록시       → LLM_PROXY (셸의 HTTPS_PROXY 는 전달 안 됨)")
        return 1

    if provider_name == "mock":
        print("  mock 은 저장된 응답만 재생합니다. 실물 호출은")
        print("  .env 의 LLM_PROVIDER 를 anthropic 또는 gateway 로 바꾸세요.")
    else:
        print("  다음: 사전 점검 → 실물 1건")
        print("   1) python scripts/check_sample.py <발주서> --customer <코드>")
        print("   2) python scripts/parse_one.py  <발주서> --customer <코드> --rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
