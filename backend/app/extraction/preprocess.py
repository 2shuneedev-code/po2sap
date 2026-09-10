"""업로드 파일 전처리: PDF/HTM → 정규화 텍스트.

두 가지 목적이 있다.
  1) LLM 입력 생성
  2) **근거(evidence) 검증용 원문 확보** — LLM이 만들어낸 값이 실제 원문에
     있는지 대조하려면, 우리 손에 원문 텍스트가 있어야 한다.

PDF에 텍스트 레이어가 없으면(스캔본) 텍스트 경로로는 처리할 수 없으므로
document(이미지) 경로로 전환하도록 kind 를 표시한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

    def numbered_text(self) -> str:
        """페이지 번호를 붙인 LLM 입력용 텍스트."""
        chunks = []
        for idx, page in enumerate(self.pages, start=1):
            chunks.append(f"===== PAGE {idx} =====\n{page}")
        return "\n\n".join(chunks)


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
