"""EAI HTTP 클라이언트.

**EAI 응답 규격은 아직 백지다.** 그래서 판정을 HTTP 상태 코드에만 건다.

    2xx            성공
    4xx            영구 실패 — 재시도하지 않는다 (같은 요청은 또 거부된다)
    5xx·타임아웃   일시 실패 — 백오프 재시도

응답 본문은 해석하지 않고 **감사 로그에 발췌를 남긴다.** 실제 트래픽이 쌓이면
본문으로 성공/부분실패를 구분하는 규격을 확정하고 여기에 판정을 추가한다.
그때까지 "HTTP 200 인데 본문에 실패가 적힌" 경우는 잡지 못한다 — 알려진 한계다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings

__all__ = ["EaiClient", "SendOutcome", "EaiConfigError"]

_EXCERPT = 2000


class EaiConfigError(ValueError):
    """보내기 전에 막는 설정 오류. 사용자에게 그대로 보여준다."""


@dataclass
class SendOutcome:
    ok: bool
    attempts: int = 0
    status_code: int | None = None
    message: str = ""
    response_excerpt: str = ""
    duration_ms: int = 0
    retryable: bool = False
    endpoint: str = ""
    headers_sent: list[str] = field(default_factory=list)


class EaiClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    # ── 인증 (design.md §5 — 현재 사내망 무인증, 설정만 유지) ──────────
    def _auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        mode = (self._s.eai_auth_mode or "none").strip().lower()
        if mode == "none":
            return {}, None
        if mode == "apikey":
            if not self._s.eai_api_key:
                raise EaiConfigError("EAI_AUTH_MODE=apikey 인데 EAI_API_KEY 가 비어 있습니다.")
            return {self._s.eai_api_key_header: self._s.eai_api_key}, None
        if mode == "basic":
            if not self._s.eai_basic_user:
                raise EaiConfigError("EAI_AUTH_MODE=basic 인데 EAI_BASIC_USER 가 비어 있습니다.")
            return {}, httpx.BasicAuth(self._s.eai_basic_user, self._s.eai_basic_password)
        raise EaiConfigError(f"알 수 없는 EAI_AUTH_MODE 입니다: {mode} (none | apikey | basic)")

    def _verify(self) -> Any:
        if not self._s.eai_verify_tls:
            # 끄는 것을 막지는 않되, 흔적은 남긴다 (감사 로그에 기록된다).
            return False
        return self._s.eai_ca_bundle or True

    # ── 전송 ───────────────────────────────────────────────────────────
    def send(self, payload: Any) -> SendOutcome:
        endpoint = self._s.require_eai_endpoint()       # 형식·HTTPS 검사
        headers, auth = self._auth()
        headers = {"Content-Type": "application/json; charset=utf-8", **headers}

        attempts = 0
        last = SendOutcome(ok=False, endpoint=endpoint, headers_sent=sorted(headers))
        started = time.monotonic()

        for attempt in range(1, max(1, self._s.eai_retries) + 1):
            attempts = attempt
            try:
                with httpx.Client(
                    timeout=self._s.eai_timeout_sec, verify=self._verify()
                ) as client:
                    response = client.post(endpoint, json=payload, headers=headers, auth=auth)
            except httpx.TimeoutException:
                last = SendOutcome(
                    ok=False, retryable=True,
                    message=f"EAI 응답 없음 (타임아웃 {self._s.eai_timeout_sec}초).",
                )
            except httpx.HTTPError as exc:
                last = SendOutcome(
                    ok=False, retryable=True, message=f"EAI 에 연결하지 못했습니다: {exc}"
                )
            else:
                excerpt = response.text[:_EXCERPT]
                if response.is_success:
                    last = SendOutcome(
                        ok=True, status_code=response.status_code, response_excerpt=excerpt
                    )
                    break
                retryable = response.status_code >= 500
                last = SendOutcome(
                    ok=False, status_code=response.status_code, retryable=retryable,
                    response_excerpt=excerpt,
                    message=(
                        f"EAI 가 요청을 거부했습니다 (HTTP {response.status_code}). "
                        + ("잠시 후 재전송할 수 있습니다." if retryable
                           else "요청 내용을 확인해야 합니다 — 재시도해도 같은 결과입니다.")
                    ),
                )

            if not last.retryable:
                break
            if attempt < max(1, self._s.eai_retries):
                time.sleep(2 ** (attempt - 1))          # 1초 · 2초 · 4초

        last.attempts = attempts
        last.endpoint = endpoint
        last.headers_sent = sorted(headers)
        last.duration_ms = int((time.monotonic() - started) * 1000)
        if last.ok and not last.message:
            last.message = "전송되었습니다."
        return last
