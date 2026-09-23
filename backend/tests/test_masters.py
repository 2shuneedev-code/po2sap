"""마스터 검증기 — masters/SCHEMA.md §7.

두 방향으로 본다.
  1) 현재 마스터가 깨끗한가
  2) **일부러 깨뜨린 마스터를 실제로 잡아내는가** — 이게 없으면 검증기는
     "항상 통과하는 장식"이 된다.

2026-09-23: msc/kl/ygjp 는 거래처 전용 규칙(결정표·csv_map·lookup 등)을
걷어내고 기본(profiles/standard)만 쓰도록 단순화됐다(§7-13 `csv_choice` 신설도
같은 변경). 검증기가 **결정표·csv_map·lookup·checks 를 여전히 잡아내는지**는
실물 거래처 파일이 아니라 이 파일 전용 합성 거래처(`fx`)로 확인한다 — 검증기
회귀 테스트가 특정 거래처의 현재 규칙 내용에 묶이면, 그 거래처 규칙이
정리될 때마다(오늘처럼) 테스트가 통째로 죽는다.
"""

from __future__ import annotations

import re
import shutil

import pytest

# ── 합성 거래처 `fx` — 검증기의 결정표/규칙/checks/grid 검사 전용 ─────────
# 실물 거래처(msc/kl/ygjp)는 이제 델타가 없다. 이 파일은 그것과 무관하게
# "결정표·csv_map·lookup·checks 를 깨뜨리면 검증기가 잡는가"를 확인해야 하므로
# 전용 합성 거래처를 둔다. customer_no 는 MSC 실번호(100249)를 그대로 써서
# `value_check` 가 실물 brand_master.csv 의 실제 등록 코드(38 등)를 본다.
FX_CUSTOMER_YAML = """\
version: 2
meta:
  code: FX
  name: "검증기 회귀 테스트 전용 합성 거래처"
  customer_no: "100249"
  owner: "※ 지정 필요"
  status: draft
  file_types: [pdf]
extends: [_base/sap_defaults, profiles/standard]
extraction:
  input: text
  page_limit: 40
split:
  by: shipment
  label: "출하처(Shipment)별로 오더를 나눈다"
  group_label: _city
tables:
  ship_to_routing:
    label: "출하처(Ship To) 분기"
    scope: shipment
    when:
      - source: shipment.ship_to_text
        fallback_source: header.ship_to_text
        op: contains_ci
        label: "출하처 블록에 포함"
    then: [KUNNR2, _city, _pack_base]
    rows:
      - { when: ["ELKHART"], then: ["100249", "ELKHART", "C"] }
      - { when: ["RENO"], then: ["319678", "RENO", "O"] }
    on_no_match:
      action: error
      message: "출하처 도시를 인식하지 못했습니다"
rules:
  brand_code:
    kind: csv_map
    label: "브랜드 판별"
    source: header.brand_text
    table_file: refs/fx_keys.csv
    filter_column: kunnr
    key_column: text
    mode_column: match
    value_column: zbrand
    case_insensitive: true
    value_check:
      table_file: refs/brand_master.csv
      value_column: zbrand
      filter_column: kunnr
    on_no_match:
      action: error
      message: "브랜드를 인식하지 못했습니다: {brand_text}"
  ref_codes:
    kind: lookup
    label: "참조표 조회"
    table_file: refs/fx_ref.csv
    optional: true
    key: line.our_item
    key_column: our_item
    return: [b_code, c_code]
    on_no_match:
      action: warn
      message: "참조표에 없는 품번입니다: {our_item}"
fields:
  KUNNR2: { from: table, table: ship_to_routing }
  BSTKD:
    from: expr
    expr: 'if(_city, concat(header.po_number, "(", _city, ")"), header.po_number)'
    required: true
  ZBRAND: { from: rule, rule: brand_code, required: true }
  ZSHCO: { from: const, value: "A" }
  MATNR: { from: doc, path: line.item_code, required: true }
  ZPKRE2:
    from: expr
    expr: 'join(",", compact([_pack_base, ref_codes.b_code, ref_codes.c_code]))'
checks:
  - id: shipment_total_match
    label: "출하처별 수량 합계 = 상단 요약표 합계"
    severity: error
grid:
  pinned: [BSTKD, KUNNR2, MATNR, KWMENG]
"""

FX_KEYS_CSV = "kunnr,zbrand,match,text,note\n100249,038,equals,HERTEL,\n"
FX_REF_CSV = "our_item,b_code,c_code,note\n09876543,B12,C7,\n"


@pytest.fixture
def workspace(tmp_path, masters_dir):
    """수정해도 되는 masters 사본 + 검증기 회귀 테스트 전용 합성 거래처(fx)."""
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    (dst / "customers" / "fx.yaml").write_text(FX_CUSTOMER_YAML, encoding="utf-8")
    (dst / "refs" / "fx_keys.csv").write_text(FX_KEYS_CSV, encoding="utf-8")
    (dst / "refs" / "fx_ref.csv").write_text(FX_REF_CSV, encoding="utf-8")
    return dst


def run(validate_masters, workspace, code="fx"):
    base = validate_masters.load_base_fields(workspace)
    return validate_masters.validate_customer(code, base, workspace)


def _patch(path, old: str, new: str) -> None:
    """앵커 한 곳을 바꿔 결함을 심는다.

    공백 차이는 무시하고 찾는다 — `master_import.py` 가 YAML 을 다시 쓰면
    `{ from: const }` 가 `{from: const}` 로 바뀐다. 앵커를 글자 그대로 찾으면
    서식이 달라졌다는 이유만으로 **검증기 역테스트 8종이 통째로 죽는다.**
    죽은 이유가 "검증기가 결함을 못 잡아서"가 아닌데도 그렇게 보인다.
    """
    text = path.read_text(encoding="utf-8")
    if text.count(old) == 1:
        path.write_text(text.replace(old, new), encoding="utf-8")
        return

    pattern = re.compile(r"[ \t]*".join(re.escape(part) for part in old.split()))
    found = pattern.findall(text)
    assert len(found) == 1, f"앵커가 유일하지 않다 ({len(found)}건): {old!r}"
    path.write_text(pattern.sub(lambda _: new, text, count=1), encoding="utf-8")


def break_fx(workspace, old: str, new: str) -> None:
    _patch(workspace / "customers" / "fx.yaml", old, new)


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
    # 하한만 둔다 — 현업이 템플릿에서 열을 빼면 줄어드는 것이 정상이다.
    # 여기서 잡으려는 것은 개수가 아니라 **목록이 비어버리는 사고**다.
    assert len(base) >= 10
    for code in validate_masters.customer_codes(masters_dir):
        from app.masters.loader import load_customer

        declared = set(load_customer(code, masters_dir).fields)
        assert declared == set(base), f"{code} 필드 불일치"


def test_expressions_in_masters_are_valid(validate_masters, workspace):
    """§7-4 — 마스터의 모든 expr 이 파싱되고 화이트리스트만 쓴다.

    실물 거래처는 이제 expr 을 쓰지 않는다 — 합성 거래처(fx)로 확인한다.
    """
    from app.masters.loader import load_customer
    from app.rules.expr import analyze

    seen = 0
    for name, spec in load_customer("fx", workspace).fields.items():
        if isinstance(spec, dict) and spec.get("from") == "expr":
            info = analyze(spec["expr"])
            assert info.ok, f"fx.{name}: {info.errors}"
            assert not info.warnings, f"fx.{name}: {info.warnings}"
            seen += 1
    assert seen >= 1


# ── 2) 역테스트: 깨뜨린 것을 잡는가 (합성 거래처 fx 로 확인) ────────────
FAULTS = [
    ("§7-1 없는 필드", 'ZSHCO: { from: const, value: "A" }',
     'ZSHCO: { from: const, value: "A" }\n  NOPE: { from: const, value: "" }'),
    ("§7-2 잘못된 from", "MATNR: { from: doc, path: line.item_code, required: true }",
     "MATNR: { from: lambda, path: line.item_code, required: true }"),
    ("§7-2 잘못된 format", "MATNR: { from: doc, path: line.item_code, required: true }",
     "MATNR: { from: doc, path: line.item_code, format: yyyy }"),
    ("§7-2 잘못된 op", "op: contains_ci", "op: fuzzy_match"),
    ("§7-2 doc 인데 path 없음", "MATNR: { from: doc, path: line.item_code, required: true }",
     "MATNR: { from: doc, required: true }"),
    ("§7-2 미정의 필드 옵션", 'ZSHCO: { from: const, value: "A" }',
     'ZSHCO: { from: const, value: "A", bogus: 1 }'),
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
    ("§7-13 csv_choice on_many default", "rules:\n  brand_code:",
     "rules:\n"
     "  brand_choice_probe:\n"
     "    kind: csv_choice\n"
     "    table_file: refs/brand_master.csv\n"
     "    filter_column: kunnr\n"
     "    value_column: zbrand\n"
     "    on_many: { action: default }\n"
     "    on_no_match: { action: warn }\n"
     "  brand_code:"),
]


@pytest.mark.parametrize("label,old,new", FAULTS, ids=[f[0] for f in FAULTS])
def test_fault_is_detected_as_error(validate_masters, workspace, label, old, new):
    break_fx(workspace, old, new)
    assert run(validate_masters, workspace).errors, f"{label} 을 놓쳤다"


def test_field_missing_from_merged_result_is_an_error(validate_masters, workspace):
    """§7-1 — 프로필에서 빠지면 그 프로필을 쓰는 전 거래처가 걸린다."""
    break_profile(workspace, '  VGPOS:   { from: const, value: "" }\n', "")
    report = run(validate_masters, workspace, "kl")
    assert any("VGPOS" in e for e in report.errors), report.errors


def test_profile_is_not_listed_as_a_customer(validate_masters, masters_dir):
    """프로필은 거래처가 아니다 — 목록·검증 대상에 끼면 안 된다."""
    assert validate_masters.customer_codes(masters_dir) == ["kl", "msc", "ygjp"]


WARN_FAULTS = [
    ("§7-6 중복 결정행",
     '- { when: ["RENO"], then: ["319678", "RENO", "O"] }',
     '- { when: ["RENO"], then: ["319678", "RENO", "O"] }\n'
     '      - { when: ["ELKHART"], then: ["100249", "X", "C"] }',
     "§7-6"),
    ("§7-6 중복 entries", "rules:\n  brand_code:",
     'rules:\n'
     '  dup_probe:\n'
     '    kind: keyword_map\n'
     '    source: header.brand_text\n'
     '    entries:\n'
     '      - { contains: "A", value: "1" }\n'
     '      - { contains: "A", value: "2" }\n'
     '    on_no_match: { action: warn, message: "x" }\n'
     "  brand_code:",
     "§7-6"),
    ("§7-7 on_no_match 누락",
     """    on_no_match:
      action: error
      message: "브랜드를 인식하지 못했습니다: {brand_text}\"""",
     "", "§7-7"),
    ("§7-4 contains 오용", 'expr: \'if(_city, concat(header.po_number, "(", _city, ")"), header.po_number)\'',
     'expr: \'if(contains("A,B", _city), "x", "y")\'', "§7-4"),
]


@pytest.mark.parametrize("label,old,new,tag", WARN_FAULTS, ids=[f[0] for f in WARN_FAULTS])
def test_fault_is_detected_as_warning(validate_masters, workspace, label, old, new, tag):
    break_fx(workspace, old, new)
    report = run(validate_masters, workspace)
    assert any(tag in w for w in report.warnings), f"{label} 을 놓쳤다: {report.warnings}"


def test_todo_is_reported(validate_masters, masters_dir):
    """§7-8 — 미확정 값은 막지 않고 목록으로 뽑는다 (원칙 P4)."""
    base = validate_masters.load_base_fields(masters_dir)
    report = validate_masters.validate_customer("kl", base, masters_dir)
    assert report.todos and report.errors == []


def test_missing_reference_table_blocks_unless_optional(validate_masters, workspace):
    (workspace / "refs" / "fx_ref.csv").unlink()
    # fx 의 lookup 은 optional: true → 경고로 끝나고 동작은 계속된다
    report = run(validate_masters, workspace)
    assert report.errors == []
    assert any("참조표 파일이 없습니다" in w for w in report.warnings)

    path = workspace / "customers" / "fx.yaml"
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
    """거래처 파일이 28개를 다시 나열하면 프로필의 의미가 없다.

    지금은 msc/kl/ygjp 모두 델타가 0개다 — 거래처 전용 규칙을 걷어내고
    기본(profiles/standard)만 쓰기 때문이다(2026-09-23). 나중에 예외를
    다시 얹으면 이 상한(12) 안에서 늘어난다.
    """
    import yaml

    for code in ("msc", "kl", "ygjp"):
        raw = yaml.safe_load((masters_dir / "customers" / f"{code}.yaml").read_text("utf-8"))
        declared = raw.get("fields") or {}
        assert "profiles/standard" in raw["extends"], code
        assert len(declared) <= 12, f"{code}: {len(declared)}개 — 델타만 적어야 한다"


def test_profile_override_replaces_the_whole_spec(workspace):
    """§1 — 항목은 통째로 교체된다. 프로필의 todo/value 가 새면 안 된다."""
    from app.masters.loader import load_customer

    fx = load_customer("fx", workspace).fields["KUNNR2"]
    assert fx == {"from": "table", "table": "ship_to_routing"}
    assert "todo" not in fx and "value" not in fx


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


# ── csv_map 참조표 매핑 (SCHEMA §4.5 · §7-10 · §7-11) — 합성 거래처(fx) ──
def break_keys(workspace, old: str, new: str) -> None:
    _patch(workspace / "refs" / "fx_keys.csv", old, new)


def test_every_mapped_code_is_registered_in_sap(validate_masters, workspace):
    """§7-10 — 등록되지 않은 ZBRAND 를 전송하면 SAP 이 거부한다."""
    import csv as _csv

    master = {
        (r["kunnr"], r["zbrand"])
        for r in _csv.DictReader((workspace / "refs" / "brand_master.csv").open(encoding="utf-8"))
    }
    keys = list(_csv.DictReader((workspace / "refs" / "fx_keys.csv").open(encoding="utf-8")))
    assert keys, "fx_keys.csv 가 비어 있다"
    unregistered = [(r["kunnr"], r["zbrand"]) for r in keys if (r["kunnr"], r["zbrand"]) not in master]
    assert unregistered == [], f"SAP 미등록 코드: {unregistered}"


def test_unregistered_code_is_an_error(validate_masters, workspace):
    break_keys(workspace, "100249,038,equals,HERTEL,", "100249,99999,equals,HERTEL,")
    report = run(validate_masters, workspace)
    assert any("99999" in e and "등록돼 있지 않" in e for e in report.errors), report.errors


def test_missing_column_is_an_error(validate_masters, workspace):
    _patch(workspace / "customers" / "fx.yaml", "key_column: text", "key_column: nope")
    assert any("없는 컬럼" in e for e in run(validate_masters, workspace).errors)


def test_bad_match_mode_is_an_error(validate_masters, workspace):
    break_keys(workspace, "100249,038,equals,HERTEL,", "100249,038,fuzzy,HERTEL,")
    assert any("contains | equals" in e for e in run(validate_masters, workspace).errors)


def test_duplicate_key_is_a_warning(validate_masters, workspace):
    """행 순서가 우선순위다 — 같은 문구가 두 번 있으면 아래 행은 도달 불가."""
    break_keys(workspace, "100249,038,equals,HERTEL,",
               "100249,038,equals,HERTEL,\n100249,127,equals,HERTEL,")
    assert any("도달할 수 없습니다" in w for w in run(validate_masters, workspace).warnings)


def test_customer_with_no_rows_is_a_warning(validate_masters, workspace):
    """§7-11 — 규칙은 걸어뒀는데 그 거래처 행이 없으면 항상 미매칭된다."""
    path = workspace / "refs" / "fx_keys.csv"
    kept = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("100249,")]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    report = run(validate_masters, workspace)
    assert any("행이 하나도 없습니다" in w for w in report.warnings), report.warnings


def test_note_column_is_reported(validate_masters, workspace):
    """§7-8 — 참조표의 note 는 필드의 todo 와 같은 역할을 한다."""
    break_keys(workspace, "100249,038,equals,HERTEL,", "100249,038,equals,HERTEL,확인 필요")
    report = run(validate_masters, workspace)
    assert report.errors == []
    assert any("fx_keys.csv" in t for t in report.todos)


def test_template_file_is_not_a_customer(masters_dir):
    """`_template.yaml` 은 새 거래처를 만들 때 복사하는 서식이다.

    거래처로 읽히면 화면 목록에 `XXX` 가 뜨고, 고르면 빈 규칙으로 파싱이 돈다.
    """
    from app.masters import list_customers

    codes = {c.code for c in list_customers(masters_dir)}
    assert "XXX" not in codes
    assert "MSC" in codes


# ── §7-12 extraction.chunking ──────────────────────────────────────────
def with_chunking(workspace, *body: str) -> None:
    """fx.yaml 의 `extraction` 에 `chunking:` 블록을 심는다."""
    lines = "\n".join(f"    {line}" for line in body)
    break_fx(workspace, "page_limit: 40", f"page_limit: 40\n  chunking:\n{lines}")


CHUNKING_FAULTS = [
    ("줄 수 0", "max_lines_per_chunk: 0"),
    ("줄 수 음수", "max_lines_per_chunk: -5"),
    ("줄 수 소수", "max_lines_per_chunk: 12.5"),
    ("줄 수 문자", 'max_lines_per_chunk: "많이"'),
    ("줄당 토큰 0", "tokens_per_line: 0"),
    ("안전 비율 0", "safety_ratio: 0"),
    ("안전 비율 100% 초과", "safety_ratio: 1.5"),
    ("앞머리 음수", "header_context_lines: -1"),
    ("enabled 가 불리언 아님", 'enabled: "yes"'),
    ("허용 밖의 키", "max_lines: 100"),
]


@pytest.mark.parametrize("label,line", CHUNKING_FAULTS, ids=[f[0] for f in CHUNKING_FAULTS])
def test_bad_chunking_is_an_error(validate_masters, workspace, label, line):
    """§7-12 — 잘못된 청크 설정을 놓치면 큰 문서에서만 조용히 이상하게 나뉜다."""
    with_chunking(workspace, line)
    report = run(validate_masters, workspace)
    assert any("§7-12" in e for e in report.errors), f"{label} 을 놓쳤다: {report.errors}"


def test_a_customer_may_override_one_chunking_key(validate_masters, workspace):
    with_chunking(workspace, "max_lines_per_chunk: 150")
    assert run(validate_masters, workspace).errors == []


def test_zero_header_context_and_disabled_chunking_are_valid(validate_masters, workspace):
    """앞머리를 안 붙이거나 분할을 끄는 것은 정당한 선택이다."""
    with_chunking(workspace, "header_context_lines: 0", "enabled: false")
    assert run(validate_masters, workspace).errors == []


def test_unknown_extraction_key_is_an_error(validate_masters, workspace):
    break_fx(workspace, "page_limit: 40", "page_limit: 40\n  bogus: 1")
    report = run(validate_masters, workspace)
    assert any("bogus" in e for e in report.errors), report.errors


def test_a_broken_base_default_is_caught_for_every_customer(validate_masters, workspace):
    """기본값이 깨지면 그 값을 물려받는 전 거래처가 걸린다."""
    _patch(workspace / "_base" / "sap_defaults.yaml", "tokens_per_line: 80", "tokens_per_line: 0")
    for code in ("msc", "kl", "ygjp"):
        report = run(validate_masters, workspace, code)
        assert any("§7-12" in e and "tokens_per_line" in e for e in report.errors), code


def test_extraction_defaults_is_allowed_at_the_top_level(validate_masters, masters_dir):
    """`_base` 조각이 병합되어 올라오는 키다 (SCHEMA §4.0) — 최상위 키 검사가 막으면 안 된다."""
    assert "extraction_defaults" in validate_masters.TOP_LEVEL_KEYS
    assert set(validate_masters.CHUNKING_KEYS) == {
        "enabled", "max_lines_per_chunk", "tokens_per_line", "safety_ratio",
        "header_context_lines",
    }
