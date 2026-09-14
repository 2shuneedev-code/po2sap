"""마스터 검증기 — masters/SCHEMA.md §7.

두 방향으로 본다.
  1) 현재 마스터가 깨끗한가
  2) **일부러 깨뜨린 마스터를 실제로 잡아내는가** — 이게 없으면 검증기는
     "항상 통과하는 장식"이 된다.
"""

from __future__ import annotations

import shutil

import pytest


@pytest.fixture
def workspace(tmp_path, masters_dir):
    """수정해도 되는 masters 사본."""
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def run(validate_masters, workspace, code="msc"):
    base = validate_masters.load_base_fields(workspace)
    return validate_masters.validate_customer(code, base, workspace)


def break_msc(workspace, old: str, new: str) -> None:
    path = workspace / "customers" / "msc.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"앵커가 유일하지 않다: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ── 1) 현재 마스터 ─────────────────────────────────────────────────────
def test_all_customers_have_no_errors(validate_masters, masters_dir):
    base = validate_masters.load_base_fields(masters_dir)
    for code in validate_masters.customer_codes(masters_dir):
        report = validate_masters.validate_customer(code, base, masters_dir)
        assert report.errors == [], f"{code}: {report.errors}"


def test_every_base_field_is_declared(validate_masters, masters_dir):
    """§7-1 — 필드 수를 코드에 박지 않는다. _base 가 정하고 전량 선언이 강제된다."""
    base = validate_masters.load_base_fields(masters_dir)
    assert len(base) >= 30
    for code in validate_masters.customer_codes(masters_dir):
        from app.masters.loader import load_customer

        declared = set(load_customer(code, masters_dir).fields)
        assert declared == set(base), f"{code} 필드 불일치"


def test_expressions_in_masters_are_valid(validate_masters, masters_dir):
    """§7-4 — 마스터의 모든 expr 이 파싱되고 화이트리스트만 쓴다."""
    from app.masters.loader import load_customer
    from app.rules.expr import analyze

    seen = 0
    for code in validate_masters.customer_codes(masters_dir):
        for name, spec in load_customer(code, masters_dir).fields.items():
            if isinstance(spec, dict) and spec.get("from") == "expr":
                info = analyze(spec["expr"])
                assert info.ok, f"{code}.{name}: {info.errors}"
                assert not info.warnings, f"{code}.{name}: {info.warnings}"
                seen += 1
    assert seen >= 3


# ── 2) 역테스트: 깨뜨린 것을 잡는가 ────────────────────────────────────
FAULTS = [
    ("§7-1 필드 누락", 'VGPOS:   { from: const, value: "" }\n', ""),
    ("§7-1 없는 필드", 'VGPOS:   { from: const, value: "" }',
     'VGPOS:   { from: const, value: "" }\n  NOPE: { from: const, value: "" }'),
    ("§7-2 잘못된 from", 'VSART:   { from: const, value: "04" }',
     'VSART:   { from: lambda, value: "04" }'),
    ("§7-2 잘못된 format", "format: integer, required: true }", "format: yyyy, required: true }"),
    ("§7-2 잘못된 op", "op: contains_ci", "op: fuzzy_match"),
    ("§7-2 doc 인데 path 없음", "MATNR:   { from: doc,   path: line.item_code, required: true }",
     "MATNR:   { from: doc,   required: true }"),
    ("§7-2 미정의 필드 옵션", "MAKTX:   { from: const, value: \"\" }",
     "MAKTX:   { from: const, value: \"\", bogus: 1 }"),
    ("§7-3 없는 규칙 참조", "rule: brand_code, required: true }", "rule: no_such_rule, required: true }"),
    ("§7-3 없는 결정표", "table: ship_to_routing }", "table: no_such_table }"),
    ("§7-4 금지 함수", "expr: 'if(_city,", "expr: 'eval(_city,"),
    ("§7-4 연산자", """expr: 'join(",", compact([_pack_base, ref_codes.b_code, ref_codes.c_code]))'""",
     """expr: '_pack_base + ref_codes.b_code'"""),
    ("§7-4 인자 개수", 'concat(header.po_number, "(", _city, ")")', "upper(header.po_number, 2)"),
    ("§7-5 없는 경로", "path: line.item_code", "path: line.nonexistent"),
    ("§7-5 없는 플레이스홀더", "{our_item}", "{no_such_name}"),
    ("§4.0 미정의 최상위 키", "version: 2", "version: 2\nbogus_key: 1"),
    ("§4.9 없는 check id", "id: shipment_total_match", "id: made_up_check"),
    ("grid 비전송 필드", "pinned: [BSTKD, KUNNR2, MATNR, KWMENG]", "pinned: [BSTKD, NOT_A_FIELD]"),
]


@pytest.mark.parametrize("label,old,new", FAULTS, ids=[f[0] for f in FAULTS])
def test_fault_is_detected_as_error(validate_masters, workspace, label, old, new):
    break_msc(workspace, old, new)
    assert run(validate_masters, workspace).errors, f"{label} 을 놓쳤다"


WARN_FAULTS = [
    ("§7-6 중복 결정행",
     '- { when: ["RENO"],       then: ["319678", "RENO",       "O"] }',
     '- { when: ["RENO"],       then: ["319678", "RENO",       "O"] }\n'
     '      - { when: ["ELKHART"],    then: ["100249", "X", "C"] }',
     "§7-6"),
    ("§7-6 중복 entries", '- { contains: "ACCUPRO",    value: "205" }',
     '- { contains: "ACCUPRO",    value: "205" }\n'
     '      - { contains: "HERTEL",     value: "999" }',
     "§7-6"),
    ("§7-7 on_no_match 누락",
     """    on_no_match:
      action: error
      message: "MSC 브랜드 키워드를 찾을 수 없습니다 (HERTEL / INTERSTATE / ACCUPRO / CLASS C)\"""",
     "", "§7-7"),
    ("§7-4 contains 오용", 'expr: \'if(_city, concat(header.po_number, "(", _city, ")"), header.po_number)\'',
     'expr: \'if(contains("A,B", _city), "x", "y")\'', "§7-4"),
]


@pytest.mark.parametrize("label,old,new,tag", WARN_FAULTS, ids=[f[0] for f in WARN_FAULTS])
def test_fault_is_detected_as_warning(validate_masters, workspace, label, old, new, tag):
    break_msc(workspace, old, new)
    report = run(validate_masters, workspace)
    assert any(tag in w for w in report.warnings), f"{label} 을 놓쳤다: {report.warnings}"


def test_todo_is_reported(validate_masters, masters_dir):
    """§7-8 — 미확정 값은 막지 않고 목록으로 뽑는다 (원칙 P4)."""
    base = validate_masters.load_base_fields(masters_dir)
    report = validate_masters.validate_customer("kl", base, masters_dir)
    assert report.todos and report.errors == []


def test_missing_reference_table_blocks_unless_optional(validate_masters, workspace):
    (workspace / "refs" / "msc_ref.csv").unlink()
    # msc 의 lookup 은 optional: true → 경고로 끝나고 동작은 계속된다
    report = run(validate_masters, workspace)
    assert report.errors == []
    assert any("참조표 파일이 없습니다" in w for w in report.warnings)

    path = workspace / "customers" / "msc.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("optional: true", "optional: false"),
        encoding="utf-8",
    )
    assert run(validate_masters, workspace).errors
