"""PARSING 으로 남은 배치 — design.md §8.2.

서버가 재기동되면 `BackgroundTasks` 로 돌던 파싱이 사라지고 배치는 PARSING 으로 디스크에 영원히
남는다. **읽을 때 한 번 나이를 보고 조회 결과에서만 FAILED 로 보인다. 디스크는 고치지 않는다.**

임시 저장소에서만 한다 — 실물 `storage/batches/` 를 건드리지 않는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.domain.models import Batch, BatchFile
from app.storage import BatchRepo
from app.storage.batch_repo import STALE_PARSING_MESSAGE


def stamp(seconds_ago: float) -> str:
    when = datetime.now(UTC).astimezone() - timedelta(seconds=seconds_ago)
    return when.isoformat(timespec="seconds")


def saved(repo: BatchRepo, *, status="PARSING", age=0.0, file_status="PARSING",
          created_at: str | None = None) -> str:
    batch = Batch(
        batch_id=repo.new_id(), customer="MSC", status=status,
        created_at=stamp(age) if created_at is None else created_at,
        files=[BatchFile(file_id="f1", name="a.htm", status=file_status),
               BatchFile(file_id="f2", name="b.htm", status="DONE", row_count=3)],
    )
    repo.save(batch)
    return batch.batch_id


def on_disk(tmp_path, batch_id: str) -> dict:
    return json.loads((tmp_path / "batches" / batch_id / "batch.json").read_text(encoding="utf-8"))


def test_an_old_parsing_batch_reads_as_failed_with_the_reason(tmp_path):
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    batch_id = saved(repo, age=3600)

    batch = repo.load(batch_id)

    assert batch.status == "FAILED"
    stuck, finished = batch.files
    assert stuck.status == "FAILED" and stuck.error == STALE_PARSING_MESSAGE
    assert STALE_PARSING_MESSAGE == "파싱이 중단되었습니다. 다시 변환하세요."
    assert finished.status == "DONE" and finished.error == ""       # 끝난 파일은 그대로


def test_the_disk_is_not_touched(tmp_path):
    """정말로 아직 돌고 있는 작업을 다른 프로세스가 죽은 것으로 단정해 덮어쓰면 안 된다."""
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    batch_id = saved(repo, age=3600)
    before = (tmp_path / "batches" / batch_id / "batch.json").read_bytes()

    repo.load(batch_id)
    repo.load(batch_id)

    assert (tmp_path / "batches" / batch_id / "batch.json").read_bytes() == before
    assert on_disk(tmp_path, batch_id)["status"] == "PARSING"
    assert on_disk(tmp_path, batch_id)["files"][0]["status"] == "PARSING"


def test_a_recent_parsing_batch_is_left_alone(tmp_path):
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    batch = repo.load(saved(repo, age=60))
    assert batch.status == "PARSING" and batch.files[0].status == "PARSING"


def test_the_threshold_is_the_configured_number_of_seconds(tmp_path):
    repo = BatchRepo(tmp_path, stale_after_sec=100)
    assert repo.load(saved(repo, age=99)).status == "PARSING"
    assert repo.load(saved(repo, age=101)).status == "FAILED"


def test_only_parsing_batches_are_reinterpreted(tmp_path):
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    for status in ("NEEDS_REVIEW", "READY", "SENDING", "SENT", "SEND_FAILED"):
        batch = repo.load(saved(repo, status=status, age=10**6, file_status="DONE"))
        assert batch.status == status


def test_an_unreadable_start_time_is_not_treated_as_stale(tmp_path):
    """언제 시작했는지 모르면 죽었다고 단정하지 않는다."""
    repo = BatchRepo(tmp_path, stale_after_sec=1)
    assert repo.load(saved(repo, created_at="")).status == "PARSING"
    assert repo.load(saved(repo, created_at="어제")).status == "PARSING"


def test_a_time_without_a_zone_is_read_as_local_time(tmp_path):
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    naive_old = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    naive_new = (datetime.now() - timedelta(seconds=10)).isoformat(timespec="seconds")
    assert repo.load(saved(repo, created_at=naive_old)).status == "FAILED"
    assert repo.load(saved(repo, created_at=naive_new)).status == "PARSING"


def test_the_default_threshold_comes_from_the_settings(tmp_path):
    assert Settings().parse_stale_sec == 1800
    repo = BatchRepo(tmp_path)                         # 생략하면 설정을 따른다 (기본 1800)
    assert repo.load(saved(repo, age=1000)).status == "PARSING"
    assert repo.load(saved(repo, age=2000)).status == "FAILED"


def test_a_stale_view_can_be_replaced_by_a_fresh_parse(tmp_path):
    """FAILED 로 보이는 배치는 다시 변환하면 된다 — 파싱이 끝나 저장되면 정상 상태가 된다."""
    repo = BatchRepo(tmp_path, stale_after_sec=1800)
    batch_id = saved(repo, age=3600)
    batch = repo.load(batch_id)
    assert batch.status == "FAILED"

    batch.files[0].status = "DONE"
    batch.status = batch.recompute_status()
    repo.save(batch)
    assert repo.load(batch_id).status != "FAILED"
