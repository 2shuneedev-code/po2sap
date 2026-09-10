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
└── send_ok.json            → §7
```
백엔드는 이 파일과 **동일한 형태**를 만들고, 프론트는 이 파일로 화면을 완성한다.
불일치가 생기면 이 문서와 예제를 먼저 고치고 양쪽이 따라간다.
