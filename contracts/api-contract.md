# API 계약 (백엔드 ↔ 프론트엔드)

> **이 문서가 두 트랙의 유일한 접점이다.**
> 백엔드는 이 응답을 만들고, 프론트는 이 응답을 그린다. 서로를 기다리지 않는다.
> 계약 변경은 **양쪽 합의 후 이 문서를 먼저 고친다.**
> v1 · 2026-09-10

---

## 0. 공통 규약

| 항목 | 규약 |
|---|---|
| Base | `/api` |
| 인코딩 | UTF-8 |
| 모든 값 | **문자열**. 숫자·날짜도 문자열 (앞자리 0 보존, 부동소수 오차 방지) |
| 빈 값 | `""` — **`null` 을 쓰지 않는다** |
| 시각 | ISO8601 `"2026-09-10T09:12:33+09:00"` |
| 오류 | HTTP 4xx/5xx + `{ "error": { "code": "...", "message": "사용자에게 보여줄 한국어" } }` |

### 0.1 프론트 개발용 목 모드

```
GET /api/... 에 ?mock=1  또는  헤더 X-Mock: 1
→ contracts/examples/ 의 고정 응답을 그대로 반환
```
백엔드 미완성 구간에서도 프론트가 끝까지 관통할 수 있다.
프론트는 `VITE_API_MODE=mock` 이면 `contracts/examples/*.json` 을 직접 import 해도 된다.

---

## 1. `GET /api/masters/customers`

거래처 선택 화면. `meta.status: draft` 는 제외한다.

```json
[
  { "code": "MSC",  "name": "MSC Industrial Supply", "customer_no": "100249", "file_types": ["htm","html"] },
  { "code": "KL",   "name": "Kennametal",            "customer_no": "107525", "file_types": ["pdf"] },
  { "code": "YGJP", "name": "YG-1 Japan",            "customer_no": "3200",   "file_types": ["pdf"] }
]
```
> `file_types` 는 **안내용**. 프론트는 이걸로 업로드를 차단하지 않는다 (다른 형식이면 안내 문구만).

---

## 2. `GET /api/masters/customers/{code}/preview`

거래처 선택 즉시 보여주는 **규칙 카드**. YAML 에서 자동 생성되므로 규칙이 바뀌면 화면도 바뀐다.

```json
{
  "code": "MSC",
  "name": "MSC Industrial Supply",
  "customer_no": "100249",
  "fixed": [
    { "field": "AUART",  "label": "오더유형", "value": "ZEXP" },
    { "field": "KUNNR1", "label": "판매처",   "value": "100249" },
    { "field": "VSART",  "label": "운송수단", "value": "04" },
    { "field": "ZSHCO",  "label": "출하조건", "value": "A" }
  ],
  "rules": [
    {
      "id": "brand_code",
      "kind": "keyword_map",
      "label": "브랜드 판별",
      "note": "위에서부터 순서대로 확인합니다",
      "columns": ["ORDERED FROM 에 포함", "→ ZBRAND"],
      "rows": [["HERTEL","38"],["INTERSTATE","127"],["ACCUPRO","205"],["CLASS C","428"]]
    },
    {
      "id": "ship_to_routing",
      "kind": "table",
      "label": "출하처(Ship To) 분기",
      "columns": ["출하처에 포함", "→ KUNNR2", "→ ZPKRE2 기본값"],
      "rows": [["ELKHART","100249","C"],["HARRISBURG","319677","N"],
               ["RENO","319678","O"],["ATLANTA","319679","A"]]
    },
    {
      "id": "ref_codes",
      "kind": "lookup",
      "label": "참조표 조회",
      "note": "거래처 품번으로 참조표를 조회해 ZPKRE2 에 추가합니다",
      "columns": [], "rows": []
    }
  ],
  "split": { "by": "shipment", "label": "출하처(Shipment)별로 오더를 나눕니다" },
  "todos": [
    { "field": "KUNNR2", "note": "출하처 코드 확인 필요" }
  ],
  "footer": "나머지 항목은 발주서에서 읽어옵니다."
}
```

프론트는 `fixed` / `rules[]` / `split` / `todos` 를 **모양 그대로** 렌더한다.
거래처별 분기 코드를 프론트에 넣지 않는다. `rules[].kind` 로 아이콘만 구분한다.

---

## 3. `GET /api/masters/fields`

그리드 컬럼 정의. `_base/sap_defaults.yaml` 의 순서 그대로.

```json
{
  "fields": [
    { "name": "AUART",  "label": "오더유형", "sheet": "SALES ORDER TYPE", "max_len": 4 },
    { "name": "KWMENG", "label": "수량",     "sheet": "ORDER QTY", "type": "decimal" }
  ]
}
```
> **필드 수는 하드코딩 금지.** 36이 34가 되어도 프론트는 그대로 동작해야 한다.

---

## 4. `POST /api/batches`

업로드 + 파싱 시작. `multipart/form-data`

| 파트 | 내용 |
|---|---|
| `customer` | `"MSC"` |
| `files` | 파일 N개 |

```json
{ "batch_id": "b_20260910_0001", "status": "PARSING",
  "files": [ { "file_id": "f1", "name": "P7588650.HTM", "status": "PARSING" } ] }
```

| 한도 | 값 | 넘으면 |
|---|---|---|
| 파일 개수 | 50 | 400 |
| 파일 하나 | 20MB | 400 |
| 합계 | 100MB | 400 |

거래처 코드가 마스터에 없으면 400. 파싱은 응답 뒤 배경에서 돌고, 프론트는 §5 를 폴링한다.

---

## 5. `GET /api/batches/{batch_id}` ★ 핵심

파싱 진행 상황 + 행 데이터. 프론트는 `status` 가 `PARSING` 이면 **1.5초 폴링**한다.

```json
{
  "batch_id": "b_20260910_0001",
  "customer": "MSC",
  "status": "NEEDS_REVIEW",
  "files": [
    { "file_id": "f1", "name": "P7988114.HTM", "status": "DONE",   "row_count": 49 },
    { "file_id": "f2", "name": "P8033553.HTM", "status": "FAILED",
      "error": "품목표를 찾지 못했습니다", "row_count": 0 }
  ],
  "columns": ["AUART","VKORG","..."],
  "grid": {
    "pinned": ["BSTKD","KUNNR2","MATNR","KWMENG"],
    "hidden": ["VTWEG","VBELN","..."],
    "width":  { "MATNR": 140 }
  },
  "rows": [
    {
      "row_id": "r_0001",
      "_file_id": "f1",
      "_file": "P7988114.HTM",
      "_group": "ELKHART",
      "_line_no": 1,
      "fields": {
        "AUART": "ZEXP", "VKORG": "1000", "VTWEG": "",
        "KUNNR1": "100249", "KUNNR2": "100249", "KUNNR3": "100249",
        "BSTKD": "7988114(ELKHART)", "ZBRAND": "205", "ZSHCO": "A",
        "MATNR": "T1634585", "KWMENG": "30", "ZPKRE2": "C", "VSART": "04"
      },
      "issues": [
        { "field": "MATNR", "severity": "error",
          "code": "REQUIRED_MISSING", "message": "자재번호를 찾지 못했습니다" }
      ],
      "edited": []
    }
  ],
  "summary": { "row_count": 49, "total_qty": "1240", "error_count": 1, "warn_count": 3 }
}
```

### 4·5 규약

| 항목 | 규약 |
|---|---|
| `fields` | **`columns` 의 전 필드가 키로 존재**한다. 값 없으면 `""` |
| `_` 접두 | **화면 전용.** 전송 JSON 에 포함되지 않음 |
| `_group` | 분할 단위 라벨(출하처 등). 분할 없으면 `""`. 그리드 구분선/필터용 |
| `_deleted` | 사람이 지운 행. 화면에서 흐리게 표시하고 **전송에서 제외**한다. `summary` 에도 빠진다 |
| `severity` | `"error"` 🔴 전송 차단 / `"warn"` 🟡 가능 |
| `edited` | 사용자가 고친 필드명 배열 🔵. 서버가 채우고 프론트가 갱신 |
| `status` | `PARSING` / `NEEDS_REVIEW` / `READY` / `SENDING` / `SENT` / `SEND_FAILED` |

---

## 6. `POST /api/batches/{batch_id}/validate`

검수 중 재검증. 프론트는 편집을 로컬 상태로 들고 있다가 이 API 로 확인한다.

```json
// 요청
{ "rows": [ { "row_id": "r_0001", "fields": { "MATNR": "T1634585", "...": "" } } ] }

// 응답
{ "status": "READY",
  "rows": [ { "row_id": "r_0001", "issues": [], "edited": ["MATNR"] } ],
  "summary": { "row_count": 49, "total_qty": "1240", "error_count": 0, "warn_count": 3 } }
```
> 응답은 **`issues`/`edited` 만** 돌려준다. 값은 프론트가 주인이다 (편집 중 값이 덮어써지지 않도록).

### 6.1 병합 규약 ★ — 서버가 자기 스냅샷을 믿는다

**서버는 파싱 직후 값을 스냅샷으로 들고 있고, 요청은 거기에 병합된다.** 요청이 보낸
것을 그대로 받아들이면 없는 행을 끼워 넣거나 규칙이 정한 코드를 임의로 바꿔도 막을
방법이 없다. 값의 최종 주인은 사람이지만(P5), **무엇이 바뀌었는지 판단하는 쪽은 서버다.**

| 요청 내용 | 서버 동작 |
|---|---|
| 아는 `row_id` + 아는 컬럼 | 반영한다 |
| **모르는 `row_id`** | **400.** 하나라도 있으면 요청 전체를 거부하고 아무것도 쓰지 않는다 |
| 모르는 컬럼 | **무시한다.** 전송 필드 목록은 `_base` 가 정한다 — 화면이 컬럼을 새로 만들 수 없다 |
| 행을 **빼고** 보냄 | 아무 일도 없다. **누락은 삭제가 아니다** |
| `"deleted": true` | 그 행을 전송에서 뺀다. `false` 로 되돌릴 수 있다 |

`edited` 는 요청이 알려주는 것이 아니라 **서버가 원본과 대조해 계산한다.** 값을 원래대로
되돌리면 `edited` 에서도 빠진다.

요청 본문의 `deleted` 는 선택이다(생략하면 현재 상태 유지).

```json
{ "rows": [ { "row_id": "r_0001", "fields": { "MATNR": "T1634585" } },
            { "row_id": "r_0007", "deleted": true } ] }
```

`SENDING` · `SENT` 상태의 배치는 수정할 수 없다 (409).

---

## 7. `POST /api/batches/{batch_id}/send`

```json
// 요청 — 화면의 최종 값 전량
{ "rows": [ { "row_id": "r_0001", "fields": { "...": "" } } ] }
```

서버는 `_` 접두 필드를 제거하고 `columns` 순서대로 정렬해 EAI 로 POST 한다.

```json
// EAI 로 나가는 페이로드
{ "rows": [ { "AUART": "ZEXP", "VKORG": "1000", "...": "" } ] }
```

```json
// 응답 — 성공
{ "status": "SENT", "sent_rows": 49, "sent_at": "2026-09-10T09:12:33+09:00",
  "message": "49건이 EAI로 전송되었습니다." }

// 응답 — 실패 (HTTP 200, status 로 구분)
{ "status": "SEND_FAILED", "sent_rows": 0, "attempts": 3,
  "message": "EAI 응답 없음 (타임아웃 60초). 재전송할 수 있습니다." }
```
- 🔴 error 가 하나라도 있으면 **HTTP 409** + `error.code = "HAS_ERRORS"`
- 재전송은 같은 API 재호출. **중복 전송 무해**

---

## 8. `GET /api/health`

```json
{ "status": "ok",
  "masters": { "ok": true, "detail": "3개 거래처: MSC, KL, YGJP" },
  "llm":     { "ok": true, "provider": "anthropic", "detail": "" },
  "eai_endpoint": "https://..." }
```

---

## 9. 예제 파일 (프론트 목 데이터)

```
contracts/examples/
├── customers.json          → §1
├── preview_msc.json        → §2
├── fields.json             → §3
├── batch_msc.json          → §5  (49행 · 오류 1 · 경고 3 · 파일 2개 중 1개 실패)
├── send_ok.json            → §7
├── brand_customers.json    → §10.1 (실제 응답에서 뽑은 6행)
└── brand_detail_msc.json   → §10.2 (실제 응답 전문)
```
백엔드는 이 파일과 **동일한 형태**를 만들고, 프론트는 이 파일로 화면을 완성한다.
불일치가 생기면 이 문서와 예제를 먼저 고치고 양쪽이 따라간다.

---

## 10. 브랜드 매핑 콘솔 `/api/brands/*`

거래처 선택 화면(§1)과 **대상이 다르다.** §1 은 규칙이 설정된 거래처만 보여주지만,
여기는 SAP 브랜드 마스터에 있는 **전 고객**을 다룬다 — 규칙이 아직 없는 고객도
브랜드 원문 키부터 채워둘 수 있어야 하기 때문이다.

화면이 하는 일은 하나다: **발주서 원문 문구 → SAP 브랜드 코드(ZBRAND)** 를 잇는 것.
SAP 이 주는 것은 `코드 → 이름`뿐이고 **원문 키는 어디에도 없다.** 사람이 채운다.

| 데이터 | 원천 | 편집 |
|---|---|---|
| 브랜드 코드·이름 | `masters/refs/brand_master.csv` (SAP 원본) | **읽기 전용** |
| 발주서 원문 키 | `masters/refs/brand_keys.csv` | 이 API 로 편집 |

### 10.1 `GET /api/brands/customers`

좌측 고객 목록. `q`(고객명·고객코드·거래처코드 부분 일치) ·
`filter`(`all` | `configured` | `unconfigured`) · `limit`(≤500) · `offset`.

```json
{
  "total": "430", "limit": "200", "offset": "0",
  "customers": [
    { "kunnr": "100249", "name": "MSC Industrial Supply", "sap_name": "SID TOOL CO., INC.",
      "code": "MSC", "file_types": ["htm","html"], "brand_count": "7", "mapped_count": "4" },
    { "kunnr": "100157", "name": "AMAYA", "sap_name": "AMAYA",
      "code": "", "file_types": [], "brand_count": "4", "mapped_count": "0" }
  ]
}
```

- `code` 가 `""` 면 **규칙 미설정** 고객이다. 화면은 브랜드만 보여주고 로직 패널을 접는다.
- `name` 은 표시용이다. 거래처 마스터가 있으면 그 이름을, 없으면 `sap_name` 을 쓴다 —
  SAP 의 `name1` 이 축약형인 경우가 있다(`107525` = `"KL"`). 검색은 둘 다 본다.

### 10.2 `GET /api/brands/customers/{kunnr}`

```json
{
  "kunnr": "100249", "name": "MSC Industrial Supply", "sap_name": "SID TOOL CO., INC.",
  "code": "MSC", "file_types": ["htm","html"], "owner": "※ 지정 필요",
  "configured": "true",
  "brands": [
    { "zbrand": "38", "name": "HERTEL BRAND", "status": "mapped",
      "keys": [ { "text": "HERTEL", "match": "contains", "note": "" } ] },
    { "zbrand": "501", "name": "UNBRANDED", "status": "unmapped", "keys": [] }
  ],
  "logic": {
    "split":  { "by": "shipment", "label": "출하처별로 오더를 나눈다" },
    "tables": [ { "id": "ship_to_routing", "label": "출하처(Ship To) 분기", "scope": "shipment",
                  "columns": ["출하처 블록에 포함", "→ KUNNR2", "→ _city", "→ _pack_base"],
                  "rows": [["ELKHART","100249","ELKHART","C"]],
                  "on_no_match": { "action": "error", "message": "..." } } ],
    "rules":  [ { "id": "brand_code", "kind": "csv_map", "label": "브랜드 판별",
                  "source": "header.brand_text", "note": "참조표 … 로 판정합니다",
                  "columns": [], "rows": [],
                  "on_no_match": { "action": "error", "message": "..." } } ],
    "fields": [ { "field": "BSTKD", "label": "고객발주번호", "max_len": "35",
                  "source": "if(_city, concat(header.po_number, \"(\", _city, \")\"), header.po_number)",
                  "explain": "발주번호 뒤에 출하처 도시명을 괄호로 붙입니다", "todo": "" } ],
    "checks": [ { "id": "shipment_total_match", "label": "출하처별 수량 합계 = 요약표 합계",
                  "severity": "error", "description": "..." } ]
  }
}
```

- `logic` 은 규칙이 없는 고객이면 **`null`** 이다 (§0 의 "null 을 쓰지 않는다"의 유일한 예외 —
  "설정 없음"과 "빈 설정"은 화면에서 다르게 보여야 한다).
- `kind: csv_map` 규칙은 `columns`·`rows` 가 비어 있다. **그 내용이 곧 위의 `brands` 표**라
  같은 화면에 두 번 그리지 않는다.
- `logic.fields` 는 고정 빈값 필드를 뺀 목록이다 — 화면에서 볼 의미가 있는 것만 남긴다.

### 10.3 `PUT /api/brands/customers/{kunnr}/{zbrand}`

원문 키 한 묶음을 **통째로 교체**한다. `keys: []` 를 보내면 매핑을 지운다.

```json
{ "keys": [ { "text": "HERTEL", "match": "contains", "note": "" } ] }
```

`match` 는 `contains`(포함) 또는 `equals`(완전일치). **배열 순서가 곧 판정 우선순위다**
(`masters/SCHEMA.md` §4.5) — 저장해도 파일에서의 위치가 유지된다.

응답은 저장된 결과다.

```json
{ "kunnr": "100249", "zbrand": "38", "status": "mapped",
  "keys": [ { "text": "HERTEL", "match": "contains", "note": "" } ] }
```

**거부되는 경우** (파일을 건드리지 않는다):

| 상황 | HTTP | 이유 |
|---|---|---|
| `zbrand` 가 그 고객에 등록돼 있지 않음 | 400 | SAP 이 거부할 코드다. 저장 자체를 막는다 |
| 같은 문구를 다른 코드가 이미 씀 | 400 | 어느 쪽으로 판정될지 알 수 없다 |
| 한 요청 안에 같은 문구가 두 번 | 400 | 아래 것이 도달 불가 |
| `match` 가 허용 목록 밖 · `text` 가 빈 값 | 422 | — |
| `kunnr` 가 브랜드 마스터에 없음 | 404 | — |

> 인증·승인 흐름·감사 로그는 현재 범위 밖이다(사내망 무인증). 대신 저장 전 검증을
> 서버에서 하고, 변경 이력은 `brand_keys.csv` 의 Git 이력이 남긴다.
