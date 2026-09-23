# 규칙 마스터 스키마 — PO2SAP 규칙 관리 아키텍처

> **이 문서가 규칙 관리의 단일 원천이다.**
> 거래처 규칙은 코드가 아니라 이 스키마를 따르는 **선언(YAML)** 으로만 존재한다.
> 엔진은 스키마를 해석할 뿐, 거래처 이름을 알지 못한다.
> 버전 v3 · 2026-09-22 (§4.5 `csv_choice` 신설 · `brand_keys.csv` 폐기 · §4.6 `choices` ·
> §4.5-A `brand_master.csv` 4컬럼 확정 + 오버레이(수동 편집) 신설 · KL·YGJP 브랜드 예외 반영)

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
│   └── sap_defaults.yaml  ← 전 거래처 공통 고정값 + 전송 필드 목록
│                            + 추출 기본값(`extraction_defaults`, §4.2)
├── profiles/
│   ├── standard.yaml      ← 대부분의 거래처가 그대로 쓰는 필드 매핑
│   └── generic.yaml       ← 전용 규칙이 없는 거래처의 최소 설정
├── customers/
│   ├── msc.yaml           ← 거래처 1개 = 파일 1개. **다른 것만** 적는다
│   ├── kl.yaml
│   └── ygjp.yaml
└── refs/
    ├── brand_master.csv        ← SAP 원본 4컬럼(kunnr,name1,zbrand,zbrant). 읽기 전용,
    │                              재추출로 통째 교체 (§4.5-A)
    ├── brand_master_manual.csv ← 현업이 화면에서 채우는 오버레이. SAP 재추출과 별개로
    │                              보존된다 (§4.5-A). 없으면 없는 대로 동작
    ├── currency.csv            ← 통화 원문 → ISO 3자리
    └── *.csv                  ← 그 밖의 참조표. 없으면 없는 대로 동작
```

**참조표는 SAP 이 주는 것만 둔다.** 예전에는 `brand_keys.csv`(발주서 원문 문구 →
브랜드 코드)를 사람이 채우는 두 번째 참조표로 뒀지만, **폐기했다**(v3).
이유는 두 가지다.

1. 채울 근거가 없는 행을 SAP 브랜드명으로 기계가 메꿔 놓으면 **확인되지 않은 값이
   조용히 판정에 쓰인다.** 실제로 301건이 그 상태였고, MSC 는 발주서에 찍히는 문구가
   `ACCUPRO BRAND` 가 아니라 `ACCUPRO` 였다 — 표는 채워져 있는데 안 맞는다.
2. 고객 대부분은 **등록된 브랜드가 하나뿐**이라 문구를 대조할 이유가 없다.

그래서 브랜드 판정의 **기본은 문구 대조가 아니라 후보 수**다 (§4.5 `csv_choice`).
문구로 판정하는 것은 **그렇게 해도 된다고 확인된 거래처만의 예외**이고, 공용 CSV 가
아니라 **그 거래처 파일 안에** 적는다 (§4.5 의 "거래처 전용 예외").

참조표의 `note` 컬럼은 자유 메모다. 값이 있으면 `validate_masters` 가 리포트로
뽑아준다(§7-8) — 필드의 `todo` 와 같은 역할이다. `csv_map`·`csv_choice`·`lookup`
모두에서 본다.

> **가짜 값으로 채운 참조표를 두지 않는다.** 실물을 못 구했으면 표를 만들지 말고
> **규칙 자체를 걷어내고** 그 필드를 빈값 + `required: warn` + `todo` 로 둔다(§4.5 끝).
> 우연히 키가 맞는 품번이 들어오면 **조용히 틀린 값이 전송되기** 때문이다.

**`brand_keys.csv` 폐기가 "사람이 브랜드 후보를 못 고친다"는 뜻은 아니다.**
`brand_master.csv` 자체는 여전히 SAP 원본·읽기 전용이지만, 그 옆에 사람이 직접
행을 채우는 **오버레이 파일**(`refs/brand_master_manual.csv`)을 따로 둔다.
SAP 원본을 침범하지 않으면서 오탈자 수정·신규 브랜드 추가·잘못된 후보 제외를
가능하게 하는 장치다. 상세는 **§4.5-A**.

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
`rules` · `fields` · `grid` 만 있다. 값을 올리는 기준:

- 거래처 3곳 이상에서 같은 값이면 올린다
- 한 곳이라도 다르면 그 거래처가 덮어쓴다
- **거래처 고유값을 넣지 않는다** — 고객코드는 `meta.customer_no`(§3) 로 받는다

거래처가 반드시 채워야 하는 필드(KUNNR2·BSTKD·ZSHCO·MATNR)는 프로필에
`todo` 를 단 빈값으로 둔다. 선언을 빠뜨려도 CI 가 막는 대신 `validate_masters` 의
TODO 리포트(§7-8)에 뜬다 — **새 거래처를 추가하다 만 상태로도 개발이 진행된다**(원칙 2).

`ZBRAND` 는 예외다 — 프로필에 빈 슬롯이 아니라 **`csv_choice` 규칙**이 걸려 있어
전용 파일이 없는 거래처도 후보가 하나뿐이면 자동으로 채워진다 (§4.5).

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
   > 쓰이지 않으면서 출력 토큰을 먹었고, 실제로 쓰인 것은 합계 한 줄이었다.
   > 실물 MSC 발주서(`P8033553.HTM`)에서 품목 행 1,226줄 중 **요약표가 405줄**,
   > Shipment 블록 안 품목이 821줄이었다 — **추출 대상이 1/3 줄어든다.**
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

> **거래처를 가르는 것은 `meta.customer_no`(= SAP `KUNNR`) 하나다.**
> `meta.code` 는 파일명·화면 배지용 별칭일 뿐 분기에 쓰지 않는다.
> `meta.name` 도 **표시용**이다 — 고객명의 원천은 `refs/brand_master.csv` 의
> `NAME1` 이고, `meta.name` 은 SAP 에 이름이 비어 있을 때의 폴백으로만 쓴다.
> 두 값이 다르면 `validate_masters` 가 경고한다(§7-15).

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

**공통 규칙 — 없는 값은 키를 생략한다. `null` 로 채우지 않는다.**
이것이 출력 토큰을 줄이는 핵심이다(design §3.3.1). 빈 값 하나에 `null` 4줄을
쓰면 품목 수만큼 곱해진다. 파서는 방어적으로 `null` 도 빈 값으로 흡수하지만,
**스키마가 요구하는 것은 '생략'이다.**

**(가) header · shipment 의 값** — 값마다 따로 포장한다.

```json
"po_number": { "value": "7588650", "src": 12, "confidence": 0.97 }
```

| 키 | 필수 | 내용 |
|---|---|---|
| `value` | ✅ | 추출한 값. **빈 문자열이 아닌 문자열**이다 |
| `src` | ✅ | 그 값이 있는 **원문 줄 번호** (전처리 텍스트의 통번호, 1-기준) |
| `src_end` | | 값이 여러 줄에 걸칠 때의 마지막 줄 (주소 블록 등) |
| `confidence` | ✅ | 0.0~1.0 |

- **값을 못 찾은 키는 포장째 넣지 않는다.** `{"value": null, …}` 을 만들지 않는다.
  즉 header 의 각 키는 **optional** 이고, 들어오면 그 안의 3개가 필수다.
- 규칙·필드에서 보는 결과는 같다 — 없는 키는 `null`(빈 값)로 읽힌다(§4.7.2).

**(나) line(품목)** — 한 줄이 한 원문 줄에서 오므로 **앵커를 줄 단위로 하나만** 둔다.

```json
{ "src": 412, "confidence": 0.97,
  "our_item": "09876543", "item_code": "YG-EM0600",
  "description": "END MILL 6MM 4FL", "quantity": "10", "unit_price": "12.50" }
```

- 값 필드는 **평평한 스칼라**다. `{value, …}` 로 다시 싸지 않는다.
- **없는 필드는 아예 넣지 않는다.** 필수는 `src` · `confidence` 둘뿐이다.
- 한 품목이 두 줄 이상에 걸치면 `src_end` 를 함께 준다.
- `line_no` 는 **받지 않는다.** 병합 후 엔진이 매긴다 (§2.1-6).

> 왜 나눴나. 품목 줄은 문서에서 가장 많고, 같은 원문 한 줄이 품번·품명·수량·
> 단가의 근거를 동시에 맡는다. 필드마다 근거를 되풀이하면 그 한 줄이
> 5번 복사되어 나온다. 실측으로 품목 1줄이 1,260자였고, 그 때문에
> `max_tokens` 안에 40줄밖에 안 들어갔다.

**`page` 는 모델에게 묻지 않는다.** `src` 에서 코드가 역산한다 — 파생 사실을
LLM 에게 시키지 않는다(원칙 3). `ExtractedValue.page` 는 계속 존재하되
엔진이 채운다.

**예외 — 스캔본(텍스트 레이어 없는 PDF).** 줄 번호가 존재하지 않으므로
`src` 를 요구할 수 없다. 이때만 `src` 가 빠진 변형 스키마를 쓰고 `page` 를
모델이 준다. 근거 대조도 건너뛴다. 전체 규약은 `design.md` §3.3.6.

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
  code: MSC              # 거래처 식별자 (파일명과 일치). **분기에 쓰지 않는다**
  name: "MSC Industrial Supply"   # 표시용 폴백. 원천은 brand_master.csv 의 NAME1
  customer_no: "100249"  # 고객코드(KUNNR) — 거래처를 가르는 유일한 키
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

`input` 이 `text` 가 아니거나(`image`) 문서에 텍스트 레이어가 없으면
**분할 추출을 쓸 수 없다** — 줄 번호가 없기 때문이다. 그때의 동작은
`design.md` §3.3.6 이 정한다. `page_limit` 이 그 경로의 실질적 상한이다.

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
| `kind` | ✅ | 아래 표의 여섯 가지 중 하나 |
| `label` | | 화면(규칙 카드)에 표시할 이름 |
| `description` | | 화면에 표시할 설명 |
| `source` | `fixed`·`lookup`·`csv_choice` 외 ✅ | 평가할 컨텍스트 경로 |
| `fallback_source` | | `source` 가 비면 이 경로로 평가한다 (예: 라인 → 헤더) |
| `case_insensitive` | | `true` 면 대소문자를 무시하고 대조한다 (기본 `false`) |
| `normalize` | | 대조 **전에** 원문에 적용할 정규화. `[trim, collapse_spaces, upper, lower]` 중 선택 |
| `value_check` | | 결정된 값이 다른 참조표에 등록돼 있는지 검증한다(§7-10) |
| `on_no_match` | | 아래 참조. **생략하면 경고**다 |

`entries[]` 의 각 행에는 `todo: "확인 필요"` 를 달 수 있다 — 값이 미확정인 행을
표시해 두는 용도이며 `validate_masters.py` 가 목록으로 뽑는다(§7-8). 동작에는 영향이 없다.

| `kind` | 용도 | 필수 키 |
|---|---|---|
| `keyword_map` | 원문에 키워드가 **포함**되면 값 결정 (위에서부터) | `source`, `entries[].contains/value` |
| `value_map` | 원문과 **완전 일치**하면 값 결정 (대량 매핑표) | `source`, `entries[].equals/value` |
| `csv_map` | **참조표(CSV)에서 매핑표를 읽어** 원문을 판정 | `table_file`, `key_column`, `value_column` |
| `csv_choice` ★ | **참조표에서 이 고객의 후보를 고른다** — 하나뿐이면 자동, 여럿이면 사람이 고른다 | `table_file`, `filter_column`, `value_column` |
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

#### `kind: csv_choice` — **후보가 하나면 자동, 여럿이면 비운다** ★

원문을 훑지 않는다. **이 고객에게 등록된 후보 목록**을 참조표에서 뽑아
개수로 판정한다. 브랜드(ZBRAND)가 이 방식의 기본이다.

```yaml
rules:
  brand_choice:
    kind: csv_choice
    label: "브랜드 — 이 고객에 등록된 코드"
    description: |
      SAP 브랜드 마스터에서 이 고객(kunnr) 행만 본다.
      후보가 1개면 그 값을 채우고, 2개 이상이면 **비워 두고** 검수 화면
      드롭다운에서 사람이 고른다. 추측해서 하나를 집지 않는다.
    table_file: refs/brand_master.csv
    filter_column: kunnr          # 이 컬럼이 meta.customer_no 와 같은 행만
    value_column: zbrand          # 채워질 값
    label_column: zbrant          # 드롭다운·화면에 함께 보일 설명 (선택)
    on_many:
      action: warn                # warn(기본) | empty | error
      message: "브랜드 후보가 {count}개입니다 — 검수 화면에서 고르세요"
    on_no_match:
      action: warn
      message: "이 고객에게 등록된 브랜드가 없습니다"
```

| 키 | 필수 | 내용 |
|---|---|---|
| `table_file` | ✅ | `masters/` 기준 상대경로 |
| `filter_column` | ✅ | 이 컬럼이 `meta.customer_no` 와 같은 행만 후보로 본다 |
| `value_column` | ✅ | 후보 값이 든 컬럼 |
| `label_column` | | 사람이 읽을 이름. 드롭다운에 `값 · 이름` 으로 함께 보인다 |
| `on_many` | | 후보가 2개 이상일 때. 기본 `{ action: warn }` |
| `on_no_match` | | 후보가 0개일 때. 기본 `{ action: warn }` |

**판정 규칙 — 이게 전부다.**

| 후보 수 | 결과 | severity |
|---|---|---|
| 1 | 그 값을 채운다 (`matched: true`) | 없음 |
| 2 이상 | **빈 값.** 후보 목록을 화면에 넘긴다 | `on_many` 가 정한다 (기본 🟡) |
| 0 | 빈 값 | `on_no_match` 가 정한다 (기본 🟡) |

- 후보는 **파일 순서**를 지키고 `value_column` 기준으로 **중복을 제거**한다.
- **`on_many` 에 `action: default` 는 쓸 수 없다.** 후보 여럿 중 하나를 마스터가
  집어 주는 것은 추측이다 — 그럴듯한 값은 사람이 확인 없이 넘긴다. 검증기가 막는다.
- `on_many.message` 에 쓸 수 있는 치환자는 **`{count}` 하나뿐**이다 (엔진이 후보 수로
  치환한다). `on_no_match.message` 는 다른 규칙과 같이 컨텍스트 경로를 쓴다.
- **후보 목록은 판정 결과와 별개로 화면에 넘어간다.** 자동으로 채워졌든 비었든,
  그 필드에 `choices`(§4.6)가 붙어 있으면 검수 화면은 드롭다운으로 그린다.

> **왜 문구 대조가 기본이 아닌가.** 고객 대부분은 등록된 브랜드가 하나뿐이라
> 대조할 것이 없고, 문구 대조표는 **사람이 채우기 전까지 비어 있는 것이 정상**인데
> 그걸 기계가 채워 두면 확인되지 않은 값이 조용히 판정에 쓰인다(§1).

#### `brand_master.csv` — 4컬럼 확정 · 오버레이(수동 편집) (§4.5-A) ★

**형식.** `masters/refs/brand_master.csv` 는 **4컬럼이 최종 포맷**이다.

```csv
kunnr,name1,zbrand,zbrant
100249,MSC INDUSTRIAL SUPPLY CO,38,HERTEL BRAND
```

| 컬럼 | 내용 |
|---|---|
| `kunnr` | 고객코드(KUNNR) |
| `name1` | 고객명 (SAP 원본 — `meta.name` 폴백의 원천, §3) |
| `zbrand` | 브랜드 코드 |
| `zbrant` | 브랜드명 |

`vkorg`·`vtweg` 는 **더 이상 쓰지 않는다.** SAP 브랜드 마스터가 영업조직·유통
채널과 무관하게 고객·브랜드 단위로만 등록되어 있어 두 컬럼이 항상 비거나
무의미했다 — 코드 어디에서도 참조하지 않았으므로 스키마에서 완전히 뺀다.
**헤더는 다른 참조표와 같은 관례로 소문자**(`kunnr,name1,zbrand,zbrant`)를 쓴다 —
`reftable.py`(엔진) 도 `brands.py`(화면) 도 헤더를 그대로 딕셔너리 키로 쓰고
대소문자를 바꿔 읽지 않기 때문이다. `currency.csv`·`msc_ref.csv` 가 이미 이
관례다.

> ✅ **로더 수정 완료 (2026-09-23).** 헤더를 소문자 4컬럼(`kunnr,name1,zbrand,zbrant`)
> 으로 바로잡았고, `scripts/import_brand_master.py` 의 `SCHEMA` 도 같은 4컬럼으로
> 맞췄다. `backend/app/masters/brands.py::load_master()` 는 그대로 두어도
> 맞았다 — 이미 소문자 키로 읽고 있었다. §4.5-A 의 오버레이 병합
> (`brand_master_manual.csv`)은 **아직 미구현**이다.

**오버레이 — 사람이 후보를 고치는 창구.** `brand_master.csv` 자체는 여전히
SAP 원본·읽기 전용이다(재추출 시 `import_brand_master.py` 가 통째 교체). 대신
**같은 모양의 별도 파일** `masters/refs/brand_master_manual.csv` 를 두고,
`ui/views/brands.py` 는 **이 오버레이 파일만** 쓴다.

```csv
kunnr,name1,zbrand,zbrant,action,note
100249,MSC INDUSTRIAL SUPPLY CO,205,ACCUPRO,override,"SAP 는 ACCUPRO BRAND 지만 발주서엔 ACCUPRO 로만 찍힌다 (확인 2026-09-22)"
```

| 컬럼 | 내용 |
|---|---|
| `kunnr`·`name1`·`zbrand`·`zbrant` | `brand_master.csv` 와 같은 뜻 |
| `action` | `add`(신규 후보 추가) · `override`(SAP 행의 `zbrant` 를 이 값으로 교체) · `suppress`(그 `kunnr`+`zbrand` 조합을 후보에서 뺀다 — `zbrant` 는 기록용으로만 둔다) |
| `note` | **필수, 자유 메모.** 왜 손으로 고쳤는지 — 확인 안 하고 지나치면 안 되는 값이라는 표시(CLAUDE.md "자동 생성한 매핑에 표시 생략 금지"와 같은 이유) |

**병합 규칙 — 판정에 쓰이는 것은 언제나 SAP ∪ 오버레이다.**
`table_file: refs/brand_master.csv` 를 참조하는 모든 규칙(`csv_choice`·
`csv_map`)과 화면·검증기는 **이 파일 하나만 읽지 않는다.** `refs/brand_master.csv`
를 가리키는 요청은 아래 순서로 합쳐진 결과를 돌려받는다 — 병합은
`backend/app/rules/reftable.py::load()` 안에 **파일명으로 분기하는 유일한 예외**로
둔다(브랜드가 SAP·수동 두 원천을 갖는 유일한 참조표라서다). `backend/app/
masters/brands.py::load_master()` 는 이 병합 함수를 재사용하는 얇은 래퍼로
바꾼다 — 병합 로직을 두 곳에 따로 구현하지 않는다.

1. `brand_master.csv` 전 행을 파일 순서대로 둔다.
2. 오버레이에서 `action: suppress` 인 (`kunnr`,`zbrand`) 조합을 뺀다.
3. 오버레이에서 `action: override` 인 행으로, 같은 (`kunnr`,`zbrand`) 자리의
   `zbrant`(필요하면 `name1`) 를 바꿔치기한다 — 자리는 그대로, 값만 바뀐다.
4. 오버레이에서 `action: add` 인 행을 그 `kunnr` 블록 끝에 오버레이 파일 순서대로
   덧붙인다.
5. `csv_choice` 의 "후보 수" 판정(§4.5)과 `csv_map`(YGJP 예시 B)의 대조는 모두
   이 **병합된 목록**을 본다.

**재추출과의 관계 — `import_brand_master.py` 는 오버레이를 건드리지 않는다.**
`brand_master.csv` 를 통째로 교체하는 지금 동작은 그대로다(§ "명령어"). 다만
`--dry-run` 보고에 오버레이 대조 항목을 하나 더한다 — **덮어쓰지도, 자동으로
지우지도 않는다.** 사람이 보고 오버레이 파일을 직접 정리한다.

| 오버레이 행 | 새 SAP 추출과 비교해 보고할 것 |
|---|---|
| `override` | 대상 (`kunnr`,`zbrand`) 이 새 추출에 없으면 → "고칠 원본이 사라졌습니다" 경고 |
| `suppress` | 대상이 새 추출에도 없으면 → "이미 빠졌으니 오버레이 행을 지워도 됩니다" 안내 |
| `add` | 같은 (`kunnr`,`zbrand`) 이 새 추출에 **등록되면** → "SAP 에 정식 등록됐습니다 — 오버레이를 지워도 됩니다" 안내 |

**화면 — `ui/views/brands.py` 재정의.** "매핑 표" 탭은 더 이상 문구→코드
(`brand_keys`, 폐기)를 편집하지 않는다. 이제 **그 고객의 `brand_master_manual.csv`
행**을 편집한다.

- 표는 그 고객의 **병합된 후보 전부**를 보여준다. SAP 원본 행은 회색(읽기전용)으로,
  오버레이 행은 편집 가능하게 — `action` 컬럼이 있는 행만 사람이 만든 것이다.
- "오탈자 수정" = SAP 행을 고르고 `override` 행을 새로 추가(`zbrant` 를 고친 값으로).
- "신규 브랜드 추가" = `add` 행 추가. `zbrand` 는 SAP 에 아직 없는 코드일 수 있다 —
  **그 경우 `value_check` 를 걸지 않는다**(SAP 미등록 코드를 전송 직전에야 안다는
  뜻이 아니라, 오버레이가 "다음 재추출에서 SAP 이 이 코드를 낼 것"이라는 예고이기
  때문이다). 대신 화면에 "SAP 미등록 — 재추출 전까지는 이 코드로 전송하면 SAP 이
  거부할 수 있습니다" 배지를 띄운다.
- "잘못된 후보 삭제" = `suppress` 행 추가. `brand_master.csv` 자체는 건드리지 않는다.
- 저장 전 검증: `zbrand`+`kunnr`+`action` 조합 중복 금지, `note` 필수, `action` 값이
  셋 중 하나인지, `suppress`/`override` 의 대상이 **현재 병합 전** SAP 원본에
  실제로 존재하는지(없는 것을 override/suppress 하는 것은 오류 — `add` 를 써야 한다).
- 저장은 `brand_store.set_keys()` 가 했던 것과 같은 안전장치를 그대로 쓴다 — 저장
  전 사본(`storage_dir`), 원자적 쓰기, 편집 잠금(`MASTER_EDIT_PASSWORD`), 저장 후
  Git 자동 커밋·푸시. **행 순서 보존**도 같다 — 같은 (`kunnr`,`zbrand`,`action`)
  자리가 있으면 그 자리를, 없으면 그 고객 블록 끝을 쓴다.

#### 거래처 전용 예외 — 그 거래처 파일 안에 가둔다 ★

> **2026-09-23 현재 아래 A·B·C 는 설계 참고용 예시이고, 실물 거래처 파일에는
> 아직 없다.** 사장님 지시로 msc/kl/ygjp 의 거래처 전용 규칙(결정표·csv_map·
> keyword_map·const 예외 전부)을 걷어내고 기본(`profiles/standard`, 위
> `csv_choice`)만 쓰도록 단순화했다 — "기본부터 만들어 놓고 예외는 나중에
> 정리해서 다시 얹는다." 세 거래처 모두 지금은 브랜드 후보가 여럿이라
> `csv_choice` 가 자동으로 비워 두고 사람이 검수 화면 드롭다운에서 고른다.
> 아래 A(MSC)·B(YGJP)·C(KL) 예시는 **그 예외를 다시 붙일 때의 참고 모양**이다
> (지운 원본 규칙은 이 절 이전의 git 이력에 그대로 있다).

전용 규칙은 공용 CSV 를 쓰지 않는다 — 그 거래처에서만 쓰는 값이 다른 78곳의
판정에 끼어들 이유가 없다. **세 가지 모양이 나왔다.** 셋 다 "그 거래처 파일
안에서만" 끝난다는 점은 같고, 무엇으로 판정하느냐가 다르다.

| 거래처 | 판정 근거 | 방식 |
|---|---|---|
| MSC | 발주서 **문구**(ORDERED FROM 블록)로 믿을 만하게 가릴 수 있다 | `keyword_map` (아래 A) |
| YGJP | 발주서 브랜드 문구가 **SAP 브랜드명과 거의 그대로 같다** — 별도 대조표 없이 마스터 자체를 대조표로 쓴다 | `csv_map` + `table_file: refs/brand_master.csv` (아래 B) |
| KL | 문구를 볼 것도 없이 **이 거래처는 늘 한 코드로 나간다** (업무 규칙, 확인됨) | `fields.ZBRAND` 를 `const` 로 고정 (아래 C) |

**A. MSC — 문구 키워드 대조 (확인됨)**

```yaml
# masters/customers/msc.yaml — MSC 는 ORDERED FROM 문구로 가른다 (확인됨)
rules:
  brand_code:
    kind: keyword_map
    label: "브랜드 판별 (이 거래처 전용)"
    description: "ORDERED FROM 블록 문구로 가린다. 다른 거래처와 공유하지 않는다."
    source: header.brand_text
    fallback_source: header.order_text
    case_insensitive: true
    entries:
      - { contains: "HERTEL",     value: "38"  }
      - { contains: "INTERSTATE", value: "127" }
      - { contains: "ACCUPRO",    value: "205" }
      - { contains: "CLASS C",    value: "428" }
    value_check:                       # SAP 에 없는 코드를 적어 두는 사고를 막는다
      table_file: refs/brand_master.csv
      value_column: zbrand
      filter_column: kunnr
    on_no_match:
      action: warn                     # 막지 않는다 — 드롭다운으로 고르면 된다
      message: "브랜드 문구를 인식하지 못했습니다: {brand_text} — 드롭다운에서 고르세요"

fields:
  ZBRAND:
    from: rule
    rule: brand_code                   # 값은 전용 규칙이 정하고
    choices: brand_choice              # 드롭다운 후보는 공용 csv_choice 가 준다
    required: warn
```

- **`entries` 를 CSV 로 빼지 않는다.** 거래처 하나의 몇 줄짜리 예외이고, 행 순서가
  곧 우선순위라 파일 안에 보이는 편이 안전하다. 수백 줄이 되면 그때 `csv_map` 으로
  옮기고 **그 거래처 전용 CSV** 를 만든다 (공용 표에 섞지 않는다).
- `value_check` 는 `keyword_map` · `value_map` · `csv_map` · `csv_choice` 에서 쓸 수 있다.
  선언하면 검증기가 **모든 후보 값**이 그 참조표에 등록돼 있는지 대조한다(§7-10).

**B. YGJP — SAP 브랜드명을 그대로 대조표로 쓴다**

YGJP 는 후보가 21개(§4.5-A)라 `csv_choice` 기본값만으로는 드롭다운이 너무 크고,
그런데 발주서 하단 브랜드 블록에 `"YG BRAND"` 처럼 **SAP 브랜드명(ZBRANT)과 거의
같은 문구가 원문 그대로** 찍힌다(`extraction.hints` 의 "[문서 하단 — 브랜드/포장/
비고 블록]" 참고). 그래서 **별도 대조표를 만들지 않고 `brand_master.csv` 자체를
`csv_map` 의 `table_file` 로 재사용**한다 — 키 컬럼이 `zbrant`(브랜드명)라는 점만
다르다.

```yaml
# masters/customers/ygjp.yaml
rules:
  brand_code:
    kind: csv_map
    label: "브랜드 판별 — SAP 브랜드명과 원문 완전일치"
    description: |
      발주서 하단 브랜드 블록의 원문이 이 거래처(kunnr)에 등록된 SAP 브랜드명
      (zbrant) 과 같으면 그 코드로 정한다. 별도 대조표를 두지 않고 브랜드
      마스터 자체를 대조표로 쓴다 — 그래서 브랜드명이 SAP 재추출로 바뀌면
      판정도 그대로 따라간다.
      코드 448/450/477 은 SAP 브랜드명과 실제 발주서 문구가 다르다고 알려져
      있다(예전 brand_keys.csv 의 확인 메모) — 원문 확인 전까지는 대조에
      실패하고 드롭다운(21개 후보)에서 사람이 고른다.
    source: header.brand_text
    table_file: refs/brand_master.csv   # 별도 CSV 없음 — 마스터를 그대로 대조
    filter_column: kunnr
    key_column: zbrant                  # ZBRAND 가 아니라 **브랜드명**이 대조 키다
    mode: equals                        # 전 행 완전일치 (mode_column 없음)
    value_column: zbrand
    case_insensitive: true
    on_no_match:
      action: warn                      # 21개 후보 드롭다운으로 넘어간다
      message: "브랜드 문구가 SAP 브랜드명과 다릅니다: {brand_text} — 드롭다운에서 고르세요"

fields:
  ZBRAND: { from: rule, rule: brand_code, choices: brand_choice, required: true }
  ZSHCO:
    from: expr
    expr: 'if(in(brand_code, ["471", "507"]), "A", "L")'
    explain: '브랜드 코드가 471 또는 507 이면 A, 그 외 L'
```

- `ZSHCO` 의 `expr` 은 그대로다 — `brand_code` 라는 **규칙 이름**만 같으면 되고,
  그 규칙이 `csv_map` 이든 `keyword_map` 이든 `<규칙명>` 참조는 똑같이 동작한다.
- `refs/brand_keys.csv` 는 더 이상 필요 없다. 지금 그 파일에 있던 "equals" 매핑은
  대부분 `zbrant` 값과 동일하므로 정보 손실이 아니다 — 다른 것만 §4.5-A 의
  오버레이로 옮긴다(아래 "이관 메모" 참고).

**C. KL — 고정값 (업무 규칙, 확인됨)**

KL 은 브랜드 후보가 2개(`2`=OEM BRAND, `58`=NO BRAND)지만, 문구를 볼 것도 없이
**항상 OEM(`2`)으로 나간다**는 것이 확인된 업무 규칙이다. 문구 대조도
`csv_choice` 자동판정(후보 1개일 때만 자동)도 필요 없다 — **필드를 그냥
고정한다.** 다만 드롭다운은 살려 둔다. 사람이 예외적으로 NO BRAND 를 골라야
하는 발주가 있을 수 있어서다.

```yaml
# masters/customers/kl.yaml
fields:
  ZBRAND:
    from: const
    value: "2"
    choices: brand_choice        # from: const 라 §4.6 의 "자동으로 자기 자신" 이
                                  # 붙지 않는다 — 여기선 반드시 명시해야 한다
    explain: "KL 은 브랜드 고정 2 (OEM) — 업무 규칙 확인됨. 드롭다운은 열어 둔다"
```

- `keyword_map`/`csv_map` 같은 `rules` 선언조차 필요 없다 — `fields` 한 줄이 전부다.
- `choices` 를 생략하면 안 된다. `from: rule` 이 아니므로 §4.6 의 자동 부착 규칙이
  적용되지 않고, 생략하면 드롭다운 없는 텍스트 칸이 되어 오타로 잘못된 코드가
  들어갈 수 있다.

`kind: csv_map` 전용 옵션 — **매핑표가 커지면 YAML 이 아니라 CSV 에 둔다**:

```yaml
rules:
  currency:
    kind: csv_map
    source: header.currency_text
    table_file: refs/currency.csv
    key_column: text              # 원문에서 찾을 문구
    mode_column: match            # 행별 판정 방식 (contains | equals)
    value_column: waerk           # 결정될 값
    case_insensitive: true
    on_no_match: { action: warn, message: "통화를 인식하지 못했습니다: {currency_text}" }
```

| 키 | 필수 | 내용 |
|---|---|---|
| `table_file` | ✅ | `masters/` 기준 상대경로 |
| `key_column` | ✅ | 원문과 대조할 문구가 든 컬럼 |
| `value_column` | ✅ | 매칭됐을 때 결정될 값이 든 컬럼 |
| `mode_column` | | 행마다 `contains`(포함) / `equals`(완전일치)를 고르게 한다. 있으면 이 값이 우선한다 |
| `mode` | | `mode_column` 이 없을 때 **전 행**에 적용할 기본 판정 방식. 생략하면 `contains` |
| `filter_column` | | 이 컬럼이 `meta.customer_no` 와 같은 행만 쓴다. 거래처별 매핑표를 한 파일에 모을 때 |
| `value_check` | | 결정된 값이 다른 참조표에 등록돼 있는지 검증한다(§7-10) |

**행 순서가 곧 우선순위다** — 위에서부터 평가하고 첫 일치에서 멈춘다.
`contains` 행은 짧은 문구가 위에 오면 아래 행이 도달 불가가 되므로 순서에 주의한다.

> 세 가지 방향을 혼동하지 않는다.
> · `lookup` 은 **키를 알고** 값을 가져온다 (품번 → 포장비고)
> · `csv_map` 은 **원문을 훑어** 어느 행에 걸리는지 찾는다 (통화 문구 → USD)
> · `csv_choice` 는 **원문을 보지 않고** 이 고객의 후보 수로 판정한다 (브랜드)

`kind: lookup` 전용 옵션:

| 키 | 내용 |
|---|---|
| `table_file` | `masters/` 기준 상대경로 |
| `key` | 조회 키로 쓸 컨텍스트 경로 |
| `key_column` | CSV 에서 키로 쓸 컬럼명 |
| `return` | 가져올 컬럼 목록. `<규칙명>.<컬럼명>` 으로 참조한다 |
| `optional` | `true` 면 **참조표 파일이 없어도 정상 동작**한다 (전 행이 미매칭 처리). 기본 `false` — 파일이 없으면 오류 |

**실물 참조표를 못 구했으면 `optional: true` 슬롯도 두지 않는다.** 규칙과 표를
같이 걷어내고, 그 필드를 **빈값 + `required: warn` + `todo`** 로 남긴다.

```yaml
# 실물 참조표가 들어오기 전까지의 모양
fields:
  ZPKRE2:
    from: expr
    expr: 'coalesce(_pack_base, "")'
    required: warn
    todo: "품번별 포장 추가비고 참조표 미확보 — 실물이 오면 lookup 규칙을 붙인다"
```

빈 슬롯이 남아 있으면 "표만 채우면 된다"로 보이지만, **가짜 행이 든 표**는
우연히 키가 맞는 순간 조용히 틀린 값을 내보낸다. 없는 것이 낫다(§1).

### 4.6 `fields` — 전송 필드 매핑 ★

**`_base/sap_defaults.yaml` 의 필드 전부가 선언되어야 한다.** 누락은 CI 실패.
(개수는 `_base` 가 정한다 — 이 문서에도 코드에도 숫자를 적지 않는다.)

검사는 **병합 결과**(§1) 기준이다. 거래처 파일에는 `profiles/standard.yaml` 과
**다른 것만** 적는다 — 전량을 다시 나열하지 않는다. 거래처가 늘어날수록
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
  choices: brand_choice        # 검수 화면 드롭다운 후보 (아래)
  explain: "화면 툴팁·규칙 카드에 표시할 설명"
  todo: "값 미확정 — SAP 담당 확인 필요"   # ← 값이 안 정해졌을 때
```

**`choices` — 검수 화면 드롭다운 ★**

| 항목 | 규약 |
|---|---|
| 값 | `kind: csv_choice` 규칙의 **이름**. 그 규칙의 후보 목록이 이 필드의 선택지가 된다 |
| 생략 시 | `from: rule` 이고 그 규칙이 `csv_choice` 면 **자동으로 자기 자신**이 붙는다 |
| 화면 | 자유 입력 대신 **드롭다운**으로 그린다. `label_column` 이 있으면 `값 · 이름` |
| 전송 | 드롭다운이 붙어도 전송되는 것은 `value_column` 의 **값 하나**다 |
| 후보 0개 | 드롭다운을 붙이지 않고 평범한 텍스트 칸으로 둔다 — **막지 않는다** |
| 규칙이 값을 채운 경우 | 드롭다운은 그대로 붙는다. 사람이 고쳐 넣는 것이 최종 진실이다(P5) |

후보 목록은 **한 배치가 거래처 하나**라는 전제 위에서 컬럼 전체에 같은 것이 붙는다.
계약상 전달 모양은 `contracts/api-contract.md` §5 의 `choices` 다 — 여기에 다시 쓰지 않는다.

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
| 없는 경로 · 추출 실패 · 매칭 실패 · **생략된 키** | `null` |
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

**드롭다운은 여기에 적지 않는다.** 필드의 `choices`(§4.6)가 정하고 화면은 그대로
그린다 — 화면에 거래처별 분기 코드를 두지 않기 위해서다.

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
   보통 KUNNR2 · BSTKD · ZSHCO · MATNR 다. **ZBRAND 는 보통 건드리지 않는다**
   — 후보가 하나뿐이면 자동으로 채워지고, 여럿이면 드롭다운이 뜬다(§4.5)
6. python scripts/validate_masters.py     ← 스키마·커버리지 검증
7. python scripts/parse_one.py <샘플> --customer <코드>
8. 기존 결과지와 diff → 맞을 때까지 YAML 만 수정
```

5번을 다 못 채워도 6~8번은 돌아간다. 미확정 값은 프로필의 `todo` 가 그대로 남아
검증 리포트에 뜬다.

**브랜드를 문구로 가리는 규칙은 처음부터 만들지 않는다.** 실물 발주서에서 그 문구가
**항상** 찍힌다는 것을 확인한 다음에 §4.5 의 "거래처 전용 예외"를 그 파일에 붙인다.

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

### 6.1 관리 UI 필요 여부 — 화면 1개(브랜드 오버레이)로 축소, 그 밖은 **불필요**

브랜드 매핑 화면(원문 문구 → 코드, `brand_keys.csv`)은 **v3 에서 없앴다.**
대신 `ui/views/brands.py` 는 **브랜드 마스터 오버레이**(`brand_master_manual.csv`,
§4.5-A) 편집기로 성격이 바뀌어 **남는다** — SAP 재추출 주기 사이에 오탈자·신규
브랜드·잘못된 후보를 고칠 창구가 없으면 그 기간 내내 잘못된 판정이 계속되기
때문이다. `brand_master.csv` 자체는 여전히 SAP 원본이라 사람이 고치지 않는다.

그 밖의 마스터(거래처 규칙·`shipping.csv` 등)를 위한 관리 UI는 아래 중
**2개 이상** 해당하면 그때 다시 본다.

- 거래처 20곳 초과에 **각각 전용 규칙이 필요**해짐
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
| 10 | 참조표가 있고 컬럼이 맞는가 · `value_check` 의 값이 전부 등록돼 있는가 (`csv_map`·`csv_choice`·`keyword_map`·`value_map`) | 오류 |
| 11 | 참조표에 이 거래처(`filter_column`) 행이 하나라도 있는가 | 경고 |
| 12 | `extraction.chunking` 의 키가 §4.2 목록에 있고 값이 양수인가 | 오류 |
| 13 | `csv_choice` 의 `on_many.action` 이 `default` 가 아닌가 | **오류** |
| 14 | 필드의 `choices` 가 존재하는 `csv_choice` 규칙을 가리키는가 | 오류 |
| 15 | `meta.name` 이 `brand_master.csv` 의 `NAME1` 과 다른가 | 경고 |
| 16 | `csv_choice` 의 후보가 2개 이상인 거래처 목록 (드롭다운으로 뜬다) | 리포트 |
| 17 | `brand_master_manual.csv` 의 `action` 이 `add`/`override`/`suppress` 중 하나이고 `note` 가 비어있지 않은가 | 오류 |
| 18 | `override`/`suppress` 행의 대상 (`kunnr`,`zbrand`) 이 `brand_master.csv`(SAP 원본)에 실제로 있는가 — 없으면 `add` 를 썼어야 한다 | 오류 |
| 19 | `brand_master_manual.csv` 전 행 목록 (수동 편집 감사용, §4.5-A) | 리포트 |
