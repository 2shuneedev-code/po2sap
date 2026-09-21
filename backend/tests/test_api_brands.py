"""브랜드 매핑 콘솔 API — contracts/api-contract.md §10.

쓰기가 있는 첫 엔드포인트다. 테스트는 **masters 사본**을 향하게 해서
저장소의 실제 참조표를 건드리지 않는다.
"""

from __future__ import annotations

import csv
import shutil

import pytest
from app.config import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient

MSC = "100249"


@pytest.fixture
def workspace(tmp_path, masters_dir):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


@pytest.fixture
def client(workspace):
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_provider="mock", masters_dir=workspace
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def master_rows(workspace):
    """SAP 브랜드 마스터 원본. 테스트가 기대치를 여기서 끌어온다."""
    path = workspace / "refs" / "brand_master.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def keys_rows(workspace):
    path = workspace / "refs" / "brand_keys.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── 목록 ───────────────────────────────────────────────────────────────
def test_lists_every_sap_customer_not_just_configured(client, workspace):
    """규칙이 없는 고객도 나와야 브랜드를 미리 채워둘 수 있다."""
    body = client.get("/api/brands/customers", params={"limit": 500}).json()
    # 참조표에 있는 고객 수를 그대로 기대한다. 숫자를 박아두면 SAP 재추출로
    # 고객 수가 바뀔 때마다(430 → 78 처럼) 멀쩡한 테스트가 죽는다.
    expected = len({r["kunnr"] for r in master_rows(workspace)})
    assert int(body["total"]) == expected
    assert sum(1 for c in body["customers"] if c["code"]) == 3


def test_filter_and_search(client):
    configured = client.get(
        "/api/brands/customers", params={"filter": "configured"}
    ).json()
    assert {c["code"] for c in configured["customers"]} == {"MSC", "KL", "YGJP"}

    unconfigured = client.get(
        "/api/brands/customers", params={"filter": "unconfigured", "limit": 500}
    ).json()
    assert all(c["code"] == "" for c in unconfigured["customers"])

    # SAP 의 name1 은 "KL" 로 축약돼 있다. 사람이 아는 이름으로도 찾혀야 한다.
    hit = client.get("/api/brands/customers", params={"q": "kennametal"}).json()
    assert [c["code"] for c in hit["customers"]] == ["KL"]
    assert hit["customers"][0]["sap_name"] == "KL"

    by_code = client.get("/api/brands/customers", params={"q": "ygjp"}).json()
    assert [c["kunnr"] for c in by_code["customers"]] == ["3200"]


def test_pagination(client):
    first = client.get("/api/brands/customers", params={"limit": 5}).json()
    second = client.get("/api/brands/customers", params={"limit": 5, "offset": 5}).json()
    assert len(first["customers"]) == 5
    assert first["total"] == second["total"]
    assert {c["kunnr"] for c in first["customers"]} & {c["kunnr"] for c in second["customers"]} == set()


def test_counts_are_strings(client):
    """계약 §0 — 숫자도 문자열로 내보낸다 (앞자리 0 보존)."""
    row = client.get("/api/brands/customers", params={"q": "SID TOOL"}).json()["customers"][0]
    assert isinstance(row["brand_count"], str) and isinstance(row["mapped_count"], str)


# ── 상세 ───────────────────────────────────────────────────────────────
def test_detail_joins_sap_codes_with_human_keys(client, workspace):
    body = client.get(f"/api/brands/customers/{MSC}").json()
    assert body["code"] == "MSC" and body["configured"] == "true"

    mapped = {b["zbrand"]: [k["text"] for k in b["keys"]] for b in body["brands"] if b["keys"]}

    # 기대치를 참조표에서 끌어온다. 초벌 시드(seed_brand_keys.py)로 매핑이
    # 늘어나도 죽지 않아야 한다 — 검사하려는 건 **코드와 문구가 이어졌는가**다.
    expected = {}
    for row in keys_rows(workspace):
        if row["kunnr"] == MSC:
            expected.setdefault(row["zbrand"], []).append(row["text"])
    assert mapped == expected

    # 사람이 채운 것은 그대로 남아 있어야 한다
    assert mapped["38"] == ["HERTEL"]


def test_unmapped_brands_are_still_listed(client):
    """매핑이 없는 코드도 목록에 나와야 현업이 무엇을 채울지 안다.

    데이터에 미매핑이 남아 있기를 기대하지 않는다 — 초벌 시드가 다 채우면
    그건 정상이다. 하나를 비워 놓고 그게 보이는지만 본다.
    """
    r = client.put(f"/api/brands/customers/{MSC}/38", json={"keys": []})
    assert r.status_code == 200

    body = client.get(f"/api/brands/customers/{MSC}").json()
    empty = [b for b in body["brands"] if b["zbrand"] == "38"]
    assert empty and empty[0]["status"] == "unmapped"
    assert empty[0]["keys"] == []


def test_detail_includes_logic_for_configured_customer(client):
    logic = client.get(f"/api/brands/customers/{MSC}").json()["logic"]
    assert logic["split"]["by"] == "shipment"
    assert [t["id"] for t in logic["tables"]] == ["ship_to_routing"]
    # **거래처 고유 규칙이 있는가**를 본다. 정확히 일치를 요구하면 공용
    # 프로필에 규칙이 하나 늘 때마다(예: 통화 변환) 멀쩡한 테스트가 죽는다.
    assert {r["id"] for r in logic["rules"]} >= {"brand_code", "ref_codes"}
    assert any(f["field"] == "BSTKD" for f in logic["fields"])


def test_unconfigured_customer_has_brands_but_no_logic(client, workspace):
    configured = {"100249", "107525", "3200"}
    kunnr = next(
        r["kunnr"] for r in master_rows(workspace) if r["kunnr"] not in configured
    )
    body = client.get(f"/api/brands/customers/{kunnr}").json()
    assert body["configured"] == "false"
    assert body["logic"] is None
    assert body["brands"], "규칙이 없어도 브랜드는 보여야 한다"


def test_unknown_customer_is_404(client):
    r = client.get("/api/brands/customers/999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


# ── 저장 ───────────────────────────────────────────────────────────────
def test_saves_keys_and_persists(client, workspace):
    r = client.put(f"/api/brands/customers/{MSC}/501",
                   json={"keys": [{"text": "UNBRANDED", "match": "contains"}]})
    assert r.status_code == 200 and r.json()["status"] == "mapped"

    saved = [x for x in keys_rows(workspace) if x["kunnr"] == MSC and x["zbrand"] == "501"]
    assert [x["text"] for x in saved] == ["UNBRANDED"]
    again = client.get(f"/api/brands/customers/{MSC}").json()
    assert any(b["zbrand"] == "501" and b["keys"] for b in again["brands"])


def test_empty_list_clears_the_mapping(client, workspace):
    client.put(f"/api/brands/customers/{MSC}/38", json={"keys": []})
    assert not [x for x in keys_rows(workspace) if x["kunnr"] == MSC and x["zbrand"] == "38"]


def test_rejects_code_not_registered_in_sap(client, workspace):
    before = keys_rows(workspace)
    r = client.put(f"/api/brands/customers/{MSC}/99999", json={"keys": [{"text": "X"}]})
    assert r.status_code == 400
    assert "등록돼 있지 않" in r.json()["error"]["message"]
    assert keys_rows(workspace) == before, "거부했으면 파일을 건드리지 않아야 한다"


def test_rejects_text_already_used_by_another_code(client):
    r = client.put(f"/api/brands/customers/{MSC}/205", json={"keys": [{"text": "HERTEL"}]})
    assert r.status_code == 400
    assert "이미 브랜드 코드 38" in r.json()["error"]["message"]


def test_rejects_duplicate_text_within_one_request(client):
    r = client.put(f"/api/brands/customers/{MSC}/38",
                   json={"keys": [{"text": "A"}, {"text": "a"}]})
    assert r.status_code == 400 and "두 번" in r.json()["error"]["message"]


def test_rejects_bad_match_mode(client):
    r = client.put(f"/api/brands/customers/{MSC}/38",
                   json={"keys": [{"text": "A", "match": "fuzzy"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"


def test_row_order_is_preserved(client, workspace):
    """행 순서가 곧 판정 우선순위다 (SCHEMA §4.5) — 저장이 순서를 흔들면 안 된다."""
    before = [(x["kunnr"], x["zbrand"]) for x in keys_rows(workspace)]
    client.put(f"/api/brands/customers/{MSC}/127",
               json={"keys": [{"text": "INTERSTATE"}, {"text": "INTRSTATE"}]})
    after = [(x["kunnr"], x["zbrand"]) for x in keys_rows(workspace)]
    assert after.index((MSC, "127")) == before.index((MSC, "127"))
    assert after.count((MSC, "127")) == 2


def test_saved_file_still_passes_the_validator(client, workspace, validate_masters):
    """화면에서 저장한 결과가 CI 를 깨면 안 된다."""
    client.put(f"/api/brands/customers/{MSC}/501", json={"keys": [{"text": "UNBRANDED"}]})
    base = validate_masters.load_base_fields(workspace)
    assert validate_masters.validate_customer("msc", base, workspace).errors == []
