"""전송 — 검수 완료 행을 EAI 로 보낸다.

라우트와 스트림릿 화면이 **같은 함수**를 부른다. 전송은 되돌릴 수 없는 동작이라
경로가 둘이면 한쪽만 고쳐지는 순간 진짜 오더가 잘못 나간다.

계약은 contracts/api-contract.md §7 이다. 판정은 HTTP 상태 코드에만 건다
(§7.1 — EAI 응답 본문 규격이 아직 없다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .batch_service import merge_edits
from .config import Settings
from .domain.models import Batch
from .storage import BatchRepo, order_keys, payload_digest, record_send
from .transport import EaiClient, build_payload, split_rows
from .transport.eai_client import EaiConfigError

__all__ = ["SendBlocked", "SendReport", "send_batch"]


class SendBlocked(Exception):
    """보내기 전에 막힌 경우. `status` 는 계약 §0 의 HTTP 코드다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class SendReport:
    status: str
    sent_rows: int
    attempts: int
    sent_at: str
    resend: bool
    message: str

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "sent_rows": self.sent_rows,
            "attempts": self.attempts,
            "sent_at": self.sent_at,
            "resend": self.resend,
            "message": self.message,
        }


@dataclass
class _Progress:
    chunks: int = 0
    done: int = 0
    rows: list = field(default_factory=list)


def send_batch(batch: Batch, edits: list[dict], settings: Settings) -> SendReport:
    """검수 값을 스냅샷에 병합하고, 오류가 없으면 EAI 로 보낸다.

    전송 직전이라고 검증을 건너뛰지 않는다 — 여기가 마지막 방어선이다.
    """
    repo = BatchRepo(settings.storage_dir, stale_after_sec=settings.parse_stale_sec)

    # 계약 §7 — 재전송은 같은 호출이다. SENT 여도 다시 보낼 수 있다.
    # 전제는 "중복 전송 무해"(design D7)인데 **CBO 업서트 키가 아직 미확정이다.**
    # 키가 없으면 재전송이 덮어쓰기가 아니라 중복 적재가 된다 — 감사 로그에
    # resend 로 남겨 나중에 되짚을 수 있게 한다.
    resend = batch.status == "SENT"
    if batch.status == "SENDING":
        raise SendBlocked(409, "전송이 진행 중입니다.")

    rejected = merge_edits(batch, edits, settings)
    if rejected:
        raise SendBlocked(400, "이 배치에 없는 행입니다: " + ", ".join(rejected[:5]))

    rows = batch.live_rows
    if not rows:
        raise SendBlocked(409, "보낼 행이 없습니다.")

    blocked = sum(r.error_count for r in rows)
    if blocked:
        repo.save(batch)
        raise SendBlocked(409, f"오류 {blocked}건을 먼저 해결해야 전송할 수 있습니다.")

    batch.status = "SENDING"
    repo.save(batch)

    client = EaiClient(settings)
    chunks = split_rows(rows, settings.eai_max_rows_per_request)
    sent = attempts = 0
    failure = ""

    try:
        for index, chunk in enumerate(chunks, start=1):
            payload = build_payload(chunk, batch.columns, root=settings.payload_root)
            outcome = client.send(payload)
            attempts += outcome.attempts

            # 감사 로그에 품번·단가는 넣지 않는다 — 5년 보존 파일이다 (design §8.1).
            record_send(settings.storage_dir, {
                "batch_id": batch.batch_id,
                "customer": batch.customer,
                "action": "resend" if resend else "send",
                "chunk": f"{index}/{len(chunks)}",
                "endpoint": outcome.endpoint,
                "auth_mode": settings.eai_auth_mode,
                "verify_tls": settings.eai_verify_tls,
                "row_count": len(chunk),
                "orders": order_keys([r.fields for r in chunk]),
                "payload_sha256": payload_digest(payload),
                "attempts": outcome.attempts,
                "http_status": outcome.status_code,
                "duration_ms": outcome.duration_ms,
                "result": "ok" if outcome.ok else "failed",
                "message": outcome.message,
                "response_excerpt": outcome.response_excerpt[:500],
            })

            if not outcome.ok:
                failure = outcome.message
                break
            sent += len(chunk)

    except EaiConfigError as exc:
        batch.status = "SEND_FAILED"
        repo.save(batch)
        record_send(settings.storage_dir, {
            "batch_id": batch.batch_id, "customer": batch.customer, "action": "send",
            "result": "config_error", "message": str(exc),
        })
        raise SendBlocked(400, str(exc)) from exc
    except ValueError as exc:                     # require_eai_endpoint
        batch.status = "SEND_FAILED"
        repo.save(batch)
        raise SendBlocked(400, str(exc)) from exc

    ok = not failure
    batch.status = "SENT" if ok else "SEND_FAILED"
    sent_at = repo.now()
    repo.save(batch)

    return SendReport(
        status=batch.status,
        sent_rows=sent,
        attempts=attempts,
        sent_at=sent_at if ok else "",
        resend=resend,
        message=(
            (f"{sent}건을 다시 전송했습니다." if resend else f"{sent}건이 EAI로 전송되었습니다.")
            if ok
            else f"{failure} ({sent}/{len(rows)}건 전송됨. 재전송할 수 있습니다.)"
        ),
    )
