"""덮어쓰기 전 사본 — 되돌릴 수단이 있는가.

브랜드 매핑은 현업이 몇 달에 걸쳐 채우고 되돌리기 버튼이 없다. Git 동기화는
네트워크·계정에 기대지만 이 사본은 아무것도 필요 없이 항상 돈다. 그래서
여기가 마지막 안전망이고, 조용히 안 도는 일이 없어야 한다.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.masters import backup
from app.masters import brands as brand_store


def _keys_file(masters: Path) -> Path:
    return masters / brand_store.KEYS_FILE


def _seed(masters: Path, rows: list[tuple[str, str, str]]) -> None:
    path = _keys_file(masters)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=brand_store.KEY_COLUMNS)
        w.writeheader()
        for kunnr, zbrand, text in rows:
            w.writerow({"kunnr": kunnr, "zbrand": zbrand, "match": "contains",
                        "text": text, "note": ""})


def test_snapshot_keeps_the_previous_content(tmp_path: Path) -> None:
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    _seed(masters, [("100249", "B1", "예전문구")])

    kept = backup.snapshot(_keys_file(masters), storage)

    assert kept is not None
    assert "예전문구" in kept.read_text(encoding="utf-8")
    assert kept.parent == backup.backup_dir(storage)


def test_first_save_has_nothing_to_back_up(tmp_path: Path) -> None:
    """파일이 아직 없으면 남길 것이 없다 — 오류가 아니다."""
    assert backup.snapshot(tmp_path / "masters" / brand_store.KEYS_FILE,
                           tmp_path / "storage") is None


def test_same_second_saves_do_not_overwrite_each_other(tmp_path: Path) -> None:
    """같은 초에 두 번 저장해도 앞의 사본이 사라지지 않는다."""
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    _seed(masters, [("100249", "B1", "첫번째")])
    first = backup.snapshot(_keys_file(masters), storage)
    _seed(masters, [("100249", "B1", "두번째")])
    second = backup.snapshot(_keys_file(masters), storage)

    assert first != second
    assert "첫번째" in first.read_text(encoding="utf-8")
    assert "두번째" in second.read_text(encoding="utf-8")


def test_prune_keeps_the_newest(tmp_path: Path) -> None:
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    _seed(masters, [("100249", "B1", "값0")])
    for i in range(5):
        _seed(masters, [("100249", "B1", f"값{i}")])
        backup.snapshot(_keys_file(masters), storage, keep=3)

    left = backup.history(_keys_file(masters), storage)
    assert len(left) == 3
    assert "값4" in left[0].read_text(encoding="utf-8")   # 최신순


def test_keep_zero_never_prunes(tmp_path: Path) -> None:
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    _seed(masters, [("100249", "B1", "값")])
    for _ in range(4):
        backup.snapshot(_keys_file(masters), storage, keep=0)
    assert len(backup.history(_keys_file(masters), storage)) == 4


def test_set_keys_backs_up_before_overwriting(tmp_path: Path) -> None:
    """**운영 경로의 핵심.** storage_dir 을 주면 덮어쓰기 전에 사본이 남는다."""
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    (masters / "refs").mkdir(parents=True)
    # value_check 를 지나려면 그 코드가 SAP 마스터에 있어야 한다
    (masters / brand_store.MASTER_FILE).write_text(
        "kunnr,zbrand,zbrant,name1\n100249,B1,브랜드1,고객\n", encoding="utf-8",
    )
    _seed(masters, [("100249", "B1", "예전문구")])

    brand_store.set_keys(
        masters, "100249", "B1",
        [brand_store.BrandKey(kunnr="100249", zbrand="B1", match="contains", text="새문구")],
        storage_dir=storage,
    )

    assert "새문구" in _keys_file(masters).read_text(encoding="utf-8")
    saved = backup.history(_keys_file(masters), storage)
    assert len(saved) == 1
    assert "예전문구" in saved[0].read_text(encoding="utf-8")


def test_set_keys_without_storage_dir_writes_but_keeps_no_copy(tmp_path: Path) -> None:
    """사본은 선택이다 — 테스트·스크립트 경로까지 storage 를 요구하지 않는다."""
    masters, storage = tmp_path / "masters", tmp_path / "storage"
    (masters / "refs").mkdir(parents=True)
    (masters / brand_store.MASTER_FILE).write_text(
        "kunnr,zbrand,zbrant,name1\n100249,B1,브랜드1,고객\n", encoding="utf-8",
    )
    _seed(masters, [("100249", "B1", "예전문구")])

    brand_store.set_keys(
        masters, "100249", "B1",
        [brand_store.BrandKey(kunnr="100249", zbrand="B1", match="contains", text="새문구")],
    )
    assert backup.history(_keys_file(masters), storage) == []


def test_tests_never_write_into_the_real_storage_dir(root: Path) -> None:
    """conftest 의 격리가 살아 있는가.

    테스트는 보통 마스터만 사본으로 갈아끼우고 `storage_dir` 은 그대로 둔다.
    그 상태로 저장 경로를 타면 **저장소의 진짜 storage/ 에 사본이 쌓인다**
    (2026-09-21 에 10개가 쌓인 걸 발견했다). 격리가 풀리면 여기서 걸린다.
    """
    from app.config import Settings

    assert Settings().storage_dir.resolve() != (root / "storage").resolve()
