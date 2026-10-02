# 거래처 전용 규칙 (Customer Rules)

> 작성 2026-10-02 · 개정 2026-10-02 (사용자 결정 반영) · architect · 대상: 현업(영업·물류 담당)과 개발자
> 원본 자료: 루트 `LOGIC.md`(POC 하드코딩 요약, git 미추적) · `samples/PO변환_비즈니스로직_명세서.md`
> 문법 원천: [`masters/SCHEMA.md`](masters/SCHEMA.md) · 전송 필드 원천: [`masters/_base/sap_defaults.yaml`](masters/_base/sap_defaults.yaml)

---

## 1. 이 문서는 무엇인가

이 프로그램은 발주서를 읽어 SAP 판매오더 한 줄 한 줄로 바꿉니다. 값이 정해지는 길은 두 가지입니다.

| 구분 | 무엇 | 어디에 있나 |
|---|---|---|
| **공용 설정** | 모든 거래처에 똑같이 적용되는 방식. 예) 판매처(Sold-to)는 고객코드, 브랜드는 브랜드 마스터에서, 출하조건·운송수단은 Shipping Master 에서 | `masters/profiles/standard.yaml` · `generic.yaml` |
| **거래처 전용 규칙** | 특정 거래처에만 있는 예외. 예) SID TOOL 는 창고 도시마다 Ship-to 가 다르다 | `masters/customers/{code}.yaml` (거래처 1곳 = 파일 1개) |

**지금(2026-10-02) 실물 `masters/customers/` 에는 전용 규칙 파일이 하나도 없습니다.** SID TOOL·KL·YGJP 도
공용 설정만으로 돌고 있습니다(2026-09-23 "기본부터 만들고 예외는 나중에 다시 얹는다" 결정).
예전 규칙 모양은 테스트용 사본 `backend/tests/fixtures/customers/{msc,kl,ygjp}.yaml` 에 남아 있습니다.

이 문서는 **전용 규칙을 다시 얹기 전에** 다음을 정리합니다.

- POC 에서 무엇을 했는지 (원본)
- 지금 구조에서 **어떤 장치로** 같은 결과를 낼지, 그리고 **왜** 그 장치인지
- 각 항목의 **상태** — 공용으로 이미 됨 / 전용 규칙 필요 / 엔진 확장 필요
- 결정 사항(§5)과 구현 순서(§6)

### 원칙 — 통제는 경고까지, 전송 차단은 하지 않는다 (2026-10-02 사용자 결정)

이 프로그램의 일은 발주서 내용을 표로 옮기는 것입니다. 잘못 나간 값은 **전송 후 SAP 에서 다시 고칠 수
있으므로** 이 프로그램이 오더를 통제하지 않습니다.

- 거래처 전용 규칙은 값을 못 정하면 **빈 칸 + 노랑(경고)** 으로 둡니다. `required: true`·`on_no_match: error`·
  `severity: error` 를 쓰지 않습니다.
- 사람이 보고 고치거나 그대로 보냅니다(P5).

### 운영 규칙 — 값은 YAML 이 진실이다 (CLAUDE.md P3)

1. **값의 원천은 `masters/customers/{code}.yaml` 과 `masters/refs/*.csv` 입니다.** 이 문서에 적힌 코드값은
   결정 내용과 POC 원본의 **인용**일 뿐입니다.
2. 한 항목이 YAML 로 구현되면, 이 문서의 해당 행은 **값을 지우고 위치만** 남깁니다.
   예) `Ship-to - KUNWE → masters/customers/sid.yaml tables.ship_to_routing`
3. 구현 뒤에 값을 바꿀 때는 YAML 만 고치고 이 문서는 고치지 않습니다. 두 곳에 같은 값을 쓰면
   언젠가 어긋나고, 어긋나면 오더가 잘못 생성됩니다.

### 이 문서의 필드 표기

화면과 같게 **"필드명 - 필드코드"** 로 씁니다. 전송 키가 화면 코드와 다른 것은 오른쪽 열을 보세요.

| 표기 | 전송 키 | 표기 | 전송 키 |
|---|---|---|---|
| 오더유형 - AUART | AUART | 자재번호 - MATNR | MATNR |
| 판매조직 - VKORG | VKORG (전송 전용, 표에 안 보임) | 수량 - KWMENG | KWMENG |
| Sold-to - KUNNR | KUNNR1 | Packing Spec - ZPKRE | ZPKRE |
| Ship-to - KUNWE | KUNNR2 | Remark - EMPST | EMPST |
| 고객발주번호 - BSTKD | BSTKD | Shipping Type - VSART | VSART |
| PO품목번호 - POSEX | POSEX | 단가 - PRICE | PRICE |
| 브랜드 - ZBRAND | ZBRAND | 통화 - WAERK | WAERK |
| Shipping Condition - ZSHCO | ZSHCO | 고객자재번호 - KDMAT | KDMAT |

전송 필드 목록·개수는 `_base/sap_defaults.yaml` 이 정합니다(지금은 위 16개). 2026-10-02 사용자 결정으로
최종고객(KUNNR3)과 납기·지불조건·인코텀즈 등 12개가 빠졌습니다. 이 문서는 남아 있는 필드만 다룹니다.

---

## 2. POC 로직을 그대로 옮기지 않는 이유

| # | POC | 지금 | 이유 |
|---|---|---|---|
| 1 | 거래처별 값이 파이썬 코드에 박혀 있다 | 값은 `masters/customers/*.yaml` · `refs/*.csv` | 코드에 거래처 이름을 두지 않는다(P2). 거래처가 50곳이 되어도 YAML 만 늘어난다 |
| 2 | 파서가 읽으면서 코드값까지 정한다 (예: "HERTEL" 을 찾으면 바로 38) | **Claude 는 원문만 읽고**, 코드는 규칙엔진이 정한다 | 읽기와 판단을 나눠야 같은 문서에서 늘 같은 결과가 나오고, 나중에 "왜 이 코드인가"를 따라갈 수 있다(P1) |
| 3 | 못 찾으면 **조용히 빈 칸**으로 파일이 만들어진다 (LOGIC.md 확인 3) | 못 찾으면 **빈 칸 + 노랑(경고)** | 빈 칸이 아무 표시 없이 SAP 로 가면 아무도 모른다. 다만 막지는 않는다(§1 원칙) |
| 4 | YGJP 브랜드는 하단 줄이 POC 자체 표(25개)와 **완전히 같아야** 인식 | **브랜드 마스터에 등록된 이 고객의 브랜드명**이 원문에 **포함**되면 그 코드. POC 표는 버린다 | 브랜드 마스터가 유일한 기준이다. 완전일치는 실물 5건 중 최소 3건에서 실패한다 (아래 근거) |
| 5 | 브랜드 코드를 `38`, `1` 처럼 앞자리 0 없이 쓴다 | **0 붙인 3자리**(`038`) — 브랜드 마스터 형식 그대로 | 드롭다운 후보·자동 값·전송 값이 한 형식이어야 한다 |
| 6 | 출하조건(ZSHCO)·운송수단(VSART)을 거래처 코드에 고정 | 화면 **Shipping Master**(`refs/shipping_master.csv`, 고객 1곳 = 값 1개) | 현업이 화면에서 고친다. 단, YGJP ZSHCO 처럼 **브랜드에 따라 달라지는** 값은 고객 1곳 = 값 1개로 표현할 수 없어 전용 규칙으로 덮어쓴다 |
| 7 | 출력물이 사전점검·S/O 업로드·PO정리 엑셀 3종 | 출력은 **EAI 전송 하나** | 범위 밖은 §7 |

### 근거 — YGJP 하단 브랜드 줄의 실물 모양 (samples/YGJP/_dump 5건)

| 실물 모양 (브랜드 줄 기준) | POC 완전일치 |
|---|---|
| `YG BRAND` / 다음 줄 `S-Y,B-Y` | 성공 |
| `SAKUSAKU BRAND` / 다음 줄 포장지시 | 성공 |
| `YAMAKATSU BRAND S-Y,B-Y` — 브랜드와 포장지시가 **한 줄** | **실패** |
| `YG BRAND (COMINIX) YG STD.` — 한 줄 | **실패** |
| 빈 줄·`Domestic stock` 다음에 `YG BRAND YG STD` — 한 줄 | **실패** |

POC 는 이 경우 브랜드·포장지시·비고가 전부 빈 값이 됩니다(LOGIC.md 확인 4).

---

## 3. 공통 — POC 공통값 vs 지금 공용 설정

| 필드 | POC (3곳 공통) | 지금 공용 설정 (`profiles/standard.yaml`) | 상태 |
|---|---|---|---|
| 오더유형 - AUART | `ZEXP` | `_base` 고정값 `ZEXP` | 공용으로 이미 됨 |
| 판매조직 - VKORG | `1000` | `_base` 고정값 `1000` (전송 전용) | 공용으로 이미 됨 |
| Sold-to - KUNNR | 고객코드 | 고객코드(`meta.customer_no`) | 공용으로 이미 됨 |
| Ship-to - KUNWE | 거래처마다 다름 | 기본 = 고객코드, 비면 노랑 | 공용 + 거래처 예외(SID TOOL·YGJP) |
| 최종고객 - KUNNR3 | 고객코드 | **전송 필드에서 삭제** (2026-10-02) | 해당 없음 |
| 고객발주번호 - BSTKD | `PO번호(Location)` | `header.po_number` 원문 그대로 | 공용 + 거래처 예외(SID TOOL·KL·YGJP) |
| PO품목번호 - POSEX | 있을 때만 | `line.posex` 원문, 없으면 빈 칸 | 공용 + 거래처 예외(KL 정수화) |
| 브랜드 - ZBRAND | 거래처별 하드코딩 | 브랜드 마스터에서 이 고객 후보 — 1개면 자동, 여럿이면 빈 칸 + 드롭다운 (`csv_choice`, 규칙 이름 `brand_code`) | 공용 + 거래처 예외(SID TOOL·YGJP). KL 은 공용 그대로 |
| Shipping Condition - ZSHCO | 거래처별 고정 | Shipping Master 값 | 공용 + 거래처 예외(YGJP) |
| 고객자재번호 - KDMAT | (없었음) | `line.our_item` (거래처 품번) | 공용으로 이미 됨 — POC 에 없던 새 필드 |
| 자재번호 - MATNR | `your_item` (KL 은 빈 칸) | `line.item_code`(우리 품번), 괄호 제거, KDMAT 가 있으면 비어도 통과 | 공용 + 거래처 예외(YGJP 경고 강화) |
| 수량 - KWMENG | qty | `line.quantity` 정수, 비면 빨강 | 공용 (수량 0 경고는 엔진 항목 N3) |
| Packing Spec - ZPKRE | 거래처별 | 빈 칸 | 거래처 예외(SID TOOL·KL) |
| Remark - EMPST | KL 만 | 빈 칸 | 거래처 예외(KL) |
| Shipping Type - VSART | 3곳 모두 `04` | Shipping Master 값 | 공용으로 이미 됨 (3곳 모두 Shipping Master 를 따른다) |
| 단가 - PRICE | **보내지 않음** | `line.unit_price` | 공용으로 이미 됨 — POC 와 다름(지금은 보낸다) |
| 통화 - WAERK | **보내지 않음** | 통화 원문 → ISO 3자리(`refs/currency.csv`) | 공용으로 이미 됨 — POC 와 다름 |

> LOGIC.md §0 의 "공통으로 비어 있는 컬럼(PRICE, WAERK …)" 설명은 이제 맞지 않습니다.
> PRICE·WAERK 는 2026-10-02 에 전송 필드로 되살아나 **실제로 보냅니다.** 나머지(VDATU·ZTERM·INCO·ETDAT)는 전송 필드에서 빠졌습니다.
> PRICE 가 빈 칸이면 SAP 가격 마스터가 채웁니다.

### 공통 주의 — 브랜드 규칙 이름

공용 프로필의 브랜드 후보 규칙(`csv_choice`) 이름이 `brand_code` 입니다. 거래처 파일이 같은 이름으로
문구 대조 규칙을 선언하면 **항목이 통째로 교체**되어(SCHEMA §1) 드롭다운 후보가 사라집니다.
그래서 전용 규칙은 `brand_text_match` 로 만들고, 필드에서 `choices: brand_code` 로 공용 후보를 가리킵니다.
(SCHEMA §4.5 예시 A·B 는 같은 이름 `brand_code` 를 쓰고 `choices: brand_choice` 를 가리키는데, 지금 프로필에는
`brand_choice` 라는 규칙이 없습니다 — 예시 쪽을 고칠 대상입니다. §6 N4)

---

## 4. 거래처별 설계

표의 "상태" 칸:

- **공용으로 이미 됨** — 전용 규칙 없이 지금도 결정대로 나온다
- **전용 규칙 필요** — `customers/{code}.yaml` 에 적으면 된다 (지금 엔진으로 가능)
- **엔진 확장 필요** — 지금 SCHEMA 문법·엔진으로는 안 된다 (§6 N 번호)

YAML 예시는 모양만 보여 줍니다. 값은 2026-10-02 결정(§5) 기준입니다.

### 4.1 SID TOOL — SID TOOL CO., INC. (고객코드 100249)

> 옛 별칭 "SID TOOL"는 쓰지 않는다. 거래처 파일은 `masters/customers/sid.yaml`(`meta.code: SID`).

- 입력: HTM. 발주서 1부에 출하 창고가 여럿이면 **창고마다 오더 1건**으로 나뉩니다(`split.by: shipment`).
- 실물 근거: `samples/MSC` 의 **SAP 업로드 결과 CSV 12개**("판매오더 업로드 내역 MSC_100249_*.csv").

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| 오더 나누기 | SHIP TO 에 `CHECK COMPLETE` 가 있으면 섹션별 | `split.by: shipment`. 출하처 블록 알아보는 법은 `hints` 에 (fixture 의 hints 재사용) | 전용 규칙 필요 |
| 출하 창고 도시 | ATLANTA/ELKHART/HARRISBURG/RENO 포함 여부 | 결정표 `tables.ship_to_routing` — Claude 는 창고 블록 원문만, 도시 판정은 결정표 | 전용 규칙 필요 |
| Ship-to - KUNWE | ELKHART 100249 · HARRISBURG 319677 · RENO 319678 · ATLANTA 319679 | 같은 결정표 `then: [KUNNR2, _city, _pack_base]` | 전용 규칙 필요 (업로드 결과와 일치) |
| 도시를 못 찾을 때 | 빈 칸 그대로 | `on_no_match: warn` — Ship-to·도시·포장 기본값이 빈 칸 + 노랑. 막지 않는다 | 전용 규칙 필요 |
| 고객발주번호 - BSTKD | `PO번호(도시)` | `if(_city, concat(PO번호, "(", _city, ")"), PO번호)` — 도시를 못 찾으면 PO번호만 | 전용 규칙 필요 (업로드 결과 `7588650(ATLANTA)` 형식과 일치) |
| 브랜드 - ZBRAND | ORDERED FROM 키워드: HERTEL→38, INTERSTATE→127, ACCUPRO→205, CLASS C→428 | 전용 `keyword_map`(`brand_text_match`): HERTEL→`038` · INTERSTATE→`127` · ACCUPRO→`205` · CLASS C→`428`. 못 찾으면 빈 칸 + 노랑 + 드롭다운(후보 7개) | 전용 규칙 필요 |
| Shipping Condition - ZSHCO | `A` 고정 | Shipping Master 를 따른다 (지금 100249 = 빈 칸 → 노랑) | 공용으로 이미 됨 |
| Shipping Type - VSART | `04` | Shipping Master 100249 = `04` | 공용으로 이미 됨 |
| Packing Spec - ZPKRE | 도시 기본값 + 참조표 B·C열 | 도시 기본값(ELKHART `C` · HARRISBURG `N` · RENO `O` · ATLANTA `A`, 결정표 `_pack_base`) + **고객자재번호(KDMAT, Your Code)가 `refs/sid_ref.csv` 에 있으면** 그 행의 Color RING 또는 HERTEL Number 값을 쉼표로 이어 붙인다 (예: `A,Blue RING` · `C,4006205`). 표에 없으면 기본값만, 경고 없음 | 전용 규칙 필요 |
| 자재번호 - MATNR | your_item | 공용 (`line.item_code`). hints 가 "Your Item Number = item_code" 를 지킨다 | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | (없음) | 공용 (`line.our_item`, SID TOOL 8자리 품번) | 공용으로 이미 됨 |
| PO품목번호 - POSEX | 넣지 않음 | 공용 (문서에 없으면 빈 칸) | 공용으로 이미 됨 |
| 단가 - PRICE | 보내지 않음 | 공용. 창고별 블록 품목표에는 Price 열이 없어 여러 창고 문서는 빈 칸 — **괜찮다**(SAP 가격 마스터가 채운다) | 공용으로 이미 됨 |
| 통화 - WAERK | 보내지 않음 | 공용 (`United States Dollars` → USD) | 공용으로 이미 됨 |
| 합계 검증 | 없음 | `checks: shipment_total_match`, `severity: warn` — 창고별 수량 합 ≠ 요약표 합계면 노랑(블록을 빠뜨렸다는 신호) | 전용 규칙 필요 |

```yaml
# masters/customers/sid.yaml (모양만)
split: { by: shipment, group_label: _city }
tables:
  ship_to_routing:
    scope: shipment
    when: [{ source: shipment.ship_to_text, fallback_source: header.ship_to_text, op: contains_ci }]
    then: [KUNNR2, _city, _pack_base]
    rows:
      - { when: ["ELKHART"],    then: ["100249", "ELKHART",    "C"] }
      - { when: ["HARRISBURG"], then: ["319677", "HARRISBURG", "N"] }
      - { when: ["RENO"],       then: ["319678", "RENO",       "O"] }
      - { when: ["ATLANTA"],    then: ["319679", "ATLANTA",    "A"] }
    on_no_match: { action: warn, message: "출하 창고 도시를 인식하지 못했습니다 — Ship-to 를 확인하세요" }
rules:
  brand_text_match:
    kind: keyword_map
    source: header.brand_text
    fallback_source: header.order_text
    case_insensitive: true
    entries:
      - { contains: "HERTEL",     value: "038" }
      - { contains: "INTERSTATE", value: "127" }
      - { contains: "ACCUPRO",    value: "205" }
      - { contains: "CLASS C",    value: "428" }
    value_check: { table_file: refs/brand_master.csv, value_column: zbrand, filter_column: kunnr }
    on_no_match: { action: warn, message: "브랜드 문구를 인식하지 못했습니다: {brand_text} — 드롭다운에서 고르세요" }
  sid_ref:                              # Color RING · HERTEL 대상 품번 (masters/refs/sid_ref.csv)
    kind: lookup
    table_file: refs/sid_ref.csv
    key: line.our_item                  # = KDMAT (Your Code)
    key_column: your_code
    return: [color_ring, hertel_no]
    on_no_match: { action: empty }      # 대상이 아닌 품번이 대부분이다 — 경고하지 않는다
fields:
  KUNNR2: { from: table, table: ship_to_routing, required: warn }
  BSTKD:  { from: expr, expr: 'if(_city, concat(header.po_number, "(", _city, ")"), header.po_number)', required: warn }
  ZBRAND: { from: rule, rule: brand_text_match, choices: brand_code, required: warn }
  ZPKRE: { from: expr, expr: 'join(",", compact([_pack_base, sid_ref.color_ring, sid_ref.hertel_no]))' }
checks:
  - { id: shipment_total_match, severity: warn }
```

### 4.2 KL — Kennametal (고객코드 107525)

- 입력: PDF. 문서 1부 = 오더 1건(`split.by: none`).
- 실물 근거: `samples/KL/4507628839.pdf` 와 그 텍스트 덤프, POC 출력 엑셀 1건.

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| 고객발주번호 - BSTKD | `Document No. 4507628839 / 040` 에서 `/` 앞 | Claude 는 `Document No.` 뒤 **원문 전체**(`4507628839 / 040`)를 `po_number` 로 읽고, `/` 앞 자르기는 `regex_extract` 규칙이 한다. **fixture 의 hints("슬래시 앞만")는 변환 지시라 고친다**(P1) | 전용 규칙 필요 |
| 브랜드 - ZBRAND | `2` (OEM) 고정 | **고정하지 않는다.** 공용 `csv_choice` 그대로 — 후보 002 OEM BRAND · 058 NO BRAND 라 빈 칸 + 드롭다운. 후보 정리는 브랜드 마스터에서 | 공용으로 이미 됨 |
| Packing Spec - ZPKRE / Remark - EMPST | 품목 `Brand:` 원문에 `WIDIA GTD` → WGT, `KENNAMETAL` → KMT | 라인 원문 `line.brand_text` 에 `keyword_map` 1개(`WIDIA GTD` 를 위에), 두 필드가 같은 규칙을 참조. 둘 다 아니면 **빈 칸**(`on_no_match: empty`) | 전용 규칙 필요 |
| PO품목번호 - POSEX | `00001` → `1` | `format: integer` | 전용 규칙 필요 |
| 자재번호 - MATNR | 항상 빈 칸 (우리 품번이 문서에 없음) | 공용 그대로 — KDMAT 가 있으면 경고 없음 | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | Kennametal Mat. No. | 공용 (`line.our_item`) | 공용으로 이미 됨 |
| Ship-to - KUNWE | 넣지 않음 | 공용 = 107525 | 공용으로 이미 됨 |
| Shipping Condition - ZSHCO | 넣지 않음 | Shipping Master 107525 = 빈 칸 → 노랑 | 공용으로 이미 됨 |
| Shipping Type - VSART | `04` | Shipping Master 107525 = `04` | 공용으로 이미 됨 |
| 단가·통화 | 보내지 않음 | 공용 | 공용으로 이미 됨 |

```yaml
# masters/customers/kl.yaml (모양만)
extraction:
  hints: |
    …
    "Document No.  4507628839 / 040"  → po_number (원문 그대로, 슬래시와 뒤 번호까지)
    …
rules:
  po_base:
    kind: regex_extract
    source: header.po_number          # 원문 "4507628839 / 040"
    pattern: '^\s*([^/]+?)\s*(/|$)'
    group: 1
    on_no_match: { action: warn, message: "발주번호 형식이 다릅니다: {po_number}" }
  brand_mark:
    kind: keyword_map
    source: line.brand_text
    case_insensitive: true
    entries:
      - { contains: "WIDIA GTD",  value: "WGT" }
      - { contains: "KENNAMETAL", value: "KMT" }
    on_no_match: { action: empty }
fields:
  BSTKD:  { from: rule, rule: po_base, required: warn }
  POSEX:  { from: doc, path: line.posex, format: integer }
  ZPKRE: { from: rule, rule: brand_mark }
  EMPST:  { from: rule, rule: brand_mark }
```

### 4.3 YGJP — YG-1 JAPAN CO., LTD. (고객코드 3200)

- 입력: PDF. 문서 1부 = 오더 1건.
- 실물 근거: `samples/YGJP/_dump` 발주서 텍스트 5건.

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| Ship-to - KUNWE | `319854` 고정 | `fields.KUNNR2: { from: const, value: "319854" }` | 전용 규칙 필요 |
| 고객발주번호 - BSTKD | `01-{Created On YYYYMMDD}-{Purchase Order ID}` | Claude 는 날짜·번호를 원문대로, 조립은 `concat("01-", date_yyyymmdd(header.po_date), "-", header.po_number)`. `01-` 은 고정 | 전용 규칙 필요 |
| 브랜드 - ZBRAND (읽기) | 하단 줄이 표와 완전일치 | Claude 는 하단 블록에서 **브랜드가 적힌 줄을 원문 그대로** `header.brand_text` 에 담는다. 포장지시가 같은 줄에 붙어 있어도 **가르지 않는다**. `Remark: YG agent : …` 줄은 브랜드가 아니라고 hints 에 적는다 | 전용 규칙 필요 (hints) |
| 브랜드 - ZBRAND (판정) | POC 자체 표 25개 | **브랜드 마스터가 기준.** `csv_map` — `refs/brand_master.csv` 의 3200 행에서 **브랜드명(zbrant)이 원문에 포함되면** 그 코드(zbrand). 대소문자 무시. 못 찾으면 빈 칸 + 노랑 + 드롭다운. POC 25개 표는 버린다 | 전용 규칙 필요 (긴 이름 우선 보장은 N2) |
| Shipping Condition - ZSHCO | 브랜드 471·507 → `A`, 그 외 `L` | YGJP 파일에서 `expr` 로 덮어쓴다: `if(in(브랜드, ["471", "507"]), "A", "L")` — **브랜드를 못 찾아도 `L`**. `in()` 사용(`contains()` 금지) | 전용 규칙 필요 |
| 브랜드를 사람이 바꿨을 때 | (해당 없음 — 엑셀을 직접 고침) | 드롭다운에서 ZBRAND 를 바꾸면 ZSHCO 가 따라가야 한다. 지금 엔진은 검수 화면 저장 시 **검증만 다시** 돌아 ZSHCO 가 옛 값으로 남는다 | **엔진 확장 필요 N1** |
| Shipping Type - VSART | `04` | Shipping Master 를 따른다 (지금 3200 = `05`) | 공용으로 이미 됨 |
| Product ID 없는 줄 | 제외 | **제외하지 않는다.** 보통 행으로 깔고 MATNR 노랑 경고. 사람이 지운다 | 전용 규칙 필요 (MATNR 덮어쓰기) |
| 수량 0 인 줄 | 제외 | **제외하지 않는다.** 보통 행으로 깔고 수량 노랑 경고. 사람이 지운다 | **엔진 확장 필요 N3** |
| Packing Spec - ZPKRE / Remark - EMPST | S/O 업로드에는 넣지 않음 | **보내지 않는다** — 공용 그대로 빈 칸 | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | Your Code | 공용 (`line.our_item`) | 공용으로 이미 됨 |
| PO품목번호 - POSEX | 있으면 | 공용 | 공용으로 이미 됨 |
| 통화 - WAERK | 헤더 `JPY` (S/O 에는 안 넣음) | 공용 — `Total Value: … JPY` 의 `JPY` → JPY | 공용으로 이미 됨 |

**사실 기록 (판단 아님, 2026-10-02 기준 `refs/brand_master.csv`)**

- 3200 후보는 112 TANAKAZEN BRAND · 166 IWASE SANGYO BRAND · 192 JIMK BRAND · 002 OEM BRAND · 039 HF BRAND ·
  004 NO MARKING · 058 NO BRAND 7개다. **471·507 은 3200 후보에 없다.**
- 실물 5건의 브랜드 줄(`YG BRAND`, `SAKUSAKU BRAND`, `YAMAKATSU BRAND`, `YG BRAND (COMINIX)`)에는 위 7개 이름이
  하나도 포함되지 않는다. 지금 마스터로는 5건 모두 브랜드 빈 칸 + 드롭다운이다.
- 7개 이름끼리는 서로 포함 관계가 없다(한 이름이 다른 이름 안에 들어 있지 않다). 마스터가 바뀌면 생길 수 있다 → N2.

```yaml
# masters/customers/ygjp.yaml (모양만)
rules:
  brand_text_match:
    kind: csv_map
    source: header.brand_text
    table_file: refs/brand_master.csv     # 브랜드 마스터가 기준. 별도 표를 두지 않는다
    filter_column: kunnr                  # 3200 행만
    key_column: zbrant                    # 브랜드명이 원문에 포함되면 (판정 방식 기본값 = 포함)
    value_column: zbrand                  # 그 코드
    case_insensitive: true
    # order: longest_first                # N2 구현 후 추가
    on_no_match: { action: warn, message: "브랜드를 인식하지 못했습니다: {brand_text} — 드롭다운에서 고르세요" }
fields:
  KUNNR2: { from: const, value: "319854" }
  BSTKD:  { from: expr, expr: 'concat("01-", date_yyyymmdd(header.po_date), "-", header.po_number)', required: warn }
  ZBRAND: { from: rule, rule: brand_text_match, choices: brand_code, required: warn }
  ZSHCO:
    from: expr
    expr: 'if(in(brand_text_match, ["471", "507"]), "A", "L")'   # N1 후에는 '최종 ZBRAND' 를 참조하도록 바꾼다
    explain: "브랜드가 471·507 이면 A, 그 밖에는(브랜드를 못 찾은 경우 포함) L"
  # 프로필 MATNR 은 통째 교체된다 — path·format 까지 다시 적는다. required_unless 를 빼서
  # KDMAT 가 있어도 Product ID 가 비면 노랗게 띄운다.
  MATNR:  { from: doc, path: line.item_code, format: strip_parens, required: warn }
checks:
  # - { id: zero_quantity, severity: warn }   # N3 구현 후 추가
```

> `csv_map` 에 `mode: contains` 를 적지 않는다. SCHEMA §4.5 표에는 `mode` 키가 있지만 지금 엔진은 읽지 않고
> (`mode_column` 만 본다, 없으면 포함 대조) 검증기 허용 키에도 없어 오류가 난다 — N4 에서 SCHEMA 를 맞춘다.
>
> `ZSHCO` 식은 지금 **규칙이 정한 브랜드**만 봅니다. 사람이 드롭다운에서 브랜드를 고르면 N1 전까지는
> ZSHCO 가 따라 바뀌지 않습니다.

---

## 5. 결정 사항

2026-10-02 사용자 결정. **남은 미결은 없습니다.**

| # | 질문 | 결정 | 일자 |
|---|---|---|---|
| Q1 | 브랜드 코드 앞자리 0 | **0 붙인 3자리** — 브랜드 마스터 형식 그대로. SID TOOL 키워드 값은 038 · 127 · 205 · 428 | 2026-10-02 |
| Q2 | SID TOOL ZSHCO=A 를 Shipping Master 에 넣을지 | **넣지 않는다.** ZSHCO 는 Shipping Master 를 따른다 | 2026-10-02 |
| Q3 | YGJP VSART 04 vs 05 | **Shipping Master 를 따른다** (지금 05). 전용 규칙 없음 | 2026-10-02 |
| Q4 | POC 브랜드 코드 25개 처리 | **브랜드 마스터가 무조건 기준.** 마스터는 건드리지 않고 POC 25개 표는 버린다 | 2026-10-02 |
| Q5 | YGJP 브랜드 판정 방식 | 마스터에 등록된 3200 의 **브랜드명(zbrant)이 원문에 포함되면** 그 코드(`csv_map`). 못 찾으면 빈 칸 + 드롭다운 | 2026-10-02 |
| Q6 | YGJP ZSHCO | ZBRAND 가 471 또는 507 이면 A, 아니면 L — **브랜드를 못 찾아도 L**. 드롭다운 변경을 따라가도록 재계산(N1) | 2026-10-02 |
| Q7 | YGJP Product ID 없음 / 수량 0 줄 | **제외하지 않는다.** 보통 행 + 노랑 경고, 사람이 지운다 | 2026-10-02 |
| Q8 | YGJP BSTKD `01-` | **고정.** `01-{Created On 을 YYYYMMDD}-{Purchase Order ID}` | 2026-10-02 |
| Q9 | YGJP 포장지시·비고 전송 | **보내지 않는다** (ZPKRE·EMPST 빈 칸). 그리고 YGJP Ship-to(KUNNR2) = **319854 고정** | 2026-10-02 |
| Q10 | KL 브랜드 고정 여부 | **고정하지 않는다.** 공용 `csv_choice` 드롭다운 유지. KL 전용 브랜드 규칙 없음 | 2026-10-02 |
| Q11 | KL WGT/KMT | **넣는다.** Brand 원문 WIDIA GTD → WGT, KENNAMETAL → KMT 를 ZPKRE·EMPST 둘 다에. 둘 다 아니면 빈 칸 | 2026-10-02 |
| Q12 | KL POSEX | **정수** (`00001` → `1`) | 2026-10-02 |
| Q13 | KL BSTKD | **`/` 앞부분만.** 읽기는 원문 전체(Claude), 자르기는 엔진(`regex_extract`) | 2026-10-02 |
| Q14 | KL Ship-to | **107525** (공용 기본 그대로) | 2026-10-02 |
| Q16 | SID TOOL 포장 참조표(sid_ref) | **연동한다** (2026-10-02 재결정). `masters/refs/sid_ref.csv`(열: Your code · Color RING · HERTEL Number). KDMAT 가 표에 있으면 그 값을 창고 기본값 뒤에 이어 붙인다. 한 행에 두 값이 함께 있는 경우는 없다(1,007행 확인). 같은 품번 10건이 중복이나 값도 같다 | 2026-10-02 |
| Q17 | SID TOOL 도시 미인식 시 전송 차단 | **막지 않는다.** 경고만 — 전송 후 SAP 에서 고칠 수 있다(§1 원칙) | 2026-10-02 |
| Q18 | SID TOOL 여러 창고 문서의 PRICE 빈 칸 | **괜찮다.** SAP 가격 마스터가 채운다 | 2026-10-02 |
| Q19 | SID TOOL 키워드에 없는 브랜드 | **빈 칸**, 드롭다운에서 고른다 | 2026-10-02 |

(Q15 · Q20 은 삭제됨.)

---

## 6. 구현 목록

### 6-a. 엔진·코드 변경

| # | 내용 | 왜 | 설계 요점 | 쓰는 곳 |
|---|---|---|---|---|
| **N1** | **사람이 고친 값에 따라 다른 필드 다시 계산** | YGJP ZSHCO 가 드롭다운으로 바꾼 ZBRAND 를 따라가야 한다. 지금 `batch_service.merge_edits` 는 `validate_row` 만 다시 돈다 | 필드 식이 **다른 필드의 최종 값**을 참조할 수 있게 한다(예: 새 네임스페이스 `field.ZBRAND`, `fields` 의 `expr` 에서만). 검수 저장 시 `field.*` 를 참조하는 `from: expr` 필드만 다시 계산한다. **사람이 직접 고친 필드는 덮어쓰지 않는다**(P5). 순환 참조는 검증기가 막는다. SCHEMA §3·§4.7, 계약 §6.1(서버가 사람이 안 고친 칸을 바꿀 수 있음)을 함께 고친다 | YGJP ZSHCO |
| **N2** | **`csv_map` 긴 이름 우선 옵션** | `csv_map` 은 파일 행 순서대로 첫 일치에서 멈춘다(`mapping_rules._csv_map`). 마스터에 서로 포함되는 이름(예: `X BRAND` 와 `X BRAND (Y)`)이 생기면 짧은 쪽이 먼저 걸릴 수 있다. 브랜드 마스터는 사람이 순서를 관리하는 표가 아니다 | 규칙 옵션 `order: longest_first` — 대조 전에 `key_column` 값 길이 내림차순으로 정렬(같은 길이는 파일 순서). 기본은 지금처럼 파일 순서. SCHEMA §4.5 `csv_map` 옵션 표 + 검증기 `RULE_OPTIONS` 에 추가 | YGJP ZBRAND |
| **N3** | **수량 0 경고** | `KWMENG` 의 `required` 는 빈 값만 본다 — `"0"` 은 값이 있는 것으로 친다 | `checks` 에 새 id `zero_quantity`(수량이 0 인 행에 KWMENG 노랑). 엔진 검사 등록 + SCHEMA §4.9 표에 등재. **주의:** 지금 `merge_edits` 는 저장 시 행 이슈를 `validate_row` 로 다시 만들고 `CHUNK_FAILED` 만 넘겨 받는다 — 배치 검사로만 구현하면 저장 한 번에 경고가 사라진다. 저장 후에도 다시 평가되게 한다 | YGJP |
| **N4** | SCHEMA §4.5 정리 (문서) | ① 예시 A·B 가 `choices: brand_choice` 를 가리키는데 프로필의 후보 규칙 이름은 `brand_code` — 그대로 베끼면 검증기 14번 오류 또는 드롭다운 소실. ② 예시 B 는 완전일치, 예시 C(KL 고정)는 Q5·Q10 결정과 반대. ③ `csv_map` 옵션 표의 `mode` 는 엔진·검증기 모두 지원하지 않는다 | 전용 규칙 이름 `brand_text_match`, `choices: brand_code`. 예시 B 를 포함 대조로, 예시 C 는 삭제 또는 "고정하지 않음"으로. `mode` 는 표에서 빼거나 구현 대상으로 표시. architect 소유 문서 | 전 거래처 |

**하지 않기로 함 (2026-10-02):** 품목 줄 자동 제외(Q7) · 브랜드 보정 파일을 보는 `value_check`·브랜드 마스터 보강(Q4) ·
브랜드 코드 0 제거 정규화(Q1) · 여러 창고 문서 단가 보충(Q18) · SID TOOL 포장 참조표 연동(Q16) · Shipping Master 값 변경(Q2·Q3).

### 6-b. YAML 만으로 되는 것

| # | 내용 | 파일 | 지금 엔진으로 가능? |
|---|---|---|---|
| Y1 | SID TOOL — meta · hints · `split: shipment` · 결정표(KUNNR2 · _city · _pack_base, warn) · BSTKD(도시 없으면 PO번호만) · ZPKRE · 브랜드 `keyword_map`(038/127/205/428, `value_check`) · 합계 검증(warn) | `masters/customers/sid.yaml` | **가능** — 엔진 의존 없음 |
| D3 | SID TOOL 포장 참조표 — `lookup` 규칙 `sid_ref` + ZPKRE 식. **열 이름에 공백이 있어 식에서 참조할 수 없다** → `sid_ref.csv` 머리글을 `your_code,color_ring,hertel_no` 로 바꾸거나(권장, 다른 참조표와 같은 소문자 규칙), 엔진이 공백 열 이름을 받게 한다 | `masters/refs/sid_ref.csv` · `sid.yaml` | 파일 들어옴. 머리글 결정 후 Y1 과 함께 |
| Y2 | KL — meta · hints(발주번호 원문 전체로 고침) · BSTKD `regex_extract` · POSEX `format: integer` · ZPKRE·EMPST `keyword_map`(WGT/KMT, `on_no_match: empty`) | `masters/customers/kl.yaml` | **가능** — 엔진 의존 없음 |
| Y3 | YGJP — meta · hints(브랜드 줄 원문 그대로, `Remark: YG agent` 줄 구분) · KUNNR2 `319854` · BSTKD 식 · 브랜드 `csv_map`(마스터 이름 포함) · ZSHCO 식 · MATNR 덮어쓰기 | `masters/customers/ygjp.yaml` | **부분 가능** — 지금 바로 얹을 수 있다. N2(`order: longest_first`)·N3(`zero_quantity`)가 끝나면 각 한 줄을 더하고, N1 이 끝나면 ZSHCO 식이 최종 ZBRAND 를 보도록 바꾼다 |

### 구현 시 고려 — 테스트 픽스처와 이름이 겹친다

`backend/tests/conftest.py` 는 실물 `masters/` 를 사본으로 복사한 뒤 `backend/tests/fixtures/customers/*.yaml` 을
**같은 이름으로 덮어쓴다.** SID TOOL 은 실물 파일명이 `sid.yaml` 이라 픽스처(`msc.yaml`)와 겹치지 않지만, 실물 `kl.yaml`·`ygjp.yaml` 을 만들면 테스트 사본에서는
픽스처가 이긴다 — 테스트는 실물 규칙을 검증하지 않는다. 실물 규칙용 회귀 테스트를 따로 두거나, 픽스처를 새 규칙에 맞춰
함께 고칠지 구현 때 정한다.

### 권장 순서

```
1. N4 (SCHEMA 정리)                ← Y1~Y3 가 베낄 원본이므로 먼저. 문서만
2. Y1 SID TOOL                          ← 지금 엔진으로 가능. 업로드 결과 12건과 대조
   → validate_masters → check_sample → parse_one --rows → 업로드 CSV 와 비교
3. Y2 KL                           ← 지금 엔진으로 가능
4. Y3 YGJP (1차)                   ← 지금 엔진으로 얹는다. ZSHCO 는 자동 판정 브랜드 기준
5. N2 · N3 · N1 (엔진, 서로 독립)  ← 끝나는 대로 Y3 에 한 줄씩 반영
   N2 → order: longest_first · N3 → checks zero_quantity · N1 → ZSHCO 가 최종 ZBRAND 참조
```

각 YAML 을 고친 뒤에는 `python scripts/validate_masters.py` 를 돌리고, 구현이 끝난 항목은 이 문서에서
값을 지우고 YAML 위치만 남긴다(§1 운영 규칙).

---

## 7. 범위 밖

| 항목 | 이유 |
|---|---|
| POC 사전점검 엑셀 (`pre_check`, Unit=PC 고정, "Your Code" 열) | 이 프로그램의 출력은 EAI 전송 하나다 |
| YGJP PO정리 엑셀 (`ygjp_po.py`) | 같은 이유. 포장지시·비고는 SAP 로 보내지 않는다(Q9) |
| `parsers/pdf_yg1.py` (YG1) | POC 에서도 쓰이지 않던 코드이고 이번 범위에서 제외 |
| POC 파일명 규칙 | 전송 페이로드에 파일명이 들어가지 않는다 |
| 삭제된 전송 필드(KUNNR3·VDATU·ZTERM·INCO1/2·ETDAT·BSTDK_E·DELCO·AUGRU·VKAUS·IHREZ_E·VGBEL·VGPOS) | 2026-10-02 사용자 결정으로 보내지 않는다. 다시 필요하면 `_base` 부터 |

---

## 8. 새 거래처 전용 규칙을 추가하는 절차

전체 절차는 [`masters/SCHEMA.md` §5](masters/SCHEMA.md) 입니다. 요약하면:

1. 전용 규칙이 없어도 브랜드 마스터에 등록된 고객이면 공용 설정으로 이미 동작합니다. **먼저 써 보고, 공용으로 안 되는 것만** 전용 규칙으로 만듭니다.
2. `masters/customers/_template.yaml` 을 복사해 `meta` 와 `extraction.hints`(문서 구조 설명, 변환 지시 금지)를 채우고, **공용과 다른 필드만** 적습니다. 브랜드 전용 규칙 이름은 `brand_code` 와 겹치지 않게 합니다.
3. 브랜드를 문구로 가리는 규칙은 실물 발주서에서 그 문구가 **늘 찍힌다는 것을 확인한 뒤에만** 만듭니다. 코드는 브랜드 마스터에 있는 것만 씁니다.
4. 못 정한 값은 빈 칸 + 경고로 둡니다. 전송을 막는 설정은 쓰지 않습니다(§1 원칙).
5. `validate_masters.py` → `check_sample.py` → `parse_one.py --rows` 로 확인하고, 이 문서에는 "무엇을 왜, 어떤 장치로"와 상태만 적습니다. 값은 YAML 에 둡니다.
