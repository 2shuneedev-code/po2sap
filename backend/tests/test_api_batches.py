"""배치 업로드·검수 API — contracts/api-contract.md §4~§6.

여기서 검증하는 가장 중요한 성질은 **서버가 자기 스냅샷을 믿는다**는 것이다.
검수 화면이 보낸 값을 그대로 받아들이면 없는 행을 끼워 넣거나 규칙이 정한 코드를
임의로 바꿔도 막을 수 없다.
"""

from __future__ import annotations

import shutil

import pytest
from app.config import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient

SAMPLE = "PO-SAMPLE-0001.htm"


@pytest.fixture
def workspace(tmp_path, masters_dir):
    shutil.copytree(masters_dir, tmp_path / "masters")
    return tmp_path


@pytest.fixture
def settings(workspace):
    return Settings(
        llm_provider="mock",
        masters_dir=workspace / "masters",
        storage_dir=workspace / "storage",
    )


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample_bytes(fixtures_dir):
    return (fixtures_dir / "msc" / SAMPLE).read_bytes()


def upload(client, sample_bytes, *, customer="MSC", name=SAMPLE, count=1):
    files = [("files", (name, sample_bytes, "text/html")) for _ in range(count)]
    return client.post("/api/batches", data={"customer": customer}, files=files)


@pytest.fixture
def batch_id(client, sample_bytes):
    return upload(client, sample_bytes).json()["batch_id"]


# ── §4 업로드 ──────────────────────────────────────────────────────────
def test_upload_starts_parsing_and_returns_ids(client, sample_bytes):
    body = upload(client, sample_bytes).json()
    assert body["batch_id"].startswith("b_")
    assert body["files"][0]["name"] == SAMPLE


def test_unknown_customer_is_rejected(client, sample_bytes):
    r = upload(client, sample_bytes, customer="NOPE")
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_REQUEST"


def test_too_many_files_rejected(client, sample_bytes):
    r = upload(client, sample_bytes, count=51)
    assert r.status_code == 400 and "50개" in r.json()["error"]["message"]


def test_oversized_file_rejected(client):
    huge = b"x" * (21 * 1024 * 1024)
    r = client.post("/api/batches", data={"customer": "MSC"},
                    files=[("files", ("big.htm", huge, "text/html"))])
    assert r.status_code == 400 and "너무 큽니다" in r.json()["error"]["message"]


# ── §5 조회 ────────────────────────────────────────────────────────────
def test_batch_reaches_ready_with_rows(client, batch_id):
    body = client.get(f"/api/batches/{batch_id}").json()
    assert body["status"] == "READY"
    assert body["files"][0]["status"] == "DONE" and body["files"][0]["row_count"] == 2
    # 건수·합계·오류 0 만 고정한다. **경고 수는 박지 않는다** — 마스터에서
    # `required: warn` 인 필드가 늘고 주는 것은 정상이고, 그때마다 멀쩡한
    # 테스트가 죽으면 안 된다 (CLAUDE.md §5 "테스트에 데이터 개수를 박기").
    assert body["summary"]["row_count"] == "2"
    assert body["summary"]["total_qty"] == "25"
    assert body["summary"]["error_count"] == "0"      # 🔴 는 전송을 막는다
    assert "warn_count" in body["summary"]


def test_rows_follow_the_contract_shape(client, batch_id):
    body = client.get(f"/api/batches/{batch_id}").json()
    row = body["rows"][0]
    assert set(row) >= {"row_id", "_file_id", "_file", "_group", "_line_no", "fields",
                        "issues", "edited"}
    assert row["_file"] == SAMPLE                      # 저장명(f1__…)이 아니라 원본명
    assert list(row["fields"]) == body["columns"]      # 전 필드가 키로 존재
    assert row["_group"] in {"ELKHART", "HARRISBURG"}


def test_split_survives_the_round_trip(client, batch_id):
    rows = client.get(f"/api/batches/{batch_id}").json()["rows"]
    assert [r["fields"]["KUNNR2"] for r in rows] == ["100249", "319677"]


def test_unknown_batch_is_404(client):
    assert client.get("/api/batches/b_20260101_0001").status_code == 404


def test_batch_id_cannot_escape_the_storage_dir(client):
    """batch_id 는 URL 에서 온다 — 경로 조작이 통하면 안 된다."""
    assert client.get("/api/batches/..%2F..%2Fetc").status_code in {404, 400}


# ── §6 재검증 — 서버가 자기 스냅샷을 믿는다 ────────────────────────────
def test_edit_is_recorded_by_the_server(client, batch_id):
    r = client.post(f"/api/batches/{batch_id}/validate",
                    json={"rows": [{"row_id": "r_0001", "fields": {"MATNR": "YG-CHANGED"}}]})
    assert r.status_code == 200
    assert r.json()["rows"][0]["edited"] == ["MATNR"]


def test_response_does_not_return_values(client, batch_id):
    """편집 중인 셀이 덮어써지면 안 된다 — 값은 프론트가 주인이다."""
    body = client.post(f"/api/batches/{batch_id}/validate",
                       json={"rows": [{"row_id": "r_0001", "fields": {"MATNR": "X"}}]}).json()
    assert "fields" not in body["rows"][0]


def test_unknown_row_id_is_rejected(client, batch_id):
    r = client.post(f"/api/batches/{batch_id}/validate",
                    json={"rows": [{"row_id": "r_9999", "fields": {"MATNR": "X"}}]})
    assert r.status_code == 400 and "없는 행" in r.json()["error"]["message"]


def test_unknown_column_is_ignored(client, batch_id):
    """컬럼을 새로 만들 수 없다 — 전송 필드 목록은 _base 가 정한다."""
    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0001", "fields": {"해킹컬럼": "X"}}]})
    row = client.get(f"/api/batches/{batch_id}").json()["rows"][0]
    assert "해킹컬럼" not in row["fields"]
    assert len(row["fields"]) == 36


def test_original_snapshot_is_kept_for_comparison(client, batch_id, settings):
    from app.storage import BatchRepo

    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0001", "fields": {"KUNNR2": "999999"}}]})
    stored = BatchRepo(settings.storage_dir).load(batch_id)
    row = next(r for r in stored.rows if r.row_id == "r_0001")
    assert row.fields["KUNNR2"] == "999999"       # 사람이 확정한 값이 전송된다 (P5)
    assert row.original["KUNNR2"] == "100249"     # 그러나 원본은 서버가 들고 있다
    assert row.edited == ["KUNNR2"]


def test_clearing_a_required_field_blocks_sending(client, batch_id):
    body = client.post(f"/api/batches/{batch_id}/validate",
                       json={"rows": [{"row_id": "r_0001", "fields": {"MATNR": ""}}]}).json()
    assert body["status"] == "NEEDS_REVIEW"
    codes = [i["code"] for i in body["rows"][0]["issues"]]
    assert "REQUIRED_MISSING" in codes


def test_deletion_is_explicit_not_omission(client, batch_id):
    """행을 빼고 보내는 것과 지우는 것은 다르다 — 누락을 삭제로 해석하지 않는다."""
    partial = client.post(f"/api/batches/{batch_id}/validate",
                          json={"rows": [{"row_id": "r_0001", "fields": {}}]}).json()
    assert partial["summary"]["row_count"] == "2"

    deleted = client.post(f"/api/batches/{batch_id}/validate",
                          json={"rows": [{"row_id": "r_0002", "deleted": True}]}).json()
    # 이 테스트가 보는 것은 **삭제가 집계에 반영되는가**다.
    # 경고 수는 마스터가 정하는 값이라 박지 않는다 (위 §5 조회 테스트와 같은 이유).
    assert deleted["summary"]["row_count"] == "1"
    assert deleted["summary"]["total_qty"] == "10"
    assert deleted["summary"]["error_count"] == "0"


def test_deletion_can_be_undone(client, batch_id):
    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0002", "deleted": True}]})
    body = client.post(f"/api/batches/{batch_id}/validate",
                       json={"rows": [{"row_id": "r_0002", "deleted": False}]}).json()
    assert body["summary"]["row_count"] == "2"


def test_edits_persist_across_requests(client, batch_id):
    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0001", "fields": {"MATNR": "KEEP-ME"}}]})
    row = client.get(f"/api/batches/{batch_id}").json()["rows"][0]
    assert row["fields"]["MATNR"] == "KEEP-ME" and row["edited"] == ["MATNR"]


# ── 실패 격리 ──────────────────────────────────────────────────────────
def test_one_bad_file_does_not_kill_the_batch(client, sample_bytes):
    r = client.post("/api/batches", data={"customer": "MSC"}, files=[
        ("files", (SAMPLE, sample_bytes, "text/html")),
        ("files", ("broken.htm", b"<html>no purchase order here</html>", "text/html")),
    ])
    body = client.get(f"/api/batches/{r.json()['batch_id']}").json()
    statuses = {f["name"]: f["status"] for f in body["files"]}
    assert statuses[SAMPLE] == "DONE"
    assert statuses["broken.htm"] == "FAILED"
    assert len(body["rows"]) == 2                 # 성공한 파일의 행은 살아 있다
