"""검수 화면 합계 — 파일별 수량·금액 합계와 발주서 인쇄 합계 대조 (`batch_service.totals`)."""

from __future__ import annotations

from app.batch_service import totals
from app.domain.models import Batch, BatchFile, BatchRow

SPECS = {"KWMENG": {"role": "quantity"}, "PRICE": {"role": "unit_price"}, "MATNR": {}}


def _batch(**printed) -> Batch:
    def row(i, qty, price, deleted=False):
        return BatchRow(row_id=f"r{i}", file_id="f1", fields={"KWMENG": qty, "PRICE": price}, deleted=deleted)

    return Batch(
        batch_id="b", customer="X",
        files=[BatchFile(file_id="f1", name="a.pdf", status="DONE", **printed)],
        rows=[row(1, "10", "1.50"), row(2, "5", "2"), row(3, "3", ""), row(4, "100", "9", deleted=True)],
    )


def test_sums_quantity_and_amount_per_file_and_overall():
    [f, grand] = totals(_batch(), SPECS)
    assert (f["rows"], f["qty"], f["amount"], f["no_price"]) == ("3", "18", "25.00", "1")
    assert (grand["qty"], grand["amount"]) == ("18", "25.00")          # 삭제한 행은 빠진다


def test_compares_with_printed_totals():
    batch = _batch(doc_total_qty="18", doc_total_amount="1,000.00", doc_line_count="3")
    batch.rows[2].fields["PRICE"] = "1"                                # 단가가 다 있어야 금액을 대조한다
    [f, _] = totals(batch, SPECS)
    assert f["amount"] == "28.00"
    assert (f["qty_match"], f["amount_match"], f["lines_match"]) == ("true", "false", "true")


def test_no_printed_total_means_no_verdict():
    [f, _] = totals(_batch(), SPECS)
    assert (f["qty_match"], f["amount_match"]) == ("", "")


def test_amount_is_not_judged_when_some_prices_are_missing():
    batch = _batch(doc_total_amount="25.00")
    [f, _] = totals(batch, SPECS)
    assert f["amount_match"] == ""                                    # 3번 행 단가가 비었다


def test_line_count_is_not_judged_for_split_documents():
    [f, _] = totals(_batch(doc_line_count="2", doc_split=True), SPECS)
    assert f["lines_match"] == ""
