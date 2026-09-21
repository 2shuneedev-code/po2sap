# 규칙 마스터 스키마 — PO2SAP 규칙 관리 아키텍처

> **이 문서가 규칙 관리의 단일 원천이다.**
> 거래처 규칙은 코드가 아니라 이 스키마를 따르는 **선언(YAML)** 으로만 존재한다.
> 엔진은 스키마를 해석할 뿐, 거래처 이름을 알지 못한다.
> 버전 v2 · 2026-09-21 (§2.1-2 · §3.1 값 포장 · §4.2 `chunking` 개정)

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
│                            + 추출 기본값(`extraction_defaults`, §4.2)
├── profiles/
│   ├── standard.yaml      ← 대부분의 거래처가 그대로 쓰는 필드 매핑
│   └── generic.yaml       ← 전용 규칙이 없는 거래처의 최소 설정
├── customers/
│   ├── msc.yaml           ← 거래처 1개 = 파일 1개. **다른 것만** 적는다
│   ├── kl.yaml
│   └── ygjp.yaml
└── refs/
    ├── brand_master.csv   ← SAP 원본 (읽기 전용, 재추출로 통째 교체)
    ├── brand_keys.csv     ← 사람이 채우는 원문 키 (발주서 문구 → 코드)
    └── *.csv              ← 그 밖의 참조표. 없으면 없는 대로 동작
```

**참조표를 둘로 나눈 이유**: SAP 이 주는 것은 `코드 → 이름`뿐이고, 시스템에 필요한
`발주서 원문 → 코드`의 **원문 키는 SAP 에 없다.** 사람이 채워야 하는 값이다.
한 파일에 섞으면 SAP 을 다시 뽑을 때 사람 작업분이 날아간다. 나눠 두면
`brand_master.csv` 를 통째로 갈아끼워도 `brand_keys.csv` 는 그대로다.

참조표의 `note` 컬럼은 자유 메모다. 값이 있으면 `validate_masters` 가 리포트로
뽑아준다(§7-8) — 필드의 `todo` 와 같은 역할이다. `csv_map` 과 `lookup` 양쪽에서 본다.

> 실물을 아직 못 구해 **가짜 값으로 채워둔 참조표**는 전 행에 `note` 를 단다.
> 그러지 않으면 우연히 키가 맞는 품번이 들어왔을 때 **조용히 틀린 값이 전송된다.**

**해석 순서**: `extends` 를 **적힌 순서대로** 깔고 거래처 파일이 덮어쓴다.

```yaml
extends: [_base/sap_defaults, profiles/standard]
```

거래처 파일에 없는 것은 프로필 값이 그대로 쓰인다. 병합 규칙은 두 가지뿐이다.

| 대상 | 규칙 |
|---|---|
| `fields` · `tables` · `rules` 의 **항목 하나** | **통째로 교체.** 거래처가 `fields.KUNNR2` 를 다시 쓰면 프로필의 KUNNR2 는 사라진다 — 일부만 덮어쓸 수 없다 |
| 리스트 (`grid.hidden`, 결정표 `rows` …) | **교체.** 항목을 더하려면 전체를 다시 적는다 |

> 항목을 통째로 교체하는 이유: 깊게 합치면 프로필의 `todo`·`value` 가 거래처의
> 재정의에 섞여 `from: table` 인데 `value` 도 있는 스펙이 만들어진다.

**예외 하나** — `extraction.chunking` 은 **키 단위로 합친다**(§4.2). 성능 손잡이라
거래처가 한 값만 조절하는 일이 흔하고, 나머지를 다시 적게 하면 `_base` 의 기본값을
올려도 그 거래처만 낡은 값에 묶이기 때문이다.

### 1.1 프로필

`profiles/standard.yaml` 은 **거래처가 아니다.** `meta` 도 `extraction` 도 없고
`fields` 와 `grid` 만 있다. 값을 올리는 기준:

- 거래처 3곳 이상에서 같은 값이면 올린다
- 한 곳이라도 다르면 그 거래처가 덮어쓴다
- **거래처 고유값을 넣지 않는다** — 고객코드는 `meta.customer_no`(§3) 로 받는다

거래처가 반드시 채워야 하는 필드(KUNNR2·BSTKD·ZBRAND·ZSHCO·MATNR)는 프로필에
`todo` 를 단 빈값으로 둔다. 선언을 빠뜨려도 CI 가 막는 대신 `validate_masters` 의
TODO 리포트(§7-8)에 뜬다 — **새 거래처를 추가하다 만 상태로도 개발이 진행된다**(원칙 2).

---

## 2. 실행 파이프라인

엔진은 아래 7단계를 **순서대로** 돈다. 각 단계는 마스터가 시킨 것만 한다.

```
① EXTRACT   Claude 가 문서를 읽어 RawPO(원문 값) 생성      ← extraction.hints
② SPLIT     RawPO 를 오더 단위(order unit)로 분할            ← split
③ CONTEXT   header / shipment / line 네임스페이스 조립      ← (엔진 고정)
④ TABLES    결정표 평가 → 파생변수(_xxx) 생성               ← tables
⑤ RULES     매핑 규칙 평가 → 규칙 결과 생성                 ← rules
⑥ FIELDS    전송 필드 전부를 렌더 → 행(row) 완성            ← fields
⑦ VALIDATE  필수값·길이·체크 검증 → 오류/경고 부착          ← fields.required, checks
```

④가 ⑤보다 먼저인 이유: 결정표의 파생변수를 규칙과 필드에서 쓰기 때문.
⑤끼리는 서로 참조할 수 없다 (순환 방지). 필요하면 `expr` 에서 조합한다.

> ①은 **LLM 호출 1회를 뜻하지 않는다.** 큰 문서는 OUTLINE 1회 + LINES N회로
> 나뉘어 불리고 병합된 뒤에 `RawPO` 가 된다. 호출 분할·병합 설계는 `design.md`
> §3.3 이며 여기에 다시 쓰지 않는다. ②~⑦은 병합이 끝난 `RawPO` 만 본다.

### 2.1 ② SPLIT 규약 — 1문서 → N오더

엔진은 `RawPO` 를 **오더 단위(order unit)** 의 목록으로 편다. 이후 ③~⑦은 오더 단위마다 1회씩 돈다.

| `split.by` | 오더 단위 | `shipment.*` 네임스페이스 |
|---|---|---|
| `none` | 문서 전체 1건. 품목은 `RawPO.lines` | 전부 빈 값 |
| `shipment` | `RawPO.shipments` 의 항목 1개 = 오더 1건 | 해당 shipment 의 값 |

**`split.by: shipment` 일 때**

1. **라인 소속** — 품목은 `shipments[i].lines` 에서 가져온다. 추출 단계에서 이미
   출하처 블록별로 나뉘어 들어오므로 엔진이 라인을 재배정하지 않는다.
2. **문서 상단 요약표는 품목으로 추출하지 않는다.** `RawPO.lines` 는 비어 있다.
   요약표에서 읽는 것은 **인쇄된 합계(`totals`)뿐**이고, 그 값이 `checks` 의
   합계 대조(요약표 합계 = 출하처별 합계)에 쓰인다.
   > 예전에는 요약표를 품목으로 전부 받아 `RawPO.lines` 에 담았다. 오더 생성에
   > 쓰이지 않으면서 **출력 토큰의 절반**을 먹었고(실물 MSC 발주서에서 613줄),
   > 실제로 쓰인 것은 합계 한 줄이었다. 합계만 받는다.
3. **`shipments` 가 비어 있으면** — 🔴 오류. 분할 대상을 하나도 찾지 못한 것이다.
4. **`shipments` 가 1건이면** — 단일 출하처 문서다. 정상이며 오더도 1건이다.
5. **헤더 폴백** — `shipment.*` 가 비면 같은 이름의 `header.*` 로 폴백한다
   (`tables.when.fallback_source` 가 그 선언 수단이다).

**공통 (`split.by` 무관)**

6. **`line_no`** 는 오더 단위 **안에서** 1부터 센다. 문서 전체 통번호가 아니다.
   **추출이 청크로 나뉘어도 마찬가지다** — 병합이 끝난 뒤 위치 순서대로 다시 매긴다.
   모델이 돌려준 번호는 청크 안에서만 센 값이므로 그대로 쓰지 않는다.
7. **`POSEX`** 는 ⑥ FIELDS 에서 오더 단위마다 다시 매긴다. 원문 `line.posex` 가 있으면
   그 값을, 없으면 `gen: line_no_x10` 같은 생성기가 정한다. **⑤ 이전 단계에서 만들지 않는다.**
8. **`BSTKD`** 는 오더 단위마다 달라진다 — 같은 문서에서 나온 오더를 구분하는 유일한 키다
   (전송 페이로드에는 `batch_id` 도 파일명도 들어가지 않는다).
9. **파생변수(`_xxx`)** 는 오더 단위 안에서만 유효하다. 오더 간에 넘기지 않는다.

---

## 3. 컨텍스트 네임스페이스

`fields` / `rules` / `tables` 에서 참조 가능한 이름은 아래가 전부다.

| 네임스페이스 | 의미 | 예 |
|---|---|---|
| `meta.*` | 거래처 마스터의 `meta` 값 (§4.1) | `meta.customer_no`, `meta.code` |
| `header.*` | 문서 헤더에서 읽은 원문 | `header.po_number`, `header.brand_text` |
| `shipment.*` | 분할 단위(출하처 등)에서 읽은 원문 | `shipment.ship_to_text` |
| `line.*` | 품목 라인에서 읽은 원문 | `line.item_code`, `line.quantity` |
| `_xxx` | **결정표가 만든 파생변수** | `_city`, `_pack_base` |
| `<규칙명>` / `<규칙명>.<반환키>` | 규칙 결과 | `brand_code`, `ref_codes.b_code` |

> `header/shipment/line` 의 하위 키는 **추출 스키마**(`extraction`)가 정의한다.
> 거래처마다 다를 수 있으나, 아래 **표준 키**를 우선 쓴다.

**`meta.*` 로 참조할 수 있는 것**: `meta.code` · `meta.customer_no` · `meta.name`.
문서에서 읽는 값이 아니라 마스터에 적힌 값이라 항상 채워져 있다. 덕분에
판매처(KUNNR1)·최종고객(KUNNR3)처럼 "고객코드 그대로"인 필드를 프로필에 한 번만
적어두면 거래처마다 다시 쓰지 않아도 된다.

### 3.1 표준 키 (거래처 공통 어휘)

> **이 목록이 추출 스키마의 단일 원천이다.** `backend/app/extraction/schema_builder.py`
> 와 `backend/app/domain/models.py` 는 여기에 맞춘다. 반대 방향으로 맞추지 않는다.
> 키를 추가·변경할 때는 **이 절을 먼저 고치고** 코드를 따라오게 한다.

```
header:    po_number, po_date, requested_date,
           brand_text, order_text,
           ship_to_text, bill_to_text,
           currency_text, incoterms_text, payment_terms_text,
           packing_spec, remark_default

shipment:  shipment_no, receiving_loc, ship_to_text, ship_by_text, remark

line:      line_no, posex,
           item_code, our_item, description,
           quantity, unit, unit_price, net_value,
           delivery_date, ship_to_text, brand_text, remark
```

**품번 두 개를 혼동하지 않는다** — 거래처마다 컬럼명이 반대인 경우가 있다.

- `item_code` = **우리(YG) 품번** → 보통 `MATNR`
- `our_item` = **거래처 품번** → 보통 참조표 조회 키
- 거래처 문서의 컬럼명이 무엇이든 이 두 개로 정규화해서 담는다.
  (MSC 는 `Your Item Number` 가 `item_code`, `Our Item Number` 가 `our_item` 이다.)

**키별 주의**

| 키 | 내용 |
|---|---|
| `po_number` | 거래처 발주번호. 문서가 `Purchase Order ID` 등 다른 이름을 써도 **이 키로 정규화**한다 |
| `order_text` | 브랜드·특기사항이 적힌 헤더 부근 원문 블록. 브랜드 키워드 탐색용 |
| `packing_spec` / `remark_default` | 문서 하단 포장 지시·공통 비고 원문 |
| `posex` | 문서에 인쇄된 품목 번호 원문. 없으면 비운다 — **생성은 ⑥ FIELDS 의 몫** |
| `net_value` | 라인 합계금액. `unit_price`(단가) 와 반드시 구분한다 |
| `delivery_date` | 라인별 납기. 라인별 납기가 없으면 비우고 `header.requested_date` 로 폴백한다 |
| `unit` | EA / PCS 등 단위 원문 |

**라인 폴백** — `line.ship_to_text` · `line.brand_text` · `line.delivery_date` 는
품목마다 다를 수 있어 라인에도 둔다. 비어 있으면 같은 이름의 `header.*` 로 폴백한다
(`fields.*.fallback` 으로 선언).

**표준 키로 안 잡히는 값**은 `extraction.extra_fields`(§4.2) 로 선언하고
`header.extra.*` / `line.extra.*` 로 참조한다. 코드 수정은 필요 없다.

### 3.2 값 포장 — 값과 근거를 어떻게 받는가 ★

표준 키의 **값 하나**가 어떤 모양으로 오는지는 두 가지다. 어느 쪽이든
규칙·필드에서 보는 이름(`line.quantity` 등)은 같다 — 포장은 엔진이 벗긴다.

**(가) header · shipment 의 값** — 값마다 따로 포장한다.

```json
"po_number": { "value": "7588650", "src": 12, "confidence": 0.97 }
```

| 키 | 필수 | 내용 |
|---|---|---|
| `value` | ✅ | 추출한 값. 못 찾으면 `null` |
| `src` | ✅ | 그 값이 있는 **원문 줄 번호** (전처리 텍스트의 통번호, 1-기준) |
| `src_end` | | 값이 여러 줄에 걸칠 때의 마지막 줄 (주소 블록 등) |
| `confidence` | ✅ | 0.0~1.0 |

**(나) line(품목)** — 한 줄이 한 원문 줄에서 오므로 **앵커를 줄 단위로 하나만** 둔다.

```json
{ "src": 412, "confidence": 0.97,
  "our_item": "09876543", "item_code": "YG-EM0600",
  "description": "END MILL 6MM 4FL", "quantity": "10", "unit_price": "12.50" }
```

- 값 필드는 **평평한 스칼라**다. `{value, …}` 로 다시 싸지 않는다.
- **없는 필드는 아예 넣지 않는다.** `null` 로 채우지 않는다.
  필수는 `src` · `confidence` 둘뿐이다.
- 한 품목이 두 줄 이상에 걸치면 `src_end` 를 함께 준다.
- `line_no` 는 **받지 않는다.** 병합 후 엔진이 매긴다 (§2.1-6).

> 왜 나눴나. 품목 줄은 문서에서 가장 많고, 같은 원문 한 줄이 품번·품명·수량·
> 단가의 근거를 동시에 맡는다. 필드마다 근거를 되풀이하면 그 한 줄이
> 5번 복사되어 나온다. 실측으로 품목 1줄이 1,260자였고, 그 때문에
> `max_tokens` 안에 40줄밖에 안 들어갔다.

**`page` 는 모델에게 묻지 않는다.** `src` 에서 코드가 역산한다 — 파생 사실을
LLM 에게 시키지 않는다(원칙 3). `ExtractedValue.page` 는 계속 존재하되
엔진이 채운다.

**`src` 가 근거인 이유와 대조 방법**은 `design.md` §3.3.5 · §3.4 다.
여기에 다시 쓰지 않는다.

---

## 4. 섹션별 스키마

### 4.0 파일 최상위 키

```yaml
version: 2                     # 이 파일의 스키마 리비전 (정수, 필수)
extends: [_base/sap_defaults]  # 병합할 조각 (§1)
meta: { ... }
extraction: { ... }
split: { ... }
tables: { ... }                # 없으면 생략 가능
rules: { ... }                 # 없으면 생략 가능
fields: { ... }                # 필수
grid: { ... }
checks: [ ... ]                # 없으면 생략 가능
```

`version` 은 **이 스키마 문서의 리비전**이다. 구조가 바뀌어 기존 파일을 손봐야 할 때
올린다. 값 변경(코드·매핑 추가)으로는 올리지 않는다 — 그건 Git 이력이 기록한다.
**위 목록에 없는 최상위 키는 오류다.**

`_base/sap_defaults.yaml` 이 병합해 올리는 `sap_defaults` · `field_specs` ·
`extraction_defaults` 는 위 목록의 예외다 (거래처 파일에 직접 쓰지 않는다).

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

#### `chunking` — 큰 문서를 몇 번에 나눠 읽을지 ★

문서 1건이 LLM 1회 호출의 출력 한도를 넘으면 구간으로 나눠 부른다.
**경계 기준과 크기를 코드가 아니라 여기서 정한다** (원칙 1 — 코드는 거래처를 모른다).

기본값은 `_base/sap_defaults.yaml` 의 `extraction_defaults.chunking` 에 있고,
거래처는 **바꾸고 싶은 키만** 적는다 (§1 의 예외 — 여기만 키 단위로 합친다).

```yaml
# masters/_base/sap_defaults.yaml
extraction_defaults:
  chunking:
    enabled: true
    max_lines_per_chunk: 120     # 청크 하나에 담을 전처리 텍스트 줄 수 상한
    tokens_per_line: 80          # 품목 1줄이 만들어내는 출력 토큰 추정치
    safety_ratio: 0.7            # max_tokens 대비 실제로 쓸 비율
    header_context_lines: 40     # 청크에 함께 붙여 보낼 문서 앞머리 줄 수
```

```yaml
# masters/customers/msc.yaml — 이 거래처만 다른 값
extraction:
  chunking:
    max_lines_per_chunk: 150
```

| 키 | 기본 | 내용 |
|---|---|---|
| `enabled` | `true` | `false` 면 한 번에 다 읽는다. 작은 문서·디버깅용 |
| `max_lines_per_chunk` | 120 | 구간 1개의 전처리 텍스트 줄 수 상한. 이 값과 `LLM_MAX_TOKENS × safety_ratio / tokens_per_line` 중 **작은 쪽**을 쓴다 |
| `tokens_per_line` | 80 | 줄당 출력 토큰 추정치. 거래처 양식이 유난히 길면 올린다 |
| `safety_ratio` | 0.7 | 추정이 빗나갈 여지 |
| `header_context_lines` | 40 | 구간만 보내면 표 머리글이 없어 컬럼을 오인한다. 문서 앞머리를 함께 붙인다 |

**경계 기준(`by`)은 선언하지 않는다.** `split.by` 가 그대로 결정한다 —
`shipment` 면 출하처 블록 경계를 먼저 지키고 그 안에서 줄 수로 더 나누며,
`none` 이면 품목표 구간을 줄 수로만 나눈다. 두 곳에 같은 뜻을 적으면 어긋난다(SSOT).

분할·병합 알고리즘과 실패 처리는 `design.md` §3.3 이다. 여기에 다시 쓰지 않는다.

#### `extra_fields` — 표준 키로 안 잡히는 값 (코드 수정 없이 확장)

§3.1 표준 키에 없는 값이 필요하면 여기에 선언한다. 추출 스키마에 자동으로 끼워지고
`header.extra.<name>` / `line.extra.<name>` 으로 참조할 수 있다.

```yaml
extraction:
  extra_fields:
    - name: contract_no
      description: "계약번호. 헤더 'Contract No.' 뒤의 값"
```

| 키 | 내용 |
|---|---|
| `name` | 참조 이름. `header.extra.<name>` · `line.extra.<name>` 양쪽에 생성된다 |
| `description` | Claude 에게 줄 설명. **무엇을 어디서 읽는지**만 쓴다 (변환 지시 금지) |

- 값 형태는 표준 키와 같다 — header 쪽은 §3.2(가), line 쪽은 §3.2(나)의 평평한 스칼라.
- **먼저 §3.1 에 넣을 수 있는지 검토한다.** 두 거래처 이상에서 같은 뜻으로 쓰이면
  `extra_fields` 가 아니라 표준 키로 올린다.

### 4.3 `split` — 1문서 → N오더

```yaml
split:
  by: none | shipment | <키>
  label: "출하처(Shipment)별로 오더를 나눈다"   # 화면 표시용. 선택
  group_label: _city                            # 그리드 구분선 라벨. 선택
  description: |                                # 규칙 카드 본문. 선택
    MSC 발주서 1부가 출하처 수만큼의 오더로 쪼개진다.
```

`group_label` 은 화면에서 오더 단위를 구분하는 라벨(계약 §5 의 `_group`)로 쓸
**컨텍스트 경로**다. 결정표가 만든 파생변수를 가리키는 것이 보통이다. 생략하면
`shipment.receiving_loc` → `shipment.shipment_no` 순으로 찾고, 그것도 없으면 빈 값이다.

`none` 이면 문서 1부 = 오더 1건. `shipment` 면 추출된 shipment 수만큼 오더가 생긴다.
화면에는 항상 한 그리드로 통합되고, 행마다 다른 값(BSTKD 등)만 달라진다.

**엔진 동작은 §2.1 이 정한다.** `split.by` 가 `none` 이 아니면 추출 스키마에
`shipments[]` 블록이 생기므로, `hints` 에 **출하처 블록을 어떻게 알아보는지**와
**어느 품목표가 그 블록의 것인지**를 반드시 설명해야 한다.
`split.by` 는 **청크 경계 기준도 겸한다** (§4.2 `chunking`).

### 4.4 `tables` — 결정표 (여러 값을 한 번에 결정)

```yaml
tables:
  <표이름>:
    label: "화면에 보여줄 이름"
    scope: header | shipment | line     # 평가 단위
    when:                                # 조건 컬럼 (N개)
      - source: shipment.ship_to_text
        op: contains_ci | equals | equals_ci | regex | starts_with
        fallback_source: header.ship_to_text   # source 가 비면 이걸로 평가. 선택
        label: "출하처 블록에 포함"             # 화면 열 제목. 선택
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

### 4.5 `rules` — 값 매핑

공통 옵션 (모든 `kind`):

| 키 | 필수 | 내용 |
|---|---|---|
| `kind` | ✅ | 아래 표의 다섯 가지 중 하나 |
| `label` | | 화면(규칙 카드)에 표시할 이름 |
| `description` | | 화면에 표시할 설명 |
| `source` | `fixed`·`lookup` 외 ✅ | 평가할 컨텍스트 경로 |
| `fallback_source` | | `source` 가 비면 이 경로로 평가한다 (예: 라인 → 헤더) |
| `case_insensitive` | | `true` 면 대소문자를 무시하고 대조한다 (기본 `false`) |
| `normalize` | | 대조 **전에** 원문에 적용할 정규화. `[trim, collapse_spaces, upper, lower]` 중 선택 |
| `on_no_match` | | 아래 참조. **생략하면 경고**다 |

`entries[]` 의 각 행에는 `todo: "확인 필요"` 를 달 수 있다 — 값이 미확정인 행을
표시해 두는 용도이며 `validate_masters.py` 가 목록으로 뽑는다(§7-8). 동작에는 영향이 없다.

| `kind` | 용도 | 필수 키 |
|---|---|---|
| `keyword_map` | 원문에 키워드가 **포함**되면 값 결정 (위에서부터) | `source`, `entries[].contains/value` |
| `value_map` | 원문과 **완전 일치**하면 값 결정 (대량 매핑표) | `source`, `entries[].equals/value` |
| `csv_map` | **참조표(CSV)에서 매핑표를 읽어** 원문을 판정 | `table_file`, `key_column`, `value_column` |
| `lookup` | 참조표(CSV) 조회 — 키로 찾아 값을 가져온다 | `table_file`, `key`, `key_column`, `return[]` |
| `regex_extract` | 원문에서 부분 추출 | `source`, `pattern`, `group` |
| `fixed` | 상수 (문서화 목적) | `value` |

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

`on_no_match.message` 에는 **컨텍스트 경로의 마지막 조각**을 중괄호로 끼워 넣을 수 있다.
`{our_item}` `{brand_text}` 처럼 쓰면 실제 값으로 치환된다. 없는 이름은 오류다.

`kind: csv_map` 전용 옵션 — **매핑표가 커지면 YAML 이 아니라 CSV 에 둔다**:

```yaml
rules:
  brand_code:
    kind: csv_map
    source: header.brand_text
    table_file: refs/brand_keys.csv
    filter_column: kunnr          # meta.customer_no 와 같은 행만 본다
    key_column: text              # 원문에서 찾을 문구
    mode_column: match            # 행별 판정 방식 (contains | equals)
    value_column: zbrand          # 결정될 값
    case_insensitive: true
    value_check:                  # 결정된 값이 실제로 등록된 코드인가
      table_file: refs/brand_master.csv
      value_column: zbrand
      filter_column: kunnr
    on_no_match: { action: error, message: "브랜드를 찾을 수 없습니다: {brand_text}" }
```

| 키 | 필수 | 내용 |
|---|---|---|
| `table_file` | ✅ | `masters/` 기준 상대경로 |
| `key_column` | ✅ | 원문과 대조할 문구가 든 컬럼 |
| `value_column` | ✅ | 매칭됐을 때 결정될 값이 든 컬럼 |
| `mode_column` | | 행마다 `contains`(포함) / `equals`(완전일치)를 고르게 한다. 생략하면 전 행 `contains` |
| `filter_column` | | 이 컬럼이 `meta.customer_no` 와 같은 행만 쓴다. 거래처별 매핑표를 한 파일에 모을 때 |
| `value_check` | | 결정된 값이 다른 참조표에 등록돼 있는지 검증한다(§7-10). 등록되지 않은 SAP 코드를 전송하는 사고를 막는다 |

**행 순서가 곧 우선순위다** — 위에서부터 평가하고 첫 일치에서 멈춘다.
`contains` 행은 짧은 문구가 위에 오면 아래 행이 도달 불가가 되므로 순서에 주의한다.

> `csv_map` 과 `lookup` 은 방향이 반대다. `lookup` 은 **키를 알고** 값을 가져오고
> (품번 → 포장비고), `csv_map` 은 **원문을 훑어** 어느 행에 걸리는지 찾는다
> (발주서 문구 → 브랜드 코드). 원문 판정에 `lookup` 을 쓸 수 없다.

`kind: lookup` 전용 옵션:

| 키 | 내용 |
|---|---|
| `table_file` | `masters/` 기준 상대경로 (예: `refs/msc_ref.csv`) |
| `key` | 조회 키로 쓸 컨텍스트 경로 |
| `key_column` | CSV 에서 키로 쓸 컬럼명 |
| `return` | 가져올 컬럼 목록. `<규칙명>.<컬럼명>` 으로 참조한다 |
| `optional` | `true` 면 **참조표 파일이 없어도 정상 동작**한다 (전 행이 미매칭 처리). 기본 `false` — 파일이 없으면 오류 |

### 4.6 `fields` — 전송 필드 매핑 ★

**`_base/sap_defaults.yaml` 의 필드 전부가 선언되어야 한다.** 누락은 CI 실패.
(현재 36개. 현업 협의로 줄어들면 `_base` 만 고치면 된다.)

검사는 **병합 결과**(§1) 기준이다. 거래처 파일에는 `profiles/standard.yaml` 과
**다른 것만** 적는다 — 36개를 다시 나열하지 않는다. 거래처가 늘어날수록
손으로 유지할 선언이 선형으로 늘어나는 것을 막기 위한 규약이다.

| `from` | 의미 | 예 |
|---|---|---|
| `const` | 고정값 | `{ from: const, value: "ZEXP" }` |
| `base` | `_base` 의 공통값 사용 | `{ from: base }` |
| `doc` | 문서에서 읽은 원문 | `{ from: doc, path: line.item_code }` |
| `table` | 결정표 결과 | `{ from: table, table: ship_to_routing }` |
| `rule` | 규칙 결과 | `{ from: rule, rule: brand_code }` |
| `expr` | 식으로 조합 | `{ from: expr, expr: '...' }` |
| `gen` | 생성기 (아래 표) | `{ from: gen, generator: line_no_x10 }` |

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

**`gen` 생성기** — 엔진에 구현된 것만 쓸 수 있다. 새 생성기가 필요하면
`backend/app/mapping/row_builder.py` 와 이 표에 함께 추가한다.

| `generator` | 결과 |
|---|---|
| `line_no_x10` | 품목 순번 × 10 을 6자리로 (`1` → `"000010"`). 앞자리 0 을 보존해야 해서 문자열이다 |

> **`todo` 가 원칙 2의 장치다.** 값이 미정이면 `todo` 를 달고 진행한다.
> 스키마 검증이 목록으로 뽑아주므로 나중에 한 번에 확정하면 된다.

### 4.7 `expr` — 식 문법 ★

`expr` 은 **프로그래밍 언어가 아니다.** 값·경로·함수 호출만 있는 식이고,
연산자(`+` `==` `and` …)도 변수 대입도 제어문도 없다. 조건 분기는 `if()` 로만 쓴다.

#### 4.7.1 문법

```
expr    := value
value   := literal | list | path | call
literal := "문자열" | '문자열' | 숫자 | true | false | null
list    := "[" [ value ("," value)* ] "]"
path    := ident ("." ident)*      # 컨텍스트 참조 (§3)
call    := ident "(" [ value ("," value)* ] ")"
ident   := [A-Za-z_][A-Za-z0-9_]*
```

- **문자열**은 `"..."` 또는 `'...'`. YAML 안에서는 식 전체를 작은따옴표로 감싸고
  내부 문자열은 큰따옴표를 쓰는 것이 안전하다: `expr: 'concat(a, "-", b)'`
- **이스케이프**는 `\"` `\'` `\\` 세 개만. 그 외 백슬래시는 오류다.
- **주석·줄바꿈**은 허용하지 않는다. 한 줄로 쓴다.
- `path` 는 §3 네임스페이스(`header.*` `shipment.*` `line.*` `_파생변수`
  `<규칙명>` `<규칙명>.<반환키>`)만 가리킬 수 있다. 그 외 이름은 오류다.
- `true` / `false` / `null` / 숫자는 **예약된 리터럴**이므로 경로가 아니다.

#### 4.7.2 값과 참

| 상황 | 결과 |
|---|---|
| 없는 경로 · 추출 실패 · 매칭 실패 | `null` |
| `null` 을 텍스트로 쓸 때 | `""` (빈 문자열) |
| **거짓**으로 치는 값 | `null`, `""`, `false`, 빈 리스트 `[]`, 숫자 `0` |
| 그 밖의 모든 값 | **참** |

식의 최종 결과는 항상 문자열로 변환되어 필드에 담긴다 (`null` → `""`).

#### 4.7.3 허용 함수 (화이트리스트, 이게 전부)

| 함수 | 인자 | 반환 | 동작 |
|---|---|---|---|
| `concat(a, b, ...)` | 1+ | text | 이어붙인다. `null` 은 `""` 로 친다 |
| `join(sep, list)` | 2 (text, list) | text | 리스트를 구분자로 잇는다. `null`·`""` 항목도 그대로 낀다 — 보통 `compact` 와 함께 쓴다 |
| `compact(list)` | 1 (list) | list | `null` 과 `""` 항목을 제거한다 |
| `coalesce(a, b, ...)` | 1+ | any | 첫 번째로 비어 있지 않은 값 |
| `if(cond, a, b)` | 3 | any | `cond` 가 참이면 `a`, 아니면 `b` |
| `contains(s, sub)` | 2 (text, text) | bool | `s` 안에 `sub` 문자열이 있는가 — **부분 문자열 검사** |
| `in(value, list)` | 2 (any, list) | bool | `value` 가 리스트 **항목과 완전 일치**하는가 |
| `upper(s)` `lower(s)` `trim(s)` | 1 | text | 대문자 · 소문자 · 앞뒤 공백 제거 |
| `replace(s, from, to)` | 3 | text | 전부 치환 |
| `substr(s, start, len)` | 3 (text, num, num) | text | 0-기준 부분 문자열 |
| `pad(s, len, ch)` | 3 (text, num, text) | text | 왼쪽을 `ch` 로 채워 `len` 자리로 |
| `integer(s)` | 1 | text | 정수 표기로 정규화 (`"25.000"` → `"25"`) |
| `decimal3(s)` | 1 | text | 소수점 3자리 문자열 (`"25"` → `"25.000"`) |
| `date_yyyymmdd(s)` | 1 | text | 날짜를 `YYYYMMDD` 로 (`"2026-05-18"` → `"20260518"`) |

`integer` · `decimal3` · `date_yyyymmdd` · `upper` · `lower` · `trim` 은
§4.6 `format` 과 같은 이름·같은 동작이다. `format` 은 필드 **전체**에,
이 함수들은 식 **일부**에 적용한다는 점만 다르다.

> ⚠ **`contains` 와 `in` 을 혼동하지 말 것.**
> `contains("471,507", brand_code)` 는 `brand_code` 가 `"1"` 이어도 참이 된다
> (`"471,507"` 안에 `"1"` 이 있으므로). 코드 목록 판정은 **반드시 `in`** 을 쓴다.
> ```yaml
> expr: 'if(in(brand_code, ["471", "507"]), "A", "L")'   # ✅
> expr: 'if(contains("471,507", brand_code), "A", "L")'   # ❌ 오판
> ```

#### 4.7.4 검증

`scripts/validate_masters.py` 가 모든 `expr` 을 파싱한다. 아래는 **오류**이며 CI 가 막는다.

- 화이트리스트 밖 함수 호출
- 인자 개수·타입 불일치 (`join` 의 2번째 인자가 리스트가 아닌 경우 등)
- 파싱 불가 (연산자 사용, 괄호 불일치, 허용되지 않은 이스케이프)
- 존재하지 않는 경로 참조 (§3.1 표준 키 · `extra_fields` · 선언된 규칙/파생변수 밖)

임의 코드 실행은 불가능하다. 파서는 위 문법만 받아들이고 그 외는 거부한다.

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
  - id: shipment_total_match          # 엔진이 아는 검사 id
    label: "출하처별 수량 합계 = 요약표 합계"
    severity: error | warn
    description: "복수 출하처일 때 블록을 하나라도 놓치면 여기서 걸린다"   # 선택
```

`id` 는 엔진에 구현된 검사 이름이다. **YAML 이 새 검사를 정의할 수는 없다** —
새 검사가 필요하면 엔진에 추가하고 이 문서에 등재한다.

| `id` | 검사 |
|---|---|
| `shipment_total_match` | 출하처별 수량 합계 = 문서에 인쇄된 합계(`totals.total_qty`) (`split.by: shipment` 전용) |

> 이 검사가 **청크 누락의 최종 안전망이다.** 구간 하나를 통째로 못 읽으면
> 수량 합계가 어긋나 🔴 가 뜬다. 사람 눈으로는 없는 줄을 볼 수 없다.

---

## 5. 신규 거래처 추가 절차 (코드 0줄)

```
1. cp masters/customers/_template.yaml masters/customers/<코드>.yaml
2. meta 채우기 (code · name · customer_no · owner · file_types)
3. extraction.hints 작성 (샘플 발주서 보며 문서 구조 설명)
4. tables / rules 작성 (분기·매핑이 있으면)
5. fields — profiles/standard.yaml 과 **다른 것만** 적는다
   보통 KUNNR2 · BSTKD · ZBRAND · ZSHCO · MATNR 다섯 개다
6. python scripts/validate_masters.py     ← 스키마·커버리지 검증
7. python scripts/parse_one.py <샘플> --customer <코드>
8. 기존 결과지와 diff → 맞을 때까지 YAML 만 수정
```

5번을 다 못 채워도 6~8번은 돌아간다. 미확정 값은 프로필의 `todo` 가 그대로 남아
검증 리포트에 뜬다.

**엔진 코드는 건드리지 않는다.** 새 `kind` 나 새 `format` 이 필요할 때만 코드를 고치고,
그때는 이 문서에 추가한다. `chunking` 도 마찬가지다 — 문서가 커서 실패하면
코드가 아니라 `extraction.chunking` 값을 조절한다(§4.2).

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
| 5 | `path` 가 추출 스키마(§3.1 표준 키 + `extra_fields`)에 있는 키인가 | **오류** |
| 6 | 결정표에 도달 불가 행 / 중복 조건이 있는가 | 경고 |
| 7 | `on_no_match` 가 선언됐는가 | 경고 |
| 8 | `todo` 가 달린 필드 · 참조표의 `note` 가 달린 행 목록 | 리포트 |
| 9 | `meta.owner` 가 비었는가 | 경고 |
| 10 | `csv_map` 의 참조표가 있고 컬럼이 맞는가 · `value_check` 의 값이 전부 등록돼 있는가 | 오류 |
| 11 | `csv_map` 이 이 거래처(`filter_column`) 행을 하나라도 가지는가 | 경고 |
| 12 | `extraction.chunking` 의 키가 §4.2 목록에 있고 값이 양수인가 | 오류 |
