"""SAP 브랜드 마스터 재추출본 반영 — 매핑을 깨뜨리면 쓰지 않는다.

`brand_master.csv` 는 SAP 원본이라 통째로 갈아끼운다. 그냥 덮어쓰면, 지금
`brand_keys.csv` 가 매핑해 둔 코드가 새 목록에서 빠졌을 때 그 거래처 발주서가
브랜드 판정에 실패한다 — 그것도 **다음 발주서가 들어올 때에야** 알게 된다.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "import_brand_master.py"


@pytest.fixture
def workspace(tmp_path, masters_dir, monkeypatch):
    dst = tmp_path / "masters"
    shutil.copytree(masters_dir, dst)
    return dst


def run(workspace: Path, export: Path, *args: str) -> subprocess.CompletedProcess:
    """**항상 사본을 가리킨다.** 가드가 깨졌을 때 실물 참조표가 망가지면 안 된다."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(export), "--masters", str(workspace), *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def write_export(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """SAP 추출기가 뱉는 모양 — 컬럼에 테이블 별칭이 붙어 있다."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["A~KUNNR", "B~NAME1", "A~ZBRAND", "C~ZBRANT"])
        w.writerows(rows)


def current_master(workspace: Path) -> list[dict]:
    path = workspace / "refs" / "brand_master.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def current_keys(workspace: Path) -> list[dict]:
    path = workspace / "refs" / "brand_keys.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_table_aliases_are_stripped(tmp_path, workspace):
    """`A~KUNNR` 의 별칭은 추출 조건마다 달라진다 — 이름만 본다."""
    export = tmp_path / "sap.csv"
    write_export(export, [("100249", "SID TOOL", "38", "HERTEL BRAND")])
    result = run(workspace, export, "--dry-run")
    # 한 줄짜리 추출본이라 매핑은 당연히 깨진다 — 여기서 보는 건 **컬럼을 읽었는가**다.
    assert "필요한 컬럼이 없습니다" not in result.stdout
    assert "신규      1행" in result.stdout


def test_missing_column_is_refused(tmp_path, workspace):
    export = tmp_path / "sap.csv"
    with export.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["A~KUNNR", "A~ZBRAND"], ["100249", "38"]])
    result = run(workspace, export, "--dry-run")
    assert result.returncode != 0
    assert "필요한 컬럼이 없습니다" in (result.stdout + result.stderr)


def test_refuses_when_a_live_mapping_would_break(tmp_path, workspace):
    """★ 지금 매핑된 코드가 새 목록에 없으면 쓰지 않는다."""
    keys = current_keys(workspace)
    assert keys, "매핑이 없으면 이 테스트가 아무것도 지키지 못한다"
    victim = keys[0]

    # 그 코드만 빼고 나머지를 그대로 넣는다.
    rows = [
        (r["kunnr"], r["name1"], r["zbrand"], r["zbrant"])
        for r in current_master(workspace)
        if not (r["kunnr"] == victim["kunnr"] and r["zbrand"] == victim["zbrand"])
    ]
    export = tmp_path / "sap.csv"
    write_export(export, rows)

    before = (workspace / "refs" / "brand_master.csv").read_bytes()
    result = run(workspace, export, "--yes")

    assert result.returncode == 1
    assert victim["text"] in result.stdout
    assert (workspace / "refs" / "brand_master.csv").read_bytes() == before, \
        "거부했으면 파일을 건드리지 않아야 한다"


def test_dry_run_never_writes(tmp_path, workspace):
    export = tmp_path / "sap.csv"
    write_export(export, [
        (r["kunnr"], r["name1"], r["zbrand"], r["zbrant"]) for r in current_master(workspace)
    ])
    before = (workspace / "refs" / "brand_master.csv").read_bytes()
    assert run(workspace, export, "--dry-run").returncode == 0
    assert (workspace / "refs" / "brand_master.csv").read_bytes() == before


def test_report_counts_what_changes(tmp_path, workspace):
    rows = [(r["kunnr"], r["name1"], r["zbrand"], r["zbrant"]) for r in current_master(workspace)]
    rows.append(("999999", "새 고객", "1", "YG BRAND"))
    export = tmp_path / "sap.csv"
    write_export(export, rows)

    result = run(workspace, export, "--dry-run")
    assert result.returncode == 0
    assert "고객 추가    1곳" in result.stdout or "고객 추가" in result.stdout
    assert "깨지는 매핑 없음" in result.stdout
