"""배치 업로드·검수 API — contracts/api-contract.md §4~§6."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..batch_service import merge_edits, parse_batch, summary
from ..config import Settings, get_settings
from ..domain.models import Batch, BatchFile, BatchRow
from ..masters import MasterError, load_customer
from ..storage import BatchNotFound, BatchRepo, order_keys, payload_digest, record_send
from ..transport import EaiClient, build_payload, split_rows
from ..transport.eai_client import EaiConfigError

router = APIRouter(prefix="/api/batches", tags=["batches"])

Injected = Annotated[Settings, Depends(get_settings)]

# 업로드 안전장치 — 없으면 디스크가 채워지거나 파싱이 멈춘다.
MAX_FILES = 50
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


class RowEdit(BaseModel):
    row_id: str
    fields: dict[str, str] = Field(default_factory=dict)
    deleted: bool | None = None


class ValidateIn(BaseModel):
    rows: list[RowEdit] = Field(default_factory=list, max_length=5000)


def _repo(settings: Settings) -> BatchRepo:
    return BatchRepo(settings.storage_dir)


def _load(settings: Settings, batch_id: str) -> Batch:
    try:
        return _repo(settings).load(batch_id)
    except BatchNotFound as exc:
        raise HTTPException(404, f"배치를 찾을 수 없습니다: {batch_id}") from exc


# ── §4 업로드 ──────────────────────────────────────────────────────────
@router.post("")
async def create_batch(
    settings: Injected,
    background: BackgroundTasks,
    customer: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> dict[str, Any]:
    try:
        load_customer(customer, settings.masters_dir)
    except MasterError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not files:
        raise HTTPException(400, "업로드된 파일이 없습니다.")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"한 번에 {MAX_FILES}개까지 올릴 수 있습니다 (요청 {len(files)}개).")

    repo = _repo(settings)
    batch_id = repo.new_id()
    entries: list[BatchFile] = []
    total = 0

    for index, upload in enumerate(files, start=1):
        data = await upload.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                400, f"{upload.filename} 이 너무 큽니다 ({len(data) // 1024 // 1024}MB). "
                     f"{MAX_FILE_BYTES // 1024 // 1024}MB 이하로 올려주세요."
            )
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(400, "업로드 합계 용량이 한도를 넘었습니다.")

        file_id = f"f{index}"
        repo.save_upload(batch_id, file_id, upload.filename or file_id, data)
        entries.append(BatchFile(file_id=file_id, name=upload.filename or file_id))

    batch = Batch(
        batch_id=batch_id, customer=customer.upper(),
        status="PARSING", created_at=repo.now(), files=entries,
    )
    repo.save(batch)
    background.add_task(parse_batch, batch_id, settings)

    return {
        "batch_id": batch_id,
        "status": batch.status,
        "files": [
            {"file_id": f.file_id, "name": f.name, "status": f.status} for f in entries
        ],
    }


# ── §5 조회 ────────────────────────────────────────────────────────────
@router.get("/{batch_id}")
def get_batch(batch_id: str, settings: Injected) -> dict[str, Any]:
    return _render(_load(settings, batch_id))


def _render(batch: Batch) -> dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "customer": batch.customer,
        "status": batch.status,
        "created_at": batch.created_at,
        "files": [
            {"file_id": f.file_id, "name": f.name, "status": f.status,
             "error": f.error, "row_count": f.row_count}
            for f in batch.files
        ],
        "columns": batch.columns,
        "grid": batch.grid,
        "rows": [_row(r) for r in batch.rows],
        "summary": summary(batch),
    }


def _row(row: BatchRow) -> dict[str, Any]:
    return {
        "row_id": row.row_id,
        "_file_id": row.file_id,
        "_file": row.file,
        "_group": row.group,
        "_line_no": row.line_no,
        "_deleted": row.deleted,
        "fields": row.fields,
        "issues": [i.model_dump() for i in row.issues],
        "edited": row.edited,
    }


# ── §6 재검증 ──────────────────────────────────────────────────────────
@router.post("/{batch_id}/validate")
def validate_batch_rows(batch_id: str, body: ValidateIn, settings: Injected) -> dict[str, Any]:
    """검수 중 재검증. **값은 프론트가 주인이지만 판단은 서버가 한다.**

    응답에 값을 되돌려주지 않는다 — 편집 중인 셀이 덮어써지면 안 되기 때문이다.
    """
    batch = _load(settings, batch_id)
    if batch.status in {"SENDING", "SENT"}:
        raise HTTPException(409, f"이미 {batch.status} 상태인 배치는 수정할 수 없습니다.")

    rejected = merge_edits(batch, [r.model_dump() for r in body.rows], settings)
    if rejected:
        raise HTTPException(
            400,
            "이 배치에 없는 행입니다: " + ", ".join(rejected[:5])
            + (" 외" if len(rejected) > 5 else "")
            + ". 화면을 새로고침해 주세요.",
        )

    _repo(settings).save(batch)
    return {
        "status": batch.status,
        "rows": [
            {"row_id": r.row_id, "issues": [i.model_dump() for i in r.issues],
             "edited": r.edited, "_deleted": r.deleted}
            for r in batch.rows
        ],
        "summary": summary(batch),
    }


# ── §7 전송 ────────────────────────────────────────────────────────────
@router.post("/{batch_id}/send")
def send_batch(batch_id: str, body: ValidateIn, settings: Injected) -> dict[str, Any]:
    """검수 완료 행을 EAI 로 보낸다.

    요청의 값도 §6.1 과 같은 규칙으로 서버 스냅샷에 병합한다 — 전송 직전이라고
    해서 검증을 건너뛰지 않는다. 오히려 여기가 마지막 방어선이다.
    """
    repo = _repo(settings)
    batch = _load(settings, batch_id)

    # 계약 §7 — 재전송은 같은 API 재호출이다. SENT 여도 다시 보낼 수 있다.
    # 전제는 "중복 전송 무해"(design D7)인데 **CBO 업서트 키가 아직 미확정이다.**
    # 키가 없으면 재전송이 덮어쓰기가 아니라 중복 적재가 된다 — 감사 로그에
    # resend 로 남겨 나중에 되짚을 수 있게 한다.
    resend = batch.status == "SENT"
    if batch.status == "SENDING":
        raise HTTPException(409, "전송이 진행 중입니다.")

    rejected = merge_edits(batch, [r.model_dump() for r in body.rows], settings)
    if rejected:
        raise HTTPException(400, "이 배치에 없는 행입니다: " + ", ".join(rejected[:5]))

    rows = batch.live_rows
    if not rows:
        raise HTTPException(409, "보낼 행이 없습니다.")

    blocked = sum(r.error_count for r in rows)
    if blocked:
        repo.save(batch)
        raise HTTPException(409, f"오류 {blocked}건을 먼저 해결해야 전송할 수 있습니다.")

    batch.status = "SENDING"
    repo.save(batch)

    client = EaiClient(settings)
    chunks = split_rows(rows, settings.eai_max_rows_per_request)
    sent = 0
    attempts = 0
    failure = ""

    try:
        for index, chunk in enumerate(chunks, start=1):
            payload = build_payload(chunk, batch.columns, root=settings.payload_root)
            outcome = client.send(payload)
            attempts += outcome.attempts

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
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:                     # require_eai_endpoint
        batch.status = "SEND_FAILED"
        repo.save(batch)
        raise HTTPException(400, str(exc)) from exc

    ok = not failure
    batch.status = "SENT" if ok else "SEND_FAILED"
    sent_at = repo.now()
    repo.save(batch)

    return {
        "status": batch.status,
        "sent_rows": sent,
        "attempts": attempts,
        "sent_at": sent_at if ok else "",
        "resend": resend,
        "message": (
            (f"{sent}건을 다시 전송했습니다." if resend else f"{sent}건이 EAI로 전송되었습니다.")
            if ok
            else f"{failure} ({sent}/{len(rows)}건 전송됨. 재전송할 수 있습니다.)"
        ),
    }
