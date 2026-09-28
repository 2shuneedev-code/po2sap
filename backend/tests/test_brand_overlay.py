"""브랜드 후보 = SAP ∪ 보정 (SCHEMA §4.5-A 병합 규칙).

병합은 `reftable.load()` 한 곳에만 있다. 규칙엔진(`csv_choice`)과 화면이 같은
후보를 보는지가 핵심이다 — 어긋나면 화면에서 지운 후보로 자동 판정된다.
"""

from __future__ import annotations

from pathlib import Path

from app.masters import brands as brand_store
from app.rules import reftable


def sap(kunnr: str, zbrand: str, name: str) -> dict[str, str]:
    return {"kunnr": kunnr, "name1": "C", "zbrand": zbrand, "zbrant": name}


def ov(kunnr: str, zbrand: str, action: str, name: str = "") -> dict[str, str]:
    return {"kunnr": kunnr, "name1": "", "zbrand": zbrand, "zbrant": name,
            "action": action, "note": "n"}


BASE = [sap("1", "A", "a"), sap("1", "B", "b"), sap("2", "C", "c")]


def codes(rows):
    return [(r["kunnr"], r["zbrand"]) for r in rows]


def test_no_overlay_is_sap_as_is():
    merged = reftable.merge_brand_overlay(BASE, [])
    assert codes(merged) == codes(BASE)
    assert {r["_source"] for r in merged} == {"sap"}


def test_suppress_removes_the_candidate():
    assert codes(reftable.merge_brand_overlay(BASE, [ov("1", "B", "suppress")])) == [
        ("1", "A"), ("2", "C"),
    ]


def test_override_keeps_position_and_changes_name():
    merged = reftable.merge_brand_overlay(BASE, [ov("1", "A", "override", "fixed")])
    assert codes(merged) == codes(BASE)
    assert merged[0]["zbrant"] == "fixed" and merged[0]["_source"] == "override"


def test_add_goes_to_the_end_of_that_customer_block():
    merged = reftable.merge_brand_overlay(BASE, [ov("1", "Z", "add", "z"), ov("9", "Q", "add", "q")])
    assert codes(merged) == [("1", "A"), ("1", "B"), ("1", "Z"), ("2", "C"), ("9", "Q")]


def test_merge_does_not_mutate_the_cached_sap_rows(tmp_path: Path):
    """`_read` 는 lru_cache 다. 병합이 캐시된 dict 를 고치면 다음 조회가 오염된다."""
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "brand_master.csv").write_text("kunnr,name1,zbrand,zbrant\n1,C,A,a\n", encoding="utf-8")
    (refs / "brand_master_manual.csv").write_text(
        "kunnr,name1,zbrand,zbrant,action,note\n1,,A,fixed,override,n\n", encoding="utf-8")
    assert reftable.load(tmp_path, "refs/brand_master.csv")[0]["zbrant"] == "fixed"
    assert brand_store.load_sap(tmp_path)[0].name == "a"


def test_engine_and_screen_see_the_same_candidates(masters_dir: Path):
    """실물 마스터로 — csv_choice 가 읽는 목록과 화면이 읽는 목록이 같다."""
    via_engine = codes(reftable.load(masters_dir, "refs/brand_master.csv"))
    via_screen = [(b.kunnr, b.zbrand) for b in brand_store.load_master(masters_dir)]
    assert via_engine == via_screen


def test_non_utf8_csv_names_the_fix(tmp_path: Path):
    """엑셀 기본 CSV 저장(cp949)이면 트레이스백 대신 고칠 방법을 알려준다."""
    import pytest

    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "brand_master.csv").write_bytes(
        "kunnr,name1,zbrand,zbrant\n4600,C,079,OEM(추가)\n".encode("cp949"))
    with pytest.raises(reftable.RefTableError, match="CSV UTF-8"):
        reftable.load(tmp_path, "refs/brand_master.csv")
    with pytest.raises(reftable.RefTableError, match="CSV UTF-8"):
        brand_store.load_sap(tmp_path)
