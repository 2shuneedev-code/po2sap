"""배치 저장소 — storage/batches/{batch_id}/.

    batch.json          상태 · 파일 · 행 (파싱 원본 스냅샷 포함)
    uploads/{file_id}   업로드 원본

**파싱 원본을 서버가 들고 있는 것이 핵심이다.** 검수 화면이 보내오는 값을 그대로
믿으면 없는 행을 끼워 넣거나 규칙이 정한 코드를 임의로 바꿔도 막을 방법이 없다.
서버는 row_id 로 자기 스냅샷에 병합하고, 무엇이 바뀌었는지(`edited`)를 스스로 계산한다.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..domain.models import Batch

__all__ = ["BatchRepo", "BatchNotFound", "STALE_PARSING_MESSAGE"]

STALE_PARSING_MESSAGE = "파싱이 중단되었습니다. 다시 변환하세요."

_SAFE_ID = re.compile(r"^b_\d{8}_\d{4}$")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class BatchNotFound(KeyError):
    pass


class BatchRepo:
    def __init__(self, storage_dir: Path, *, stale_after_sec: int | None = None) -> None:
        """`stale_after_sec` — PARSING 으로 이만큼 지난 배치를 중단된 것으로 본다 (아래 `load`).

        생략하면 설정(`PARSE_STALE_SEC`)을 따른다. 테스트는 값을 직접 넘겨 시계를 다룬다.
        """
        self._root = Path(storage_dir) / "batches"
        self._stale_after_sec = stale_after_sec

    # ── 경로 ───────────────────────────────────────────────────────────
    def _dir(self, batch_id: str) -> Path:
        if not _SAFE_ID.match(batch_id):
            # 경로 조작 차단 — batch_id 는 URL 에서 온다.
            raise BatchNotFound(batch_id)
        return self._root / batch_id

    def upload_path(self, batch_id: str, file_id: str, name: str) -> Path:
        safe = _UNSAFE_NAME.sub("_", Path(name).name).strip("_") or "upload"
        return self._dir(batch_id) / "uploads" / f"{file_id}__{safe}"

    # ── 식별자 ─────────────────────────────────────────────────────────
    def new_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self._root.mkdir(parents=True, exist_ok=True)
        used = {p.name for p in self._root.glob(f"b_{today}_*")}
        for n in range(1, 10000):
            candidate = f"b_{today}_{n:04d}"
            if candidate not in used:
                return candidate
        raise RuntimeError("하루 배치 한도(9999)를 넘었습니다.")

    @staticmethod
    def now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    # ── 읽기/쓰기 ──────────────────────────────────────────────────────
    def exists(self, batch_id: str) -> bool:
        try:
            return (self._dir(batch_id) / "batch.json").exists()
        except BatchNotFound:
            return False

    def load(self, batch_id: str) -> Batch:
        """저장된 배치. **오래된 PARSING 은 반환 객체에서만 FAILED 로 보인다** (design.md §8.2).

        서버가 재기동되면 `BackgroundTasks` 로 돌던 파싱이 사라지고 배치는 PARSING 으로
        디스크에 영원히 남는다. 읽을 때 한 번 나이를 보고 `PARSE_STALE_SEC` 를 넘겼으면
        실패로 보여 준다. **디스크는 고치지 않는다** — 정말로 아직 돌고 있는 작업을 다른
        프로세스가 죽은 것으로 단정해 덮어쓰는 사고를 피한다.
        """
        path = self._dir(batch_id) / "batch.json"
        if not path.exists():
            raise BatchNotFound(batch_id)
        batch = Batch.model_validate_json(path.read_text(encoding="utf-8"))
        return self._as_stale_if_abandoned(batch)

    def _as_stale_if_abandoned(self, batch: Batch) -> Batch:
        if batch.status != "PARSING":
            return batch
        limit = (
            self._stale_after_sec
            if self._stale_after_sec is not None
            else get_settings().parse_stale_sec
        )
        try:
            created = datetime.fromisoformat(batch.created_at)
        except ValueError:
            return batch                    # 언제 시작했는지 모르면 단정하지 않는다
        if created.tzinfo is None:
            created = created.astimezone()  # 시간대 없는 값은 서버 로컬로 본다
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age <= limit:
            return batch

        for entry in batch.files:
            if entry.status == "PARSING":
                entry.status, entry.error = "FAILED", STALE_PARSING_MESSAGE
        batch.status = "FAILED"
        return batch

    def save(self, batch: Batch) -> None:
        directory = self._dir(batch.batch_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "batch.json"

        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".batch.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(json.loads(batch.model_dump_json()), f, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def save_upload(self, batch_id: str, file_id: str, name: str, data: bytes) -> Path:
        path = self.upload_path(batch_id, file_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
