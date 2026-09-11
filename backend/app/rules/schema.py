"""마스터 YAML 로딩용 Pydantic 모델 (D2-1).

`masters/SCHEMA.md` §4.0~§4.10 의 구조를 그대로 옮긴 것이다. **이 파일은 원문
그대로의 거래처 YAML(확장 전) 과 `_base/sap_defaults.yaml` 의 "구조" 를 검증할
뿐**, 아래는 이번 작업의 범위 밖이다 (다음 작업 engine.py 에서 다룬다):

- `extends` 병합 (베이스 → 거래처 덮어쓰기)
- `rules`/`tables`/`fields` 의 실제 평가·실행
- `expr` 화이트리스트 함수 검증 (문자열 값으로만 저장한다)
- `validate_masters.py` 의 교차 검증(§7): 참조 무결성(`table`/`rule` 존재 여부),
  `_base` 필드 커버리지, `path` 가 추출 스키마에 있는지 등

원칙(CLAUDE.md §6):
  G1 — 거래처 이름을 코드에 쓰지 않는다. 이 파일 어디에도 "MSC"/"KL"/"YGJP"
       조건 분기가 없다. `meta.code` 는 문서 예시에서만 등장한다.
  G2 — 필드 개수를 하드코딩하지 않는다. `field_specs` 는 YAML 에서 읽은
       `dict` 이고, 개수는 그 dict 의 길이일 뿐이다.

최상위(`CustomerMasterSchema`, `BaseDefaultsSchema`)는 **엄격**(`extra="forbid"`)
하게, 그 하위 섹션들은 **관대**(`extra="allow"`)하게 검증한다. 실제 YAML 에는
문서화되지 않은 보조 키(예: `ygjp.yaml` 의 `rules.brand_code.normalize`)가
있기 때문이다 — 이건 alias/known 필드로 명시적으로 흡수하거나, 모르는 키는
`extra="allow"` 로 통과시킨다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MasterSchemaError(RuntimeError):
    """마스터 YAML 이 스키마(SCHEMA.md §4)에 맞지 않을 때."""


# ─────────────────────────────────────────────────────────────────
# §4.1 meta
# ─────────────────────────────────────────────────────────────────
class Meta(BaseModel):
    """거래처 식별 정보. `code` 만 필수(파일명과 일치해야 함, 검증은 로더 몫)."""

    model_config = ConfigDict(extra="allow")

    code: str
    name: str = ""
    customer_no: str = ""
    owner: str = ""
    status: Literal["active", "draft", "disabled"] = "draft"
    file_types: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# §4.2 extraction
# ─────────────────────────────────────────────────────────────────
class Extraction(BaseModel):
    """Claude 에게 줄 문서 구조 설명. `hints` 는 변환 지시를 쓰지 않는다는
    규칙은 엔진이 강제할 수 없으므로(자연어) 여기서는 문자열로만 받는다."""

    model_config = ConfigDict(extra="allow")

    input: Literal["text", "image", "auto"] = "text"
    page_limit: int | None = None
    hints: str = ""


# ─────────────────────────────────────────────────────────────────
# §4.3 split
# ─────────────────────────────────────────────────────────────────
class Split(BaseModel):
    """`by` 는 `none` / `shipment` 외에 문서상 "<키>" 로 자유 확장 가능하므로
    Literal 로 제한하지 않는다 (엔진이 인식 못 하는 값이면 실행 단계에서 오류)."""

    model_config = ConfigDict(extra="allow")

    by: str = "none"
    label: str | None = None
    description: str | None = None


# ─────────────────────────────────────────────────────────────────
# 공통 — on_no_match (rules 와 tables 가 공유)
# ─────────────────────────────────────────────────────────────────
class OnNoMatch(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: Literal["error", "warn", "default", "empty"]
    value: Any | None = None  # action: default 일 때 결과 컬럼 수만큼의 리스트 또는 단일값
    message: str | None = None


# ─────────────────────────────────────────────────────────────────
# §4.4 tables
# ─────────────────────────────────────────────────────────────────
class TableWhenCond(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    op: Literal["contains_ci", "equals", "equals_ci", "regex", "starts_with"]
    fallback_source: str | None = None
    label: str | None = None


class TableRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    when: list[str]
    then: list[str]


class TableDef(BaseModel):
    """결정표 1개. `rows[].when`/`then` 길이가 컬럼 수와 같은지는 여기서
    바로 검증한다 (SCHEMA.md §4.4: "길이는 컬럼 수와 같아야 한다")."""

    model_config = ConfigDict(extra="allow")

    label: str | None = None
    description: str | None = None
    scope: Literal["header", "shipment", "line"]
    when: list[TableWhenCond]
    then: list[str]
    rows: list[TableRow] = Field(default_factory=list)
    on_no_match: OnNoMatch | None = None

    @model_validator(mode="after")
    def _check_row_lengths(self) -> "TableDef":
        n_when = len(self.when)
        n_then = len(self.then)
        for i, row in enumerate(self.rows):
            if len(row.when) != n_when:
                raise ValueError(
                    f"rows[{i}].when 길이({len(row.when)})가 when 컬럼 수({n_when})와 다릅니다"
                )
            if len(row.then) != n_then:
                raise ValueError(
                    f"rows[{i}].then 길이({len(row.then)})가 then 컬럼 수({n_then})와 다릅니다"
                )
        return self


# ─────────────────────────────────────────────────────────────────
# §4.5 rules
# ─────────────────────────────────────────────────────────────────
class RuleEntry(BaseModel):
    """`keyword_map`(contains) / `value_map`(equals) 공용 엔트리.

    실제 YAML 에서 하나의 규칙은 항상 같은 종류의 키(`contains` 또는
    `equals`)만 쓰지만, 두 kind 가 같은 모양(`{ ..., value, todo? }`)이라
    모델 하나로 관대하게 받는다."""

    model_config = ConfigDict(extra="allow")

    contains: str | None = None
    equals: str | None = None
    value: str
    todo: str | None = None

    @model_validator(mode="after")
    def _check_key(self) -> "RuleEntry":
        if self.contains is None and self.equals is None:
            raise ValueError("entries 항목에 contains 또는 equals 중 하나가 있어야 합니다")
        return self


class RuleDef(BaseModel):
    """`rules.<이름>` 하나. `kind` 로 종류가 갈리지만 discriminated union 대신
    단일 유연한 모델로 둔다 — 실제 YAML(`ygjp.yaml`)에 문서화되지 않은
    `normalize` 같은 보조 키가 이미 존재하기 때문이다 (§4.5 에 없음, 여기서는
    막지 않고 알려진 선택 필드로 흡수한다). 알 수 없는 추가 키는
    `extra="allow"` 로 통과시킨다.

    kind 별 필수 키는 SCHEMA.md §4.5 표 그대로 `_check_required_by_kind` 에서
    검증하고, 같은 메서드에서 `kind`(keyword_map→contains / value_map→equals)와
    `entries[]` 의 키 종류가 짝이 맞는지도 교차 검증한다 (reviewer 지적 반영).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kind: Literal["keyword_map", "value_map", "lookup", "regex_extract", "fixed"]
    label: str | None = None
    description: str | None = None
    on_no_match: OnNoMatch | None = None

    # 공통 옵션 (keyword_map / value_map / regex_extract)
    source: str | None = None
    fallback_source: str | None = None
    case_insensitive: bool | None = None

    # keyword_map / value_map
    entries: list[RuleEntry] | None = None
    normalize: list[str] | None = None  # ygjp.yaml 실사용 — §4.5 미문서화 보조 키

    # lookup
    table_file: str | None = None
    key: str | None = None
    key_column: str | None = None
    return_: list[str] | None = Field(default=None, alias="return")
    optional: bool = False

    # regex_extract
    pattern: str | None = None
    group: int | None = None

    # fixed
    value: str | None = None

    @model_validator(mode="after")
    def _check_required_by_kind(self) -> "RuleDef":
        missing: list[str] = []
        if self.kind in ("keyword_map", "value_map"):
            if not self.source:
                missing.append("source")
            if not self.entries:
                missing.append("entries")
        elif self.kind == "lookup":
            for k in ("table_file", "key", "key_column"):
                if not getattr(self, k):
                    missing.append(k)
            if not self.return_:
                missing.append("return")
        elif self.kind == "regex_extract":
            for k in ("source", "pattern"):
                if not getattr(self, k):
                    missing.append(k)
            if self.group is None:
                missing.append("group")
        elif self.kind == "fixed":
            if self.value is None:
                missing.append("value")
        if missing:
            raise ValueError(
                f"kind={self.kind} 인 규칙에 필수 키가 없습니다: {', '.join(missing)}"
            )

        # kind 와 entries[].contains/equals 짝이 맞는지 교차 검증한다.
        # (keyword_map 은 contains, value_map 은 equals 만 써야 한다 — §4.5)
        if self.kind == "keyword_map" and self.entries:
            bad = [i for i, e in enumerate(self.entries) if e.contains is None]
            if bad:
                raise ValueError(
                    f"kind=keyword_map 인데 entries[{bad}] 가 'contains' 대신 'equals' 를 씁니다"
                )
        if self.kind == "value_map" and self.entries:
            bad = [i for i, e in enumerate(self.entries) if e.equals is None]
            if bad:
                raise ValueError(
                    f"kind=value_map 인데 entries[{bad}] 가 'equals' 대신 'contains' 를 씁니다"
                )
        return self


# ─────────────────────────────────────────────────────────────────
# §4.6 fields
# ─────────────────────────────────────────────────────────────────
class FieldDef(BaseModel):
    """`fields.<SAP필드명>` 하나. `from` 종류별로 필요한 키가 다르지만
    (§4.6 표) `rules.RuleDef` 와 같은 이유로 단일 유연한 모델로 둔다.

    `expr` 값은 문자열로만 저장한다 — 화이트리스트(§4.7) 함수 검증은 이
    스키마의 책임이 아니라 engine 의 expr 실행 단계 책임이다 (`ygjp.yaml`
    의 `date_yyyymmdd(...)` 처럼 §4.7 에 없는 함수를 써도 여기서는 통과한다).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    from_: Literal["const", "base", "doc", "table", "rule", "expr", "gen"] = Field(
        alias="from"
    )

    # const
    value: str | None = None
    # doc
    path: str | None = None
    fallback: str | None = None
    # table
    table: str | None = None
    # rule
    rule: str | None = None
    key: str | None = None  # from=rule 이 여러 반환키를 가질 때 선택
    # expr
    expr: str | None = None
    # gen
    generator: str | None = None

    # 공통 옵션
    required: bool = False
    format: str | None = None
    default: str | None = None
    explain: str | None = None
    todo: str | None = None

    @model_validator(mode="after")
    def _check_required_by_from(self) -> "FieldDef":
        required_key = {
            "const": "value",
            "doc": "path",
            "table": "table",
            "rule": "rule",
            "expr": "expr",
            "gen": "generator",
        }.get(self.from_)
        # const 는 "" 도 유효한 값이므로 None 인지만 확인한다 (빈 문자열 허용).
        if required_key and getattr(self, required_key) is None:
            raise ValueError(
                f"from={self.from_} 인 필드에 '{required_key}' 값이 필요합니다"
            )
        return self


# ─────────────────────────────────────────────────────────────────
# §4.8 grid
# ─────────────────────────────────────────────────────────────────
class Grid(BaseModel):
    model_config = ConfigDict(extra="allow")

    pinned: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    width: dict[str, int] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# §4.9 checks
# ─────────────────────────────────────────────────────────────────
class CheckDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str | None = None
    severity: Literal["error", "warn"] = "error"
    description: str | None = None


# ─────────────────────────────────────────────────────────────────
# §4.0 최상위 (거래처 파일) — 여기만 엄격(extra="forbid")
# ─────────────────────────────────────────────────────────────────
class CustomerMasterSchema(BaseModel):
    """거래처 YAML 최상위. §4.0 표에 없는 키는 로딩 실패(오류)여야 한다."""

    model_config = ConfigDict(extra="forbid")

    version: int
    meta: Meta
    extends: list[str] = Field(default_factory=list)
    extraction: Extraction
    split: Split = Field(default_factory=Split)
    tables: dict[str, TableDef] = Field(default_factory=dict)
    rules: dict[str, RuleDef] = Field(default_factory=dict)
    fields: dict[str, FieldDef]
    grid: Grid | None = None
    checks: list[CheckDef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# §4.10 _base/sap_defaults.yaml — 최상위 2키만, 엄격
# ─────────────────────────────────────────────────────────────────
class FieldSpec(BaseModel):
    """`field_specs.<필드명>` 하나. 전송 필드의 유일한 원천(개수 포함)."""

    model_config = ConfigDict(extra="allow")

    label: str
    sheet: str | None = None
    max_len: int | None = None
    type: Literal["date", "decimal"] | None = None
    added: str | None = None


class BaseDefaultsSchema(BaseModel):
    """`_base/sap_defaults.yaml` 최상위. 키는 `sap_defaults`/`field_specs` 둘뿐."""

    model_config = ConfigDict(extra="forbid")

    sap_defaults: dict[str, str]
    field_specs: dict[str, FieldSpec]


# ─────────────────────────────────────────────────────────────────
# 로더 — extends 병합은 하지 않는다 (범위 밖. engine.py 에서 다룬다)
# ─────────────────────────────────────────────────────────────────
def _read_yaml_dict(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise MasterSchemaError(f"마스터 형식이 올바르지 않습니다(맵이 아님): {path}")
    return data


def load_customer_yaml(path: Path) -> CustomerMasterSchema:
    """거래처 YAML 파일 1개(확장 전 원본)를 읽어 스키마를 검증한다."""

    data = _read_yaml_dict(path)
    return CustomerMasterSchema.model_validate(data)


def load_customer_master_schema(code: str, masters_dir: Path) -> CustomerMasterSchema:
    """`masters/customers/{code}.yaml` 을 읽는 편의 함수 (디렉터리 관례 고정)."""

    path = Path(masters_dir) / "customers" / f"{code.lower()}.yaml"
    if not path.exists():
        raise MasterSchemaError(f"거래처 마스터를 찾을 수 없습니다: {path}")
    return load_customer_yaml(path)


def load_base_defaults_yaml(path: Path) -> BaseDefaultsSchema:
    """`_base/sap_defaults.yaml` 파일 1개를 읽어 스키마를 검증한다."""

    data = _read_yaml_dict(path)
    return BaseDefaultsSchema.model_validate(data)


def load_base_defaults(masters_dir: Path) -> BaseDefaultsSchema:
    """`masters/_base/sap_defaults.yaml` 을 읽는 편의 함수."""

    path = Path(masters_dir) / "_base" / "sap_defaults.yaml"
    if not path.exists():
        raise MasterSchemaError(f"_base 마스터를 찾을 수 없습니다: {path}")
    return load_base_defaults_yaml(path)
