# 거래처 전용 규칙 (Customer Rules)

> 작성 2026-10-02 · architect · 대상: 현업(영업·물류 담당)과 개발자
> 원본 자료: 루트 `LOGIC.md`(POC 하드코딩 요약, git 미추적) · `samples/PO변환_비즈니스로직_명세서.md`
> 문법 원천: [`masters/SCHEMA.md`](masters/SCHEMA.md) · 전송 필드 원천: [`masters/_base/sap_defaults.yaml`](masters/_base/sap_defaults.yaml)

---

## 1. 이 문서는 무엇인가

이 프로그램은 발주서를 읽어 SAP 판매오더 한 줄 한 줄로 바꿉니다. 값이 정해지는 길은 두 가지입니다.

| 구분 | 무엇 | 어디에 있나 |
|---|---|---|
| **공용 설정** | 모든 거래처에 똑같이 적용되는 방식. 예) 판매처(Sold-to)는 고객코드, 브랜드는 브랜드 마스터에서, 출하조건·운송수단은 Shipping Master 에서 | `masters/profiles/standard.yaml` · `generic.yaml` |
| **거래처 전용 규칙** | 특정 거래처에만 있는 예외. 예) MSC 는 창고 도시마다 Ship-to 가 다르다 | `masters/customers/{code}.yaml` (거래처 1곳 = 파일 1개) |

**지금(2026-10-02) 실물 `masters/customers/` 에는 전용 규칙 파일이 하나도 없습니다.** MSC·KL·YGJP 도
공용 설정만으로 돌고 있습니다(2026-09-23 "기본부터 만들고 예외는 나중에 다시 얹는다" 결정).
예전 규칙 모양은 테스트용 사본 `backend/tests/fixtures/customers/{msc,kl,ygjp}.yaml` 에 남아 있습니다.

이 문서는 **전용 규칙을 다시 얹기 전에** 다음을 정리합니다.

- POC 에서 무엇을 했는지 (원본)
- 지금 구조에서 **어떤 장치로** 같은 결과를 낼지, 그리고 **왜** 그 장치인지
- 각 항목의 **상태** — 이미 공용으로 됨 / 전용 규칙 필요 / 데이터 보강 필요 / 엔진 확장 필요 / 확인 필요
- 사용자에게 물어야 할 것과 구현 순서

### 운영 규칙 — 값은 YAML 이 진실이다 (CLAUDE.md P3)

1. **값의 원천은 `masters/customers/{code}.yaml` 과 `masters/refs/*.csv` 입니다.** 이 문서에 적힌 코드값은
   "POC 에서 이랬다"는 **참고 인용**일 뿐입니다.
2. 한 항목이 YAML 로 구현되면, 이 문서의 해당 행은 **값을 지우고 위치만** 남깁니다.
   예) `Ship-to - KUNWE → masters/customers/msc.yaml tables.ship_to_routing`
3. 구현 뒤에 값을 바꿀 때는 YAML 만 고치고 이 문서는 고치지 않습니다. 두 곳에 같은 값을 쓰면
   언젠가 어긋나고, 어긋나면 오더가 잘못 생성됩니다.

### 이 문서의 필드 표기

화면과 같게 **"필드명 - 필드코드"** 로 씁니다. 전송 키가 화면 코드와 다른 것은 오른쪽 열을 보세요.

| 표기 | 전송 키 | 표기 | 전송 키 |
|---|---|---|---|
| 오더유형 - AUART | AUART | 자재번호 - MATNR | MATNR |
| 판매조직 - VKORG | VKORG (전송 전용, 표에 안 보임) | 수량 - KWMENG | KWMENG |
| Sold-to - KUNNR | KUNNR1 | Packing Spec - ZPKRE | ZPKRE2 |
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
| 3 | 못 찾으면 **조용히 빈 칸**으로 파일이 만들어진다 (LOGIC.md 확인 3) | 못 찾으면 **노랑(경고) 또는 빨강(전송 차단)** 으로 표시 | 빈 칸이 아무 표시 없이 SAP 로 가면 아무도 모른다 |
| 4 | YGJP 브랜드는 하단 줄이 표와 **완전히 같아야** 인식 | 포함 대조(`keyword_map`) + 사람 검수 드롭다운 | 실물 5건 중 최소 3건에서 완전일치가 실패한다 (아래 근거) |
| 5 | 브랜드 코드를 `38`, `1` 처럼 앞자리 0 없이 쓴다 | 브랜드 마스터(`refs/brand_master.csv`)는 `038`, `002` 처럼 3자리 | 형식이 다르면 마스터 등록 검사(`value_check`)에서 막히거나, 드롭다운 값과 자동 값이 따로 논다 — **Q1** |
| 6 | 출하조건(ZSHCO)·운송수단(VSART)을 거래처 코드에 고정 | 화면 **Shipping Master**(`refs/shipping_master.csv`, 고객 1곳 = 값 1개) | 현업이 화면에서 고칠 수 있어야 한다. 단, YGJP 처럼 **브랜드에 따라 달라지는** 값은 고객 1곳 = 값 1개로 표현할 수 없어 전용 규칙으로 덮어쓴다 |
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
| Sold-to - KUNNR | 고객코드 | 고객코드(`meta.customer_no`), 비면 빨강 | 공용으로 이미 됨 |
| Ship-to - KUNWE | 거래처마다 다름 | 기본 = 고객코드, 비면 노랑 | 공용 + 거래처 예외(MSC·YGJP) |
| 최종고객 - KUNNR3 | 고객코드 | **전송 필드에서 삭제** (2026-10-02) | 해당 없음 |
| 고객발주번호 - BSTKD | `PO번호(Location)` | `header.po_number` 원문 그대로 | 공용 + 거래처 예외(MSC·KL·YGJP) |
| PO품목번호 - POSEX | 있을 때만 | `line.posex` 원문, 없으면 빈 칸 | 공용으로 이미 됨 (KL 형식만 Q12) |
| 브랜드 - ZBRAND | 거래처별 하드코딩 | 브랜드 마스터에서 이 고객 후보 — 1개면 자동, 여럿이면 빈 칸 + 드롭다운 (`csv_choice`, 규칙 이름 `brand_code`) | 공용 + 거래처 예외(3곳 모두) |
| Shipping Condition - ZSHCO | 거래처별 고정 | Shipping Master 값 | 공용 + 데이터/예외(MSC·YGJP) |
| 고객자재번호 - KDMAT | (없었음) | `line.our_item` (거래처 품번) | 공용으로 이미 됨 — POC 에 없던 새 필드 |
| 자재번호 - MATNR | `your_item` (KL 은 빈 칸) | `line.item_code`(우리 품번), 괄호 제거, KDMAT 가 있으면 비어도 통과 | 공용으로 이미 됨 |
| 수량 - KWMENG | qty | `line.quantity` 정수, 비면 빨강 | 공용으로 이미 됨 |
| Packing Spec - ZPKRE | 거래처별 | 빈 칸 | 거래처 예외(MSC·KL) |
| Remark - EMPST | KL 만 | 빈 칸 | 거래처 예외(KL) — Q11 |
| Shipping Type - VSART | 3곳 모두 `04` | Shipping Master 값 | 공용 + 데이터 확인(YGJP Q3) |
| 단가 - PRICE | **보내지 않음** | `line.unit_price` | 공용으로 이미 됨 — POC 와 다름(지금은 보낸다) |
| 통화 - WAERK | **보내지 않음** | 통화 원문 → ISO 3자리(`refs/currency.csv`) | 공용으로 이미 됨 — POC 와 다름 |

> LOGIC.md §0 의 "공통으로 비어 있는 컬럼(PRICE, WAERK …)" 설명은 이제 맞지 않습니다.
> PRICE·WAERK 는 2026-10-02 에 전송 필드로 되살아나 **실제로 보냅니다.** 나머지(VDATU·ZTERM·INCO·ETDAT)는 전송 필드에서 빠졌습니다.

### 공통 주의 — 브랜드 규칙 이름

공용 프로필의 브랜드 후보 규칙(`csv_choice`) 이름이 `brand_code` 입니다. 거래처 파일이 같은 이름으로
문구 대조 규칙을 선언하면 **항목이 통째로 교체**되어(SCHEMA §1) 드롭다운 후보가 사라집니다.
그래서 이 문서의 예시는 전용 규칙을 `brand_text_match` 같은 **다른 이름**으로 만들고,
필드에서 `choices: brand_code` 로 공용 후보를 가리킵니다. (SCHEMA §4.5 예시 A·B 는 같은 이름 `brand_code`
를 쓰고 `choices: brand_choice` 를 가리키는데, 지금 프로필에는 `brand_choice` 라는 규칙이 없습니다 — 예시 쪽을 고칠 대상입니다. §6-a E6)

---

## 4. 거래처별 설계

표의 "상태" 칸:

- **공용으로 이미 됨** — 전용 규칙 없이 지금도 같은 결과가 나온다
- **전용 규칙 필요** — `customers/{code}.yaml` 에 적어야 한다 (엔진 변경 없음)
- **데이터 보강 필요** — 참조표·Shipping Master·브랜드 마스터에 값이 없거나 다르다
- **엔진 확장 필요** — 지금 SCHEMA 문법으로는 표현할 수 없다 (§6-a)
- **확인 필요** — POC 와 지금 자료가 어긋난다. §5 질문 번호 표시

YAML 예시는 모양만 보여 줍니다. 코드값 칸에 `<Q1>` 처럼 적힌 곳은 확인 뒤에 채웁니다.

### 4.1 MSC — SID TOOL CO., INC. (고객코드 100249)

- 입력: HTM. 발주서 1부에 출하 창고가 여럿이면 **창고마다 오더 1건**으로 나뉩니다(`split.by: shipment`).
- 실물 근거: `samples/MSC` 의 **SAP 업로드 결과 CSV 12개**("판매오더 업로드 내역 MSC_100249_*.csv").
  POC 설명이 아니라 실제로 SAP 에 들어간 값이라 가장 믿을 만한 근거입니다.

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| 오더 나누기 | SHIP TO 에 `CHECK COMPLETE` 가 있으면 섹션별 | `split.by: shipment`. 출하처 블록 알아보는 법은 `hints` 에 (fixture 의 hints 재사용) | 전용 규칙 필요 |
| 출하 창고 도시 | ATLANTA/ELKHART/HARRISBURG/RENO 포함 여부 | 결정표 `tables.ship_to_routing` — Claude 는 창고 블록 원문만, 도시 판정은 결정표 | 전용 규칙 필요 |
| Ship-to - KUNWE | ELKHART 100249 · HARRISBURG 319677 · RENO 319678 · ATLANTA 319679 | 같은 결정표의 `then: [KUNNR2, _city, _pack_base]` | 전용 규칙 필요 (업로드 결과와 일치 확인됨) |
| 도시를 못 찾을 때 | 빈 칸 그대로 | `on_no_match: error` 권장 — 엉뚱한 Ship-to 로 나가면 물건이 다른 창고로 간다 | 확인 필요 Q17 |
| 고객발주번호 - BSTKD | `PO번호(도시)` | `expr: 'concat(header.po_number, "(", _city, ")")'` | 전용 규칙 필요 (업로드 결과 `7588650(ATLANTA)` 형식과 일치) |
| 브랜드 - ZBRAND | ORDERED FROM 키워드: HERTEL→38, INTERSTATE→127, ACCUPRO→205, CLASS C→428 | `keyword_map` (SCHEMA §4.5 예시 A). 못 찾으면 노랑 + 드롭다운(후보 7개) | 전용 규칙 필요 + Q1(0 패딩) · Q19 |
| Shipping Condition - ZSHCO | `A` 고정 | Shipping Master 100249 의 zshco 를 `A` 로 채우면 YAML 없이 끝 | 데이터 보강 필요 Q2 (지금 빈 칸) |
| Shipping Type - VSART | `04` | Shipping Master 100249 = `04` | 공용으로 이미 됨 |
| Packing Spec - ZPKRE | 도시 기본값(ELKHART C · HARRISBURG N · RENO O · ATLANTA A) + 참조표 B·C열을 콤마로 | 기본값은 결정표 `_pack_base`. 참조표 조회는 **원본 표를 확보한 뒤** `lookup` 규칙으로 | 전용 규칙 필요 + 데이터 보강 필요 Q16 |
| 자재번호 - MATNR | your_item | 공용 (`line.item_code`). hints 가 "Your Item Number = item_code" 를 지킨다 | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | (없음) | 공용 (`line.our_item`, MSC 8자리 품번) | 공용으로 이미 됨 |
| PO품목번호 - POSEX | 넣지 않음 | 공용 (문서에 없으면 빈 칸) | 공용으로 이미 됨 |
| 단가 - PRICE | 보내지 않음 | 공용. 단, **창고별 블록 품목표에는 Price 열이 없어** 여러 창고 문서는 빈 칸이 된다 | 확인 필요 Q18 |
| 통화 - WAERK | 보내지 않음 | 공용 (`United States Dollars` → USD) | 공용으로 이미 됨 |
| 합계 검증 | 없음 | `checks: shipment_total_match` — 창고별 수량 합 = 요약표 합계. 블록을 하나 빠뜨리면 빨강 | 전용 규칙 필요 |

참고 — 업로드 결과의 Packing Spec 은 `A` 단독 또는 `A,Blue RING` 처럼 **기본값 + 참조표 값**입니다.
`samples/MSC/MSC_REF.xlsx.csv` 는 이름과 달리 참조표가 아니라 **업로드 결과 사본**이므로 쓸 수 없습니다.
참조표 원본(거래처 품번 → B·C열)이 저장소에 없습니다.

```yaml
# masters/customers/msc.yaml (모양만)
split: { by: shipment, group_label: _city }
tables:
  ship_to_routing:
    scope: shipment
    when: [{ source: shipment.ship_to_text, fallback_source: header.ship_to_text, op: contains_ci }]
    then: [KUNNR2, _city, _pack_base]
    rows:
      - { when: ["ELKHART"], then: ["100249", "ELKHART", "C"] }
      # HARRISBURG · RENO · ATLANTA 동일 모양
    on_no_match: { action: error, message: "출하 창고 도시를 인식하지 못했습니다" }
rules:
  brand_text_match:
    kind: keyword_map
    source: header.brand_text
    fallback_source: header.order_text
    case_insensitive: true
    entries:
      - { contains: "HERTEL", value: "<Q1: 38 또는 038>" }
      # INTERSTATE · ACCUPRO · CLASS C
    value_check: { table_file: refs/brand_master.csv, value_column: zbrand, filter_column: kunnr }
    on_no_match: { action: warn, message: "브랜드 문구를 인식하지 못했습니다: {brand_text} — 드롭다운에서 고르세요" }
fields:
  KUNNR2: { from: table, table: ship_to_routing }
  BSTKD:  { from: expr, expr: 'concat(header.po_number, "(", _city, ")")', required: true }
  ZBRAND: { from: rule, rule: brand_text_match, choices: brand_code, required: warn }
  ZPKRE2:
    from: expr
    expr: 'coalesce(_pack_base, "")'
    required: warn
    todo: "품번별 포장 추가비고 참조표 미확보 (Q16) — 원본이 오면 lookup 규칙을 붙인다"
checks:
  - { id: shipment_total_match, severity: error }
```

참조표가 들어온 뒤의 ZPKRE2 모양(참고): `lookup` 규칙 `pack_ref`(키 `line.our_item`)를 두고
`expr: 'join(",", compact([_pack_base, pack_ref.<B열>, pack_ref.<C열>]))'`. 빈 값은 `compact` 가 빼므로
`A` 단독도 `A,Blue RING` 도 같은 식으로 나옵니다. 열 이름은 원본을 받은 뒤 정합니다.

### 4.2 KL — Kennametal (고객코드 107525)

- 입력: PDF. 문서 1부 = 오더 1건(`split.by: none`).
- 실물 근거: `samples/KL/4507628839.pdf` 와 그 텍스트 덤프, 그리고 **POC 가 만든 출력 엑셀 1건**.
  그 엑셀은 ZBRAND=2, POSEX=`00001`, ZPKRE2·EMPST·MATNR 빈 칸 — **LOGIC.md 설명(WGT/KMT, POSEX 정수화)과 다릅니다.**
  SAP 업로드 결과는 없습니다. KL 은 근거가 가장 약합니다.

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| 고객발주번호 - BSTKD | `Document No. 4507628839 / 040` 에서 `/` 앞 | Claude 는 `Document No.` 뒤 **원문 전체**를 읽고, 앞부분 자르기는 `regex_extract` 규칙이. (지금 fixture hints 는 Claude 에게 "슬래시 앞만" 시키는데, 이건 변환 지시라 P1 위반 소지) | 전용 규칙 필요 + Q13 |
| 브랜드 - ZBRAND | `2` (OEM) 고정 | `fields.ZBRAND: { from: const, value: "<Q1>", choices: brand_code }` (SCHEMA §4.5 예시 C). 후보 002 OEM BRAND · 058 NO BRAND 는 드롭다운으로 남긴다 | 전용 규칙 필요 + Q1 · Q10 |
| Packing Spec - ZPKRE / Remark - EMPST | 품목 `Brand:` 원문에 `WIDIA GTD` → WGT, `KENNAMETAL` → KMT, 둘 다 아니면 빈 칸 | 라인 원문 `line.brand_text` 에 `keyword_map` 1개, 두 필드가 같은 규칙을 참조. `WIDIA GTD` 를 위에 둔다 | 확인 필요 Q11 (실제 출력 엑셀은 빈 칸) |
| PO품목번호 - POSEX | `00001` → `1` | 공용은 원문 그대로(`00001`). 정수로 바꾸려면 `format: integer` 한 줄 | 확인 필요 Q12 |
| 자재번호 - MATNR | 항상 빈 칸 (우리 품번이 문서에 없음) | 공용 그대로 — 빈 칸이어도 KDMAT 가 있으면 경고 없음 | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | Kennametal Mat. No. (사전점검 Your Code) | 공용 (`line.our_item`) | 공용으로 이미 됨 |
| Ship-to - KUNWE | 넣지 않음 | 공용 = 107525 | 확인 필요 Q14 |
| Shipping Condition - ZSHCO | 넣지 않음 | Shipping Master 107525 = 빈 칸 → 노랑 | 공용으로 이미 됨 (POC 와 같음) |
| Shipping Type - VSART | `04` | Shipping Master 107525 = `04` | 공용으로 이미 됨 |
| 단가·통화 | 보내지 않음 | 공용 | 공용으로 이미 됨 |

```yaml
# masters/customers/kl.yaml (모양만)
rules:
  po_base:
    kind: regex_extract
    source: header.po_number          # 원문 "4507628839 / 040"
    pattern: '^\s*(\d+)'
    group: 1
    on_no_match: { action: warn, message: "발주번호 형식이 다릅니다: {po_number}" }
  brand_mark:                          # Q11 이 "쓴다"일 때만
    kind: keyword_map
    source: line.brand_text
    case_insensitive: true
    entries:
      - { contains: "WIDIA GTD",  value: "WGT" }
      - { contains: "KENNAMETAL", value: "KMT" }
    on_no_match: { action: warn, message: "Brand 원문을 인식하지 못했습니다: {brand_text}" }
fields:
  BSTKD:  { from: rule, rule: po_base, required: true }
  ZBRAND: { from: const, value: "<Q1>", choices: brand_code, explain: "KL 은 OEM 고정. 드롭다운은 열어 둔다" }
  ZPKRE2: { from: rule, rule: brand_mark }
  EMPST:  { from: rule, rule: brand_mark }
  # POSEX: { from: doc, path: line.posex, format: integer }   # Q12 결과에 따라
```

### 4.3 YGJP — YG-1 JAPAN CO., LTD. (고객코드 3200)

- 입력: PDF. 문서 1부 = 오더 1건.
- 실물 근거: `samples/YGJP/_dump` 발주서 텍스트 5건. SAP 업로드 결과는 없습니다.

| 항목 | POC | 새 방식 (장치) | 상태 |
|---|---|---|---|
| Ship-to - KUNWE | `319854` 고정 | `fields.KUNNR2: { from: const, value: "319854" }` | 전용 규칙 필요 |
| 고객발주번호 - BSTKD | `01-{Created On YYYYMMDD}-{Purchase Order ID}` | Claude 는 날짜·번호를 원문대로, 조립은 `expr: 'concat("01-", date_yyyymmdd(header.po_date), "-", header.po_number)'`. 날짜를 못 읽으면 빈 값으로 넘기지 않고 오류가 난다 | 전용 규칙 필요 + Q8 |
| 브랜드 - ZBRAND (읽기) | 하단 줄이 표와 완전일치 | Claude 는 하단 블록에서 **브랜드가 적힌 줄을 원문 그대로** `header.brand_text` 에 담는다. 포장지시가 같은 줄에 붙어 있어도 **가르지 않는다** — 가르는 판단까지 시키면 경계를 잘못 자를 수 있다. `Remark: YG agent : …` 줄은 브랜드가 아니라고 hints 에 적는다(대리점 이름에 브랜드와 같은 단어가 섞일 수 있다) | 전용 규칙 필요 (hints) |
| 브랜드 - ZBRAND (판정) | BRAND_MAP 25개 | `keyword_map`(포함 대조), **긴 문구가 위로**: `YG BRAND (COMINIX)` · `(SAKUSAKU)` · `(YGT Y)` · `(CHUO KOKI)` · `(IBIDEN)` 를 `YG BRAND` 보다 먼저, `SIAM YAMAKATSU BRAND` 를 `YAMAKATSU BRAND` 보다 먼저. 실물 5건 모양 모두 이렇게 잡힌다 | 전용 규칙 필요 + Q4 · Q5 |
| 브랜드 코드 등록 | — | 브랜드 마스터 3200 후보는 지금 112·166·192·002·039·004·058 **7개뿐**. POC 코드 25개 대부분이 3200 에 없고, 마스터 전체에도 없는 코드가 많다. `value_check` 를 걸면 막힌다 | **데이터 보강 필요 Q4 (선행 조건)** |
| Shipping Condition - ZSHCO | 브랜드 471·507 → `A`, 그 외 `L` | Shipping Master 는 고객 1곳 = 값 1개라 표현 불가 → YGJP 파일에서 `expr` 로 덮어쓴다(`in()` 사용 — `contains()` 금지). 브랜드를 못 정했으면 `L` 로 추측하지 않고 **빈 칸 + 노랑** | 전용 규칙 필요 + Q6 + **엔진 확장 필요 E1** |
| 브랜드를 사람이 바꿨을 때 | (해당 없음 — 엑셀을 직접 고침) | 지금 엔진은 검수 화면에서 값을 고치면 **검증만 다시** 돌고 규칙은 다시 계산하지 않는다. 드롭다운에서 ZBRAND 를 바꿔도 ZSHCO 는 옛 값 그대로 남는다 | **엔진 확장 필요 E1** |
| Shipping Type - VSART | `04` | Shipping Master 3200 = **`05`** | 확인 필요 Q3 |
| 제외할 품목 | Product ID 가 없거나 수량 0 인 줄 제외 | Claude 는 **모든 줄을 읽고**, 제외 판단은 엔진이 한다. 제외된 줄은 사라지지 않고 "삭제됨" 상태로 표에 남아 사람이 되살릴 수 있다 | **엔진 확장 필요 E2** + Q7 |
| Packing Spec - ZPKRE / Remark - EMPST | S/O 업로드에는 넣지 않음 (PO정리 엑셀에만) | 공용 그대로 빈 칸 | 공용으로 이미 됨 + Q9 |
| 자재번호 - MATNR | Product ID | 공용 (`line.item_code`) | 공용으로 이미 됨 |
| 고객자재번호 - KDMAT | Your Code | 공용 (`line.our_item`) | 공용으로 이미 됨 |
| PO품목번호 - POSEX | 있으면 | 공용 | 공용으로 이미 됨 |
| 통화 - WAERK | 헤더 `JPY` (S/O 에는 안 넣음) | 공용 — `Total Value: … JPY` 의 `JPY` → JPY | 공용으로 이미 됨 |

**왜 `csv_map`(브랜드 마스터의 브랜드명을 대조표로 쓰는 SCHEMA 예시 B)이 아니라 `keyword_map` 인가.**
발주서 문구(`YG BRAND (COMINIX)`, `NEW CENTURY BRAND(COMINIX)` 등)가 SAP 브랜드명과 같다는 보장이 없고,
같게 만들려면 브랜드 마스터의 표시 이름을 발주서 문구로 바꿔야 합니다(마스터 오염). 또 예시 B 는 완전일치라
위 실물 3건이 그대로 실패합니다. 25줄이면 거래처 파일 안에 두어도 충분히 작습니다(SCHEMA §4.5 "entries 를
CSV 로 빼지 않는다"). 다만 결정은 Q5 로 확인합니다.

```yaml
# masters/customers/ygjp.yaml (모양만)
rules:
  brand_text_match:
    kind: keyword_map
    source: header.brand_text
    normalize: [collapse_spaces]
    case_insensitive: true
    entries:                                   # 긴 문구가 위 — 행 순서 = 우선순위
      - { contains: "YG BRAND (COMINIX)",          value: "<Q1·Q4>" }
      - { contains: "NEW CENTURY BRAND(COMINIX)",  value: "<Q1·Q4>" }
      - { contains: "SIAM YAMAKATSU BRAND",        value: "<Q1·Q4>" }
      # … 나머지, 맨 아래 근처에 "YAMAKATSU BRAND", "YG BRAND"
    value_check: { table_file: refs/brand_master.csv, value_column: zbrand, filter_column: kunnr }
    on_no_match: { action: warn, message: "브랜드 문구를 인식하지 못했습니다: {brand_text} — 드롭다운에서 고르세요" }
fields:
  KUNNR2: { from: const, value: "319854" }
  BSTKD:  { from: expr, expr: 'concat("01-", date_yyyymmdd(header.po_date), "-", header.po_number)', required: true }
  ZBRAND: { from: rule, rule: brand_text_match, choices: brand_code, required: warn }
  ZSHCO:
    from: expr
    expr: 'if(brand_text_match, if(in(brand_text_match, ["471", "507"]), "A", "L"), "")'   # 코드 형식은 Q1
    required: warn
    explain: "브랜드가 471·507 이면 A, 그 밖의 브랜드면 L. 브랜드를 못 정했으면 비워 둔다"
```

> 위 `ZSHCO` 식은 **자동으로 정해진 브랜드**만 봅니다. 사람이 드롭다운에서 브랜드를 고르면 ZSHCO 가
> 따라 바뀌지 않습니다 — E1 이 풀려야 완성됩니다. E1 전까지는 YGJP 의 ZSHCO 를 사람이 직접 확인해야 합니다.

---

## 5. 확인 필요 — POC 와 지금이 안 맞는 것

각 질문: **근거** / **권장안**. 답이 나오면 해당 YAML·참조표에 반영하고 `rules:` 커밋 본문에 일자·확인자를 남깁니다.

### 전 거래처

- **Q1. 브랜드 코드 앞자리 0 — SAP 에 `38` 로 보내야 하나, `038` 로 보내야 하나?**
  근거: MSC 업로드 결과는 `38`, `205`(0 없음). 브랜드 마스터는 `038`, `002`. EAI 가 CBO 에 문자열 그대로 넣으면 둘은 다른 값입니다.
  권장: 브랜드 마스터 기준인 **`038` 형식**을 쓰고 YAML 코드도 3자리로 적는다. 0 없는 형식으로 보내야 한다면 정규화 지점을 한 곳으로 정한다(E4) — 드롭다운 값과 자동 값이 같은 형식이어야 하므로.
- **Q20. 거래처별 규칙 책임자(`meta.owner`)는 누구인가?**
  근거: 규칙 변경 승인자인데 3곳 모두 미지정.
  권장: 거래처마다 1명 지정.

### MSC (100249)

- **Q2. Shipping Condition `A` 를 Shipping Master 에 넣어도 되나?**
  근거: 업로드 결과 12건 전부 ZSHCO=`A`. Shipping Master 100249 의 zshco 는 빈 칸.
  권장: 화면 Shipping Master 에서 100249 = `A` 로 입력. YAML 은 손대지 않는다.
- **Q16. 포장 추가비고 참조표(거래처 품번 → B·C열) 원본은 어디 있나?**
  근거: `MSC_REF.xlsx.csv` 는 업로드 결과 사본이다. 원본 `MSC_REF.xlsx` 가 저장소에 없다.
  권장: 원본을 받아 `refs/` 에 CSV 로 두고 `lookup` 규칙을 붙인다. 받기 전까지는 도시 기본값만 + 노랑 + `todo`. 가짜 표를 만들지 않는다.
- **Q17. 창고 도시를 못 찾으면 전송을 막을까?**
  근거: 확정된 업무 규칙이고, 틀리면 물건이 다른 창고로 간다.
  권장: 막는다(빨강). 새 창고가 생기면 결정표에 한 줄 추가.
- **Q18. 여러 창고 발주서의 단가가 빈 칸이어도 되나?**
  근거: 창고별 블록 품목표에는 Price 열이 없고, 요약표는 품목으로 읽지 않는다(SCHEMA §2.1-2). POC 는 단가를 보내지 않았다.
  권장: 당장은 빈 칸 허용. 필요하면 별도 설계(E5).
- **Q19. 키워드에 없는 브랜드 후보(002 OEM BRAND · 004 NO MARKING · 501 UNBRANDED)는 발주서에 어떤 문구로 찍히나?**
  근거: 브랜드 마스터 100249 후보는 7개, POC 키워드는 4개.
  권장: 당장은 드롭다운으로 고르게 두고, 실물 문구가 확인되면 키워드를 더한다.

### KL (107525)

- **Q10. 브랜드를 `002` 로 고정할까, 드롭다운(002 OEM BRAND · 058 NO BRAND)에서 고르게 할까?**
  근거: POC 는 2 고정. POC 주석에는 "2/58 아이템 레벨"이라는 말이 있으나 구현은 안 됨(LOGIC.md 확인 2).
  권장: 고정 + 드롭다운 열어 둠(SCHEMA 예시 C). 품목별로 058 이 필요한 기준이 있다면 알려 달라.
- **Q11. Packing Spec·Remark 에 WGT/KMT 를 실제로 넣나?**
  근거: LOGIC.md·명세서는 넣는다고 하지만, POC 가 실제로 만든 KL 출력 엑셀은 두 칸 모두 빈 칸.
  권장: 실제로 쓰지 않으면 규칙을 만들지 않는다.
- **Q12. PO품목번호를 `00001` 로 보낼까, `1` 로 보낼까?**
  근거: LOGIC.md 는 정수 `1`, 실제 출력 엑셀은 `00001`.
  권장: 정수로 보낸다면 `format: integer` 한 줄.
- **Q13. 발주번호 `4507628839 / 040` 의 `/040` 은 버려도 되나?**
  근거: POC 는 `/` 앞만 사용. `/040` 이 개정 번호라면 같은 발주의 개정본이 같은 BSTKD 로 들어간다(중복 적재 위험, CLAUDE.md §8).
  권장: POC 대로 앞부분만 쓰되, 개정본이 오는 경우의 처리를 확인.
- **Q14. Ship-to 를 107525 로 보내도 되나?**
  근거: POC 는 빈 칸. 지금 공용 설정은 고객코드(107525).
  권장: 107525 유지.


### YGJP (3200)

- **Q3. Shipping Type 은 `04` 인가 `05` 인가?**
  근거: POC 는 `04`, Shipping Master 3200 은 `05`.
  권장: 답에 따라 Shipping Master 한 곳만 고친다. YAML 로 덮어쓰지 않는다.
- **Q4. POC 브랜드 코드 25개를 브랜드 마스터에 어떻게 올릴까? "별도" 항목(448 NIKKO KIZAI 별도 · 449 YG BRAND 별도 · 450 YAMAKATSU 별도)의 실제 발주서 문구는?**
  근거: 3200 후보는 7개(112·166·192·002·039·004·058)뿐이고 POC 코드 대부분이 없음. 마스터 전체에도 없는 코드가 많음. "별도"는 한국어라 일본 발주서에 그대로 찍힐 가능성이 낮음.
  권장: 브랜드 마스터 재추출(`import_brand_master.py --dry-run` 먼저). 재추출 전까지 급하면 화면 Brand Master 보정(`add`, `note` 필수)으로 올린다(E3 선행). "별도" 3개는 실물 문구를 받기 전까지 표에 넣지 않는다(드롭다운으로 처리).
- **Q5. YGJP 브랜드 판정을 거래처 파일의 포함 대조(`keyword_map`)로 해도 되나?**
  근거: 실물 5건 중 3건은 브랜드 줄에 포장지시가 붙어 있어 완전일치가 실패. SAP 브랜드명을 대조표로 쓰는 방식(SCHEMA 예시 B)도 완전일치라 같은 문제.
  권장: `keyword_map`, 긴 문구를 위에. 문구 목록은 POC 표에서 가져오되 Q4 답으로 코드를 채운다.
- **Q6. 브랜드를 못 정했을 때 ZSHCO 는?**
  근거: POC 는 브랜드가 없어도 "471·507 이 아니므로" `L`.
  권장: 비워 두고 노랑. 브랜드가 정해지면 같이 정해진다(E1).
- **Q7. "Product ID 없음 또는 수량 0" 줄을 자동 제외할 때, 표에서 아예 지울까, "삭제됨"으로 남길까?**
  근거: 제외는 판단이므로 엔진 몫(P1). 행 누락은 통신 유실과 구분되지 않는다(계약 §6.1).
  권장: "삭제됨"으로 남기고 사유를 표시. 사람이 되살릴 수 있다(P5).
- **Q8. BSTKD 앞의 `01-` 는 언제나 고정인가?**
  근거: POC 코드에 상수로 박혀 있고 의미 설명이 없다.
  권장: 고정으로 구현하되 YAML `explain` 에 의미를 적을 수 있게 확인만 받는다.
- **Q9. 포장지시(S-Y,B-Y 등)와 비고를 SAP 의 Packing Spec·Remark 로 보낼까?**
  근거: POC 는 S/O 업로드에 넣지 않았고 PO정리 엑셀(범위 밖)에만 썼다.
  권장: 지금처럼 보내지 않는다(빈 칸). 필요하다고 하면 그때 hints 와 필드 두 줄을 더한다.

---

## 6. 구현 목록 — 확인이 끝난 뒤

### 6-a. 엔진·코드 변경이 필요한 것

| # | 내용 | 왜 | 설계 요점 | 선행 |
|---|---|---|---|---|
| **E1** | **사람이 고친 값에 따라 다른 필드 다시 계산** | YGJP ZSHCO 가 ZBRAND 를 따라가야 한다. 지금 `batch_service.merge_edits` 는 `validate_row` 만 다시 돈다 | 필드 식이 **다른 필드의 최종 값**을 참조할 수 있게 한다(예: 새 네임스페이스 `field.ZBRAND`). 검수 저장 시 `field.*` 를 참조하는 `from: expr` 필드만 다시 계산한다. 단 **사람이 직접 고친 필드는 덮어쓰지 않는다**(P5) — 대신 두 값이 어긋나면 노랑. 순환 참조는 검증기가 막는다. SCHEMA §3·§4.7, 계약 §6.1(서버가 사람이 안 고친 칸을 바꿀 수 있음)을 함께 고친다 | Q6 |
| **E2** | **품목 줄 자동 제외** | YGJP "Product ID 없음 / 수량 0". 지금은 Claude 에게 "읽지 말라"고 하는 방법뿐 | **P1 판단: 엔진 몫이다.** 제외 여부는 판단이고, Claude 가 안 읽으면 그 줄이 있었는지 아무도 모른다(근거 대조·합계 검증도 어긋난다). Claude 는 모든 줄을 읽고, 엔진이 선언된 조건으로 행을 `deleted: true` + 사유 표시로 만든다. 선언 위치는 새 최상위 키를 늘리지 않도록 `split` 아래(예: `split.exclude_lines: [{ when: '<expr>', reason: "…" }]`)를 제안. 조건은 지금 식 문법으로 표현 가능: `if(line.item_code, in(integer(line.quantity), ["0"]), true)` — 단 빈 수량에서 `integer()` 가 어떻게 동작하는지 확인 필요. SCHEMA §2.1·§4.3 등재 | Q7 |
| **E3** | **`value_check` 가 브랜드 보정 파일까지 보게** | `scripts/validate_masters.py` 의 `check_value_registry` 는 `brand_master.csv` 원본만 읽는다. Q4 를 보정(`add`)으로 풀면 YGJP 코드가 "미등록"으로 막힌다 | 병합은 `reftable.load()` 한 곳(CLAUDE.md §2). 검증기도 그것을 쓴다. `add` 행 처리 방침은 SCHEMA §4.5-A 와 맞춘다 | Q4 |
| E4 | (조건부) 브랜드 코드 형식 정규화 | Q1 이 "0 없이"로 나올 때만 | 드롭다운 후보·자동 값·전송 값이 한 형식이어야 한다. 정규화 지점을 한 곳으로 정한다 | Q1 |
| E5 | (조건부) 여러 창고 문서의 단가 | Q18 이 "필요"일 때만 | 요약표 단가를 품번으로 끌어오는 장치. 추출량이 다시 늘어나는 비용과 함께 검토 | Q18 |
| E6 | SCHEMA §4.5 예시 A·B·C 정리 (문서) | 예시가 `choices: brand_choice` 를 가리키는데 프로필의 후보 규칙 이름은 `brand_code`. 그대로 베끼면 검증기 14번 오류 또는 드롭다운 소실 | 예시의 전용 규칙 이름을 `brand_text_match` 로, `choices` 를 `brand_code` 로. architect 소유 문서 | 없음 |

### 6-b. YAML·참조표만으로 되는 것

| # | 내용 | 파일 | 선행 |
|---|---|---|---|
| D1 | Shipping Master: 100249 ZSHCO=`A`, 3200 VSART 확정 | 화면 Shipping Master (`refs/shipping_master.csv`) | Q2 · Q3 |
| D2 | 브랜드 마스터 3200 보강 (SAP 재추출 또는 보정 `add`) | `refs/brand_master.csv` / `brand_master_manual.csv` | Q4 (보정이면 E3) |
| D3 | MSC 포장 추가비고 참조표 + `lookup` 규칙 | `refs/` 새 CSV + `msc.yaml` | Q16 |
| Y1 | `msc.yaml` — meta·hints·split·결정표(KUNNR2·_city·_pack_base)·브랜드 키워드·BSTKD·ZPKRE2·합계 검증 | `masters/customers/msc.yaml` | Q1 · Q17 (D3 없이 먼저 가능) |
| Y2 | `kl.yaml` — hints(발주번호 원문 전체로 고침)·BSTKD regex·ZBRAND 고정·(조건부) WGT/KMT·POSEX 형식 | `masters/customers/kl.yaml` | Q1 · Q10~Q13 |
| Y3 | `ygjp.yaml` — hints(브랜드 줄 원문 그대로, 대리점 Remark 줄 구분)·KUNNR2·BSTKD·브랜드 키워드·ZSHCO 식·제외 조건 | `masters/customers/ygjp.yaml` | Q1 · Q4~Q8, D2, E1, E2 |

### 권장 순서

```
1. 질문 답 받기 (특히 Q1 — 세 거래처 브랜드 전부에 걸린다)
2. D1 (화면에서 값만)                         ← 바로 효과, 코드 0
3. E6 (SCHEMA 예시 정리)                       ← Y1~Y3 가 베낄 원본이므로 먼저
4. Y1 MSC                                       ← 업로드 결과 12건이 있어 대조 가능. 가장 확실
   → validate_masters → check_sample → parse_one --rows → 업로드 CSV 와 비교
5. Y2 KL                                         ← Q10~Q13 답을 받은 뒤
6. E3 → D2                                       ← YGJP 브랜드 코드 등록
7. E1, E2 (엔진)                                 ← YGJP 전에 필요. 서로 독립이라 병행 가능
8. Y3 YGJP
9. D3                                            ← MSC 참조표 원본이 오는 대로 (언제든)
```

각 YAML 을 고친 뒤에는 `python scripts/validate_masters.py` 를 돌리고, 구현이 끝난 항목은 이 문서에서
값을 지우고 YAML 위치만 남긴다(§1 운영 규칙).

---

## 7. 범위 밖

| 항목 | 이유 |
|---|---|
| POC 사전점검 엑셀 (`pre_check`, Unit=PC 고정, "Your Code" 열) | 이 프로그램의 출력은 EAI 전송 하나다 |
| YGJP PO정리 엑셀 (`ygjp_po.py`) | 같은 이유. 포장지시·비고를 SAP 로 보낼지는 Q9 로 따로 묻는다 |
| `parsers/pdf_yg1.py` (YG1) | POC 에서도 쓰이지 않던 코드이고 이번 범위에서 제외 |
| POC 파일명 규칙 | 전송 페이로드에 파일명이 들어가지 않는다 |
| 삭제된 전송 필드(KUNNR3·VDATU·ZTERM·INCO1/2·ETDAT·BSTDK_E·DELCO·AUGRU·VKAUS·IHREZ_E·VGBEL·VGPOS) | 2026-10-02 사용자 결정으로 보내지 않는다. 다시 필요하면 `_base` 부터 |

---

## 8. 새 거래처 전용 규칙을 추가하는 절차

전체 절차는 [`masters/SCHEMA.md` §5](masters/SCHEMA.md) 입니다. 요약하면:

1. 전용 규칙이 없어도 브랜드 마스터에 등록된 고객이면 공용 설정으로 이미 동작합니다. **먼저 써 보고, 공용으로 안 되는 것만** 전용 규칙으로 만듭니다.
2. `masters/customers/_template.yaml` 을 복사해 `meta` 와 `extraction.hints`(문서 구조 설명, 변환 지시 금지)를 채우고, **공용과 다른 필드만** 적습니다. 브랜드 전용 규칙 이름은 `brand_code` 와 겹치지 않게 합니다.
3. 브랜드를 문구로 가리는 규칙은 실물 발주서에서 그 문구가 **늘 찍힌다는 것을 확인한 뒤에만** 만듭니다.
4. `validate_masters.py` → `check_sample.py` → `parse_one.py --rows` 로 확인하고, 실제 SAP 오더와 맞을 때까지 YAML 만 고칩니다.
5. 이 문서에 그 거래처 절을 추가할 때는 "무엇을 왜, 어떤 장치로"와 상태만 적고, 값은 YAML 에 둡니다.
