# 구조 단순화 설계 v2 — 기본 2층 구조 · 템플릿 주도 매핑

> 작성 2026-09-21 · architect · **v1(같은 날 오전)을 전면 교체한다.**
> 근거: `NEXT.md` **§2-C**(2·3차 지시). §2-C 가 §2-A·§2-B 와 v1 보다 **위**다.
> 버린 것은 §6 에 모았다 — 남은 사람이 v1 을 보고 헷갈리지 않게.
>
> 핵심 한 줄: **규칙엔진은 "모든 필드를 채우는 장치"가 아니라 "예외를 처리하는 장치"다.**
>
> ⚠ **`SALES ORDER` 템플릿 실물은 아직 없다.** 템플릿 관련 설계는 전부 "올라오면
> 이렇게 동작한다"이고, **올라오기 전 동작(= `_base` 폴백)이 곧 지금 동작**이다.
> 개발은 템플릿을 기다리지 않는다(§3.4).

---

## 0. 결정 요약

번호는 `design.md` §0 의 D1~D11 에 이어 붙인다.

| # | 결정 |
|---|---|
| **D12** | **전송 필드의 목록·순서는 템플릿 2행**이 정한다. `_base` 는 **규격**(label·max_len·type·required)만 맡는다 |
| **D13** | **템플릿 1행(설명)·2행(필드명)이 곧 Claude 추출 스키마**가 된다 |
| **D14** | **선언이 없는 필드 = Claude 가 채운다.** `FIELD_NOT_DECLARED` 🔴 를 **폐지**한다 |
| **D15** | **값의 출처는 2층**이다 — [1층] 마스터·기본값·Claude(전 거래처 공통) / [2층] 거래처 예외. §1 |
| **D16** | 엔진 소관 필드는 Claude 스키마에서 뺀다. 목록을 **코드에 박지 않는다** — `fields` 선언이 있는 필드가 곧 뺄 필드(§3.2) |
| **D17** | 브랜드는 **그 고객의 브랜드 수**로 판정. 1건=자동 · 2건 이상=공란+드롭다운. "1개"의 기준은 **`brand_master.csv` 의 그 `kunnr` 행 수** |
| **D18** | **고객–VSART–ZSHCO 는 참조표 1:1:1**(`refs/shipping.csv`). 행이 없으면 **공란**(수기) |
| **D19** | **KUNNR1 = KUNNR2 = KUNNR3 = 고객코드가 기본** |
| **D20** | **템플릿 서명을 LLM 캐시 키에 넣는다.** 낡은 모양의 응답을 조용히 재생하지 않는다(§3.3) |

**뒤집는 기존 결정**

| 뒤집는 것 | 어디에 있었나 | 왜 |
|---|---|---|
| Claude 는 **원문 값만** 추출한다 (매핑은 전부 엔진) | `CLAUDE.md` §1 P1 | 필드 매칭을 Claude 가 한다. 교체문은 **§2** |
| 전송 필드 **전량**이 거래처 YAML 에 선언돼 있어야 한다 | `SCHEMA.md` §4.6 · `row_builder.py:40` | D14 |
| 브랜드는 `csv_map` 문구 대조가 기본 | `profiles/generic.yaml` · `msc/ygjp.yaml` | 자동 초벌 301건은 확인 안 된 값이다. 후보 수 판정이 기본이 된다 |
| 공용 프로필은 모르는 값을 **비워 둔다** | `CLAUDE.md` §5 | **KUNNR1/2/3 한정**으로 푼다. 나머지 필드는 금지 그대로 |

---

## 1. 값은 어디서 오는가 — 기본 / 예외 2층 ★

### 1.1 [1층] 기본 — 전 거래처 공통. **거래처별 선언이 없다**

| 필드 | 출처 | 어떻게 |
|---|---|---|
| `VSART` · `ZSHCO` | **마스터 CSV** | `refs/shipping.csv` 를 고객코드로 조회 (고객 1 : VSART 1 : ZSHCO 1). 행이 없으면 **공란**(검수 화면에서 수기) |
| `ZBRAND` | **마스터 CSV** | `refs/brand_master.csv` 의 그 고객 행이 1건이면 기본값, 2건 이상이면 **공란 + 드롭다운** |
| `KUNNR1` · `KUNNR2` · `KUNNR3` | **기본값** | 셋 다 고객코드(`meta.customer_no`) |
| `AUART` · `VKORG` · `VTWEG` | **공통 고정값** | `_base/sap_defaults.yaml` 의 `sap_defaults`. 선언 없이 적용된다(§4.2) |
| `BSTKD` · `POSEX` | **Claude** | 발주서에서 읽어 해당 칸에 넣는다 |
| **그 밖의 모든 필드** | **Claude** | 템플릿 1행(설명)·2행(필드명)을 보고 매칭 |

> 1층에는 **거래처 이름이 한 번도 등장하지 않는다**(P2). 고객마다 달라지는 것은
> 참조표를 거는 키(`meta.customer_no`) 하나뿐이다.

### 1.2 [2층] 예외 — 고객별로 **하나씩 붙여나간다**

처음부터 다 만들지 않는다. 필요한 곳에만 `customers/<code>.yaml` 에 적는다.
현재 유일한 본격 사례가 **MSC** 다.

| MSC 의 예외 | 스키마 | 1층 대비 |
|---|---|---|
| 발주서 1부가 출하처 수만큼 오더로 쪼개진다 | `split: {by: shipment}` | 1층에 없는 동작 |
| 출하지에 따라 `KUNNR2` 가 달라진다 | `tables.ship_to_routing` (결정표) | 1층의 "고객코드" 기본값을 **덮어쓴다** |
| 출하지에 따라 브랜드가 결정된다 | 같은 결정표의 `then` 에 `ZBRAND` 를 얹는다 | 1층의 **마스터 기본값을 덮어쓴다** |
| 포장비고가 출하지 + 참조표로 조합된다 | `rules.ref_codes` + `fields.ZPKRE2` | 1층에 없는 동작 |

> ⚠ **확인 필요**: 지시에는 "MSC 는 **출하지에 따라 브랜드가 결정된다**"고 되어 있으나
> 현행 `masters/customers/msc.yaml` 은 브랜드를 **ORDERED FROM 문구**로 가린다
> (`rules.brand_code` → `brand_keys.csv`). 둘은 다른 규칙이다. 어느 쪽이 운영
> 사실인지 확인 전까지 **현행(문구 판정)을 유지**하고, 결정표로 옮기는 것은
> 확인 후에 한다 → §9-1 `todo:`. 어느 쪽이든 **표현 방법은 §1.3 으로 같다.**

### 1.3 2층이 1층을 덮어쓰는 규약 ★

값 하나가 정해지는 순서. **처음 값이 나오는 곳에서 멈춘다.**

| 순위 | 어디 | 예 |
|---|---|---|
| 1 | **거래처 예외 선언** — `customers/<code>.yaml` 의 `fields`(+ `tables`·`rules`) | MSC `KUNNR2: {from: table, table: ship_to_routing}` |
| 2 | **1층 선언** — `profiles/standard.yaml` 의 `fields` | `KUNNR2: {from: expr, expr: 'meta.customer_no'}` |
| 3 | **공통 고정값** — `_base.sap_defaults` (선언 불필요) | `AUART = "ZEXP"` |
| 4 | **Claude 가 템플릿 칸에 채운 값** (`row.<필드>`) | `MATNR` · `KWMENG` · `BSTKD` · `POSEX` … |
| 5 | 공란 | |

**규약 셋**

1. **병합은 항목 단위 교체**다(SCHEMA §1). 거래처가 `KUNNR2` 를 선언하면 1층 선언은
   **통째로** 대체된다. 일부만 덮어쓸 수 없다 — 필요한 키를 전부 다시 적는다.
2. **예외를 붙이는 순간 그 필드는 Claude 의 스키마에서 빠진다**(D16). 선언이 있다는 것은
   "이 칸은 엔진이 정한다"는 뜻이고, 그래야 두 출처가 충돌하지 않는다.
3. 반대로 **1층 선언을 걷어내고 Claude 에게 맡기려면 `{from: llm}`** 을 명시한다
   (병합이 항목 단위 교체라 "지움"을 표현할 방법이 필요하다).

```yaml
# customers/<code>.yaml — 이 거래처만 출하조건을 발주서에서 읽게 한다
fields:
  ZSHCO: { from: llm }
```

### 1.4 흐름 한 장

```
masters/templates/SALES ORDER.xlsx
  1행  오더유형  판매조직  …  자재번호   수량     PO품목번호
  2행  AUART     VKORG     …  MATNR     KWMENG   POSEX
                                └──────── Claude 스키마의 rows[] 속성 ────────┘
                                          (선언이 있는 필드는 여기서 빠진다)
발주서 ──→ Claude ──→ rows[]  {MATNR:{value,evidence,…}, KWMENG:{…}, POSEX:{…}, …}
                      doc     {po_number, po_date, ship_to_text, …}  ← 2층 규칙의 입력
                                │
                                ▼
                      [1층] shipping.csv · brand_master.csv · 고객코드 · 공통 고정값
                                │
                                ▼
                      [2층] 거래처 예외 (있는 곳만) — 결정표 · split · 조합식
                                │
                                ▼
                      전송 행 = 템플릿 2행 순서 그대로 → 검수(P5) → JSON → HTTPS → EAI
```

**엔진 코드는 거의 그대로다.** 이미 `field_order = list(field_specs)` 로 돌고 있어
(`rules/engine.py:74`) 로더가 `field_specs` 를 템플릿 순서로 갈아끼우면 행 생성·검증·
그리드·전송이 전부 따라온다. 새로 만드는 것은 ① 템플릿 리더 ② 템플릿 기반 추출 스키마
③ `from: llm` 기본 동작 ④ `csv_choice`(브랜드 후보), 넷이다.

---

## 2. `CLAUDE.md` §1 P1 교체문 ★

### 2.1 표의 P1 행 — **이 문장 그대로** 교체한다

```
| P1 | **배치는 Claude, 코드는 규칙엔진** | Claude 는 ① 문서의 **원문 값**을 읽고 ② 그 값이 **템플릿의 어느 칸**에 들어가는지까지 정한다 (1행=설명 · 2행=SAP 필드명을 주므로 자연어 매칭이다). **그러나 값을 만들어내지 않는다** — SAP 코드 결정(`ZBRAND`·`VSART`·`ZSHCO`·`KUNNR1/2/3` 과 거래처 예외가 정하는 필드), 참조표 조회, 날짜·수량 **형식 변환**은 규칙엔진 몫이고, 그 필드들은 **애초에 Claude 의 출력 스키마에 없다**. 모든 값에는 원문 evidence 가 붙는다 |
```

### 2.2 표 아래 인용문 — 교체한다

```
> P1을 어기면 재현성과 감사가 무너진다. **"HARRISBURG" 를 읽고 그것이
> `SHIP-TO PARTY` 칸의 근거라고 보는 데까지가 LLM 이고, `KUNNR2=319677` 을
> 정하는 건 결정표다.** 경계는 말이 아니라 **출력 스키마가 지킨다** — 엔진이
> 정하는 필드는 스키마에 자리가 없어 Claude 가 값을 넣을 방법 자체가 없다.
>
> **여전히 금지**
> · `hints` · 템플릿 1행에 **변환 지시**를 쓰는 것 ("ELKHART 면 100249", "YYYYMMDD 로 바꿔라")
> · 엔진이 정하는 필드를 LLM 출력으로 채우는 것 (스키마에서 빼고, 들어와도 버린다)
> · evidence 없는 값을 근거 있는 값처럼 다루는 것
> · **템플릿 1행에 업무 규칙을 적는 것.** 1행은 "이 칸이 무엇인가"를 설명하는
>   자리이지 "언제 무엇을 넣어라"를 지시하는 자리가 아니다
```

### 2.3 왜 이 경계인가 (근거 — 문서에는 옮기지 않는다)

칸 배치를 LLM 에 맡겨도 안전한 이유는 **틀려도 사람이 즉시 알아본다**는 데 있다 —
수량 칸에 단가가 들어가 있으면 그리드에서 보인다. 코드 결정은 반대다: `KUNNR2` 에
`319678` 이 들어 있으면 맞는지 틀린지 화면으로 알 수 없고, 틀리면 **SAP 오더가 조용히
잘못 생성된다.** 그래서 코드는 끝까지 데이터(마스터)가 정한다.

> ⚠ 1층이 "그 밖의 모든 필드"를 Claude 에게 맡기므로, **코드성 필드**(`ZTERM`
> `INCO1` `AUGRU` `VKAUS` 등)에 문서 원문이 그대로 들어갈 수 있다("NET 30" → 4자리
> 코드 자리). 안전망은 ① `max_len` 검증 ② 검수 화면 ③ SAP 거부, 셋이다.
> 그 열을 안 쓰면 **현업이 템플릿에서 빼는 것**이 정답이고, 써야 하면 **2층 예외로
> 매핑표를 붙인다**(§5). 이 위험을 `check_template.py` 가 목록으로 띄운다.

---

## 3. 템플릿을 Claude 에게 어떻게 넘기나 ★

### 3.1 템플릿 읽기

| 항목 | 값 |
|---|---|
| 경로 | `masters/templates/SALES ORDER.xlsx` · **Git 추적**(생성물이 아니라 입력물이다) |
| `.env` 재정의 | `FIELD_TEMPLATE=` · `FIELD_TEMPLATE_SHEET=` (기본: 첫 시트) |
| 읽는 곳 | **1행 = 설명** · **2행 = SAP 필드명**. 3행 이하는 보지 않는다 |
| 열 범위 | A열부터 오른쪽. **빈 칸 5칸 연속**이면 종료(잔여 서식·병합 때문에 used range 를 믿지 않는다) |
| 필드명 정규화 | `strip` → 공백·개행 제거 → 대문자. `[A-Z][A-Z0-9_]*` 만 인정. 중복은 **첫 번째만** + 경고 |
| 캐시 | `(경로, mtime, size)` — 로더의 `_load_yaml` 과 같은 방식. 서버 재시작 불필요 |
| 실패 | **예외를 올리지 않는다.** `TemplateStatus{ok, source, path, reason, fields, descriptions}` 를 항상 돌려준다 |

`source` 는 `template` | `memory`(이 프로세스가 앞서 읽어 둔 목록) | `base`.
`template` 이 아니면 **항상 배너**를 띄운다 — 조용히 낡은 목록을 쓰는 것이 가장 나쁘다.
노출 지점: `GET /api/masters/fields` · `GET /api/health` · 화면 상단 배너 ·
`scripts/check_template.py` · `validate_masters.py`.

### 3.2 추출 스키마의 모양 (`schema_builder.py`)

지금은 **고정 표준 키**(`_HEADER_FIELDS` 12 · `_LINE_FIELDS` 13) + `extra_fields` 다.
바뀐 뒤는 **두 블록**이다.

```
extract_purchase_order(input_schema)
├─ doc        ← 2층 규칙의 입력으로 쓰이는 원문만 남긴다 (축소)
│    po_number, po_date, ship_to_text, brand_text, packing_spec, remark_default
├─ shipments[]  ← split.by != none 일 때만 (지금은 MSC 한 곳)
│    shipment_no, receiving_loc, ship_to_text, ship_by_text, remark, rows[]
├─ rows[]     ← ★ **속성 이름이 템플릿 2행 그대로**
│    _line_no : integer            (발주서에 나타난 순서. 스냅샷 대조 기준)
│    our_item : 거래처 품번          (참조표 조회 키 — 전송 칸이 아니다)
│    MATNR · KWMENG · POSEX · BSTKD · MAKTX · PRICE …
│        각각 {value, evidence, page, confidence}
├─ totals { line_count, total_qty, total_amount }
└─ notes[]
```

| 항목 | 규약 |
|---|---|
| 속성 이름 | 템플릿 **2행** 문자열 그대로(정규화 후) |
| 속성 `description` | 템플릿 **1행**. 비었으면 `_base.field_specs[name].label` + `sheet`. 둘 다 없으면 필드명 자체 + 🟡(`check_template` 이 "설명 없는 칸"으로 띄운다) |
| 값 봉투 | `{value, evidence, page, confidence}` — **바꾸지 않는다.** 환각 차단(`grounding.py`)의 전제다 |
| 헤더/라인 구분 | 두지 않는다. **템플릿은 행 단위 양식**이고 헤더성 값은 행마다 반복된다. 판단을 Claude 에게 떠넘기지 않는다 |
| 빈 칸 | 못 찾으면 `value: null`. 지어내지 않는다 (시스템 프롬프트 1번 그대로) |
| 거래처 고유 원문 | `extraction.extra_fields` 로 계속 선언 가능. **다만 이제 "엔진 입력 전용"** 이다 (전송 칸은 템플릿이 만든다) |

**엔진이 정하는 필드를 빼는 방법 — 목록을 박지 않는다**

```
llm_field_names = [ f for f in effective_field_list if f not in merged_master.fields ]
```

병합된 마스터에 `fields` 선언이 있는 필드 = 엔진이 정하는 필드 = 스키마에서 제외.
코드에 필드 이름도 거래처 이름도 등장하지 않는다(P2 · §5 금지 "엔진 코드에 전송 필드
이름 나열"). 거래처가 예외를 하나 붙이면 **그 거래처의 스키마에서만** 그 칸이 빠진다.
그래도 응답에 섞여 오면 **버리고 배치 노트 1건**(행마다 경고하지 않는다).

### 3.3 캐시 키와 픽스처에 미치는 영향 ★★

지금 런타임 캐시 키는 `sha256(문서 ‖ prompt_version ‖ customer ‖ model)` 이고
(`providers/cache.py:30`) **추출 스키마는 키에 없다.** 스키마가 바뀌면 사람이
`LLM_PROMPT_VERSION` 을 올려 무효화하는 수동 방식이다. 템플릿을 현업이 아무 때나
고치는 구조에서 이대로 두면 **낡은 모양의 응답이 조용히 재생된다** — 열을 추가해도
그 칸이 영원히 비어 나오고 아무도 이유를 모른다.

**결정(D20)**: 캐시 키에 **템플릿 서명**을 한 부분으로 추가한다.

```
template_sig = sha256( "\x00".join(llm_field_names) )[:16]      # 이름 + 순서만
cache_key    = sha256( 문서 ‖ prompt_version ‖ customer ‖ model ‖ template_sig )
```

| 무엇 | 키에 | 왜 |
|---|---|---|
| 필드 **이름과 순서** | ✅ | 출력 **모양**이 바뀐다. 재생하면 칸이 비거나 남는다 — 틀린 결과다 |
| 1행 **설명 문구** | ❌ | 모양이 아니라 **프롬프트 품질**이다. `hints` 를 키에서 뺀 것과 같은 이유 — 문구 한 글자 고칠 때마다 전 문서 재파싱이 유료면 아무도 문구를 못 고친다(`cache.py` 머리말) |

- 마스터에서 **필드 선언을 추가·삭제해도 캐시가 갈린다**(`llm_field_names` 가 달라진다).
  의도한 동작이다 — 스키마 모양이 실제로 바뀐다.
- 설명만 고치고 다시 뽑고 싶으면 기존 수단 그대로 `LLM_PROMPT_VERSION` 을 올린다.
- 캐시 파일에 `template_sig` 와 **설명 서명**(`desc_sig`)을 함께 적어 둔다.
  `check_template.py` 가 "이 캐시는 예전 설명으로 뽑혔습니다"를 보여줄 수 있다.
- 서명이 갈리면 옛 캐시 항목은 고아가 된다. **지우지 않는다**(되돌릴 근거다).
  용량이 문제가 되면 그때 정리 스크립트를 만든다 → `todo:`.

**픽스처는 키가 아니라 이름(`{거래처}__{파일명}`)으로 찾는다.** 그래서 템플릿이 바뀌어도
**픽스처는 그대로 재생된다** — 장점이자 이번 변경의 함정이다. 낡은 템플릿으로 박은
픽스처가 현재 모양과 다른 채 조용히 재생된다.

| 조치 | 내용 |
|---|---|
| 서명 기록 | `pin_fixture.py` 가 `{"template": {"sig": …, "fields": [...]}}` 를 같이 적는다 |
| 재생 시 **모양 보정** | 픽스처에만 있는 키 → 버린다 · 현재 템플릿에만 있는 키 → 빈 값. **예외를 올리지 않는다**(시연 중에 죽으면 안 된다) |
| 어긋나면 알린다 | 배치 노트 1건 + `pytest` 경고. 행마다 달지 않는다 |
| 시연 전 | 템플릿을 바꿨으면 `pin_fixture.py` 를 다시 돌린다. `check_template.py` 가 "픽스처 N건이 현재 템플릿과 다릅니다"로 알려준다 |
| 골든 테스트 | 기대 컬럼을 **유효 필드 목록에서 끌어온다**. 이름·개수를 박지 않는다 (`test_engine.py:40` · `test_send.py:126` · `test_api_masters.py:46` 이 해당) |

### 3.4 템플릿이 없을 때 = **지금 동작**

| 상황 | 유효 필드 목록 | 설명 문구 | 알림 |
|---|---|---|---|
| 템플릿 있음 | 2행 순서 | 1행 | — |
| 파일 없음 / 못 읽음 / 2행에서 0개 | `_base.field_specs` 순서 | `_base` 의 `label` + `sheet` | 🟡 배너 + `/api/health` |

**폴백이 현행 동작과 같으므로** 템플릿이 올라오기 전에 전 구간을 만들고 테스트할 수 있다.
테스트는 실물이 아니라 `backend/tests/fixtures/templates/` 의 작은 xlsx 를 쓴다
(실물 `masters/` 를 건드리지 않는다 — `--masters` 사본 규약과 같다).

---

## 4. 마스터 파일이 얼마나 비는가

### 4.1 원칙 한 줄

> **선언은 예외를 적는 자리다.** 선언이 없으면 Claude 가 채운다(D14).
> `row_builder.build_row` 의 `FIELD_NOT_DECLARED` 🔴 를 **없애고**, 선언이 없는 필드는
> `row.<필드명>`(없으면 `""`)을 쓴다. 이 한 줄이 YAML 수십 줄을 지운다.

### 4.2 `profiles/standard.yaml` — **36 선언 → 6 선언 + 2 규칙**

1층을 코드가 아니라 **데이터로** 적되, 한 곳에 여섯 줄이면 끝난다.
(코드에 필드 이름을 나열하는 것은 `CLAUDE.md` §5 금지다.)

```yaml
version: 2

rules:
  shipping:                        # 고객 1 : VSART 1 : ZSHCO 1
    kind: lookup
    table_file: refs/shipping.csv
    optional: true                 # 파일이 없어도 정상 동작
    key: meta.customer_no
    key_column: kunnr
    return: [vsart, zshco]
    on_no_match: { action: empty } # 공란. 경고도 띄우지 않는다 — 대부분이 여기다

  brand_pick:                      # ★ 신규 kind: csv_choice
    kind: csv_choice
    table_file: refs/brand_master.csv
    filter_column: kunnr           # meta.customer_no 와 같은 행만 후보
    value_column: zbrand
    label_column: zbrant           # 드롭다운에 함께 보일 이름
    when_single: auto              # 1건이면 채운다
    when_multi: empty              # 2건 이상이면 공란 + 드롭다운
    on_no_candidates: { action: warn, message: "이 고객에게 등록된 브랜드가 없습니다" }

fields:
  KUNNR1: { from: expr, expr: 'meta.customer_no', required: true }
  KUNNR2: { from: expr, expr: 'meta.customer_no', required: warn,
            explain: "기본은 판매처와 같습니다. 출하처가 다른 거래처는 예외가 덮어씁니다" }
  KUNNR3: { from: expr, expr: 'meta.customer_no', required: true }
  VSART:  { from: expr, expr: 'shipping.vsart', required: warn,
            explain: "고객–운송수단 마스터(refs/shipping.csv)" }
  ZSHCO:  { from: expr, expr: 'shipping.zshco', required: warn,
            explain: "고객–출하조건 마스터(refs/shipping.csv)" }
  ZBRAND: { from: rule, rule: brand_pick, choices_from: brand_pick, required: warn }

grid:
  pinned: [BSTKD, MATNR, KWMENG]
  # hidden 은 두지 않는다 — 안 쓰는 열은 템플릿에서 뺀다
```

**지워지는 것**: `const ""` 21줄 전량 · `KWMENG`(doc) · `MATNR` · `ZPKRE2` · `EMPST` ·
`BSTKD`(→ Claude) · `POSEX`(→ Claude) · `AUART`/`VKORG`/`VTWEG`(→ §4.3) ·
`grid.hidden` 22개 나열.

`KUNNR2` 를 `warn` 으로 두는 이유: 값은 항상 채워지지만 **검수자가 지웠을 때 막지
않기 위해서다.** 그 판단은 사람 몫이고(P5), 대신 노랗게 보인다.

### 4.3 `_base/sap_defaults.yaml` — 선언 없이 적용

`sap_defaults` 에 키가 있으면 **선언 없이** 그 값이 쓰인다(해결 순서 3위, §1.3).
`AUART`·`VKORG`·`VTWEG` 세 줄의 `{from: base}` 선언이 사라진다.

- **빈 문자열도 정해진 값으로 본다.** `LGORT: ""` · `ZTERM: ""` 는 "비워서 보낸다"이다.
  그 칸을 Claude 에게 맡기려면 **`sap_defaults` 에서 그 키를 빼면 된다** (데이터 한 줄).
- `field_specs` 에 **`required: true|warn` 를 규격의 일부로** 받는다. 선언이 사라진
  필드(`MATNR` 등)의 `required` 가 갈 곳이다. 기본은 `warn` — **막지 않는다**가 원칙이다.
- `_base` 는 **36개를 그대로 둔다.** 줄이는 것은 현업이 템플릿에서 한다(§6-1).

### 4.4 `masters/refs/shipping.csv` (신규)

```csv
kunnr,vsart,zshco,note
100249,04,A,기존 운영 확인분 (msc.yaml 에서 이관)
107525,04,,ZSHCO 미확정 — 공란으로 둔다 (todo)
3200,04,,ZSHCO 는 브랜드 조건 분기라 거래처 예외가 정한다
```

위 세 행은 추측이 아니라 **현행 YAML 에 확정값으로 적혀 있던 것을 옮긴 것**이다
(MSC `ZSHCO: "A"`, 전 거래처 `VSART: "04"`). KL 의 `ZSHCO` 는 지금도 `todo:` 이므로
**빈 칸 그대로** 둔다 — 비슷한 고객 것을 베껴 넣지 않는다.
검증: 같은 `kunnr` 중복 → **오류**(어느 행이 이길지 알 수 없다) · 둘 다 빈 행 → 리포트.
값 자체의 유효성(SAP 에 등록된 `VSART` 인가)은 코드 마스터를 받은 적이 없어 검사하지 않는다 → `todo:`.

### 4.5 `profiles/generic.yaml` — 거의 빈다

`fields`(BSTKD·MATNR·KWMENG·KUNNR2) **전부 삭제** · `rules.brand_code`(csv_map)
**삭제**(1층의 `brand_pick` 을 그대로 쓴다). `extraction.hints` 는 **유지**하되
품목표 컬럼 안내는 덜어낸다 — 이제 템플릿 1행이 그 일을 한다. 머리말의
"추측해서 채우지 않는다"에 **"단 `KUNNR1/2/3` 은 예외다(기본값=고객코드, 2026-09-21)"** 한 줄.

### 4.6 `customers/*.yaml` — 조건이 있는 것만

| 파일 | 남는 것 | 지우는 것 |
|---|---|---|
| `msc.yaml` | `meta` · `hints` · **`split`** · **`tables.ship_to_routing`** · `rules.brand_by_text`(※§1.2 확인 전까지) · `rules.ref_codes` · `fields`: `KUNNR2` `BSTKD`(도시 붙이기) `ZBRAND` `ZPKRE2` · `checks` | `ZSHCO`(→마스터) · `MATNR`(→Claude) · `grid.hidden` 대부분 |
| `kl.yaml` | `meta` · `hints` · `rules.pack_remark`(브랜드 원문→`WGT`/`KMT`) · `fields`: `ZBRAND: const "2"` `ZPKRE2` `EMPST` | `KUNNR2`(→고객코드 기본) · `ZSHCO`(→마스터) · `MATNR: const ""`(→Claude) · `POSEX`(→Claude) · `BSTKD`(→Claude) |
| `ygjp.yaml` | `meta` · `hints` · `rules.brand_by_text` · `fields`: `KUNNR2: "319854"`(고객코드 3200 과 다르다=조건) `BSTKD`(`01-YYYYMMDD-ID` 조합) `ZBRAND` `ZSHCO`(브랜드 471/507 분기) `ZPKRE2` `EMPST` `WAERK: "JPY"` | `MATNR`(→Claude) · `grid.hidden` 대부분 |

### 4.7 컨텍스트 네임스페이스에 한 줄 — `row.*`

선언이 사라진 값을 규칙·검증이 참조해야 할 때가 있다(MSC 의
`checks.shipment_total_match` 는 수량 합계를 본다). **Claude 가 템플릿 칸에 채운 값**은
`row.<필드명>` 으로 참조한다 (`row.KWMENG` · `row.MATNR`). `line.*` 은 **엔진 입력용
축소 표준 키**로 남는다. MSC 의 `checks` 는 `line.quantity` → `row.KWMENG` 로 바뀐다.

### 4.8 `POSEX` 가 Claude 로 간 결과 — 짚고 넘어갈 것 ★

`POSEX` 는 1층에서 **Claude 가 발주서에서 읽어** 채운다. 발주서에 품목번호가 인쇄돼
있지 않으면 **빈 칸**이 된다.

- `CLAUDE.md` §8 의 **"CBO 업서트 키 미확정"** 갭이 그대로 남는다. 행 식별자가 없으면
  재전송은 덮어쓰기가 아니라 **중복 적재**다. 감사 로그가 `send`/`resend` 를 구분하므로
  사후 추적은 된다.
- 필요해지면 **2층 예외**로 순번 생성을 붙인다 — `{from: doc, path: line.posex,
  fallback_gen: line_no_x10}`. 생성기 `line_no_x10` 은 이미 있다(`row_builder.py:21`).
  그때 순번의 기준은 **파싱 직후 스냅샷의 `_line_no`** 여야 한다. 화면의 현재 행 위치를
  쓰면, 검수자가 중간 행을 지우고 재전송할 때 **다음 행이 지운 행의 키를 물려받아
  엉뚱한 행을 덮어쓴다**(계약 §6.1 의 스냅샷이 이미 있다).
- 검증: 같은 오더(`BSTKD`) 안에서 `POSEX` 중복이면 🟡. 막지는 않는다.
- 현업이 템플릿에서 `POSEX` 열을 빼면 식별자가 아예 사라진다 →
  `check_template.py` 가 **경고 한 줄**을 낸다. 막지는 않는다.
- SAP 담당 확인 질문: **"CBO 업서트 키는 무엇인가. 우리가 만든 번호를 `POSEX` 에
  넣어도 되는가."** → §9-2.

---

## 5. 예외를 하나씩 붙이는 절차 (코드 0줄) ★

### 5.1 증상 → 어디에 적나

| 증상 | 어디에 | 무엇을 |
|---|---|---|
| 운송수단·출하조건이 이 고객만 다르다 | `refs/shipping.csv` | **행 한 줄 추가.** 거래처 파일을 만들 필요도 없다 |
| 브랜드가 여러 개인데 발주서 문구로 가릴 수 있다 | `refs/brand_keys.csv` + `customers/<code>.yaml` 의 `rules.brand_by_text` | 문구 행 + `csv_map` 규칙 1개 |
| 어떤 값이 **조건에 따라 갈린다** (출하지·품목 등) | `customers/<code>.yaml` 의 `tables` | 결정표 1개. `then` 에 여러 필드를 한 번에 |
| 여러 값을 **조합**해야 한다 | 같은 파일의 `fields.<필드>.expr` | `concat` · `join` · `coalesce` · `if` (SCHEMA §4.7 화이트리스트) |
| 품번으로 **참조표**를 봐야 한다 | `refs/<표>.csv` + `rules.<이름>` (`kind: lookup`) | `optional: true` 로 두면 파일이 없어도 동작 |
| 발주서 1부가 **여러 오더**로 쪼개진다 | `split: {by: shipment}` | 화면은 한 그리드, 오더 키만 달라진다 |
| 이 고객만 어떤 칸을 **Claude 에게 맡기고 싶다** | `fields.<필드>: {from: llm}` | 1층 선언을 걷어낸다(§1.3-3) |

### 5.2 새 예외를 붙이는 순서

```
1. masters/customers/_template.yaml 을 복사해 <code>.yaml 을 만든다
   (마스터에 없는 고객이면 meta 만 채워도 1층으로 바로 돈다 — generic 프로필)
2. meta 를 채운다 (code · name · customer_no · owner · status · file_types)
3. extraction.hints 에 **문서 구조만** 적는다 (변환 지시 금지 — P1)
4. ★ 예외가 되는 것만 적는다. 1층과 같은 값은 적지 않는다
5. python scripts/validate_masters.py --customer <code>
6. python scripts/check_sample.py <발주서> --customer <code>   # 비용 0. hints 앵커 대조
7. python scripts/parse_one.py <발주서> --customer <code> --rows
8. rules: 커밋 — 본문에 **근거(일자 · 확인자 · 영향 범위)**. Git 이력이 규칙 변경 대장이다
```

**적지 말아야 할 것**: 1층과 같은 값(고객코드 = `KUNNR2` 등)을 "명시적으로" 다시 적는 것.
줄이 늘어날 뿐이고, 1층이 바뀌어도 따라오지 않아 **어긋난 채 남는다.**

### 5.3 예외가 없는 고객

`customers/<code>.yaml` 이 없으면 `profiles/generic.yaml` 로 돈다. SAP 에 브랜드가
등록된 고객이면 **파일 하나 없이** 발주서를 읽고 전송까지 열린다(78곳). 브랜드가
0건인 고객은 `CatalogEntry.ready == False` 로 업로드를 막는다 — 판정할 근거가 없다.

---

## 6. v1 에서 **버리는** 것 ★

| # | 버리는 것 | 왜 |
|---|---|---|
| 1 | **필드 36 → 15 축소 논의**(v1 §7 전체 — 후보표·뺄 필드 20개) | 현업이 템플릿에서 정한다. `_base` 는 규격표로 그대로 둔다 |
| 2 | **필드별 `from/path` 공통 선언** (v1 의 `standard.yaml` 개편안) | 1층은 6줄이면 된다(§4.2) |
| 3 | **`BSTKD`·`POSEX` 를 규칙엔진이 만든다**는 설계 | 3차 확인으로 **Claude 소관**이 됐다. `POSEX` 순번 생성은 2층 선택지로만 남는다(§4.8) |
| 4 | **템플릿에만 있는 필드에 `{from: const, value: ""}` 자동 주입** | 주입할 이유가 사라졌다. 선언이 없는 것이 **정상**이다. `FIELD_NOT_DECLARED` 자체를 폐지 |
| 5 | **거래처 YAML 에 전송 필드 전량 선언**(SCHEMA §4.6 · 검증 검사 1) | 검사 1 은 "선언된 필드가 유효 목록 안에 있는가"(반대 방향)로 바꾼다 |
| 6 | **고정 표준 키 25개 전량 추출** | 2층이 참조하는 것만 남긴다(§3.2). `requested_date`·`order_text`·`bill_to_text`·`currency_text`·`incoterms_text`·`payment_terms_text`·`item_code`·`description`·`quantity`·`unit`·`unit_price`·`net_value`·`delivery_date` 는 **템플릿 칸이 대신한다** |
| 7 | **출하 마스터 관리 화면** | 당분간 CSV 를 직접 고치고 Git 이력으로 남긴다(SCHEMA §6.1 기준) |
| 8 | **붙여넣기 대안 C**(textarea 상자) | A(드롭다운 대신 `TextColumn`+후보 안내)·B(열 일괄 채우기)로 안 될 때만 |
| 9 | **엑셀 내보내기 버튼** | 종착점은 EAI(HTTPS/JSON)다. 엑셀은 **입력물**이지 산출물이 아니다 |
| 10 | v1 의 **W0~W7 작업 순서** | §8 로 대체 |

---

## 7. 다른 문서 반영 (요약 — 상세는 각 문서에서)

### 7.1 `CLAUDE.md`

| 절 | 무엇을 |
|---|---|
| §1 P1 행 · 인용문 | **§2.1 · §2.2 의 문장 그대로** 교체 |
| §2 SSOT 표 첫 행 | 3행으로 쪼갠다 — ① `전송 필드 목록·순서` → 템플릿 **2행** ② `필드 설명(LLM 매칭용)` → 템플릿 **1행**(없으면 `_base.label`) ③ `필드 규격`(label·max_len·type·required) → `_base/sap_defaults.yaml` |
| §2 표 추가 2행 | `고객별 브랜드 후보` → `refs/brand_master.csv` · `고객별 운송수단·출하조건` → `refs/shipping.csv` |
| §2 "거래처 공통 필드 매핑" 행 | "**1층 6필드 + 2규칙만** 적는다. 나머지는 선언하지 않는다(= Claude 가 채운다)" |
| §2 굵은 문장 | "현재 36개지만" → "**목록과 순서는 템플릿 2행이 정한다.** 36이 15가 되어도 코드·화면·전송은 그대로 동작해야 한다. 못 읽으면 `_base` 로 폴백하되 **조용히 넘어가지 않는다**" |
| §5 금지 추가 | · 템플릿 읽기 실패에 예외 올리기 · 엔진이 정하는 필드를 LLM 스키마에 넣기 · **선언이 없다고 🔴 달기** · 템플릿 서명 확인 없이 픽스처 재생 · **1층과 같은 값을 거래처 파일에 다시 적기** |
| §5 기존 행 수정 | "공용 프로필이 모르는 값을 추측해 채우기" 끝에 "**단 KUNNR1/2/3 은 예외다**(기본값=고객코드, 2026-09-21)" |
| §3 명령어 | `python scripts/check_template.py` 한 줄 |
| §4 구조 트리 | `masters/templates/` · `refs/shipping.csv` · `backend/app/masters/template.py` |
| §8 갭 | "`prompt.py`·`schema_builder.py` 가 날짜 변환을 지시한다(P1 위반)" → **W2 에서 해소**. `POSEX`/업서트 키 갭은 **남긴다**(§4.8) |

### 7.2 `masters/SCHEMA.md` (architect 소유)

| 절 | 무엇을 |
|---|---|
| §1 트리 | `templates/SALES ORDER.xlsx` · `refs/shipping.csv` |
| §1.1 프로필 | "`fields`·`grid` 만" → "**`rules`·`fields`·`grid`**" (1층 규칙이 여기 산다) |
| §2 파이프라인 | ⑥ FIELDS 의 설명을 **§1.3 해결 순서 5단계**로 교체 |
| §3 네임스페이스 | **`row.*` 한 줄 추가**(§4.7) · `line.*` 을 "엔진 입력용 축소 표준 키"로 |
| §3.1 표준 키 | **축소**(§3.2 의 `doc`/`shipments`/`rows` 가 새 원천) |
| §4.2 `extraction` | `extra_fields` 를 **엔진 입력 전용**으로 좁힌다 |
| §4.5 `rules` | `kind` 표에 **`csv_choice`** + 옵션표 |
| §4.6 `fields` | "전부 선언되어야 한다" → "**예외만 선언한다. 선언이 없으면 Claude 가 채운다**". `from` 에 **`llm`**, 옵션에 **`choices_from`**·**`fallback_gen`** |
| §4.6a (신규) | **"유효 필드 목록"** — 템플릿 2행 ∩ 동작 · 폴백 · `llm_field_names` 계산(§3.2). ★ 이 주제의 SSOT |
| §5 신규 거래처 절차 | **§5 를 그대로** 옮긴다 (증상→위치 표 + 8단계) |
| §7 검증 | 검사 1 방향 전환 · 신규: 템플릿 읽힘(경고) · 템플릿↔`_base` 차집합 양방향 · `shipping.csv` 중복 `kunnr`(오류) · `csv_choice` 스키마 · 픽스처 서명 불일치 · **1층과 동일한 값의 중복 선언**(리포트) |

### 7.3 `contracts/api-contract.md` (공용 — 단독 PR)

| 절 | 변경 |
|---|---|
| §3 `/api/masters/fields` | 필드에 `description`(템플릿 1행) · 응답에 `template: {ok, source, path, reason}` · "순서 = `_base`" → "**유효 필드 목록 순서**" |
| §5 `/api/batches/{id}` | `choices`(필드→후보. **후보 개념이 없으면 키를 안 내린다**) · `notes`(배치 단위 안내. 비면 `[]`) |
| §6.1 병합 | "모르는 컬럼" 기준을 `_base` → **유효 필드 목록**으로 |
| §8 `/api/health` | `template` 블록 |
| `examples/*.json` | 같은 PR 에서 갱신. **프론트가 이 파일로 화면을 만든다** |

### 7.4 그 밖

`design.md`(SSOT 표·§0 결정·디렉터리·검증표) · `process.md` §4(드롭다운·배너·노트) ·
`profiles/generic.yaml` 머리말(§4.5) · `NEXT.md`(§2-C 의 "규칙엔진은 아래 6개만
변환한다" 문장을 **2층 구조 표로** 정정, §2-B 닫기).

---

## 8. developer 작업 순서 ★

전제: `feat/be-rules`(백엔드·마스터·스크립트) · `contracts/**` 는 단독 PR ·
**각 단위마다 커밋**하고 `rules:` 커밋은 본문에 근거를 남긴다.
**W3 을 W5 보다 먼저 한다** — 순서를 바꾸면 YAML 을 지운 순간 전 행이 🔴 가 된다.

| 단계 | 무엇을 | 파일 | 끝났다는 기준 |
|---|---|---|---|
| **W0** | 계약 먼저 (단독 PR) | `contracts/api-contract.md` · `examples/fields.json` · `batch_msc.json` | 프론트·백엔드가 같은 문서를 본다(§7.3) |
| **W1** | 템플릿 리더 | `backend/app/config.py` · **`masters/template.py`**(신규) · `masters/loader.py`(`_apply_template`) · `preview.py` · `api/routes_masters.py` · `main.py` · **`scripts/check_template.py`**(신규, `use_utf8()`) · `check.bat`(cp949+CRLF) · **`tests/test_template.py`** + `tests/fixtures/templates/` | 템플릿 **없이** 기존 테스트 전량 통과(폴백=현행). 작은 xlsx 로 순서가 바뀌는 것 확인 |
| **W2** | 추출 스키마 템플릿화 ★ | `extraction/schema_builder.py`(`rows[]`·설명 주입·`llm_field_names`) · `extraction/prompt.py`(**날짜·형식 변환 지시 삭제** = §8 P1 갭 해소) · `extractor.py` · `providers/cache.py`(`template_sig`·`desc_sig`) · `grounding.py` · `scripts/pin_fixture.py` · 픽스처 **모양 보정** | 템플릿 열을 하나 추가하면 캐시가 갈리고, 낡은 픽스처는 **경고와 함께** 재생(§3.3) |
| **W3** | 엔진 — 선언 없는 필드 | `mapping/row_builder.py`(**`FIELD_NOT_DECLARED` 폐지**·`from: llm`·`fallback_gen`·`sap_defaults` 자동 적용) · `rules/context.py`(**`row.*`**) · `rules/engine.py` · `validation/validator.py`(`required`·`max_len` 을 `field_specs` 에서) · `domain/models.py` | 선언을 지워도 값이 그대로 나온다. 해결 순서 5단계(§1.3)가 테스트로 고정된다 |
| **W4** | 1층 마스터 | `masters/refs/shipping.csv`(신규) · `rules/mapping_rules.py`(`csv_choice`) · `rules/engine.py`(후보 배치 합집합) · `domain/models.py`(`choices`·`notes`) · `row_builder`/`validator`(`choices_from`·🟡 `NOT_IN_CHOICES`) · `preview.py` · `api/routes_batches.py` · `batch_service.py` | 후보 1건=자동 · N건=공란+후보 · 0건=업로드 차단. **개수는 참조표에서 끌어온다** |
| **W5** | 마스터 다이어트 | `profiles/standard.yaml`(§4.2) · `generic.yaml`(§4.5) · `customers/{msc,kl,ygjp}.yaml`(§4.6) · `_base/sap_defaults.yaml`(`required` 이관) · `scripts/validate_masters.py`(검사 방향 전환·신규) | `validate_masters` 통과 + 골든 2종의 `VSART`·`ZSHCO`·`KUNNR2`·`ZBRAND` 가 의도대로 |
| **W6** | 화면 | `ui/service.py`(`choices`·`notes`·`template`) · `ui/views/convert.py`(드롭다운·배너·노트, **필드명 하드코딩 금지**) · `ui/e2e/paste.mjs`(신규) · `tests/test_ui_*.py` | 드롭다운이 떠도 **붙여넣기가 살아 있다.** 충돌하면 붙여넣기를 살린다 |
| **W7** | 문서 (**architect**) | `CLAUDE.md`(§7.1) · `masters/SCHEMA.md`(§7.2) · `design.md` · `process.md` · `NEXT.md` | 문서 간 값이 어긋나지 않는다 |
| **W8** | 관통 | `check_template.py` → `validate_masters.py` → `pytest` → `ruff` → 모의 EAI + 스트림릿 → `flow.mjs`·`paste.mjs` | 전송 페이로드의 **키 순서 = 템플릿 2행 순서**를 눈으로 확인 |

> 템플릿 실물이 W2 전에 오면 W1 끝에 커밋한다 (**거래처 실데이터 시트가 없는지
> 먼저 확인** — `samples/` 가 대외비인 이유와 같다). 안 와도 W8 까지 전부 진행된다.

---

## 9. 남은 `todo:`

| # | 항목 | 어디에 |
|---|---|---|
| 1 | **MSC 브랜드가 출하지로 결정되는가, ORDERED FROM 문구로 결정되는가** (§1.2) | `customers/msc.yaml` 의 `todo:` — 확인 전까지 현행 유지 |
| 2 | **CBO 업서트 키** — 생성한 번호를 `POSEX` 에 넣어도 되는가 (§4.8) | `NEXT.md` §5 · `CLAUDE.md` §8 (이미 등재) |
| 3 | `shipping.csv` 의 KL `ZSHCO` | `refs/shipping.csv` 의 `note` |
| 4 | `VSART`/`ZSHCO` **코드 마스터**를 SAP 에서 받을 수 있나 (받으면 `value_check`) | `NEXT.md` §5 |
| 5 | `st.data_editor` **붙여넣기 · 드롭다운** 동시 동작 (실제 브라우저 1회면 판가름) | `NEXT.md` §5 |
| 6 | 템플릿 실물의 **1행 문구 품질** — 설명이 비면 매칭 정확도가 떨어진다 | `check_template.py` 가 목록으로 띄운다 |
| 7 | **코드성 필드**(`ZTERM`·`INCO1` 등)를 Claude 에게 맡길지, 템플릿에서 뺄지 (§2.3) | 현업 확인 → `NEXT.md` §5 |
| 8 | `storage/llm_cache/` **고아 항목 정리** 필요 여부 (§3.3) | `NEXT.md` §5 |
| 9 | YGJP `WAERK: "JPY"` 를 Claude 에게 맡길지 | `customers/ygjp.yaml` 의 `todo:` |
