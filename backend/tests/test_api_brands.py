"""브랜드 후보 콘솔 API — contracts/api-contract.md §10.

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
    """브랜드 마스터 원본. 테스트가 기대치를 여기서 끌어온다."""
    path = workspace / "refs" / "brand_master.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def manual_rows(workspace):
    path = workspace / "refs" / "brand_master_manual.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def msc_codes(workspace):
    return [r["zbrand"] for r in master_rows(workspace) if r["kunnr"] == MSC]


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
    assert isinstance(row["brand_count"], str) and isinstance(row["manual_count"], str)


# ── 상세 ───────────────────────────────────────────────────────────────
def test_detail_lists_sap_candidates_with_source(client, workspace):
    body = client.get(f"/api/brands/customers/{MSC}").json()
    assert [b["zbrand"] for b in body["brands"]] == msc_codes(workspace)
    assert {b["source"] for b in body["brands"]} == {"sap"}
    assert body["manual"] == []


def test_detail_includes_logic_for_configured_customer(client):
    """MSC 는 출하처별 SHIP-TO PARTY(KUNNR2) 결정표만 예외로 다시 얹었다(2026-09-23).

    브랜드·통화는 여전히 공용 기본(profiles/standard)이다.
    """
    logic = client.get(f"/api/brands/customers/{MSC}").json()["logic"]
    assert logic["split"]["by"] == "shipment"
    assert [t["id"] for t in logic["tables"]] == ["ship_to_routing"]
    # **공용 기본 규칙은 붙어 있는가**를 본다. 정확히 일치를 요구하면 공용
    # 프로필에 규칙이 하나 늘 때마다(예: 통화 변환) 멀쩡한 테스트가 죽는다.
    assert {r["id"] for r in logic["rules"]} >= {"brand_code", "currency"}
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


# ── 저장 (보정) ─────────────────────────────────────────────────────────
def put(client, rows):
    return client.put(f"/api/brands/customers/{MSC}/manual", json={"rows": rows})


def test_add_override_suppress_change_the_candidates(client, workspace):
    first, second = msc_codes(workspace)[:2]
    r = put(client, [
        {"zbrand": "9999", "zbrant": "NEW BRAND", "action": "add", "note": "SAP 등록 대기"},
        {"zbrand": first, "zbrant": "FIXED NAME", "action": "override", "note": "오탈자"},
        {"zbrand": second, "action": "suppress", "note": "단종"},
    ])
    assert r.status_code == 200, r.text
    assert len(manual_rows(workspace)) == 3

    brands = {b["zbrand"]: b for b in client.get(f"/api/brands/customers/{MSC}").json()["brands"]}
    assert brands["9999"]["source"] == "add"
    assert brands[first]["name"] == "FIXED NAME" and brands[first]["source"] == "override"
    assert second not in brands


def test_empty_rows_clear_the_customer_overlay(client, workspace):
    put(client, [{"zbrand": "9999", "zbrant": "X", "action": "add", "note": "n"}])
    assert put(client, []).status_code == 200
    assert manual_rows(workspace) == []


@pytest.mark.parametrize("row, why", [
    ({"zbrand": "99999", "zbrant": "X", "action": "override", "note": "n"}, "브랜드 마스터에 없는"),
    ({"zbrand": "99999", "action": "suppress", "note": "n"}, "브랜드 마스터에 없는"),
    ({"zbrand": "__FIRST__", "zbrant": "X", "action": "add", "note": "n"}, "이미 SAP 에"),
    ({"zbrand": "9999", "zbrant": "", "action": "add", "note": "n"}, "브랜드명"),
])
def test_rejected_rows_leave_the_file_alone(client, workspace, row, why):
    row = {**row, "zbrand": msc_codes(workspace)[0] if row["zbrand"] == "__FIRST__" else row["zbrand"]}
    before = manual_rows(workspace)
    r = put(client, [row])
    assert r.status_code == 400
    assert why in r.json()["error"]["message"]
    assert manual_rows(workspace) == before


def test_note_and_action_are_required(client):
    assert put(client, [{"zbrand": "9999", "zbrant": "X", "action": "add", "note": ""}]).status_code == 422
    assert put(client, [{"zbrand": "9999", "zbrant": "X", "action": "rename", "note": "n"}]).status_code == 422


def test_saved_file_still_passes_the_validator(client, workspace, validate_masters):
    """화면에서 저장한 결과가 CI 를 깨면 안 된다."""
    put(client, [{"zbrand": "9999", "zbrant": "NEW", "action": "add", "note": "n"}])
    base = validate_masters.load_base_fields(workspace)
    assert validate_masters.validate_customer("msc", base, workspace).errors == []
