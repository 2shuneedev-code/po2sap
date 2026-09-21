"""업로드 파일 전처리: PDF/HTM → 정규화 텍스트.

세 가지 목적이 있다.
  1) LLM 입력 생성
  2) **줄 번호 앵커(`src`)의 기준 제공** — 전 줄에 문서 통번호를 붙여 보내고,
     모델이 돌려준 번호로 그 줄의 원문을 다시 꺼낸다 (design.md §3.3.5).
  3) **근거 검증용 원문 확보** — LLM이 만들어낸 값이 실제 원문에 있는지 대조하려면,
     우리 손에 원문 텍스트가 있어야 한다 (design.md §3.4).

PDF에 텍스트 레이어가 없으면(스캔본) 텍스트 경로로는 처리할 수 없으므로
document(이미지) 경로로 전환하도록 kind 를 표시한다.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

# 텍스트 레이어 유무 판정 기준 (페이지당 평균 문자 수)
_MIN_CHARS_PER_PAGE = 40


@dataclass
class SourceDoc:
    filename: str
    ext: str                       # "pdf" | "htm"
    pages: list[str] = field(default_factory=list)
    has_text_layer: bool = True
    raw_bytes: bytes | None = None  # 스캔본 PDF를 그대로 LLM에 넘길 때 사용

    @property
    def full_text(self) -> str:
        return "\n".join(self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    # ── 줄 번호 (design.md §3.3.5) ─────────────────────────────────────
    # 번호와 줄은 1:1 이다. 페이지 머리글(`===== PAGE k =====`)도 한 줄을 차지하고,
    # 빈 줄도 한 줄이다. 그래야 번호만 보고 `line_at` · `page_of` 로 되짚을 수 있다.
    # `pages` 를 바꾸면 이 캐시는 낡는다 — 로드 후 고치지 않는 값으로 다룬다.
    @cached_property
    def _numbered(self) -> tuple[list[str], list[int]]:
        lines: list[str] = []
        starts: list[int] = []          # 각 페이지 머리글의 0-기준 줄 위치
        for idx, page in enumerate(self.pages, start=1):
            starts.append(len(lines))
            lines.append(f"===== PAGE {idx} =====")
            lines.extend(page.split("\n"))
        return lines, starts

    @property
    def doc_lines(self) -> list[str]:
        """번호를 뗀 문서 줄 목록. `doc_lines[n - 1]` 이 n 번 줄이다."""
        return self._numbered[0]

    @property
    def line_count(self) -> int:
        return len(self.doc_lines)

    def line_at(self, n: int) -> str | None:
        """n 번 줄(1-기준)의 내용. 범위 밖이면 None."""
        if 1 <= n <= self.line_count:
            return self.doc_lines[n - 1]
        return None

    def slice_text(self, start: int, end: int) -> str:
        """start~end 줄(양끝 포함)의 원문. **번호를 붙이지 않는다.**

        앵커 대조용이다. 범위는 문서 안으로 잘라 준다.
        """
        lo, hi = max(start, 1), min(end, self.line_count)
        return "\n".join(self.doc_lines[lo - 1:hi]) if lo <= hi else ""

    def numbered_text(self, start: int | None = None, end: int | None = None) -> str:
        """`L000123| 내용` 형식의 LLM 입력용 텍스트.

        start·end 를 주면 그 구간(양끝 포함)만 돌려주되 **번호는 문서 통번호 그대로**다.
        슬라이스는 번호를 다시 매기지 않는다 — OUTLINE 이 말한 412 와 LINES 청크가
        말한 412 가 같은 줄이어야 한다.
        """
        lo = 1 if start is None else max(start, 1)
        hi = self.line_count if end is None else min(end, self.line_count)
        return "\n".join(
            f"L{n:06d}| {self.doc_lines[n - 1]}" for n in range(lo, hi + 1)
        )

    def page_of(self, n: int) -> int | None:
        """n 번 줄이 속한 페이지(1-기준). 범위 밖이면 None.

        페이지는 모델에게 묻지 않고 `src` 로부터 코드가 역산한다 (SCHEMA.md §3.2).
        """
        if not 1 <= n <= self.line_count:
            return None
        return bisect_right(self._numbered[1], n - 1)


def normalize_ws(text: str) -> str:
    """공백 정규화 — 근거 대조 시 원문/추출값의 공백 차이를 흡수한다."""
    return re.sub(r"\s+", " ", text or "").strip()


def load_document(path: str | Path) -> SourceDoc:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {p}")

    ext = p.suffix.lower().lstrip(".")
    if ext == "pdf":
        return _load_pdf(p)
    if ext in {"htm", "html"}:
        return _load_htm(p)
    raise ValueError(f"지원하지 않는 파일 형식입니다: .{ext} (pdf, htm 만 지원)")


# ── PDF ────────────────────────────────────────────────────────────────
def _load_pdf(p: Path) -> SourceDoc:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(p) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
            pages.append(text.strip())

    total_chars = sum(len(t) for t in pages)
    has_text = bool(pages) and (total_chars / max(len(pages), 1)) >= _MIN_CHARS_PER_PAGE

    return SourceDoc(
        filename=p.name,
        ext="pdf",
        pages=pages,
        has_text_layer=has_text,
        raw_bytes=p.read_bytes(),
    )


# ── HTM ────────────────────────────────────────────────────────────────
def _load_htm(p: Path) -> SourceDoc:
    from bs4 import BeautifulSoup

    raw = p.read_bytes()
    html = _decode_html(raw)
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()

    # 표는 구조가 곧 의미이므로 "셀 | 셀" 형태로 보존한다.
    # (평문으로 뭉개면 품목 라인이 붙어버려 LLM이 열을 오인한다)
    for table in soup.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [
                normalize_ws(td.get_text(" ", strip=True))
                for td in tr.find_all(["td", "th"])
            ]
            if any(cells):
                lines.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(lines) + "\n")

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return SourceDoc(
        filename=p.name,
        ext="htm",
        pages=[text],
        has_text_layer=bool(text.strip()),
        raw_bytes=raw,
    )


def _decode_html(raw: bytes) -> str:
    """거래처 HTM은 인코딩이 제각각이다. 순서대로 시도한다."""
    for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
