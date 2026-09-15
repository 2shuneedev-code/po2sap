"""값 변환 — SCHEMA.md §4.6 `format` · §4.7.3 의 같은 이름 함수.

`format` 은 필드 **전체**에, expr 함수는 식 **일부**에 적용된다. 동작은 같아야 하므로
구현을 한 곳에 둔다. 두 벌로 두면 조용히 어긋난다.

변환 실패는 빈값으로 넘기지 않고 예외로 올린다 — 날짜를 못 읽었는데 ""로 전송되면
사람이 눈치채지 못한 채 잘못된 오더가 만들어진다. 검증 단계가 잡아서 화면에 띄운다.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["FORMATS", "FormatError", "apply_format"]


class FormatError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지."""


_NUM_JUNK = re.compile(r"[,\s]")


def _decimal(text: str, label: str) -> Decimal:
    cleaned = _NUM_JUNK.sub("", text)
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise FormatError(f"{label}로 바꿀 수 없는 값입니다: {text}") from exc


def to_integer(text: str) -> str:
    """'25.000' · '1,250' → '25' · '1250'. 소수부가 있으면 오류."""
    value = _decimal(text, "정수")
    if value != value.to_integral_value():
        raise FormatError(f"정수가 아닙니다: {text}")
    return str(int(value))


def to_decimal3(text: str) -> str:
    """'25' → '25.000'. 전송 규약이 문자열 decimal 이라 자릿수를 고정한다."""
    return f"{_decimal(text, '수량/금액'):.3f}"


_DATE_PATTERNS = (
    re.compile(r"^(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})$"),
    re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$"),
)
_SLASH = re.compile(r"^(?P<a>\d{1,2})[-./](?P<b>\d{1,2})[-./](?P<y>\d{2}|\d{4})$")


def to_yyyymmdd(text: str) -> str:
    """날짜 원문 → 'YYYYMMDD'.

    거래처마다 표기가 다르다: '2026-05-18' · '2026.05.11' · '2/17/26'.

    **M/D 와 D/M 은 원문만으로 구분할 수 없다.** 앞자리가 12를 넘으면 일(日)로 보고,
    그렇지 않으면 월(月)로 본다 — 미국 표기 기준이다. 유럽식 D/M 을 쓰는 거래처가
    생기면 그때는 추측하지 말고 거래처 설정에 표기 순서를 선언해야 한다.
    """
    raw = (text or "").strip()
    if not raw:
        raise FormatError("날짜가 비어 있습니다")

    for pattern in _DATE_PATTERNS:
        m = pattern.match(raw)
        if m:
            return _assemble(int(m["y"]), int(m["m"]), int(m["d"]), raw)

    m = _SLASH.match(raw)
    if m:
        a, b = int(m["a"]), int(m["b"])
        year = int(m["y"])
        year += 2000 if year < 100 else 0
        month, day = (a, b) if a <= 12 else (b, a)
        return _assemble(year, month, day, raw)

    raise FormatError(f"날짜 형식을 알 수 없습니다: {text}")


def _assemble(year: int, month: int, day: int, raw: str) -> str:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise FormatError(f"날짜 범위를 벗어났습니다: {raw}")
    return f"{year:04d}{month:02d}{day:02d}"


FORMATS = {
    "integer": to_integer,
    "decimal3": to_decimal3,
    "date_yyyymmdd": to_yyyymmdd,
    "upper": lambda s: s.upper(),
    "lower": lambda s: s.lower(),
    "trim": lambda s: s.strip(),
}


def apply_format(name: str, text: str) -> str:
    """빈값은 변환하지 않는다 — 비어 있다는 사실 자체는 required 가 판단한다."""
    if not text:
        return text
    fn = FORMATS.get(name)
    if fn is None:
        raise FormatError(f"알 수 없는 format 입니다: {name}")
    return fn(text)
