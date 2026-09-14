"""골든 테스트 — LLM 호출 없이 관통 동작을 고정한다.

이 테스트가 통과한다는 것은 **새 클론에서 API 키 없이 전 파이프라인이 돈다**는 뜻이다
(design.md §9 "오프라인 · CI 비용 0"의 실제 근거).

픽스처는 합성 문서다. 실물 발주서는 대외비라 커밋하지 않는다(CONTRIBUTING §1.1).
실물로 검증할 때는 LLM_PROVIDER=anthropic 으로 1회 파싱해 런타임 캐시를 채운 뒤
같은 방식으로 재생한다.
"""

from __future__ import annotations

import json

import pytest
from app.config import Settings
from app.extraction import Extractor

SAMPLE = "PO-SAMPLE-0001.htm"
CUSTOMER = "MSC"


@pytest.fixture(scope="module")
def result(fixtures_dir):
    return Extractor(Settings(llm_provider="mock")).parse_file(
        fixtures_dir / "msc" / SAMPLE, CUSTOMER
    )


def test_parses_without_api_key(result):
    assert result.cached is True
    assert result.provider == "fixture"


def test_no_validation_issues(result):
    assert result.error_count == 0, [i.model_dump() for i in result.issues]
    assert result.warn_count == 0


def test_splits_into_one_order_per_shipment(result):
    raw = result.raw
    assert raw.is_split
    assert len(raw.shipments) == 2
    assert [s.receiving_loc.value for s in raw.shipments] == ["ELK", "HAR"]


def test_summary_table_is_not_an_order(result):
    """상단 요약표는 합계 대조용 — 오더 품목이 되면 수량이 두 배가 된다."""
    raw = result.raw
    assert len(raw.lines) == 2
    assert len(raw.all_lines) == 2
    assert [ln.item_code.value for ln in raw.all_lines] == ["YG-EM0600", "YG-DR0800"]


def test_item_columns_are_not_swapped(result):
    """MSC 는 Our/Your 가 우리와 반대다 (SCHEMA §3.1). 뒤집히면 MATNR 이 오염된다."""
    first = result.raw.all_lines[0]
    assert first.item_code.value == "YG-EM0600"     # 우리 YG 품번 → MATNR
    assert first.our_item.value == "09876543"       # MSC 품번 → 참조표 키


def test_matches_golden(result, fixtures_dir):
    golden = json.loads(
        (fixtures_dir / "golden" / "msc__PO-SAMPLE-0001.json").read_text(encoding="utf-8")
    )
    assert result.raw.model_dump() == golden
