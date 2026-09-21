"""통화 원문 → ISO 3자리 (refs/currency.csv).

왜 규칙이 필요한가 — `WAERK` 는 SAP 코드 필드(max_len 5)인데 발주서에는
"United States Dollars"(21자) 같은 문장이 적혀 있다. 그대로 넣으면 길이
초과로 🔴 가 떠서 **전송이 통째로 막힌다** (2026-09-21 실제로 확인).

여기서 지키려는 것은 정확도보다 **오판 방지**다. 참조표는 위에서부터
순서대로 보므로(SCHEMA §4.5), "Canadian Dollar" 가 "United States Dollar"
보다 **위에** 있어야 캐나다 달러가 USD 로 넘어가지 않는다. 순서가 뒤집히면
조용히 틀린 통화가 SAP 으로 간다 — 검수자가 알아채기 어려운 종류다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from app.rules.context import EvalContext
from app.rules.mapping_rules import evaluate_rule

TABLE = "refs/currency.csv"

RULE = {
    "kind": "csv_map",
    "source": "header.currency_text",
    "table_file": TABLE,
    "key_column": "text",
    "value_column": "waerk",
    "mode_column": "match",
    "case_insensitive": True,
    "on_no_match": {"action": "warn", "message": "통화를 인식하지 못했습니다"},
}


def convert(text: str, masters_dir: Path):
    ctx = EvalContext(header={"currency_text": text})
    return evaluate_rule("currency", RULE, ctx, masters_dir)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("United States Dollars", "USD"),
        ("U.S. Dollar", "USD"),
        ("US Dollars", "USD"),
        ("USD", "USD"),
        ("usd", "USD"),                      # 대소문자 무시
        ("Japanese Yen", "JPY"),
        ("JPY", "JPY"),
        ("Euro", "EUR"),
        ("Korean Won", "KRW"),
        ("Pound Sterling", "GBP"),
    ],
)
def test_known_currencies_convert(text: str, expected: str, masters_dir: Path) -> None:
    out = convert(text, masters_dir)
    assert out.matched and out.value == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Canadian Dollars", "CAD"),
        ("Australian Dollar", "AUD"),
        ("Singapore Dollars", "SGD"),
        ("Hong Kong Dollar", "HKD"),
        ("New Taiwan Dollars", "TWD"),
    ],
)
def test_other_dollars_do_not_become_usd(text: str, expected: str, masters_dir: Path) -> None:
    """**가장 중요한 검사.** 'Dollar' 만 보고 USD 로 넘기면 조용히 틀린다."""
    out = convert(text, masters_dir)
    assert out.value == expected, f"{text} 가 {out.value} 로 판정됐다"
    assert out.value != "USD"


def test_unknown_currency_warns_and_stays_empty(masters_dir: Path) -> None:
    """모르는 통화를 **추측해 채우지 않는다.** 빈 칸은 눈에 띄고 전송은 열려 있다."""
    out = convert("Thai Baht", masters_dir)
    assert not out.matched
    assert out.value == ""
    assert out.severity == "warn"           # 🔴 가 아니다 — 전송을 막지 않는다


def test_every_code_is_three_letters(masters_dir: Path) -> None:
    """SAP `WAERK` 는 ISO 4217 세 자리다. 길이가 틀리면 SAP 이 거부한다."""
    rows = _rows(masters_dir)
    bad = [r for r in rows if len(r["waerk"]) != 3 or not r["waerk"].isupper()]
    assert bad == [], f"ISO 3자리 대문자가 아닌 행: {bad}"


def test_other_dollars_sit_above_usd(masters_dir: Path) -> None:
    """**행 순서가 곧 판정 우선순위다.** 이 순서가 뒤집히면 위 테스트가 조용히
    통과하다 어느 날 캐나다 달러가 USD 로 나간다. 순서 자체를 고정한다."""
    codes = [r["waerk"] for r in _rows(masters_dir)]
    first_usd = codes.index("USD")
    for code in ("CAD", "AUD", "SGD", "HKD", "TWD"):
        assert codes.index(code) < first_usd, f"{code} 가 USD 보다 아래에 있다"


def _rows(masters_dir: Path) -> list[dict[str, str]]:
    with (masters_dir / TABLE).open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
