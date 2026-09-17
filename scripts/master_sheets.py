"""거래처 마스터 ↔ 엑셀 — 시트 정의와 변환 규칙 한 곳.

`master_export.py`(YAML→엑셀)와 `master_import.py`(엑셀→YAML)가 이 파일을
공유한다. 컬럼 이름이 두 스크립트에 따로 적혀 있으면 한쪽만 고쳐져 값이
조용히 빈 채로 들어간다.

**표로 옮기는 것과 아닌 것**
  · 고정값 · 문서경로 · 결정표 · 브랜드 매핑  → 엑셀에서 편집한다
  · 산출식(expr) · 읽기 힌트(hints)          → YAML 이 원천. 엑셀에는 읽기전용

산출식은 로직이고 힌트는 1,500자짜리 서술이라 셀에 담으면 편집이 고역이다.
그래도 **엑셀에 보여는 준다** — 안 보이면 "엑셀에 없는 값이 어디서 나오지?"
가 된다.
"""

from __future__ import annotations

from typing import Any

# 시트 이름 — 엑셀 탭에 그대로 보인다.
S_GUIDE = "안내"
S_CUSTOMER = "거래처"
S_FIXED = "고정값"
S_DOC = "문서매핑"
S_TABLE = "결정표"
S_BRAND = "브랜드매핑"
S_EXPR = "산출식(읽기전용)"
S_HINTS = "읽기힌트(읽기전용)"

READ_ONLY = {S_EXPR, S_HINTS}

# 각 시트의 컬럼. 순서가 곧 엑셀 열 순서다.
COLUMNS: dict[str, list[str]] = {
    S_CUSTOMER: ["거래처코드", "거래처명", "고객코드", "파일형식", "담당자", "상태",
                 "오더분할", "분할설명"],
    S_FIXED:    ["거래처코드", "전송필드", "값", "확인필요(todo)", "설명"],
    S_DOC:      ["거래처코드", "전송필드", "문서경로", "형식", "필수", "대체경로"],
    S_TABLE:    ["거래처코드", "결정표", "적용범위", "조건필드", "비교", "조건값",
                 "결과필드", "결과값", "해당없음"],
    S_BRAND:    ["고객코드", "브랜드코드", "브랜드명(SAP)", "발주서 원문 문구", "비교", "비고"],
    S_EXPR:     ["거래처코드", "전송필드", "산출식", "설명"],
    S_HINTS:    ["거래처코드", "읽기 힌트"],
}

# 상태·분할·비교의 허용값. 엑셀 드롭다운과 가져오기 검증이 같이 쓴다.
ALLOWED: dict[tuple[str, str], list[str]] = {
    (S_CUSTOMER, "상태"): ["active", "draft", "disabled"],
    (S_CUSTOMER, "오더분할"): ["none", "shipment"],
    (S_BRAND, "비교"): ["contains", "equals"],
    (S_DOC, "필수"): ["Y", "N"],
}

GUIDE = [
    ("이 파일은 무엇인가", ""),
    ("", "거래처별 SAP 전송 규칙을 현업이 직접 고치는 양식입니다."),
    ("", "고친 뒤 `python scripts/master_import.py <이 파일>` 을 돌리면"),
    ("", "검증을 거쳐 masters/ 에 반영되고, 무엇이 바뀌었는지 Git 이력에 남습니다."),
    ("", ""),
    ("시트 설명", ""),
    (S_CUSTOMER, "거래처 1곳 = 1행. 여기에 없는 거래처는 화면에 안 뜹니다."),
    (S_FIXED, "발주서와 무관하게 늘 같은 값 (출하처코드·출하조건·통화 등)."),
    (S_DOC, "발주서에서 그대로 읽어오는 값. 문서경로는 표준 키입니다 (SCHEMA §3.1)."),
    (S_TABLE, "조건에 따라 값이 갈리는 경우. 위에서부터 순서대로 판정합니다."),
    (S_BRAND, "발주서에 찍힌 문구 → SAP 브랜드 코드. 행 순서가 우선순위입니다."),
    (S_EXPR, "조립식으로 만드는 값. **읽기전용** — 개발자가 YAML 에서 관리합니다."),
    (S_HINTS, "AI 에게 문서 읽는 법을 알려주는 서술. **읽기전용** — YAML 이 원천입니다."),
    ("", ""),
    ("주의", ""),
    ("", "· 회색 시트(읽기전용)를 고쳐도 반영되지 않습니다."),
    ("", "· 전송필드 이름은 masters/_base/sap_defaults.yaml 에 있는 것만 씁니다."),
    ("", "· 브랜드 코드는 그 고객에게 SAP 이 등록한 것만 됩니다 (아니면 저장이 거부됩니다)."),
    ("", "· 값을 비우면 '빈 값으로 전송'입니다. 아직 못 정했으면 확인필요 칸에 적으세요."),
]


def file_types_to_text(types: list[str]) -> str:
    return "/".join(t.strip().lower() for t in types if t and t.strip())


def text_to_file_types(text: str) -> list[str]:
    return [t.strip().lower() for t in str(text or "").replace(",", "/").split("/") if t.strip()]


def as_text(value: Any) -> str:
    """엑셀 셀 → 문자열. 엑셀이 `100249` 를 숫자로 돌려주는 것을 되돌린다.

    고객코드가 `100249.0` 이 되면 참조표 조회가 전부 빗나간다.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
