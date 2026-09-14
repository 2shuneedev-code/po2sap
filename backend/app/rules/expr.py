"""`expr` 식 파서 — masters/SCHEMA.md §4.7 구현.

문법은 SCHEMA.md §4.7.1 이 원천이다. 여기서 문법을 바꾸지 않는다.

이 모듈은 **파싱과 정적 검증까지만** 한다. 실제 값 계산(평가)은 D2 규칙엔진의 몫이고,
같은 AST 를 받아 수행한다. 검증이 파싱과 같은 파서를 쓰기 때문에
"검증은 통과했는데 엔진에서 깨지는" 경우가 생기지 않는다.

    parse("if(_city, concat(header.po_number, \"(\", _city, \")\"), header.po_number)")

임의 코드 실행은 불가능하다. 아래 문법에 맞는 것만 받아들이고 나머지는 거부한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal as TypingLiteral

# ── 타입 ───────────────────────────────────────────────────────────────
# any = 정적으로 알 수 없음(경로 참조 등). 검증에서 어떤 기대 타입과도 충돌하지 않는다.
ValueType = TypingLiteral["text", "num", "bool", "list", "any"]


class ExprError(ValueError):
    """식 문법·화이트리스트 위반. message 에 위치(칼럼)를 담는다."""

    def __init__(self, message: str, pos: int | None = None) -> None:
        self.pos = pos
        super().__init__(message if pos is None else f"{message} (위치 {pos + 1})")


# ── AST ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Literal:
    value: str | float | bool | None
    type: ValueType
    pos: int = 0


@dataclass(frozen=True)
class ListNode:
    items: tuple["Node", ...]
    pos: int = 0
    type: ValueType = "list"


@dataclass(frozen=True)
class Path:
    """컨텍스트 참조. `header.po_number`, `_city`, `ref_codes.b_code` 등."""

    parts: tuple[str, ...]
    pos: int = 0
    type: ValueType = "any"

    @property
    def dotted(self) -> str:
        return ".".join(self.parts)

    @property
    def root(self) -> str:
        return self.parts[0]


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple["Node", ...]
    pos: int = 0


Node = Literal | ListNode | Path | Call


# ── 화이트리스트 (SCHEMA.md §4.7.3) ────────────────────────────────────
@dataclass(frozen=True)
class FuncSpec:
    name: str
    min_args: int
    max_args: int | None          # None = 가변
    returns: ValueType
    arg_types: tuple[ValueType, ...] = ()   # 위치별 기대 타입. 부족하면 "any"
    summary: str = ""

    def expected_arity(self) -> str:
        if self.max_args is None:
            return f"{self.min_args}개 이상"
        if self.min_args == self.max_args:
            return f"{self.min_args}개"
        return f"{self.min_args}~{self.max_args}개"

    def arg_type(self, index: int) -> ValueType:
        if index < len(self.arg_types):
            return self.arg_types[index]
        return self.arg_types[-1] if self.arg_types else "any"


def _f(name, mn, mx, ret, args=(), summary="") -> FuncSpec:
    return FuncSpec(name, mn, mx, ret, args, summary)


FUNCTIONS: dict[str, FuncSpec] = {
    f.name: f
    for f in (
        _f("concat", 1, None, "text", ("any",), "이어붙인다"),
        _f("join", 2, 2, "text", ("text", "list"), "리스트를 구분자로 잇는다"),
        _f("compact", 1, 1, "list", ("list",), "null·빈 항목 제거"),
        _f("coalesce", 1, None, "any", ("any",), "첫 번째로 비어 있지 않은 값"),
        _f("if", 3, 3, "any", ("any", "any", "any"), "조건 분기"),
        _f("contains", 2, 2, "bool", ("text", "text"), "부분 문자열 검사"),
        _f("in", 2, 2, "bool", ("any", "list"), "리스트 항목과 완전 일치"),
        _f("upper", 1, 1, "text", ("text",), "대문자"),
        _f("lower", 1, 1, "text", ("text",), "소문자"),
        _f("trim", 1, 1, "text", ("text",), "앞뒤 공백 제거"),
        _f("replace", 3, 3, "text", ("text", "text", "text"), "전부 치환"),
        _f("substr", 3, 3, "text", ("text", "num", "num"), "부분 문자열"),
        _f("pad", 3, 3, "text", ("text", "num", "text"), "왼쪽 채우기"),
        _f("integer", 1, 1, "text", ("any",), "정수 표기로 정규화"),
        _f("decimal3", 1, 1, "text", ("any",), "소수점 3자리"),
        _f("date_yyyymmdd", 1, 1, "text", ("any",), "날짜 → YYYYMMDD"),
    )
}

RESERVED = {"true": True, "false": False, "null": None}


# ── 토크나이저 ─────────────────────────────────────────────────────────
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_PUNCT = set("(),[].")
_ESCAPES = {'"': '"', "'": "'", "\\": "\\"}


@dataclass
class _Token:
    kind: str          # ident | number | string | punct | end
    text: str
    pos: int
    value: object = None


def _tokenize(src: str) -> list[_Token]:
    out: list[_Token] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\n\r":
            raise ExprError("식은 한 줄로 써야 합니다 (줄바꿈 불가)", i)
        if ch in " \t":
            i += 1
            continue
        if ch in _PUNCT:
            out.append(_Token("punct", ch, i))
            i += 1
            continue
        if ch in "\"'":
            quote, buf, j = ch, [], i + 1
            while True:
                if j >= n:
                    raise ExprError("문자열이 닫히지 않았습니다", i)
                c = src[j]
                if c == "\\":
                    if j + 1 >= n or src[j + 1] not in _ESCAPES:
                        nxt = src[j + 1] if j + 1 < n else ""
                        raise ExprError(
                            f"허용되지 않은 이스케이프입니다: \\{nxt} "
                            "(\\\" \\' \\\\ 만 가능)",
                            j,
                        )
                    buf.append(_ESCAPES[src[j + 1]])
                    j += 2
                    continue
                if c == quote:
                    j += 1
                    break
                if c in "\n\r":
                    raise ExprError("문자열 안에 줄바꿈을 넣을 수 없습니다", j)
                buf.append(c)
                j += 1
            out.append(_Token("string", src[i:j], i, "".join(buf)))
            i = j
            continue
        m = _NUMBER.match(src, i)
        if m and (ch.isdigit() or (ch == "-" and i + 1 < n and src[i + 1].isdigit())):
            text = m.group(0)
            out.append(_Token("number", text, i, float(text) if "." in text else int(text)))
            i = m.end()
            continue
        m = _IDENT.match(src, i)
        if m:
            out.append(_Token("ident", m.group(0), i))
            i = m.end()
            continue
        raise ExprError(f"해석할 수 없는 문자입니다: {ch!r}", i)
    out.append(_Token("end", "", len(src)))
    return out


# ── 파서 ───────────────────────────────────────────────────────────────
class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._t = tokens
        self._i = 0

    @property
    def cur(self) -> _Token:
        return self._t[self._i]

    def _eat(self, text: str) -> _Token:
        tok = self.cur
        if tok.kind == "end":
            raise ExprError(f"'{text}' 가 필요한데 식이 끝났습니다", tok.pos)
        if tok.text != text:
            raise ExprError(f"'{text}' 가 필요한데 '{tok.text}' 가 왔습니다", tok.pos)
        self._i += 1
        return tok

    def parse(self) -> Node:
        node = self.value()
        if self.cur.kind != "end":
            raise ExprError(
                f"식이 끝난 뒤에 '{self.cur.text}' 가 남았습니다 "
                "(연산자는 지원하지 않습니다 — SCHEMA §4.7.1)",
                self.cur.pos,
            )
        return node

    def value(self) -> Node:
        tok = self.cur
        if tok.kind == "end":
            raise ExprError("식이 비어 있습니다", tok.pos)
        if tok.kind == "string":
            self._i += 1
            return Literal(tok.value, "text", tok.pos)
        if tok.kind == "number":
            self._i += 1
            return Literal(tok.value, "num", tok.pos)
        if tok.text == "[":
            return self.list_node()
        if tok.kind == "ident":
            return self.ident_node()
        raise ExprError(f"값이 필요한데 '{tok.text}' 가 왔습니다", tok.pos)

    def list_node(self) -> ListNode:
        start = self._eat("[").pos
        items: list[Node] = []
        if self.cur.text != "]":
            items.append(self.value())
            while self.cur.text == ",":
                self._i += 1
                items.append(self.value())
        self._eat("]")
        return ListNode(tuple(items), start)

    def ident_node(self) -> Node:
        tok = self.cur
        self._i += 1

        if self.cur.text == "(":                       # 함수 호출
            self._i += 1
            args: list[Node] = []
            if self.cur.text != ")":
                args.append(self.value())
                while self.cur.text == ",":
                    self._i += 1
                    args.append(self.value())
            self._eat(")")
            return Call(tok.text, tuple(args), tok.pos)

        if tok.text in RESERVED:                       # true / false / null
            if self.cur.text == ".":
                raise ExprError(f"'{tok.text}' 는 예약어라 경로로 쓸 수 없습니다", tok.pos)
            value = RESERVED[tok.text]
            return Literal(value, "bool" if isinstance(value, bool) else "any", tok.pos)

        parts = [tok.text]                             # 경로
        while self.cur.text == ".":
            self._i += 1
            nxt = self.cur
            if nxt.kind != "ident":
                raise ExprError("'.' 뒤에는 이름이 와야 합니다", nxt.pos)
            parts.append(nxt.text)
            self._i += 1
        return Path(tuple(parts), tok.pos)


def parse(src: str) -> Node:
    """식을 AST 로 만든다. 문법 오류는 ExprError."""
    if not isinstance(src, str) or not src.strip():
        raise ExprError("식이 비어 있습니다", 0)
    return _Parser(_tokenize(src)).parse()


# ── 정적 검증 ──────────────────────────────────────────────────────────
def node_type(node: Node) -> ValueType:
    if isinstance(node, Call):
        spec = FUNCTIONS.get(node.name)
        return spec.returns if spec else "any"
    return node.type


def check_calls(node: Node) -> list[str]:
    """화이트리스트·인자 개수·인자 타입을 본다. 오류 메시지 목록을 돌려준다."""
    errors: list[str] = []

    def walk(n: Node) -> None:
        if isinstance(n, ListNode):
            for item in n.items:
                walk(item)
            return
        if not isinstance(n, Call):
            return

        spec = FUNCTIONS.get(n.name)
        if spec is None:
            near = _suggest(n.name)
            errors.append(
                f"허용되지 않은 함수입니다: {n.name}()"
                + (f" — {near} 를 쓰려던 것 아닙니까?" if near else "")
                + f" (허용: {', '.join(sorted(FUNCTIONS))})"
            )
            for a in n.args:
                walk(a)
            return

        count = len(n.args)
        if count < spec.min_args or (spec.max_args is not None and count > spec.max_args):
            errors.append(
                f"{n.name}() 의 인자는 {spec.expected_arity()}여야 하는데 {count}개입니다"
            )

        for idx, arg in enumerate(n.args):
            walk(arg)
            expected = spec.arg_type(idx)
            actual = node_type(arg)
            if expected == "any" or actual == "any":
                continue
            if expected != actual:
                errors.append(
                    f"{n.name}() 의 {idx + 1}번째 인자는 {expected} 여야 하는데 "
                    f"{actual} 입니다"
                )

    walk(node)
    return errors


def _suggest(name: str) -> str | None:
    lowered = name.lower()
    for known in FUNCTIONS:
        if known == lowered or known.startswith(lowered[:4]) and len(lowered) >= 4:
            return f"{known}()"
    return None


def lint_calls(node: Node) -> list[str]:
    """문법은 맞지만 의도와 다를 가능성이 큰 형태 (경고).

    대표 사례는 `contains` 의 인자 뒤바뀜이다. SCHEMA §4.7.3 이 경고하는 패턴으로,
    `contains("471,507", brand_code)` 는 brand_code 가 "1" 이어도 참이 된다.
    """
    warnings: list[str] = []

    def walk(n: Node) -> None:
        if isinstance(n, ListNode):
            for item in n.items:
                walk(item)
            return
        if not isinstance(n, Call):
            return
        for a in n.args:
            walk(a)

        if n.name == "contains" and len(n.args) == 2:
            haystack, needle = n.args
            if isinstance(haystack, Literal) and isinstance(needle, Path):
                literal = str(haystack.value)
                hint = ""
                if "," in literal:
                    items = ", ".join(
                        f'"{x.strip()}"' for x in literal.split(",") if x.strip()
                    )
                    hint = f' → in({needle.dotted}, [{items}])'
                warnings.append(
                    f'contains("{literal}", {needle.dotted}) 는 부분 문자열 검사입니다. '
                    f"{needle.dotted} 가 목록 항목의 일부이기만 해도 참이 됩니다. "
                    f"코드 목록 판정이라면 in() 을 쓰세요{hint}"
                )

    walk(node)
    return warnings


def paths(node: Node) -> list[Path]:
    """식이 참조하는 컨텍스트 경로 전부 (등장 순서)."""
    out: list[Path] = []

    def walk(n: Node) -> None:
        if isinstance(n, Path):
            out.append(n)
        elif isinstance(n, ListNode):
            for item in n.items:
                walk(item)
        elif isinstance(n, Call):
            for a in n.args:
                walk(a)

    walk(node)
    return out


@dataclass
class ExprInfo:
    """검증 결과 한 덩어리."""

    source: str
    ast: Node | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    referenced_paths: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def analyze(src: str) -> ExprInfo:
    """파싱 + 화이트리스트/인자 검증을 한 번에. 참조 경로 존재 검사는 호출자 몫."""
    try:
        ast = parse(src)
    except ExprError as exc:
        return ExprInfo(source=src, errors=[str(exc)])
    return ExprInfo(
        source=src,
        ast=ast,
        errors=check_calls(ast),
        warnings=lint_calls(ast),
        referenced_paths=paths(ast),
    )
