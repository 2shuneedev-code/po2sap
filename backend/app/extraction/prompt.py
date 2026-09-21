"""추출용 프롬프트.

공통 시스템 프롬프트는 전 거래처 동일(캐싱 대상)하고,
거래처별 차이는 masters/customers/{code}.yaml 의 extraction.hints 로만 주입한다.
→ 거래처 추가 시 코드를 건드리지 않는다.

호출은 패스마다 다르다 (design.md §3.3.2).
  · OUTLINE  `build_outline_prompt` — 골격만. 품목은 읽지 않는다
  · LINES    `build_lines_prompt`   — 구간 하나의 품목만
  · SINGLE   `build_scan_prompt`    — 스캔본. 문서 1건을 한 번에 (줄 번호가 없어 나눌 수 없다,
                                      design.md §3.3.6)
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
당신은 제조업 발주서(Purchase Order) 판독 전문가입니다.
PDF/HTML 발주서에서 정보를 정확히 추출해 구조화하는 것이 임무입니다.

# 절대 규칙

1. **원문에 있는 값만 추출한다.** 추측하거나 만들어내지 않는다.
   찾을 수 없으면 **그 필드를 응답에서 생략한다.** null·빈 문자열·임의의 값을 넣지 않는다.

2. **모든 값에 src(근거 줄 번호)를 붙인다.**
   원문의 각 줄 앞에는 `L000123|` 형식의 줄 번호가 붙어 있다.
   그 값이 적힌 줄의 **숫자를 그대로 복사**한다 (`L000123|` → 123). 직접 세지 않는다.
   값이 여러 줄에 걸치면 src 와 src_end 로 구간을 준다.
   이 번호는 시스템이 그 줄의 원문과 값을 자동 대조한다.

3. **코드로 변환하지 않는다.**
   브랜드명, 출하처 주소 등은 **원문 문구 그대로** 담는다.
   예: "INTERSTATE" 를 숫자 코드로 바꾸지 않는다. "ELKHART" 를 고객코드로 바꾸지 않는다.
   코드 변환은 시스템의 별도 규칙엔진이 담당한다.

4. **품목을 빠뜨리지 않는다.**
   여러 페이지에 걸친 표, 페이지마다 반복되는 머리글에 주의한다.
   발주서에 인쇄된 합계(총 수량/총 금액/품목 수)가 있으면 totals 에 담는다.
   이 값은 누락 검증에 쓰인다.

5. **숫자는 순수한 숫자 문자열로.**
   천단위 쉼표를 제거한다. 통화기호를 붙이지 않는다. 예: "1,250.00" → "1250.00"

6. **날짜는 YYYY-MM-DD 로 정규화한다.**
   원문이 애매하면(예: 03/04/2026) 문서의 다른 날짜 표기나 지역을 보고 판단하고,
   그래도 애매하면 confidence 를 낮게 준다.

7. **단가와 합계금액을 혼동하지 않는다.**
   Unit Price / 단가 컬럼을 unit_price 에 넣는다.
   Extended / Amount / 합계 컬럼이 아니다.

8. **confidence 를 정직하게 매긴다.**
   확실하면 0.95 이상, 애매하면 0.7 이하. 사람이 우선 검토할 항목을 고르는 데 쓰인다.
"""


def _head(customer_name: str, hints: str | None) -> list[str]:
    parts = [f"# 거래처\n{customer_name}"]
    if hints and hints.strip():
        parts.append(f"# 이 거래처 발주서의 특징 (반드시 반영할 것)\n{hints.strip()}")
    return parts


def build_scan_prompt(*, customer_name: str, hints: str | None) -> str:
    """스캔본(텍스트 레이어 없음) — 첨부된 PDF 를 한 번에 판독시킨다 (design.md §3.3.6).

    이 문서에는 줄 번호가 없다. 시스템 프롬프트의 "src 를 붙인다"는 규칙이 이 호출에는
    해당하지 않음을 여기서 분명히 한다 — 도구 스키마에도 `src` 가 없고 `page` 가 대신 있다.
    """
    parts = _head(customer_name, hints)
    parts.append("# 발주서\n첨부된 문서를 판독하세요.")
    parts.append(
        "위 발주서를 판독해 제공된 도구로 결과를 반환하세요.\n"
        "- 이 문서에는 줄 번호가 없습니다. **src 대신 page(그 값이 있는 PDF 페이지 번호, 1부터)** 를 "
        "모든 값과 품목에 붙이세요.\n"
        "- 모든 품목을 빠짐없이 포함하세요."
    )
    return "\n\n".join(parts)


def build_outline_prompt(
    customer_name: str,
    hints: str | None,
    document_text: str,
    *,
    include_shipments: bool = False,
) -> str:
    """OUTLINE 호출 — 품목을 빼고 골격만 읽힌다 (design.md §3.3.2).

    `document_text` 는 `SourceDoc.numbered_text()` 전체다.
    """
    parts = _head(customer_name, hints)
    parts.append(f"# 발주서 원문\n\n{document_text}")

    if include_shipments:
        boundary = (
            "출하처 블록마다 shipments 에 1건씩 담고, 각 블록의 src~src_end 는 "
            "그 블록의 **품목표 마지막 줄까지** 잡으세요. "
            "블록끼리 겹치거나 빠진 줄이 없어야 합니다."
        )
    else:
        boundary = "품목표가 있는 구간을 line_range 로 알려주세요 (첫 품목 줄 ~ 마지막 품목 줄)."

    parts.append(
        "위 발주서의 **골격만** 판독해 제공된 도구로 반환하세요.\n"
        "- **품목은 한 줄도 읽지 마세요.** 품목은 다음 단계에서 구간별로 따로 읽습니다.\n"
        "- 문서 상단의 요약 품목표도 품목으로 읽지 말고, 인쇄된 합계(품목 수·총 수량·총 금액)만 "
        "totals 에 담으세요.\n"
        f"- {boundary}\n"
        "- 모든 값에 근거 줄 번호(src)를 붙이세요."
    )
    return "\n\n".join(parts)


def build_lines_prompt(
    customer_name: str,
    hints: str | None,
    header_excerpt: str,
    chunk_text: str,
    start: int,
    end: int,
) -> str:
    """LINES 호출 — 구간 하나의 품목만 읽힌다 (design.md §3.3.2).

    `chunk_text` 는 `SourceDoc.numbered_text(start, end)` 다. 번호는 문서 통번호 그대로다.
    `header_excerpt` 는 표 머리글·컬럼을 이해하기 위한 문맥이며 품목을 읽는 대상이 아니다.
    """
    parts = _head(customer_name, hints)
    if header_excerpt and header_excerpt.strip():
        parts.append(
            "# 문서 앞머리 (표 머리글·컬럼 이해용 문맥 — **여기서 품목을 읽지 마세요**)\n\n"
            f"{header_excerpt}"
        )
    parts.append(f"# 읽을 구간: L{start:06d} ~ L{end:06d}\n\n{chunk_text}")
    parts.append(
        f"위 **L{start:06d} ~ L{end:06d} 구간의 품목만** 판독해 제공된 도구로 반환하세요.\n"
        "- 이 구간 밖의 줄은 참조하지 마세요. src 는 반드시 이 구간 안의 번호여야 합니다.\n"
        "- 구간의 모든 품목을 빠짐없이 포함하세요. 품목이 없으면 빈 배열을 반환하세요.\n"
        "- 품목마다 그 품목이 적힌 줄 번호(src)와 confidence 를 붙이고, "
        "원문에 없는 필드는 키를 생략하세요.\n"
        "- 헤더·합계는 반환하지 마세요."
    )
    return "\n\n".join(parts)
