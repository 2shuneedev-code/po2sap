# 규칙 마스터 스키마 — PO2SAP 규칙 관리 아키텍처

> **이 문서가 규칙 관리의 단일 원천이다.**
> 거래처 규칙은 코드가 아니라 이 스키마를 따르는 **선언(YAML)** 으로만 존재한다.
> 엔진은 스키마를 해석할 뿐, 거래처 이름을 알지 못한다.
> 버전 v1.1 · 2026-09-11 (§4.0 최상위 키 · §4.10 `_base` 구조 추가)

---

## 0. 원칙 3개

| # | 원칙 | 위반하면 |
|---|---|---|
| 1 | **거래처 이름이 코드에 등장하지 않는다** | 거래처 50개가 되면 if문 지옥 |
| 2 | **값은 슬롯, 규칙은 선언** — 값이 미정이면 슬롯만 두고 `TODO` 표시 | 값 확정을 기다리느라 개발이 멈춤 |
| 3 | **Claude 는 읽기만, 코드 결정은 마스터가** | 재현성·감사 붕괴 |

> 원칙 2 때문에 **값이 안 정해져도 개발은 진행된다.** 미정 값은 `?` 로 두고
> 스키마 검증에서 `TODO` 경고만 낸다. 나중에 YAML 한 줄 고치면 끝.

---

## 1. 계층 구조

```
masters/
├── SCHEMA.md              ← 이 문서 (스키마 정의)
├── _base/
│   └── sap_defaults.yaml  ← 전 거래처 공통 고정값 + 전송 필드 목록(현 36개)
├── customers/
│   ├── msc.yaml           ← 거래처 1개 = 파일 1개
│   ├── kl.yaml
│   └── ygjp.yaml
└── refs/
    └── *.csv              ← 참조표 (품번→값 매핑 등). 없으면 없는 대로 동작
```

**해석 순서**: `_base` → `extends` 로 병합 → 거래처 파일이 덮어씀.
거래처 파일에 없는 필드는 `_base` 값이 그대로 쓰인다.

---

## 2. 실행 파이프라인

엔진은 아래 7단계를 **순서대로** 돈다. 각 단계는 마스터가 시킨 것만 한다.

```
① EXTRACT   Claude 가 문서를 읽어 RawPO(원문 값) 생성      ← extraction.hints
② SPLIT     RawPO 를 오더 단위로 분할                       ← split
③ CONTEXT   header / shipment / line 네임스페이스 조립      ← (엔진 고정)
④ TABLES    결정표 평가 → 파생변수(_xxx) 생성               ← tables
⑤ RULES     매핑 규칙 평가 → 규칙 결과 생성                 ← rules
⑥ FIELDS    전송 필드 전부를 렌더 → 행(row) 완성            ← fields
⑦ VALIDATE  필수값·길이·체크 검증 → 오류/경고 부착          ← fields.required, checks
```

④가 ⑤보다 먼저인 이유: 결정표의 파생변수를 규칙과 필드에서 쓰기 때문.
⑤끼리는 서로 참조할 수 없다 (순환 방지). 필요하면 `expr` 에서 조합한다.

---

## 3. 컨텍스트 네임스페이스

`fields` / `rules` / `tables` 에서 참조 가능한 이름은 아래가 전부다.

| 네임스페이스 | 의미 | 예 |
|---|---|---|
| `header.*` | 문서 헤더에서 읽은 원문 | `header.po_number`, `header.brand_text` |
| `shipment.*` | 분할 단위(출하처 등)에서 읽은 원문 | `shipment.ship_to_text` |
| `line.*` | 품목 라인에서 읽은 원문 | `line.item_code`, `line.quantity` |
| `_xxx` | **결정표가 만든 파생변수** | `_city`, `_pack_base` |
| `<규칙명>` / `<규칙명>.<반환키>` | 규칙 결과 | `brand_code`, `ref_codes.b_code` |

> `header/shipment/line` 의 하위 키는 **추출 스키마**(`extraction`)가 정의한다.
> 거래처마다 다를 수 있으나, 아래 **표준 키**를 우선 쓴다.

### 3.1 표준 키 (거래처 공통 어휘)

```
header:    po_number, po_date, brand_text, currency_text, incoterms_text,
           payment_terms_text, ship_to_text, packing_spec, remark_default
shipment:  ship_to_text, ship_by_text, remark
line:      line_no, posex, item_code, our_item, description,
           quantity, unit_price, net_value, delivery_date, brand_text, remark
```

- `item_code` = **우리(YG) 품번** → 보통 `MATNR`
- `our_item` = **거래처 품번** → 보통 참조표 조회 키
- 거래처 문서의 컬럼명이 무엇이든 이 두 개로 정규화해서 담는다.
- 표준 키로 안 잡히는 값은 `header.extra.*` 에 자유롭게 담을 수 있다.

---

## 4. 섹션별 스키마

### 4.0 최상위 키 (거래처 파일) ★

거래처 YAML 의 최상위에 올 수 있는 키는 **아래가 전부다.** 그 외 키는 로딩 실패(오류).

| 키 | 필수 | 타입 | 의미 |
|---|---|---|---|
| `version` | ✅ | int | 이 YAML 이 따르는 스키마 세대. 현재 `1` 또는 `2` |
| `meta` | ✅ | map | §4.1 |
| `extends` | — | list[str] | 병합할 베이스. 예: `[_base/sap_defaults]`. 생략 시 병합 없음 |
| `extraction` | ✅ | map | §4.2 |
| `split` | — | map | §4.3. 생략 시 `{ by: none }` |
| `tables` | — | map | §4.4. 결정표가 없으면 생략 |
| `rules` | — | map | §4.5. 규칙이 없으면 생략 |
| `fields` | ✅ | map | §4.6 |
| `grid` | — | map | §4.8 |
| `checks` | — | list | §4.9 |

- `version` 은 **엔진 동작을 바꾸지 않는다.** 호환성 추적·마이그레이션 판단용 기록이다.
  값이 다르다고 로딩을 막지 않는다 (미래 세대가 생기면 그때 분기).
- `extends` 경로는 `masters/` 기준 상대경로이며 **확장자를 쓰지 않는다.**
- 주석(`#`)은 어디에나 쓸 수 있다. 파서가 무시한다.

### 4.1 `meta`

```yaml
meta:
  code: MSC              # 거래처 식별자 (파일명과 일치)
  name: "MSC Industrial Supply"
  customer_no: "100249"  # 고객코드
  owner: "이름/부서"      # 규칙 책임자. 변경 승인 주체
  status: active         # active | draft | disabled
  file_types: [htm]      # 안내용. 업로드 차단 안 함
```

### 4.2 `extraction` — Claude 에게 줄 문서 구조 설명

```yaml
extraction:
  input: text            # text | image | auto
  page_limit: 40
  hints: |
    (자연어로 문서 구조를 설명. 어떤 라벨 아래 어떤 값이 있는지,
     혼동하기 쉬운 컬럼이 무엇인지. 값 변환은 지시하지 않는다.)
```

**규칙**: `hints` 에 "코드로 바꿔라", "날짜를 YYYYMMDD로" 같은 **변환 지시를 쓰지 않는다.**
변환은 전부 `rules`/`fields` 의 몫이다.

### 4.3 `split` — 1문서 → N오더

```yaml
split:
  by: none | shipment | <키>
  label: "출하처(Shipment)별로 오더를 나눈다"   # 선택. 화면 표시용
  description: |                                # 선택. 문서화용
    화면에는 한 그리드로 통합해 보여준다.
```

`none` 이면 문서 1부 = 오더 1건. `shipment` 면 추출된 shipment 수만큼 오더가 생긴다.
화면에는 항상 한 그리드로 통합되고, 행마다 다른 값(BSTKD 등)만 달라진다.

> `label` / `description` 은 **엔진이 쓰지 않는다.** 화면·문서 생성용이다.
> 이 문서 전반에서 `label` `description` `explain` 은 항상 이 성격이다.

### 4.4 `tables` — 결정표 (여러 값을 한 번에 결정)

```yaml
tables:
  <표이름>:
    label: "화면에 보여줄 이름"
    description: "선택"
    scope: header | shipment | line     # 평가 단위
    when:                                # 조건 컬럼 (N개)
      - source: shipment.ship_to_text
        op: contains_ci | equals | equals_ci | regex | starts_with
        fallback_source: header.ship_to_text   # 선택. source 가 비면 이걸 본다
        label: "출하처 블록에 포함"              # 선택. 화면 컬럼 머리글
    then: [KUNNR2, _city, _pack_base]    # 결과 컬럼 (N개). _접두사 = 파생변수
    rows:
      - { when: ["ELKHART"], then: ["100249", "ELKHART", "C"] }
    on_no_match:
      action: error | warn | default
      value: [ ... ]                     # action: default 일 때
      message: "사용자에게 보여줄 문구"
```

- `then` 에 **SAP 필드명**을 쓰면 그 필드가 바로 채워진다.
- `_` 로 시작하면 **파생변수**로만 남고 전송되지 않는다.
- 행은 **위에서부터** 평가하고 첫 일치에서 멈춘다 (우선순위 = 작성 순서).
- `rows[].when` 의 길이는 `when` 컬럼 수와, `rows[].then` 의 길이는 `then` 컬럼 수와 **같아야 한다.**

### 4.5 `rules` — 값 매핑

공통 키: `kind`(필수), `label`, `description`, `on_no_match`.
원문을 읽는 `kind`(`keyword_map` / `value_map` / `regex_extract`)는 아래 공통 옵션도 쓸 수 있다.

| 공통 옵션 | 의미 |
|---|---|
| `source` | 읽을 경로. 예: `line.brand_text` |
| `fallback_source` | `source` 가 비었을 때 대신 읽을 경로 (선택) |
| `case_insensitive` | 대소문자 무시 비교 (기본 `false`) |

| `kind` | 용도 | 필수 키 |
|---|---|---|
| `keyword_map` | 원문에 키워드가 **포함**되면 값 결정 (위에서부터) | `source`, `entries[].contains/value` |
| `value_map` | 원문과 **완전 일치**하면 값 결정 (대량 매핑표) | `source`, `entries[].equals/value` |
| `lookup` | 참조표(CSV) 조회 | `table_file`, `key`, `key_column`, `return[]` |
| `regex_extract` | 원문에서 부분 추출 | `source`, `pattern`, `group` |
| `fixed` | 상수 (문서화 목적) | `value` |

`lookup` 전용 옵션:

| 키 | 의미 |
|---|---|
| `optional` | `true` 면 **참조표 파일이 없어도 로딩·실행이 성공**하고, 조회 결과는 빈값이 된다. 기본 `false`(파일 없으면 오류) |

```yaml
rules:
  brand_code:
    kind: keyword_map
    source: header.brand_text
    case_insensitive: true
    entries:
      - { contains: "HERTEL", value: "38" }
    on_no_match: { action: error, message: "브랜드를 찾을 수 없습니다" }
```

`on_no_match.action`: `error`(전송 차단) / `warn`(경고, 전송 가능) / `default`(값 지정) / `empty`(빈값).
`message` 안의 `{키}` 는 컨텍스트 값으로 치환된다 (예: `"참조표에 없는 품번입니다: {our_item}"`).

### 4.6 `fields` — 전송 필드 매핑 ★

**`_base/sap_defaults.yaml` 의 `field_specs` 키 전부를 선언해야 한다.** 누락은 CI 실패.
(현재 36개. 현업 협의로 줄어들면 `_base` 만 고치면 된다. **개수를 코드에 쓰지 않는다.**)

| `from` | 의미 | 예 |
|---|---|---|
| `const` | 고정값 | `{ from: const, value: "ZEXP" }` |
| `base` | `_base` 의 공통값 사용 | `{ from: base }` |
| `doc` | 문서에서 읽은 원문 | `{ from: doc, path: line.item_code }` |
| `table` | 결정표 결과 | `{ from: table, table: ship_to_routing }` |
| `rule` | 규칙 결과 | `{ from: rule, rule: brand_code }` |
| `expr` | 식으로 조합 | `{ from: expr, expr: '...' }` |
| `gen` | 생성기 | `{ from: gen, generator: line_no_x10 }` |

공통 옵션:

```yaml
MATNR:
  from: doc
  path: line.item_code
  fallback: line.our_item      # path 가 비면 이걸 사용
  required: true               # 비면 🔴 전송 차단
  format: integer | decimal3 | date_yyyymmdd | upper | trim
  default: ""                  # 최종 폴백
  explain: "화면 툴팁·규칙 카드에 표시할 설명"
  todo: "값 미확정 — SAP 담당 확인 필요"   # ← 값이 안 정해졌을 때
```

- `from: table` 은 그 결정표의 `then` 에 **해당 필드명이 있을 때만** 유효하다.
- `from: rule` 이 여러 반환키를 갖는 규칙을 가리키면 `key:` 로 하나를 고른다.
  단일 값 규칙이면 생략한다. 같은 규칙을 여러 필드가 가리켜도 된다 (KL 의 `ZPKRE2`/`EMPST`).

> **`todo` 가 원칙 2의 장치다.** 값이 미정이면 `todo` 를 달고 진행한다.
> 스키마 검증이 목록으로 뽑아주므로 나중에 한 번에 확정하면 된다.
> `todo` 가 달려 있어도 **엔진은 정상 동작한다.** 전송을 막지 않는다.

### 4.7 `expr` — 허용 함수 (화이트리스트, 이게 전부)

```
join(sep, list)          compact(list)        concat(a, b, ...)
upper(s)  lower(s)  trim(s)
if(cond, a, b)           coalesce(a, b, ...)
contains(s, sub)         replace(s, from, to)
substr(s, start, len)    pad(s, len, ch)
```
임의 코드 실행은 불가. 파서가 화이트리스트 밖 호출을 만나면 로딩 자체가 실패한다.
리터럴은 문자열·숫자·`[ ]` 리스트만 허용한다. 빈 문자열은 거짓으로 취급한다.

### 4.8 `grid` — 검수 화면

```yaml
grid:
  pinned: [BSTKD, MATNR]    # 좌측 고정
  hidden: [VBELN, BATCH]    # 화면에서만 숨김. 전송 JSON 에는 "" 로 포함
  width:  { MATNR: 140 }
```

### 4.9 `checks` — 거래처별 추가 검증

```yaml
checks:
  - id: shipment_total_match
    label: "출하처별 수량 합계 = 요약표 합계"
    severity: error | warn
    description: "선택"
```

`id` 는 엔진이 구현한 체크 함수의 이름이다. **거래처 이름이 아니라 검증 로직의 이름**이므로
다른 거래처도 같은 `id` 를 재사용할 수 있다. 미구현 `id` 는 로딩 시 오류.

### 4.10 `_base/sap_defaults.yaml` 구조 ★

베이스 파일은 거래처 파일과 **스키마가 다르다.** 최상위 키는 둘뿐이다.

| 키 | 필수 | 의미 |
|---|---|---|
| `sap_defaults` | ✅ | `{필드명: 값}` — `from: base` 가 참조하는 공통 고정값 |
| `field_specs` | ✅ | `{필드명: 스펙}` — **전송 필드의 유일한 원천.** 선언 순서 = 전송·화면 컬럼 순서 |

`field_specs` 의 스펙:

| 키 | 필수 | 의미 |
|---|---|---|
| `label` | ✅ | 한글 이름 (화면 헤더) |
| `sheet` | — | 업로드 양식의 영문 헤더 |
| `max_len` | — | 최대 길이. 초과 시 ⑦ VALIDATE 에서 경고 |
| `type` | — | `date` \| `decimal`. 생략 시 문자열 |
| `added` | — | 추가 이력 메모 |

> **필드 개수·목록·순서는 전부 이 파일에서 읽는다.** 코드·문서에 개수를 적지 않는다.
> `sap_defaults` 에 없는 필드를 `from: base` 로 참조하면 로딩 오류.

---

## 5. 신규 거래처 추가 절차 (코드 0줄)

```
1. cp masters/customers/_template.yaml masters/customers/<코드>.yaml
2. meta 채우기
3. extraction.hints 작성 (샘플 발주서 보며 문서 구조 설명)
4. tables / rules 작성 (분기·매핑이 있으면)
5. fields 전부 선언 — 모르는 값은 const "" + todo
6. python scripts/validate_masters.py     ← 스키마·커버리지 검증
7. python scripts/parse_one.py <샘플> --customer <코드>
8. 기존 결과지와 diff → 맞을 때까지 YAML 만 수정
```

**엔진 코드는 건드리지 않는다.** 새 `kind` 나 새 `format` 이 필요할 때만 코드를 고치고,
그때는 이 문서에 추가한다.

---

## 6. 변경 관리

| 항목 | 방침 |
|---|---|
| 변경 단위 | YAML 파일 1개 = 거래처 1개 |
| 승인 | `meta.owner` 승인 후 반영 (Git PR 또는 대장 기록) |
| 이력 | Git 이력이 곧 규칙 변경 이력 |
| 검증 | `validate_masters.py` 를 CI/커밋 훅에서 강제 |
| 회귀 | 거래처별 골든 테스트 — 규칙 바꾸면 기존 결과와 diff 확인 |
| 화면 반영 | 규칙 미리보기 카드는 **YAML 에서 자동 생성** → 문서-실동작 불일치 없음 |

### 6.1 관리 UI 필요 여부 — 현재 결론: **불필요**

거래처 3곳 · 변경 빈도 낮음 · 변경자는 시스템 담당자 → YAML + Git 으로 충분.
아래 중 **2개 이상** 해당하면 그때 도입한다.

- 거래처 20곳 초과
- 현업이 직접 규칙을 바꿔야 함
- 월 5건 이상 규칙 변경
- 참조표 행 수 1,000건 초과 → 이건 UI 보다 **DB 전환**이 먼저

---

## 7. 스키마 검증 규칙 (`validate_masters.py`)

| # | 검사 | 실패 시 |
|---|---|---|
| 1 | `_base` 의 전송 필드가 거래처 파일에 **전부 선언**됐는가 | 오류 |
| 2 | `from` / `kind` / `op` 가 허용 목록에 있는가 | 오류 |
| 3 | 참조하는 `table`/`rule` 이 존재하는가 | 오류 |
| 4 | `expr` 이 화이트리스트 함수만 쓰는가 | 오류 |
| 5 | `path` 가 추출 스키마에 있는 키인가 | 경고 |
| 6 | 결정표에 도달 불가 행 / 중복 조건이 있는가 | 경고 |
| 7 | `on_no_match` 가 선언됐는가 | 경고 |
| 8 | `todo` 가 달린 필드 목록 | 리포트 |
| 9 | `meta.owner` 가 비었는가 | 경고 |
