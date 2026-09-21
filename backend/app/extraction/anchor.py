"""앵커 대조 — `src` 줄의 원문에서 `value` 를 실제로 찾는다 (design.md §3.4).

예전에는 "모델이 준 evidence 문자열이 원문 **어딘가**에 있는가"를 봤다. 모델이
아무 데서나 그럴듯한 문장을 베껴 붙여도 통과했다 — 값과 근거가 묶여 있지 않았다.
지금은 모델이 준 **줄 번호의 원문**에서 값을 찾는다. 값을 지어내면 그 줄에 없으므로
반드시 걸린다.

다만 `value` 는 정규화된 값이라(날짜 `2/17/26` → `2026-02-17`, 수량 `1,250.00` → `1250`)
글자 그대로는 안 맞는다. 그래서 판정 사다리를 위에서부터 내려간다.

  exact    공백·대소문자 정규화 후 포함              통과
  numeric  양쪽을 Decimal 로 읽어 수치 비교           통과
  date     value 를 그 줄에 나올 법한 표기들로 되돌려 대조  통과
  fuzzy    토큰 겹침 비율이 임계 이상                 🟡 경고
  miss     그 밖                                      🔴 오류

**날짜 되돌리기에 실패하면 miss 가 아니라 fuzzy** 다. 지역별 표기는 다양해서 우리가
못 만들어 본 형식이 얼마든지 있고, 멀쩡한 값을 🔴 로 막으면 사람이 경고를 무시하기
시작한다.

이 모듈은 판정만 한다. 어느 줄을 넘길지·어떤 수준의 이슈로 올릴지는 grounding 의 몫이다.
"""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from .preprocess import normalize_ws

# 토큰 겹침 비율 임계. 두 토큰짜리 값에서 한 토큰만 맞으면(0.5) 미달이다.
FUZZY_MIN_RATIO = 0.6


class AnchorResult(StrEnum):
    EXACT = "exact"
    NUMERIC = "numeric"
    DATE = "date"
    FUZZY = "fuzzy"
    MISS = "miss"

    @property
    def passed(self) -> bool:
        """이슈 없이 통과하는 판정인가 (exact · numeric · date)."""
        return self in (AnchorResult.EXACT, AnchorResult.NUMERIC, AnchorResult.DATE)


def locate(value: str | None, source_text: str) -> AnchorResult:
    """`source_text`(= `src` 줄들의 원문) 안에서 `value` 를 찾는다.

    빈 값은 대조할 것이 없으므로 MISS 다 — 호출자가 빈 값을 걸러 넘기는 것이 정상이다.
    """
    needle = normalize_ws(value or "").lower()
    hay = normalize_ws(source_text or "").lower()
    if not needle or not hay:
        return AnchorResult.MISS

    if _exact(needle, hay):
        return AnchorResult.EXACT

    number = _parse_number(needle)
    if number is not None and number in _numbers_in(hay):
        return AnchorResult.NUMERIC

    day = _parse_date(needle)
    if day is not None:
        # 날짜인 것이 분명한 값은 표기를 못 만들어도 miss 로 떨구지 않는다.
        return AnchorResult.DATE if _date_in(day, hay) else AnchorResult.FUZZY

    if _token_overlap(needle, hay) >= FUZZY_MIN_RATIO:
        return AnchorResult.FUZZY
    return AnchorResult.MISS


# ── exact ──────────────────────────────────────────────────────────────
def _exact(needle: str, hay: str) -> bool:
    """포함 검사. 단, 숫자로 시작·끝나는 값은 **이웃 숫자를 침범하지 않아야** 한다.

    그냥 포함만 보면 수량 `5` 가 줄의 `15` 안에서 찾아져 통과한다 — 수량 오독을
    걸러야 할 자리에서 가장 흔한 사고다. `1,250` 안의 `1` · `10.5` 안의 `10` 도 같다.
    문자가 이웃한 것(`10EA`)은 침범으로 보지 않는다.
    """
    pattern = ""
    if needle[0].isdigit():
        pattern += r"(?<!\d)(?<!\d[.,])"
    pattern += re.escape(needle)
    if needle[-1].isdigit():
        pattern += r"(?!\d)(?![.,]\d)"
    return re.search(pattern, hay) is not None


# ── numeric ────────────────────────────────────────────────────────────
_NUMBER_VALUE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_NUMBER_RUN = re.compile(r"\d[\d.,]*\d|\d")
_CURRENCY = re.compile(r"[\s,$€¥£₩]")


def _parse_number(text: str) -> Decimal | None:
    """값 전체가 숫자일 때만 Decimal(절댓값). 부호는 대조에서 무시한다."""
    cleaned = _CURRENCY.sub("", text)
    if not _NUMBER_VALUE.fullmatch(cleaned):
        return None
    try:
        return abs(Decimal(cleaned))
    except InvalidOperation:
        return None


def _numbers_in(hay: str) -> set[Decimal]:
    """줄에 적힌 숫자 덩어리를 가능한 해석 전부로 읽는다.

    `1,250.00` 과 유럽식 `1.250,00` · `12,50` 을 모두 받아들인다 — 어느 쪽으로
    읽어도 값과 같으면 그 줄에 있다고 본다. 부호는 무시한다 (`YG-0600` 의 `-` 가
    음수가 되면 안 된다).
    """
    out: set[Decimal] = set()

    def add(s: str) -> None:
        with suppress(InvalidOperation):
            out.add(Decimal(s))

    for run in _NUMBER_RUN.findall(hay):
        add(run.replace(",", ""))                          # 1,250.00 · 12.50 · 1250
        if "," in run:
            add(run.replace(".", "").replace(",", "."))    # 1.250,00 · 12,50
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", run):
            add(run.replace(".", ""))                      # 1.250 (천 단위 점)
    return out


# ── date ───────────────────────────────────────────────────────────────
_DATE_VALUE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{4})(\d{2})(\d{2})")
_ORDINAL = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b")

# 로케일에 기대지 않는다 — strftime("%b") 는 한국어 윈도우에서 다른 글자를 낸다.
_MONTHS = (
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may", "may"), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "september", "sept"), ("oct", "october"), ("nov", "november"),
    ("dec", "december"),
)


def _parse_date(text: str) -> date | None:
    """`YYYY-MM-DD` · `YYYY/MM/DD` · `YYYY.MM.DD` · `YYYYMMDD` 로 쓰인 유효한 날짜만."""
    m = _DATE_VALUE.fullmatch(text)
    if not m:
        return None
    parts = [g for g in m.groups() if g is not None]
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _date_forms(d: date) -> set[str]:
    """그 날짜가 문서에 적혀 있을 법한 표기 전부 (소문자).

    월/일 순서는 미국식(M/D)·유럽식(D/M)·동아시아식(Y/M/D)을 모두 만든다. 어느 쪽인지
    가리는 것은 이 모듈의 일이 아니다 — 그 줄에 **그 날짜로 읽힐 표기가 있는가**만 본다.
    """
    y, m, dd = d.year, d.month, d.day
    yy = y % 100
    forms: set[str] = set()

    for sep in ("/", "-", "."):
        for ys in (str(y), f"{yy:02d}"):
            for ms in (str(m), f"{m:02d}"):
                for ds in (str(dd), f"{dd:02d}"):
                    forms.add(f"{ms}{sep}{ds}{sep}{ys}")     # M/D/Y
                    forms.add(f"{ds}{sep}{ms}{sep}{ys}")     # D/M/Y
                    forms.add(f"{ys}{sep}{ms}{sep}{ds}")     # Y/M/D

    forms |= {
        f"{y}{m:02d}{dd:02d}", f"{yy:02d}{m:02d}{dd:02d}",   # YYYYMMDD · YYMMDD
        f"{m:02d}{dd:02d}{y}", f"{m:02d}{dd:02d}{yy:02d}",   # MMDDYYYY · MMDDYY
        f"{dd:02d}{m:02d}{y}", f"{dd:02d}{m:02d}{yy:02d}",   # DDMMYYYY · DDMMYY
    }

    for name in _MONTHS[m - 1]:
        for ds in (str(dd), f"{dd:02d}"):
            for ys in (str(y), f"{yy:02d}"):
                forms |= {
                    f"{ds}-{name}-{ys}", f"{ds} {name} {ys}", f"{ds}{name}{ys}",
                    f"{ds}/{name}/{ys}", f"{ds}. {name} {ys}",
                    f"{name} {ds}, {ys}", f"{name} {ds},{ys}", f"{name} {ds} {ys}",
                    f"{name}-{ds}-{ys}", f"{name}/{ds}/{ys}",
                }
    return forms


def _date_in(d: date, hay: str) -> bool:
    # 월 표기 뒤의 서수(1st · 2nd · 3rd · 4th)는 걷어낸다: "march 10th, 2026"
    hay = _ORDINAL.sub("", hay)
    forms = sorted(_date_forms(d), key=len, reverse=True)
    # 앞뒤가 영숫자·슬래시로 이어지면 다른 날짜의 일부다 ("12/17/26" 안의 "2/17/26").
    pattern = r"(?<![\w/])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![\w/])"
    return re.search(pattern, hay) is not None


# ── fuzzy ──────────────────────────────────────────────────────────────
_TOKEN = re.compile(r"\w+")


def _token_overlap(needle: str, hay: str) -> float:
    """값의 토큰 중 줄에도 있는 것의 비율."""
    want = set(_TOKEN.findall(needle))
    if not want:
        return 0.0
    have = set(_TOKEN.findall(hay))
    return len(want & have) / len(want)
