"""expr 파서 — masters/SCHEMA.md §4.7."""

from __future__ import annotations

import pytest
from app.rules.expr import Call, ExprError, ListNode, Literal, Path, analyze, parse

# 실제 마스터가 쓰고 있는 식 — 전부 통과해야 한다
REAL = [
    'if(_city, concat(header.po_number, "(", _city, ")"), header.po_number)',
    'join(",", compact([_pack_base, ref_codes.b_code, ref_codes.c_code]))',
    'join("-", ["01", date_yyyymmdd(header.po_date), header.po_number])',
    'if(in(brand_code, ["471", "507"]), "A", "L")',
]


@pytest.mark.parametrize("src", REAL)
def test_real_expressions_parse(src):
    assert analyze(src).ok


def test_ast_shape():
    node = parse('concat(header.po_number, "-", 3)')
    assert isinstance(node, Call) and node.name == "concat"
    assert isinstance(node.args[0], Path)
    assert node.args[0].dotted == "header.po_number"
    assert isinstance(node.args[1], Literal) and node.args[1].value == "-"
    assert node.args[2].type == "num"


def test_list_literal():
    node = parse('in(x, ["a", "b"])')
    assert isinstance(node.args[1], ListNode)
    assert [i.value for i in node.args[1].items] == ["a", "b"]


def test_reserved_literals():
    assert parse("true").value is True
    assert parse("null").value is None
    with pytest.raises(ExprError):
        parse("true.x")


@pytest.mark.parametrize(
    "src",
    [
        'header.po_number + "-"',      # 연산자 없음
        "concat(a, b",                  # 괄호 불일치
        'concat("a)',                   # 문자열 안 닫힘
        "concat(a) extra",              # 뒤에 잔여 토큰
        "",                             # 빈 식
        'concat("a\\q")',               # 허용되지 않은 이스케이프
    ],
)
def test_syntax_errors(src):
    assert not analyze(src).ok


def test_unknown_function_rejected():
    errors = analyze('eval("import os")').errors
    assert errors and "허용되지 않은 함수" in errors[0]


def test_arity_checked():
    assert any("인자는 1개" in e for e in analyze("upper(a, b)").errors)
    assert any("인자는 2개" in e for e in analyze('join("-")').errors)


def test_argument_type_checked():
    # join 의 2번째 인자는 리스트여야 한다
    assert any("list" in e for e in analyze('join("-", "notalist")').errors)
    # 경로는 정적으로 타입을 알 수 없으므로 통과시킨다 (거짓 경보 방지)
    assert analyze('join("-", header.anything)').ok


def test_referenced_paths_collected():
    info = analyze('if(_city, concat(header.po_number, line.item_code), null)')
    assert {p.dotted for p in info.referenced_paths} == {
        "_city", "header.po_number", "line.item_code",
    }


def test_contains_misuse_is_linted():
    """SCHEMA §4.7.3 — 코드 목록 판정에 contains 를 쓰면 오판한다."""
    info = analyze('if(contains("471,507", brand_code), "A", "L")')
    assert info.ok                      # 문법은 합법
    assert info.warnings                # 그러나 경고한다
    assert 'in(brand_code, ["471", "507"])' in info.warnings[0]


def test_correct_in_usage_is_not_linted():
    assert not analyze('if(in(brand_code, ["471", "507"]), "A", "L")').warnings


def test_newline_rejected():
    assert not analyze('concat(\n"a")').ok
