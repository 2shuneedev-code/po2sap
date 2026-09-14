"""마스터 YAML 검증 — masters/SCHEMA.md §7 의 9종 검사.

CI 1단계이자 거래처 추가 절차(§5-6)의 관문이다. LLM 을 호출하지 않으므로 비용 0.

사용법
    python scripts/validate_masters.py
    python scripts/validate_masters.py --customer MSC
    python scripts/validate_masters.py --quiet        # 오류만

종료 코드: 0 = 오류 없음 / 1 = 오류 있음 (경고·TODO 는 0)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.extraction.extractor import splits_by_shipment  # noqa: E402
from app.extraction.schema_builder import build_tool_schema  # noqa: E402
from app.masters.loader import MasterError, load_customer  # noqa: E402
from app.rules import expr as expr_mod  # noqa: E402

MASTERS = ROOT / "masters"

# ── SCHEMA.md 가 정한 허용 목록 ────────────────────────────────────────
TOP_LEVEL_KEYS = {                      # §4.0
    "version", "extends", "meta", "extraction", "split",
    "tables", "rules", "fields", "grid", "checks",
    "sap_defaults", "field_specs",      # _base 조각이 병합되어 올라온다
}
FIELD_FROM = {"const", "base", "doc", "table", "rule", "expr", "gen"}     # §4.6
FIELD_OPTIONS = {
    "from", "value", "path", "table", "rule", "expr", "generator",
    "fallback", "required", "format", "default", "explain", "todo",
}
FORMATS = {"integer", "decimal3", "date_yyyymmdd", "upper", "lower", "trim"}
GENERATORS = {"line_no_x10"}
RULE_KINDS = {"keyword_map", "value_map", "csv_map", "lookup", "regex_extract", "fixed"}  # §4.5
RULE_OPTIONS = {
    "kind", "label", "description", "source", "fallback_source",
    "case_insensitive", "normalize", "entries", "on_no_match",
    "table_file", "key", "key_column", "return", "optional",
    "value_column", "mode_column", "filter_column", "value_check",
    "pattern", "group", "value",
}
NORMALIZE_OPS = {"trim", "collapse_spaces", "upper", "lower"}
TABLE_OPS = {"contains_ci", "equals", "equals_ci", "regex", "starts_with"}     # §4.4
NO_MATCH_ACTIONS = {"error", "warn", "default", "empty"}
CHECK_IDS = {"shipment_total_match"}                                           # §4.9

PATH_KEYS = ("path", "fallback", "source", "fallback_source", "key")


# ── 리포트 ─────────────────────────────────────────────────────────────
@dataclass
class Report:
    customer: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)

    def error(self, check: int, message: str) -> None:
        self.errors.append(f"[§7-{check}] {message}")

    def warn(self, check: int, message: str) -> None:
        self.warnings.append(f"[§7-{check}] {message}")


# ── 컨텍스트 경로 목록 ─────────────────────────────────────────────────
def valid_paths(master: Any) -> set[str]:
    """이 거래처에서 참조 가능한 컨텍스트 경로 전부 (SCHEMA.md §3)."""
    extra_fields = master.extraction.get("extra_fields") or []
    schema = build_tool_schema(extra_fields, include_shipments=splits_by_shipment(master))
    props = schema["properties"]

    # meta.* 는 문서가 아니라 마스터에 적힌 값이다 (SCHEMA §3).
    out: set[str] = {"meta.code", "meta.customer_no", "meta.name"}
    for key in props["header"]["properties"]:
        if key != "extra":
            out.add(f"header.{key}")
    for key in props["lines"]["items"]["properties"]:
        if key != "extra":
            out.add(f"line.{key}")
    if "shipments" in props:
        for key in props["shipments"]["items"]["properties"]:
            if key != "lines":
                out.add(f"shipment.{key}")
    for f in extra_fields:
        out.add(f"header.extra.{f['name']}")
        out.add(f"line.extra.{f['name']}")

    for table in (master.tables or {}).values():
        for col in table.get("then") or []:
            if str(col).startswith("_"):
                out.add(str(col))

    for name, rule in (master.rules or {}).items():
        out.add(name)
        for col in rule.get("return") or []:
            out.add(f"{name}.{col}")

    return out


def check_path(report: Report, where: str, value: Any, allowed: set[str], num: int = 5) -> None:
    if not isinstance(value, str) or not value:
        return
    if value in allowed:
        return
    near = [p for p in sorted(allowed) if p.split(".")[-1] == value.split(".")[-1]]
    hint = f" — {near[0]} 말입니까?" if near else ""
    report.error(num, f"{where}: 추출 스키마에 없는 경로입니다: {value}{hint}")


# ── 개별 검사 ──────────────────────────────────────────────────────────
def check_top_level(report: Report, data: dict[str, Any]) -> None:
    for key in data:
        if key not in TOP_LEVEL_KEYS:
            report.error(2, f"정의되지 않은 최상위 키입니다: {key} (SCHEMA §4.0)")
    if "version" not in data:
        report.warn(2, "version 이 없습니다 (SCHEMA §4.0)")
    if not (data.get("fields") or {}):
        report.error(1, "fields 섹션이 없습니다")


def check_meta(report: Report, master: Any) -> None:
    owner = str((master.raw.get("meta") or {}).get("owner") or "").strip()
    if not owner or owner.startswith("※"):
        report.warn(9, f"meta.owner 가 지정되지 않았습니다 (현재: {owner or '빈 값'})")


def check_fields(
    report: Report, master: Any, base_fields: list[str], allowed: set[str]
) -> None:
    declared = master.fields or {}

    missing = [f for f in base_fields if f not in declared]
    if missing:
        report.error(
            1,
            f"전송 필드 {len(missing)}개가 선언되지 않았습니다: {', '.join(missing)}",
        )
    unknown = [f for f in declared if f not in base_fields]
    if unknown:
        report.error(
            1,
            f"_base 에 없는 필드를 선언했습니다: {', '.join(unknown)}",
        )

    tables, rules = master.tables or {}, master.rules or {}

    for name, spec in declared.items():
        if not isinstance(spec, dict):
            report.error(2, f"fields.{name}: 매핑이 아닙니다")
            continue

        for key in spec:
            if key not in FIELD_OPTIONS:
                report.error(2, f"fields.{name}: 정의되지 않은 옵션입니다: {key}")

        src = spec.get("from")
        if src not in FIELD_FROM:
            report.error(
                2,
                f"fields.{name}: from 이 허용 목록 밖입니다: {src!r} "
                f"(허용: {', '.join(sorted(FIELD_FROM))})",
            )

        fmt = spec.get("format")
        if fmt is not None and fmt not in FORMATS:
            report.error(
                2,
                f"fields.{name}: format 이 허용 목록 밖입니다: {fmt!r} "
                f"(허용: {', '.join(sorted(FORMATS))})",
            )

        if src == "doc" and not spec.get("path"):
            report.error(2, f"fields.{name}: from: doc 인데 path 가 없습니다")
        if src == "const" and "value" not in spec:
            report.error(2, f"fields.{name}: from: const 인데 value 가 없습니다")

        for key in ("path", "fallback"):
            check_path(report, f"fields.{name}.{key}", spec.get(key), allowed)

        if src == "table":
            ref = spec.get("table")
            if ref not in tables:
                report.error(3, f"fields.{name}: 없는 결정표를 참조합니다: {ref}")
        if src == "rule":
            ref = spec.get("rule")
            if ref not in rules:
                report.error(3, f"fields.{name}: 없는 규칙을 참조합니다: {ref}")
        if src == "gen":
            gen = spec.get("generator")
            if gen not in GENERATORS:
                report.error(
                    2,
                    f"fields.{name}: 없는 생성기입니다: {gen!r} "
                    f"(허용: {', '.join(sorted(GENERATORS))})",
                )
        if src == "expr":
            check_expr(report, f"fields.{name}", spec.get("expr"), allowed)

        if spec.get("todo"):
            report.todos.append(f"fields.{name}: {spec['todo']}")


def check_expr(report: Report, where: str, source: Any, allowed: set[str]) -> None:
    if not isinstance(source, str) or not source.strip():
        report.error(4, f"{where}: from: expr 인데 expr 이 비어 있습니다")
        return

    info = expr_mod.analyze(source)
    for message in info.errors:
        report.error(4, f"{where}: {message}")
    for message in info.warnings:
        report.warn(4, f"{where}: {message}")
    for path in info.referenced_paths:
        check_path(report, f"{where} (expr)", path.dotted, allowed)


def check_tables(report: Report, master: Any, allowed: set[str]) -> None:
    for name, table in (master.tables or {}).items():
        where = f"tables.{name}"
        conditions = table.get("when") or []
        results = table.get("then") or []

        if not conditions:
            report.error(2, f"{where}: when 이 비어 있습니다")
        if not results:
            report.error(2, f"{where}: then 이 비어 있습니다")

        scope = table.get("scope")
        if scope not in {None, "header", "shipment", "line"}:
            report.error(2, f"{where}: scope 가 허용 목록 밖입니다: {scope!r}")
        if scope == "shipment" and not splits_by_shipment(master):
            report.error(
                3,
                f"{where}: scope: shipment 인데 split.by 가 none 입니다 "
                "— shipment 네임스페이스가 비어 있게 됩니다",
            )

        for idx, cond in enumerate(conditions, start=1):
            op = cond.get("op")
            if op not in TABLE_OPS:
                report.error(
                    2,
                    f"{where}.when[{idx}]: op 이 허용 목록 밖입니다: {op!r} "
                    f"(허용: {', '.join(sorted(TABLE_OPS))})",
                )
            for key in ("source", "fallback_source"):
                check_path(report, f"{where}.when[{idx}].{key}", cond.get(key), allowed)

        seen: Counter[tuple] = Counter()
        for idx, row in enumerate(table.get("rows") or [], start=1):
            when = tuple(str(x) for x in (row.get("when") or []))
            then = row.get("then") or []
            if len(when) != len(conditions):
                report.error(
                    2,
                    f"{where}.rows[{idx}]: when 이 {len(conditions)}개여야 하는데 "
                    f"{len(when)}개입니다",
                )
            if len(then) != len(results):
                report.error(
                    2,
                    f"{where}.rows[{idx}]: then 이 {len(results)}개여야 하는데 "
                    f"{len(then)}개입니다",
                )
            seen[when] += 1
            if seen[when] == 2:
                report.warn(
                    6,
                    f"{where}.rows[{idx}]: 위 행과 조건이 같아 도달할 수 없습니다: "
                    f"{list(when)}",
                )

        check_no_match(report, where, table, results, allowed)


def check_rules(
    report: Report, master: Any, allowed: set[str], masters_dir: Path = MASTERS
) -> None:
    for name, rule in (master.rules or {}).items():
        where = f"rules.{name}"

        kind = rule.get("kind")
        if kind not in RULE_KINDS:
            report.error(
                2,
                f"{where}: kind 가 허용 목록 밖입니다: {kind!r} "
                f"(허용: {', '.join(sorted(RULE_KINDS))})",
            )
        for key in rule:
            if key not in RULE_OPTIONS:
                report.error(2, f"{where}: 정의되지 않은 옵션입니다: {key}")

        for op in rule.get("normalize") or []:
            if op not in NORMALIZE_OPS:
                report.error(
                    2,
                    f"{where}: normalize 가 허용 목록 밖입니다: {op!r} "
                    f"(허용: {', '.join(sorted(NORMALIZE_OPS))})",
                )

        for key in ("source", "fallback_source", "key"):
            check_path(report, f"{where}.{key}", rule.get(key), allowed)

        if kind == "lookup":
            table_file = rule.get("table_file")
            if not table_file:
                report.error(2, f"{where}: lookup 인데 table_file 이 없습니다")
            elif not (masters_dir / table_file).exists():
                if rule.get("optional"):
                    report.warn(
                        3,
                        f"{where}: 참조표 파일이 없습니다: {table_file} "
                        "(optional: true — 기본값으로 동작)",
                    )
                else:
                    report.error(3, f"{where}: 참조표 파일이 없습니다: {table_file}")
            if not rule.get("return"):
                report.error(2, f"{where}: lookup 인데 return 이 없습니다")
        elif kind == "csv_map":
            check_csv_map(report, where, rule, master, masters_dir)
        elif kind in {"keyword_map", "value_map"}:
            entries = rule.get("entries") or []
            if not entries:
                report.error(2, f"{where}: entries 가 비어 있습니다")
            match_key = "contains" if kind == "keyword_map" else "equals"
            seen: Counter[str] = Counter()
            for idx, entry in enumerate(entries, start=1):
                if match_key not in entry:
                    report.error(
                        2, f"{where}.entries[{idx}]: {match_key} 키가 없습니다"
                    )
                else:
                    token = str(entry[match_key])
                    seen[token] += 1
                    if seen[token] == 2:
                        report.warn(
                            6,
                            f"{where}.entries[{idx}]: 위 행과 조건이 같아 "
                            f"도달할 수 없습니다: {token!r}",
                        )
                if "value" not in entry:
                    report.error(2, f"{where}.entries[{idx}]: value 키가 없습니다")
                if entry.get("todo"):
                    report.todos.append(
                        f"{where}.entries[{idx}] ({entry.get(match_key)}): {entry['todo']}"
                    )

        check_no_match(report, where, rule, None, allowed)


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def check_csv_map(
    report: Report, where: str, rule: dict[str, Any], master: Any, masters_dir: Path
) -> None:
    """§7-10 · §7-11 — 참조표 기반 매핑표 (SCHEMA §4.5)."""
    table_file = rule.get("table_file")
    if not table_file:
        report.error(2, f"{where}: csv_map 인데 table_file 이 없습니다")
        return

    path = masters_dir / table_file
    if not path.exists():
        report.error(10, f"{where}: 참조표 파일이 없습니다: {table_file}")
        return

    rows, header = _read_csv(path)

    required = {"key_column": rule.get("key_column"), "value_column": rule.get("value_column")}
    optional = {"mode_column": rule.get("mode_column"), "filter_column": rule.get("filter_column")}
    for name, col in required.items():
        if not col:
            report.error(2, f"{where}: csv_map 인데 {name} 이 없습니다")
        elif col not in header:
            report.error(
                10,
                f"{where}.{name}: {table_file} 에 없는 컬럼입니다: {col} "
                f"(있는 컬럼: {', '.join(header)})",
            )
    for name, col in optional.items():
        if col and col not in header:
            report.error(
                10,
                f"{where}.{name}: {table_file} 에 없는 컬럼입니다: {col} "
                f"(있는 컬럼: {', '.join(header)})",
            )

    key_col, value_col = rule.get("key_column"), rule.get("value_column")
    mode_col, filter_col = rule.get("mode_column"), rule.get("filter_column")
    if not (key_col in header and value_col in header):
        return

    mine = rows
    if filter_col and filter_col in header:
        mine = [r for r in rows if (r.get(filter_col) or "").strip() == master.customer_no]
        if not mine:
            report.warn(
                11,
                f"{where}: {table_file} 에 이 거래처({filter_col}={master.customer_no}) "
                "행이 하나도 없습니다 — 항상 미매칭됩니다",
            )
            return

    seen: Counter[str] = Counter()
    for idx, row in enumerate(mine, start=1):
        text = (row.get(key_col) or "").strip()
        if not text:
            report.error(10, f"{where}: {table_file} {idx}번째 행의 {key_col} 이 비어 있습니다")
            continue
        if mode_col:
            mode = (row.get(mode_col) or "contains").strip()
            if mode not in {"contains", "equals"}:
                report.error(
                    10,
                    f"{where}: {table_file} {idx}번째 행의 {mode_col} 이 "
                    f"허용 목록 밖입니다: {mode!r} (contains | equals)",
                )
        seen[text] += 1
        if seen[text] == 2:
            report.warn(
                6,
                f"{where}: {table_file} 에 같은 {key_col} 이 두 번 있습니다 — "
                f"아래 행은 도달할 수 없습니다: {text!r}",
            )
        if (row.get("note") or "").strip():
            report.todos.append(f"{table_file} [{row.get(value_col)}] {text}: {row['note'].strip()}")

    check_value_registry(report, where, rule, master, masters_dir, mine, value_col)


def check_value_registry(
    report: Report, where: str, rule: dict[str, Any], master: Any,
    masters_dir: Path, rows: list[dict[str, str]], value_col: str,
) -> None:
    """§7-10 — 결정될 값이 실제로 등록된 코드인가 (미등록 코드 전송 방지)."""
    spec = rule.get("value_check")
    if not spec:
        return

    path = masters_dir / (spec.get("table_file") or "")
    if not path.exists():
        report.error(10, f"{where}.value_check: 참조표 파일이 없습니다: {spec.get('table_file')}")
        return

    registry, header = _read_csv(path)
    col = spec.get("value_column")
    if col not in header:
        report.error(10, f"{where}.value_check.value_column: 없는 컬럼입니다: {col}")
        return

    filter_col = spec.get("filter_column")
    if filter_col and filter_col in header:
        registry = [r for r in registry if (r.get(filter_col) or "").strip() == master.customer_no]

    known = {(r.get(col) or "").strip() for r in registry}
    for row in rows:
        value = (row.get(value_col) or "").strip()
        if value and value not in known:
            report.error(
                10,
                f"{where}: {value_col}={value} 가 {spec['table_file']} 에 "
                f"등록돼 있지 않습니다 (거래처 {master.customer_no}) — "
                "SAP 이 거부할 코드입니다",
            )


def check_no_match(
    report: Report, where: str, spec: dict[str, Any], results: Any, allowed: set[str]
) -> None:
    no_match = spec.get("on_no_match")
    if not no_match:
        report.warn(7, f"{where}: on_no_match 가 선언되지 않았습니다")
        return

    action = no_match.get("action")
    if action not in NO_MATCH_ACTIONS:
        report.error(
            2,
            f"{where}.on_no_match: action 이 허용 목록 밖입니다: {action!r} "
            f"(허용: {', '.join(sorted(NO_MATCH_ACTIONS))})",
        )
    if action == "default":
        if "value" not in no_match:
            report.error(2, f"{where}.on_no_match: action: default 인데 value 가 없습니다")
        elif results is not None and len(no_match["value"]) != len(results):
            report.error(
                2,
                f"{where}.on_no_match: value 가 {len(results)}개여야 하는데 "
                f"{len(no_match['value'])}개입니다",
            )

    message = no_match.get("message")
    if isinstance(message, str):
        leaves = {p.split(".")[-1] for p in allowed}
        for token in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", message):
            if token not in leaves:
                report.error(
                    5,
                    f"{where}.on_no_match.message: 없는 이름을 참조합니다: {{{token}}}",
                )


def check_checks(report: Report, master: Any) -> None:
    for idx, check in enumerate(master.raw.get("checks") or [], start=1):
        cid = check.get("id")
        if cid not in CHECK_IDS:
            report.error(
                2,
                f"checks[{idx}]: 엔진에 없는 검사 id 입니다: {cid!r} "
                f"(허용: {', '.join(sorted(CHECK_IDS))})",
            )
        if check.get("severity") not in {"error", "warn"}:
            report.error(
                2, f"checks[{idx}]: severity 는 error | warn 이어야 합니다"
            )


def check_grid(report: Report, master: Any, base_fields: list[str]) -> None:
    grid = master.grid or {}
    known = set(base_fields)
    for key in ("pinned", "hidden"):
        for name in grid.get(key) or []:
            if name not in known:
                report.error(2, f"grid.{key}: 전송 필드가 아닙니다: {name}")
    for name in (grid.get("width") or {}):
        if name not in known:
            report.error(2, f"grid.width: 전송 필드가 아닙니다: {name}")


# ── 실행 ───────────────────────────────────────────────────────────────
def validate_customer(
    code: str, base_fields: list[str], masters_dir: Path = MASTERS
) -> Report:
    report = Report(customer=code.upper())
    try:
        master = load_customer(code, masters_dir)
    except (MasterError, yaml.YAMLError) as exc:
        report.error(2, f"로딩 실패: {exc}")
        return report

    allowed = valid_paths(master)

    check_top_level(report, master.raw)
    check_meta(report, master)
    check_tables(report, master, allowed)
    check_rules(report, master, allowed, masters_dir)
    check_fields(report, master, base_fields, allowed)
    check_checks(report, master)
    check_grid(report, master, base_fields)
    return report


def load_base_fields(masters_dir: Path = MASTERS) -> list[str]:
    data = yaml.safe_load((masters_dir / "_base" / "sap_defaults.yaml").read_text("utf-8"))
    return list((data or {}).get("field_specs") or {})


def customer_codes(masters_dir: Path = MASTERS) -> list[str]:
    """`_` 로 시작하는 파일(_template 등)은 거래처가 아니다."""
    return sorted(
        p.stem
        for p in (masters_dir / "customers").glob("*.yaml")
        if not p.stem.startswith("_")
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="마스터 YAML 검증 (SCHEMA.md §7)")
    ap.add_argument("--customer", "-c", help="이 거래처만 검사")
    ap.add_argument("--quiet", "-q", action="store_true", help="오류만 출력")
    args = ap.parse_args()

    base_fields = load_base_fields()
    if not base_fields:
        print("[실패] _base/sap_defaults.yaml 에 field_specs 가 없습니다", file=sys.stderr)
        return 1

    codes = (
        [args.customer]
        if args.customer
        else customer_codes()
    )

    print(f"전송 필드 {len(base_fields)}개 기준 · 거래처 {len(codes)}곳\n")

    reports = [validate_customer(code, base_fields) for code in codes]
    errors = warnings = todos = 0

    for r in reports:
        errors += len(r.errors)
        warnings += len(r.warnings)
        todos += len(r.todos)

        mark = "FAIL" if r.errors else ("WARN" if r.warnings else "OK")
        print(f"── {r.customer}  [{mark}]  "
              f"오류 {len(r.errors)} / 경고 {len(r.warnings)} / TODO {len(r.todos)}")
        for message in r.errors:
            print(f"   ⛔ {message}")
        if not args.quiet:
            for message in r.warnings:
                print(f"   ⚠  {message}")
            for message in r.todos:
                print(f"   📌 {message}")
        print()

    print("═" * 70)
    print(f"합계: 오류 {errors} / 경고 {warnings} / TODO {todos}")
    if errors:
        print("→ 오류를 고쳐야 전송 필드가 올바르게 생성됩니다.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
