"""EAI 전송 — design.md §5 · 계약 §7.

실제 서버 대신 테스트가 띄운 로컬 HTTP 서버로 보낸다. 재시도·백오프는 실제
경로를 타되 sleep 만 잘라낸다 — 대기 시간이 테스트를 느리게 할 이유가 없다.
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from app.config import Settings, get_settings
from app.main import app
from app.storage import read_month
from app.transport import eai_client
from fastapi.testclient import TestClient

SAMPLE = "PO-SAMPLE-0001.htm"


# ── 로컬 EAI 스텁 ──────────────────────────────────────────────────────
class _Stub:
    def __init__(self) -> None:
        self.status = 200
        self.received: list[dict] = []
        self.headers: list[dict] = []

    def start(self) -> str:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                stub.received.append(json.loads(raw.decode("utf-8")))
                stub.headers.append(dict(self.headers))
                body = json.dumps({"result": "OK"}).encode()
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/po2sap/order"

    def stop(self) -> None:
        self._server.shutdown()


@pytest.fixture
def stub():
    s = _Stub()
    s.url = s.start()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(eai_client.time, "sleep", lambda _: None)


@pytest.fixture
def workspace(tmp_path, masters_dir):
    shutil.copytree(masters_dir, tmp_path / "masters")
    return tmp_path


def make_client(workspace, stub_url: str, **over):
    settings = Settings(
        llm_provider="mock",
        masters_dir=workspace / "masters",
        storage_dir=workspace / "storage",
        eai_endpoint=stub_url,
        **over,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), settings


@pytest.fixture
def client(workspace, stub):
    c, settings = make_client(workspace, stub.url)
    c.settings = settings
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def batch_id(client, fixtures_dir):
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    return client.post("/api/batches", data={"customer": "MSC"},
                       files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]


def audit(settings):
    return read_month(settings.storage_dir, datetime.now().strftime("%Y-%m"))


# ── 전송 ───────────────────────────────────────────────────────────────
def test_sends_and_marks_sent(client, batch_id, stub):
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["status"] == "SENT" and body["sent_rows"] == 2 and body["sent_at"]
    assert client.get(f"/api/batches/{batch_id}").json()["status"] == "SENT"


def test_payload_is_rows_of_every_field(client, batch_id, stub, masters_dir):
    import yaml

    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    payload = stub.received[0]
    base = yaml.safe_load((masters_dir / "_base" / "sap_defaults.yaml").read_text("utf-8"))

    assert list(payload) == ["rows"]
    assert len(payload["rows"]) == 2
    for row in payload["rows"]:
        assert list(row) == list(base["field_specs"])      # 순서까지 _base 그대로
        assert all(isinstance(v, str) for v in row.values())
        assert not [k for k in row if k.startswith("_")]   # 화면 전용 키는 안 나간다


def test_array_root_is_configurable(workspace, stub, fixtures_dir):
    c, _ = make_client(workspace, stub.url, payload_root="array")
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    bid = c.post("/api/batches", data={"customer": "MSC"},
                 files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]
    c.post(f"/api/batches/{bid}/send", json={"rows": []})
    assert isinstance(stub.received[0], list)
    app.dependency_overrides.clear()


def test_deleted_rows_are_not_sent(client, batch_id, stub):
    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0002", "deleted": True}]})
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["sent_rows"] == 1
    assert len(stub.received[0]["rows"]) == 1


def test_errors_block_sending(client, batch_id, stub):
    client.post(f"/api/batches/{batch_id}/validate",
                json={"rows": [{"row_id": "r_0001", "fields": {"MATNR": ""}}]})
    r = client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    assert r.status_code == 409 and "오류" in r.json()["error"]["message"]
    assert stub.received == []                             # 한 건도 나가지 않았다


def test_chunking(workspace, stub, fixtures_dir):
    c, _ = make_client(workspace, stub.url, eai_max_rows_per_request=1)
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    bid = c.post("/api/batches", data={"customer": "MSC"},
                 files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]
    body = c.post(f"/api/batches/{bid}/send", json={"rows": []}).json()
    assert body["sent_rows"] == 2 and len(stub.received) == 2
    app.dependency_overrides.clear()


# ── 실패 · 재시도 ──────────────────────────────────────────────────────
def test_5xx_retries_then_fails(client, batch_id, stub):
    stub.status = 503
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["status"] == "SEND_FAILED" and body["sent_rows"] == 0
    assert body["attempts"] == 3 and len(stub.received) == 3


def test_4xx_does_not_retry(client, batch_id, stub):
    """같은 요청은 또 거부된다 — 재시도는 시간만 버린다."""
    stub.status = 400
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["status"] == "SEND_FAILED" and body["attempts"] == 1
    assert len(stub.received) == 1
    assert "확인해야" in body["message"]


def test_failed_batch_can_be_resent(client, batch_id, stub):
    stub.status = 503
    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    stub.status = 200
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["status"] == "SENT" and body["sent_rows"] == 2


def test_sent_batch_can_be_resent(client, batch_id, stub):
    """계약 §7 — 재전송은 같은 API 재호출이다."""
    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    body = client.post(f"/api/batches/{batch_id}/send", json={"rows": []}).json()
    assert body["status"] == "SENT" and body["resend"] is True
    assert [e["action"] for e in audit(client.settings)] == ["send", "resend"]


# ── 설정 방어 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "endpoint,fragment",
    [
        ("http://eai-dev.yg1.solutions:5443/po2sap/order", "HTTPS"),
        ("", "설정되지 않았습니다"),
        ("ftp://x/y", "형식이 올바르지"),
    ],
)
def test_bad_endpoint_is_refused_before_sending(workspace, fixtures_dir, endpoint, fragment):
    c, _ = make_client(workspace, endpoint)
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    bid = c.post("/api/batches", data={"customer": "MSC"},
                 files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]
    r = c.post(f"/api/batches/{bid}/send", json={"rows": []})
    assert r.status_code == 400 and fragment in r.json()["error"]["message"]
    app.dependency_overrides.clear()


def test_apikey_auth_sets_the_header(workspace, stub, fixtures_dir):
    c, _ = make_client(workspace, stub.url, eai_auth_mode="apikey",
                       eai_api_key="secret-key", eai_api_key_header="X-EAI-Key")
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    bid = c.post("/api/batches", data={"customer": "MSC"},
                 files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]
    c.post(f"/api/batches/{bid}/send", json={"rows": []})
    assert stub.headers[0].get("X-EAI-Key") == "secret-key"
    app.dependency_overrides.clear()


def test_apikey_without_key_is_refused(workspace, stub, fixtures_dir):
    c, _ = make_client(workspace, stub.url, eai_auth_mode="apikey")
    data = (fixtures_dir / "msc" / SAMPLE).read_bytes()
    bid = c.post("/api/batches", data={"customer": "MSC"},
                 files=[("files", (SAMPLE, data, "text/html"))]).json()["batch_id"]
    r = c.post(f"/api/batches/{bid}/send", json={"rows": []})
    assert r.status_code == 400 and "EAI_API_KEY" in r.json()["error"]["message"]
    assert stub.received == []
    app.dependency_overrides.clear()


# ── 감사 로그 ──────────────────────────────────────────────────────────
def test_audit_records_the_attempt(client, batch_id, stub):
    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    entry = audit(client.settings)[0]
    assert entry["result"] == "ok" and entry["row_count"] == 2
    assert entry["orders"] == ["PO-SAMPLE-0001(ELKHART)", "PO-SAMPLE-0001(HARRISBURG)"]
    assert len(entry["payload_sha256"]) == 64
    assert entry["endpoint"] == stub.url and entry["http_status"] == 200


def test_audit_does_not_keep_values(client, batch_id, stub):
    """design.md §8 — 원문·단가는 기록하지 않는다. 남기는 것은 되짚을 키뿐이다."""
    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    raw = json.dumps(audit(client.settings), ensure_ascii=False)
    assert "YG-EM0600" not in raw           # 품번
    assert "12.50" not in raw               # 단가
    assert "END MILL" not in raw            # 품명


def test_audit_records_failures_too(client, batch_id, stub):
    stub.status = 503
    client.post(f"/api/batches/{batch_id}/send", json={"rows": []})
    entry = audit(client.settings)[0]
    assert entry["result"] == "failed" and entry["attempts"] == 3
