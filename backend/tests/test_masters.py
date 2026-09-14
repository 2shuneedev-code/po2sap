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


def _patch(path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"앵커가 유일하지 않다: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def break_msc(workspace, old: str, new: str) -> None:
    _patch(workspace / "customers" / "msc.yaml", old, new)


def break_profile(workspace, old: str, new: str) -> None:
    """프로필이 채우던 필드를 없애면 병합 결과에서 빠진다 (SCHEMA §4.6)."""
    _patch(workspace / "profiles" / "standard.yaml", old, new)


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
# 거래처 파일을 깨뜨리는 결함 (msc.yaml 은 이제 델타만 담는다)
FAULTS = [
    ("§7-1 없는 필드", 'ZSHCO:   { from: const, value: "A" }',
     'ZSHCO:   { from: const, value: "A" }\n  NOPE: { from: const, value: "" }'),
    ("§7-2 잘못된 from", "MATNR:   { from: doc,   path: line.item_code, required: true }",
     "MATNR:   { from: lambda, path: line.item_code, required: true }"),
    ("§7-2 잘못된 format", "MATNR:   { from: doc,   path: line.item_code, required: true }",
     "MATNR:   { from: doc,   path: line.item_code, format: yyyy }"),
    ("§7-2 잘못된 op", "op: contains_ci", "op: fuzzy_match"),
    ("§7-2 doc 인데 path 없음", "MATNR:   { from: doc,   path: line.item_code, required: true }",
     "MATNR:   { from: doc,   required: true }"),
    ("§7-2 미정의 필드 옵션", 'ZSHCO:   { from: const, value: "A" }',
     'ZSHCO:   { from: const, value: "A", bogus: 1 }'),
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


def test_field_missing_from_merged_result_is_an_error(validate_masters, workspace):
    """§7-1 — 프로필에서 빠지면 그 프로필을 쓰는 전 거래처가 걸린다."""
    break_profile(workspace, '  VGPOS:   { from: const, value: "" }\n', "")
    report = run(validate_masters, workspace)
    assert any("VGPOS" in e for e in report.errors), report.errors


def test_profile_is_not_listed_as_a_customer(validate_masters, masters_dir):
    """프로필은 거래처가 아니다 — 목록·검증 대상에 끼면 안 된다."""
    assert validate_masters.customer_codes(masters_dir) == ["kl", "msc", "ygjp"]


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


# ── 프로필 상속 (SCHEMA §1.1) ──────────────────────────────────────────
def test_merged_declaration_covers_every_field(validate_masters, masters_dir):
    """거래처 파일은 델타만 적지만, 병합 결과는 전송 필드 전량을 채운다."""
    from app.masters.loader import load_customer

    base = set(validate_masters.load_base_fields(masters_dir))
    for code in validate_masters.customer_codes(masters_dir):
        assert set(load_customer(code, masters_dir).fields) == base, code


def test_customer_files_declare_only_deltas(masters_dir):
    """거래처 파일이 36개를 다시 나열하면 프로필의 의미가 없다."""
    import yaml

    for code in ("msc", "kl", "ygjp"):
        raw = yaml.safe_load((masters_dir / "customers" / f"{code}.yaml").read_text("utf-8"))
        declared = raw.get("fields") or {}
        assert "profiles/standard" in raw["extends"], code
        assert len(declared) <= 12, f"{code}: {len(declared)}개 — 델타만 적어야 한다"


def test_profile_override_replaces_the_whole_spec(masters_dir):
    """§1 — 항목은 통째로 교체된다. 프로필의 todo/value 가 새면 안 된다."""
    from app.masters.loader import load_customer

    msc = load_customer("msc", masters_dir).fields["KUNNR2"]
    assert msc == {"from": "table", "table": "ship_to_routing"}
    assert "todo" not in msc and "value" not in msc


def test_customer_code_comes_from_meta_not_a_literal(masters_dir):
    """KUNNR1/KUNNR3 은 프로필에서 meta.customer_no 로 한 번만 적는다."""
    import yaml
    from app.masters.loader import load_customer

    for code in ("msc", "kl", "ygjp"):
        m = load_customer(code, masters_dir)
        for field in ("KUNNR1", "KUNNR3"):
            assert m.fields[field]["expr"] == "meta.customer_no", f"{code}.{field}"
        raw = yaml.safe_load((masters_dir / "customers" / f"{code}.yaml").read_text("utf-8"))
        assert "KUNNR1" not in (raw.get("fields") or {}), code


def test_meta_paths_are_valid_references(validate_masters, masters_dir):
    """§3 — meta.* 가 참조 가능한 경로로 인정되어야 §7-5 가 오탐하지 않는다."""
    from app.masters.loader import load_customer

    allowed = validate_masters.valid_paths(load_customer("msc", masters_dir))
    assert {"meta.code", "meta.customer_no", "meta.name"} <= allowed


def test_new_customer_from_template_validates(validate_masters, workspace):
    """템플릿을 복사해 코드만 채우면 오류 없이 통과하고, 미정 값은 TODO 로 뜬다."""
    src = workspace / "customers" / "_template.yaml"
    text = src.read_text(encoding="utf-8").replace("code: XXX", "code: NEWCO")
    (workspace / "customers" / "newco.yaml").write_text(text, encoding="utf-8")

    base = validate_masters.load_base_fields(workspace)
    report = validate_masters.validate_customer("newco", base, workspace)
    assert report.errors == []
    assert report.todos, "미확정 값이 리포트에 떠야 한다 (원칙 2)"
    assert "newco" in validate_masters.customer_codes(workspace)
    assert "_template" not in validate_masters.customer_codes(workspace)
