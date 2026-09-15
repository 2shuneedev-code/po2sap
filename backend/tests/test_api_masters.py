"""마스터 조회 API — contracts/api-contract.md §1·§2·§3.

여기서 지키려는 것은 두 가지다.
  · 응답이 **YAML 에서 파생**된다 — 규칙을 고치면 화면이 따라온다
  · 필드 개수를 세지 않는다 — 36이 34가 되어도 통과해야 한다
"""

from __future__ import annotations

import shutil

import pytest
import yaml
from app.config import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient


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


# ── §1 거래처 목록 ────────────────────────────────────────────────────
def test_customers_carry_what_the_upload_screen_needs(client):
    body = client.get("/api/masters/customers").json()
    assert body
    for item in body:
        assert set(item) == {"code", "name", "customer_no", "file_types"}


# ── §3 필드 정의 ─────────────────────────────────────────────────────
def test_fields_follow_base_order_and_count(client, workspace):
    spec = yaml.safe_load((workspace / "_base" / "sap_defaults.yaml").read_text("utf-8"))
    expected = list(spec["field_specs"])

    body = client.get("/api/masters/fields").json()
    assert [f["name"] for f in body["fields"]] == expected


def test_fields_shrink_with_the_base_file(client, workspace):
    """필드 개수가 코드에 박혀 있지 않다는 증거. _base 에서 빼면 응답도 준다."""
    path = workspace / "_base" / "sap_defaults.yaml"
    spec = yaml.safe_load(path.read_text("utf-8"))
    before = len(spec["field_specs"])
    spec["field_specs"].pop(list(spec["field_specs"])[-1])
    path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")

    body = client.get("/api/masters/fields").json()
    assert len(body["fields"]) == before - 1


# ── §2 규칙 카드 ─────────────────────────────────────────────────────
def test_preview_has_the_shape_the_front_renders(client):
    body = client.get("/api/masters/customers/MSC/preview").json()
    assert set(body) >= {"code", "name", "customer_no", "fixed", "rules", "split",
                         "todos", "footer"}
    for rule in body["rules"]:
        assert set(rule) >= {"id", "kind", "label", "columns", "rows"}


def test_preview_is_case_insensitive_on_the_code(client):
    assert client.get("/api/masters/customers/msc/preview").status_code == 200


def test_unknown_customer_is_404_with_a_korean_message(client):
    r = client.get("/api/masters/customers/NOPE/preview")
    assert r.status_code == 404
    assert r.json()["error"]["message"]


def test_fixed_holds_only_values_settled_before_reading_the_document(client):
    """★ 문서를 읽어야 정해지는 값이 확정값으로 찍히면 안 된다.

    `join("-", ["01", header.po_date, ...])` 는 문서 값이 비어도 `"01--"` 를
    내놓는다. 그걸 고정값으로 보여주면 검수자가 틀린 발주번호를 믿게 된다.
    """
    body = client.get("/api/masters/customers/YGJP/preview").json()
    fixed = {f["field"] for f in body["fixed"]}

    assert "BSTKD" not in fixed      # header.po_number 를 참조한다
    assert "ZSHCO" not in fixed      # brand_code 규칙 결과를 참조한다
    assert "KUNNR1" in fixed         # meta.customer_no 만 쓴다 → 확정값


def test_fixed_resolves_customer_code_from_meta(client):
    body = client.get("/api/masters/customers/YGJP/preview").json()
    fixed = {f["field"]: f["value"] for f in body["fixed"]}
    assert fixed["KUNNR1"] == body["customer_no"]


def test_rule_cards_come_from_yaml_not_from_code(client, workspace):
    """거래처 YAML 의 라벨을 고치면 카드 라벨이 바뀐다."""
    path = workspace / "customers" / "msc.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    data["tables"]["ship_to_routing"]["label"] = "출하처 분기(수정됨)"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    body = client.get("/api/masters/customers/MSC/preview").json()
    labels = [r["label"] for r in body["rules"]]
    assert "출하처 분기(수정됨)" in labels


def test_brand_map_shows_only_this_customers_rows(client):
    """거래처를 고르면 그 거래처 브랜드만 보인다 — 참조표는 전 고객 공용이다."""
    msc = client.get("/api/masters/customers/MSC/preview").json()
    ygjp = client.get("/api/masters/customers/YGJP/preview").json()

    def brand_rows(body):
        for rule in body["rules"]:
            if rule["kind"] == "csv_map":
                return {r[0] for r in rule["rows"]}
        return set()

    assert brand_rows(msc)
    assert brand_rows(ygjp)
    assert not brand_rows(msc) & brand_rows(ygjp)


def test_todos_surface_unconfirmed_values(client):
    """P4 — 미확정 값은 개발을 막지 않지만 검수자는 알아야 한다."""
    body = client.get("/api/masters/customers/KL/preview").json()
    assert [t for t in body["todos"] if t["field"] == "KUNNR2"]


def test_split_tells_the_front_whether_orders_are_divided(client):
    msc = client.get("/api/masters/customers/MSC/preview").json()
    kl = client.get("/api/masters/customers/KL/preview").json()
    assert msc["split"]["by"] == "shipment"
    assert kl["split"]["by"] == "none"
