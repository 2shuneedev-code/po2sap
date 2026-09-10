# PO2SAP 시스템 설계서

> **거래처 선택** → PDF/HTM 업로드 → **Claude API 파싱** → **통합 스프레드시트 검수(33컬럼)** → **EAI로 HTTPS/JSON 일괄 전송** → SAP CBO 적재
>
> 버전 **v0.5** · 2026-09-09 · 업무 프로세스/화면 상세는 `process.md`
>
> **v0.4 → v0.5 확정 반영**
> · 업로드 전 **거래처 선택** + 거래처 규칙 미리보기 (자동판별 불필요)
> · 한 배치 = **한 거래처 + 다중 파일**, 전 파일을 **한 그리드에 통합 검수 → 일괄 전송**
> · 페이로드 = **`{"rows":[...]}` 만** (batch_id·meta 제거)
> · 이력 화면 제외

---

## 0. 핵심 설계 결론

| # | 결정 | 요약 |
|---|---|---|
| D1 | **LLM은 '읽기', 규칙엔진은 '판단'** | Claude는 원문 값만 추출. SAP 코드는 **절대 LLM이 정하지 않음** |
| D2 | 파싱 = Claude API + 거래처별 **추출 설정(YAML)** | 거래처 추가 시 파서 코드 없음 |
| D3 | 분기 로직 = **결정표(Decision Table)** | 설정이 곧 화면 (업로드 화면의 규칙 미리보기도 동일 원천) |
| D4 | 거래처별 **33필드 전부 선언 강제** | 누락 시 CI 실패 |
| D5 | **거래처 선택 후 업로드** | 자동판별 오판 리스크 제거 + 규칙을 사전에 현업에 노출 |
| D6 | 검수 = **다중 파일 통합 평면 33컬럼 그리드** | 헤더성 필드도 품목마다 다를 수 있음 |
| D7 | 전송 = **`rows` 배열 일괄, 인증·멱등키 없음** | 중복 전송 무해 → 재전송 단순 |
| D8 | **DB 없음** — YAML 마스터 + 파일 저장 + Git | |
| D9 | LLM 결과는 **근거(evidence) 강제 + 자동 검증** | 환각 차단 4중 |
| D10 | **LLM 프로바이더 추상화** | 사내 계정 전환 시 코드 0줄, `.env`만 교체 |

---

## 1. 설계 원칙

| # | 원칙 |
|---|---|
| P1 | **읽기와 판단의 분리** — Claude는 추출, 규칙엔진은 코드 결정 |
| P2 | **규칙은 데이터, 엔진은 코드** — 거래처 규칙은 전부 YAML |
| P3 | **설정 파일 = 현업 화면** — 규칙 미리보기·결정표를 YAML에서 자동 렌더링 |
| P4 | **거래처 추가 = 설정 작성** — 정상 케이스는 코드 0줄 |
| P5 | **검수 화면이 최종 진실** — 사람이 확정한 값이 그대로 전송 |
| P6 | **모든 값에 근거를 남긴다** — 규칙 경로 + 원문 위치 |
| P7 | **외부 의존은 교체 가능하게** — LLM 프로바이더, EAI 엔드포인트 |
| P8 | **DB 없이 시작, 트리거 충족 시 승격** |

---

## 2. 기술 스택

### 2.1 백엔드 — Python 3.11 + FastAPI

| 항목 | 선정 | 근거 |
|---|---|---|
| 언어/프레임워크 | **Python 3.11 + FastAPI** | Anthropic SDK, Pydantic v2, OpenAPI 자동 생성 |
| 검증 | **Pydantic v2** | 추출 스키마 · 전송 페이로드 · YAML 마스터를 동일 엔진으로 |
| **파싱** | **Claude API** (Tool Use 구조화 출력) + 프로바이더 추상화 | §3 |
| PDF 전처리 | **pypdf / pdfplumber** | 텍스트 레이어 판정, **근거 검증용 원문 확보** |
| HTM 전처리 | **BeautifulSoup4 + lxml** | 깨진 HTM 복구 |
| HTTP | **httpx + tenacity** | 비동기, 프록시/사설 CA, 백오프 |
| 실행 | **FastAPI BackgroundTasks** | 파일별 병렬 파싱, 폴링으로 상태 확인 |
| 설정 | **pydantic-settings** | `.env` — 환경 전환의 단일 창구 |

### 2.2 프론트엔드 — React 18 + TypeScript + Vite

| 항목 | 선정 | 근거 |
|---|---|---|
| **그리드** | **AG Grid Community (MIT)** ★ | 33컬럼 + 다중 파일 수백 행 가상 스크롤, 인라인 편집, 셀 색상, **Excel 붙여넣기**, `Ctrl+D`, 컬럼 고정/숨김 — 전부 무료 |
| 프레임워크 | React 18 + TS + Vite | |
| 상태 | TanStack Query + Zustand | 서버 상태 / 편집 상태 분리 |
| UI | Mantine | 드롭존·모달·알림 |

### 2.3 저장소 — DB 없이

| 데이터 | 방식 | 경로 |
|---|---|---|
| 거래처 마스터 | YAML (Git) | `masters/customers/{code}.yaml` |
| 참조표 | CSV (Git) | `masters/refs/msc_ref.csv` |
| 업로드 원본 | 파일 | `storage/uploads/{batch_id}/` |
| 배치 상태 | JSON | `storage/batches/{batch_id}/batch.json` |
| LLM 응답 캐시 | 파일(해시 키) | `storage/llm_cache/` |
| 전송 감사 로그 | JSONL | `storage/audit/{YYYY-MM}/` |

> `batch_id`는 **서버 내부 식별자**로만 사용한다(작업 세션 관리·파일 저장). **전송 페이로드에는 포함하지 않는다.**

**DB 승격 트리거**: ① 동시 사용자 5명 초과 ② 이력 검색/통계 요구 ③ 배치 10,000건 초과

---

## 3. 파싱 아키텍처 (Claude API)

### 3.1 절대 원칙

| 구분 | 내용 |
|---|---|
| ✅ **LLM에게 시킴 (읽기)** | PO번호, 발주일, 납기일, Ship To **원문 텍스트**, 품번, 품명, 수량, 단가, 통화, 브랜드 **원문 문구** |
| ❌ **절대 안 시킴 (판단)** | ZBRAND(38/127/205…), KUNNR2(319677…), ZPKRE2(N,B12,C7), ZSHCO(A/L), VSART, 참조표 조회 |

> LLM이 "HARRISBURG"를 읽으면 → `KUNNR2=319677`은 **결정표**가 정한다.
> SAP 코드는 틀리면 오더가 잘못 생성되므로 재현성·감사·즉시 반영이 필요하다.

### 3.2 파이프라인

```
거래처 선택 → 파일 업로드 (N개)
  파일별 병렬 ─┐
 ① 전처리       PDF: 텍스트 레이어 판정 → 텍스트/이미지 경로
                HTM: BS4 정리 → 마크다운
 ② Claude 추출  공통 시스템 프롬프트(캐시) + 거래처 hints + Tool Use 강제
 ③ 근거 검증    evidence 원문 대조 · 합계 교차검증              §3.5
 ④ 정규화       날짜/수량/통화 파싱
      ▼ RawPO (원문 값만, 파일별)
 ⑤ 규칙엔진 → EnrichedPO                                        §5
 ⑥ 행 생성  → SapRow[] (33필드 × 품목 수)                       §6
             ─┘
 ⑦ 전 파일 행 병합 → 통합 그리드 (파일 출처 메타 유지)
 ⑧ 검증     → CellIssue[]                                       §7
```

### 3.3 LLM 호출 설계

| 항목 | 설정 |
|---|---|
| 출력 강제 | **Tool Use** (`extract_purchase_order` 단일 툴, `tool_choice` 고정) |
| temperature | **0** |
| 모델 | 역할 별칭(`extract`/`extract_fallback`) → 실제 ID는 설정 주입 §3.7 |
| 프롬프트 캐싱 | 공통 시스템 프롬프트 + 스키마 캐시, 거래처 힌트만 가변 |
| 페이지 | 20p 초과 시 청크 분할 후 라인 병합 |
| 응답 캐시 | `sha256(파일)+프롬프트버전+거래처+모델ID` |
| 병렬 | 파일 단위 동시 실행 (`LLM_MAX_CONCURRENCY`) |
| 재시도 | 120s 타임아웃, 429·5xx만 3회 백오프 |

### 3.4 추출 스키마

```jsonc
{
  "header": {
    "po_number":      { "value": "PO-4471902", "evidence": "Purchase Order No: PO-4471902", "page": 1, "confidence": 0.98 },
    "po_date": {...}, "requested_date": {...},
    "ship_to_text":   { "value": "1234 Main St, HARRISBURG, PA 17111", ... },
    "bill_to_text": {...}, "brand_text": { "value": "INTERSTATE", ... },
    "incoterms": {...}, "payment_terms": {...}, "currency": {...},
    "order_text":     { "value": "<브랜드 키워드 탐색용 원문 블록>", ... }
  },
  "lines": [
    { "line_no": 1,
      "our_item":  { "value": "09876543", ... },     // 거래처 품번
      "item_code": { "value": "1234567890", ... },   // 자사 품번
      "description": {...}, "quantity": {...}, "unit": {...},
      "unit_price": {...}, "req_date": {...},
      "ship_to_text": {...},   // ★ 품목마다 다를 수 있음
      "brand_text": {...}, "extra": {} }
  ],
  "totals": { "line_count": 12, "total_qty": "310", "total_amount": "3,828.50" },
  "notes": []
}
```

**모든 값은 `{value, evidence, page, confidence}` 4종 세트 강제.** `evidence`는 원문에서 그대로 복사한 문자열.

> ★ **라인별 헤더값**: Ship To·브랜드·납기가 **품목마다 다를 수 있으므로** 라인 레벨에도 동일 필드를 둔다. 라인 값이 없으면 헤더 값으로 폴백(`fallback_source`).

### 3.5 환각 차단 4중 장치 ★

| # | 장치 | 동작 |
|---|---|---|
| 1 | **근거 그라운딩** | `evidence`가 실제 원문에 존재하는지 코드로 대조. 없으면 🔴 |
| 2 | **합계 교차검증** | 문서 기재 합계(행수/수량/금액)와 산술 대조 → 불일치 시 🔴 "라인 누락 가능" |
| 3 | **신뢰도 임계** | `confidence < 0.9` → 🟡, 필수 필드 `< 0.7` → 🔴 |
| 4 | **사람 검수** | 위 3개 통과해도 전송 전 반드시 검수 통과 |

### 3.6 거래처별 추출 설정

```yaml
extraction:
  input: auto              # auto | text | image
  hints: |
    - MSC Industrial 표준 양식이다.
    - "Customer Part No." = our_item, "Vendor Part No." = item_code
    - Ship To 는 "SHIP TO:" 블록 전체를 원문 그대로. 품목별로 다를 수 있음.
    - 브랜드는 품명 컬럼에 HERTEL / INTERSTATE / ACCUPRO / CLASS C 로 표기
    - 단가는 "Unit Price" 컬럼. "Ext. Price"(합계)와 혼동 금지
  extra_fields:
    - { name: release_no, description: "Release Number (있는 경우)" }
  page_limit: 20
```

### 3.7 LLM 프로바이더 추상화 (사내 계정 전환)

```python
class LLMProvider(Protocol):
    def extract(self, *, system, tools, content, model_alias, max_tokens) -> ToolCallResult: ...
    def health(self) -> ProviderHealth: ...
# anthropic_direct / bedrock / vertex / gateway / mock
```

```bash
LLM_PROVIDER=anthropic          # anthropic | bedrock | vertex | gateway | mock
LLM_API_KEY=...                 # ← 사내 계정 키로 교체하는 지점
LLM_BASE_URL=
LLM_MODEL_EXTRACT=...           # 역할 별칭 → 실제 모델 ID
LLM_MODEL_FALLBACK=...
HTTPS_PROXY=                    # 사내 프록시
REQUESTS_CA_BUNDLE=             # 사내 SSL 검사 장비 대응
LLM_MAX_CONCURRENCY=4
LLM_PROMPT_VERSION=v1
```

| 전환 시 체크 | 내용 |
|---|---|
| `.env` 교체 | `LLM_API_KEY`, `LLM_MODEL_*` |
| 방화벽 | 사내 서버 → 인터넷 아웃바운드 허용 (**폐쇄망이면 gateway/bedrock 전환**) |
| 프록시/CA | 사내 SSL 검사 장비 있으면 인증서 번들 |
| **골든 테스트 전량 실행** ★ | 모델이 바뀌면 추출 정확도가 달라질 수 있음 |

> `LLM_PROVIDER=mock` — 저장된 골든 응답 재생. **프론트 개발/CI는 API 키 없이 비용 0.**

---

## 4. 거래처 지정 = 사용자 선택 (자동판별 불필요)

**업로드 전에 사용자가 거래처를 선택한다.** 자동판별을 하지 않으므로 오판 리스크가 없고, 파싱 힌트·규칙·컬럼 설정이 처음부터 확정된다.

| 효과 | 내용 |
|---|---|
| 오판 제거 | 거래처 오인식으로 전 행이 잘못되는 사고 원천 차단 |
| **규칙 사전 노출** ★ | 선택 즉시 그 거래처의 고정값·판별규칙을 화면에 표시 (§4.1) |
| 배치 일관성 | 한 배치 = 한 거래처 → 다중 파일을 **동일 컬럼 구성으로 통합** 가능 |
| 파일 형식 검증 | 거래처별 허용 확장자와 다르면 업로드 시 즉시 경고 |

### 4.1 규칙 미리보기 (YAML에서 자동 생성)

업로드 화면에 표시할 내용을 **마스터 YAML에서 자동 생성**한다. 규칙이 바뀌면 화면도 자동으로 바뀌므로 문서-실동작 불일치가 발생하지 않는다.

```
GET /api/masters/customers/{code}/preview
→ {
    "fixed":   [ {field:"KUNNR1", label:"판매처",   value:"107525"},
                 {field:"ZBRAND", label:"브랜드",   value:"2", note:"OEM"},
                 {field:"VSART",  label:"운송수단", value:"04"} ],
    "keyword_rules": [
      { label:"브랜드 문구 분류", targets:["ZPKRE2","EMPST"],
        note:"위에서부터 순서대로 확인",
        entries:[ {contains:"WIDIA GTD", value:"WGT"},
                  {contains:"KENNAMETAL", value:"KMT"} ] } ],
    "tables": [ { label:"출하처(Ship To) 분기", when:[...], then:[...], rows:[...] } ],
    "lookups": [ { label:"MSC 참조표 (B/C코드)", target:"ZPKRE2" } ],
    "from_document": ["BSTKD","MATNR","MAKTX","KWMENG","PRICE","VDATU", ...],
    "file_types": ["htm"]
  }
```

> 2차 확장: 자동판별(지문) 도입 시 "선택된 거래처와 문서 내용이 다릅니다" **교차검증 경고**만 추가한다. 선택 방식 자체는 유지.

---

## 5. 규칙 마스터 설계

### 5.1 결론: YAML 마스터 + Git 리뷰 + 스키마 검증

| 후보 | 판정 |
|---|---|
| 코드 하드코딩 | ✗ 배포 없이 변경 불가 |
| **YAML** | ✅ 결정표 표현, Git diff 리뷰, 화면 자동 렌더링 |
| Excel/Sheets | △ 단순 룩업표(MSC_REF)만 CSV |
| DB | 보류 |

### 5.2 규칙 프리미티브

| 종류 | 용도 |
|---|---|
| `const` | 고정값 (`VSART: "04"`) |
| `doc` | 발주서 추출값 그대로 |
| `keyword_map` | 키워드 **포함** 시 매핑 (위→아래 첫 매칭) |
| `exact_map` | 정확 일치 매핑 (정규화 후) |
| **`decision_table`** ★ | **다중 조건 분기** |
| `lookup` | 참조표(CSV) 조회 |
| `expr` | 결과 조합 (화이트리스트 미니 평가기) |
| `gen` | 생성값 (`POSEX` = 행번호×10) |

> `expr`이 늘어나면 설계 실패 신호 — 결정표로 흡수한다.

### 5.3 결정표 ★

```yaml
tables:
  ship_to_routing:
    label: "출하처(Ship To) 분기"
    description: "Ship To 주소의 도시명으로 도착지 고객코드와 포장구분 기본값을 결정"
    scope: line                     # line | header — 품목마다 다르면 line
    when:
      - { source: line.ship_to_text, op: contains_ci, label: "Ship To 주소에 포함" }
    then: [KUNNR2, _pack_base]
    rows:
      - { when: ["ELKHART"],    then: ["100249", "C"], note: "인디애나 물류센터" }
      - { when: ["HARRISBURG"], then: ["319677", "N"] }
      - { when: ["RENO"],       then: ["319678", "O"] }
      - { when: ["ATLANTA"],    then: ["319679", "A"] }
    on_no_match: { action: error, message: "Ship To 도시를 인식하지 못했습니다 (ATLANTA/ELKHART/HARRISBURG/RENO)" }
```

다중 조건:
```yaml
  shipping:
    when:
      - { source: rule.ZBRAND,      op: in,          label: "브랜드" }
      - { source: header.incoterms, op: contains_ci, label: "인도조건" }
    then: [ZSHCO, VSART]
    rows:
      - { when: [["471","507"], "*"], then: ["A", "04"] }
      - { when: ["*",           "*"], then: ["L", "04"] }   # 기본행
```

- 연산자: `equals` `contains_ci` `in` `startswith` `regex` `is_empty` `*`
- 평가: **위→아래 첫 매칭**
- CI가 **도달 불가 행 / 중복 조건 / 기본행 누락** 자동 검출
- `scope: line` → 품목별 개별 평가 (행마다 다른 KUNNR2 가능)
- **이 표가 업로드 화면 규칙 미리보기에 그대로 렌더링됨** (§4.1)

### 5.4 필드 매핑표 — 33필드 전부 선언 강제

```yaml
fields:
  AUART:   { from: const, value: "ZOR",    label: "오더유형" }
  VKORG:   { from: const, value: "1000",   label: "판매조직" }
  VTWEG:   { from: const, value: "10",     label: "유통경로" }
  VBELN:   { from: const, value: "",       label: "SAP 오더번호(공란)" }
  KUNNR1:  { from: const, value: "100249", label: "판매처" }
  KUNNR2:  { from: table, table: ship_to_routing, label: "도착지" }
  KUNNR3:  { from: const, value: "",       label: "지급인" }
  BSTKD:   { from: doc,   path: header.po_number,   label: "고객발주번호", required: true }
  VDATU:   { from: doc,   path: line.req_date,      label: "납품요청일", required: true,
             fallback: header.requested_date }
  ZTERM:   { from: const, value: "NT30",   label: "지급조건" }
  INCO1:   { from: doc,   path: header.incoterms,   label: "인도조건" }
  INCO2:   { from: const, value: "",       label: "인도조건2" }
  ZBRAND:  { from: rule,  rule: brand_code, label: "브랜드", required: true }
  ZSHCO:   { from: const, value: "A",      label: "출하구분" }
  ZPKRE1:  { from: const, value: "",       label: "포장구분1" }
  MATNR:   { from: doc,   path: line.item_code,   label: "자재번호", required: true }
  MAKTX:   { from: doc,   path: line.description, label: "자재내역" }
  KWMENG:  { from: doc,   path: line.quantity,    label: "수량", required: true }
  LGORT:   { from: const, value: "",       label: "저장위치" }
  ETDAT:   { from: doc,   path: line.req_date, label: "출고일" }
  BATCH:   { from: const, value: "",       label: "배치" }
  VALTY:   { from: const, value: "",       label: "평가유형" }
  ZPKRE2:  { from: expr,  expr: 'join(",", compact([_pack_base, ref_codes.b_code, ref_codes.c_code]))',
             label: "포장구분2",
             explain: "출하처 기본값(C/N/O/A) 뒤에 참조표 B코드·C코드를 쉼표로 연결" }
  EMPST:   { from: const, value: "",       label: "담당부서" }
  VSART:   { from: const, value: "04",     label: "운송수단" }
  PRICE:   { from: doc,   path: line.unit_price,  label: "단가" }
  WAERK:   { from: doc,   path: header.currency,  label: "통화" }
  BSTDK_E: { from: doc,   path: header.po_date,   label: "발주일" }
  POSEX:   { from: gen,   generator: line_no_x10, label: "품목번호" }   # 000010, 000020…
  DELCO:   { from: const, value: "",       label: "납품완료" }
  BSTKD_E: { from: doc,   path: header.po_number, label: "고객발주번호(확장)" }
  AUGRU:   { from: const, value: "",       label: "오더사유" }
  VKAUS:   { from: const, value: "",       label: "용도" }
```

**33개 전부 선언되지 않으면 CI 실패.** 값이 없어도 `{ from: const, value: "" }`로 명시.

### 5.5 화면 컬럼 설정 (거래처별)

```yaml
grid:
  pinned:  [POSEX, MATNR, MAKTX]                # 좌측 고정 (+ 시스템 컬럼 #, 파일)
  hidden:  [VBELN, BATCH, VALTY, AUGRU, VKAUS]  # 화면에서만 숨김
  order:   [POSEX, MATNR, MAKTX, KWMENG, PRICE, WAERK, ETDAT, VDATU,
            BSTKD, KUNNR1, KUNNR2, ZBRAND, ZPKRE2, EMPST, ...]
  width:   { MAKTX: 260, MATNR: 140 }
```

| 컬럼 종류 | 전송 포함 | 설명 |
|---|---|---|
| SAP 필드 33개 | ✅ (숨겨도 포함, 빈값 `""`) | CBO 테이블 컬럼 고정이므로 화면 표시와 전송을 분리 |
| **`#`(행번호)** | ❌ | 화면 전용 |
| **`파일`(출처 파일명)** | ❌ | 화면 전용 — 다중 파일 통합 그리드에서 출처 식별 |

### 5.6 상속

```yaml
extends: [_base/sap_defaults, _base/us_distributor]
```
하위(거래처) 우선 병합. `tables.rows`는 기본 교체, `merge: append` 시 추가.

### 5.7 마스터 파일 구조

```
masters/
├── _base/{sap_defaults,us_distributor,jp_group}.yaml
├── customers/{msc,kl,ygjp,...}.yaml     # 1 거래처 = 1 파일
├── refs/msc_ref.csv                     # our_item, b_code, c_code
└── schema/customer.schema.json          # 편집기 자동완성 + CI 검증
```

```yaml
version: 1
meta:       { code, name, customer_no, owner, status, file_types }
extends:    [...]
extraction: { ... }    # §3.6
tables:     { ... }    # §5.3
rules:      { ... }    # keyword_map / exact_map / lookup
fields:     { ... }    # §5.4 (33개 전부)
grid:       { ... }    # §5.5
```

### 5.8 기존 3사 규칙

#### MSC (100249) — PDF
```yaml
rules:
  brand_code:
    kind: keyword_map
    label: "브랜드 판별"
    source: line.brand_text
    fallback_source: header.order_text
    case_insensitive: true
    entries:
      - { contains: "HERTEL",     value: "38"  }
      - { contains: "INTERSTATE", value: "127" }
      - { contains: "ACCUPRO",    value: "205" }
      - { contains: "CLASS C",    value: "428" }
    on_no_match: { action: error, message: "MSC 브랜드 키워드를 찾을 수 없습니다" }

  ref_codes:
    kind: lookup
    label: "MSC 참조표 조회 (B/C코드)"
    table_file: refs/msc_ref.csv
    key: line.our_item
    key_column: our_item
    return: [b_code, c_code]
    on_no_match: { action: warn, message: "참조표 미등록 품번: {our_item}" }

tables:
  ship_to_routing: { ... §5.3 ... }      # scope: line
```
고정값: `ZSHCO="A"`, `VSART="04"`

#### KL / Kennametal (107525) — HTM
```yaml
rules:
  brand_class:
    kind: keyword_map
    label: "브랜드 문구 분류"
    description: "WIDIA GTD 를 먼저 확인 (동시 등장 시 WGT 우선)"
    source: header.brand_text
    case_insensitive: true
    entries:
      - { contains: "WIDIA GTD",  value: "WGT" }
      - { contains: "KENNAMETAL", value: "KMT" }
    on_no_match: { action: error, message: "KL 브랜드 분류 실패" }
fields:
  ZBRAND: { from: const, value: "2", label: "브랜드(OEM 고정)" }
  ZPKRE2: { from: rule,  rule: brand_class }
  EMPST:  { from: rule,  rule: brand_class }
  VSART:  { from: const, value: "04" }
```

#### YGJP (3200) — PDF
```yaml
rules:
  brand_code:
    kind: exact_map
    label: "브랜드명 → 코드 (24종)"
    source: line.brand_text
    fallback_source: header.brand_text
    normalize: [trim, upper, collapse_space]
    entries:
      "YG BRAND": "1"                     "YAMAKATSU BRAND": "142"
      "YSK BRAND": "181"                  "YMKT BRAND": "183"
      "YCS BRAND": "209"                  "NIKKO KIZAI BRAND": "227"
      "SUGIMOTO BRAND": "245"             "KURODA BRAND": "248"
      "SAKANOSHITA BRAND": "249"          "DAIWA SHOKAI": "250"
      "TOSA KIKO BRAND": "411"            "CHUO KOKI BRAND": "412"
      "SIAM YAMAKATSU BRAND": "435"       "YAMA-K": "439"
      "KUMAZAWA": "465"                   "YG BRAND (COMINIX)": "471"
      "SAKUSAKU BRAND": "476"             "YG BRAND (SAKUSAKU)": "477"
      "YG BRAND (YGT Y)": "480"           "YG BRAND (CHUO KOKI)": "481"
      "YG BRAND (IBIDEN)": "482"          "NEW CENTURY BRAND(COMINIX)": "507"
    ambiguous:      # ⚠ 원문 구분 키 미확정 → 검수 화면에서 선택 강제
      - { candidates: ["227","448"], base_text: "NIKKO KIZAI" }
      - { candidates: ["1","449"],   base_text: "YG BRAND" }
      - { candidates: ["142","450"], base_text: "YAMAKATSU" }
    on_no_match: { action: error, message: "YGJP 브랜드 매핑 실패: '{brand_text}'" }

tables:
  shipping:
    label: "출하구분 분기"
    when: [{ source: rule.brand_code, op: in, label: "브랜드 코드" }]
    then: [ZSHCO]
    rows:
      - { when: [["471","507"]], then: ["A"], note: "COMINIX 계열" }
      - { when: ["*"],           then: ["L"] }
```
고정값: `KUNNR2="319854"`, `VSART="04"`

> ⚠ YGJP `448/449/450`은 227·1·142와 원문 텍스트가 겹쳐 구분 키 미확정 → `ambiguous` 처리.

---

## 6. 전송 페이로드 (EAI)

### 6.1 요청

```
POST {EAI_ENDPOINT}
Content-Type: application/json; charset=utf-8
```
```json
{
  "rows": [
    { "AUART":"ZOR","VKORG":"1000","VTWEG":"10","VBELN":"",
      "KUNNR1":"107525","KUNNR2":"319677","KUNNR3":"",
      "BSTKD":"PO-4471902","VDATU":"20260920","ZTERM":"NT30",
      "INCO1":"FCA","INCO2":"INCHEON","ZBRAND":"2","ZSHCO":"A","ZPKRE1":"",
      "MATNR":"1234567890","MAKTX":"END MILL 10MM 4FL","KWMENG":"25.000",
      "LGORT":"","ETDAT":"20260915","BATCH":"","VALTY":"",
      "ZPKRE2":"WGT","EMPST":"WGT","VSART":"04",
      "PRICE":"12.35","WAERK":"USD","BSTDK_E":"20260901","POSEX":"000010",
      "DELCO":"","BSTKD_E":"PO-4471902","AUGRU":"","VKAUS":"" }
  ]
}
```

| 규약 | 내용 |
|---|---|
| 구조 | **`rows` 배열만.** 1행 = 1품목, **33필드 전부 포함** |
| 다중 파일 | 전 파일의 행이 **같은 배열**에 병합 (파일 구분자 없음, `BSTKD`로 구분) |
| 날짜 | `"YYYYMMDD"` 문자열 |
| 수량/금액 | **문자열 decimal** (`"25.000"`) — 부동소수 오차 방지 |
| 코드값 | 문자열, 앞자리 0 보존 (`"04"`, `"000010"`) |
| 빈 값 | `""` (null 미사용) |
| 인코딩 | UTF-8 |
| 최상위 형태 | `PAYLOAD_ROOT=rows\|array` 설정으로 전환 가능 |

### 6.2 응답 / 전송 정책

| 응답 | 동작 |
|---|---|
| 2xx `{"status":"OK"}` | `SENT` 처리 |
| 2xx `ERROR` / 4xx | 메시지 표시, 재전송 가능 |
| 5xx / 타임아웃 | 3회 백오프 재시도 → [재전송] 버튼 |

| 정책 | 내용 |
|---|---|
| 인증 | **없음** (사내망). `EAI_AUTH_MODE=none\|apikey\|basic` 설정만 유지 |
| 멱등키 | **없음** — 중복 전송 허용 (SAP에서 덮어씀) |
| 오더 분할 | **없음** |
| 전송 단위 | **배치 전체 일괄** (다중 파일 통합) |
| 대용량 | 행 수가 매우 많으면 청크 분할 (`EAI_MAX_ROWS_PER_REQUEST`, 기본 무제한) |

---

## 7. 검증 (전송 차단 기준)

| 종류 | 판정 | 예 |
|---|---|---|
| 필수값 누락 | 🔴 | MATNR, KWMENG, BSTKD, VDATU, ZBRAND |
| 규칙 매칭 실패 | 🔴 | 브랜드/도착지 미인식, `ambiguous` 미선택 |
| 형식 오류 | 🔴 | 날짜 파싱 실패, 수량 비숫자 |
| 길이 초과 | 🔴 | 필드별 max_len (`_base/sap_defaults.yaml`) |
| 합계 불일치 | 🔴 | 파일별 기재 합계 ≠ 추출 합계 |
| 참조표 미등록 | 🟡 | MSC B/C코드 없음 |
| 낮은 신뢰도 | 🟡 | confidence < 0.9 |

**전 파일 통틀어 🔴 0건이어야 [전체 전송] 활성화.**

---

## 8. 백엔드 API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/masters/customers` | 거래처 목록 (코드/명/고객번호/허용 파일형식) |
| GET | `/api/masters/customers/{code}/preview` | **규칙 미리보기** (업로드 화면용) §4.1 |
| GET | `/api/masters/customers/{code}/grid` | 컬럼 구성(순서/고정/숨김/한글명) |
| POST | `/api/batches` | 배치 생성 (`customer_code`) |
| POST | `/api/batches/{id}/files` | 파일 다중 업로드 → 파일별 파싱 시작 |
| GET | `/api/batches/{id}` | 상태 + 파일별 진행 + **통합 33컬럼 행** + issues (폴링) |
| DELETE | `/api/batches/{id}/files/{fid}` | 파일 제거 (해당 행 삭제) |
| PATCH | `/api/batches/{id}/rows` | 셀 편집 반영 → 재검증 |
| POST | `/api/batches/{id}/revalidate` | 전체 재검증 |
| GET | `/api/batches/{id}/preview` | 전송할 JSON 미리보기 |
| POST | `/api/batches/{id}/send` | **EAI 일괄 전송** |
| POST | `/api/masters/reload` | 마스터 재로딩 |
| GET | `/api/health` | 마스터 로딩 + LLM 프로바이더 + EAI 연결 |

**표준 에러**
```json
{ "error": { "code": "PARSE_FAILED", "message": "발주서를 읽지 못했습니다.",
  "detail": { "file": "KL_003.htm", "reason": "NO_TEXT_LAYER" },
  "recoverable": true, "action": "MANUAL_INPUT" } }
```

---

## 9. 화면 (요약 — 상세는 `process.md` §4)

### 9.1 업로드 화면
① 거래처 선택 → ② **규칙 미리보기 카드**(고정값·판별규칙·분기표, YAML에서 자동 생성) → ③ 다중 파일 업로드 → 파일별 파싱 진행 표시 → [검수하기]

### 9.2 통합 검수 화면 ★
**여러 파일의 전 품목을 한 그리드에. 1행 = 1품목. 33컬럼 + 화면전용 2컬럼.**

| 요소 | 설계 |
|---|---|
| 컬럼 | 33개 전부 + `#`, `파일`(전송 제외). `#`/`파일`/`POSEX`/`MATNR`/`MAKTX` 좌측 고정 |
| 헤더 | SAP 필드명 + 한글명 2줄 |
| 파일 구분 | 파일 경계에 구분선, **파일 필터**로 부분 조회 |
| 편집 보조 | **열 일괄 채우기**(적용범위: 전체/현재 파일), `Ctrl+D`, **Excel 붙여넣기**, `Ctrl+Z`, 행 삭제 |
| 색상 | 🔴 오류(차단) 🟡 경고 🔵 사람수정 |
| 이슈 패널 | **파일명 + 행번호** 표기, 클릭 시 셀 이동 |
| 합계 바 | 전체 및 파일별 합계, 문서 기재 합계와 대조 |
| 원본 보존 | `value` / `original_value` 동시 저장 |
| 2차 | 근거 툴팁, 원문 PDF 대조 뷰 |

### 9.3 전송 모달
전송 확인(거래처·파일 목록·행수·JSON 미리보기) → 전송 → 완료 (**"세일즈오더 생성은 SAP에서 확인" 문구 필수**)

---

## 10. 에러 처리

| 단계 | 오류 | 처리 |
|---|---|---|
| 업로드 | 거래처 허용 형식 불일치 | 즉시 경고, 업로드 거부 |
| LLM | API 오류/타임아웃 | 3회 재시도 → 해당 **파일만** 실패 표시, 나머지 진행 |
| LLM | 인증/한도 오류 | 관리자 알림 + `/api/health` |
| LLM | 근거 검증 실패 | 해당 필드 🔴 |
| LLM | 합계 불일치 | 🔴 "라인 누락 가능" |
| LLM | 텍스트 없음(스캔본) | 1차: 안내 / 2차: 이미지 경로 자동 전환 |
| 규칙 | 매칭 실패 | 🔴 + 후보 드롭다운 |
| 규칙 | 참조표 미등록 | 🟡 + 기본값 진행 |
| 규칙 | `ambiguous` | 🔴 + 선택 강제 |
| 전송 | 5xx/타임아웃 | 3회 백오프 → [재전송] (중복 무해) |
| 전송 | 4xx/업무오류 | 메시지 표시, 수정 후 재전송 |
| 전송 후 | 오류 발견 | **SAP에서 직접 수정** |

---

## 11. 테스트 & 거버넌스

| 종류 | 내용 |
|---|---|
| **규칙 스펙 테스트** ★ | 마스터의 모든 매핑 행 전수 검증 (3사 기준 40+ 케이스) |
| 결정표 정합성 | 도달 불가 행, 중복 조건, 기본행 누락 |
| 필드 커버리지 | 거래처별 **33필드 전부 선언** (CI 실패 조건) |
| **골든 테스트 (LLM)** ★ | 샘플 → 기대 33필드 행 고정 비교. **프롬프트·모델·계정 변경 시 회귀 검출** |
| 다중 파일 병합 | 파일 순서·행번호·POSEX 재부여 검증 |
| 오프라인 테스트 | `LLM_PROVIDER=mock` → CI 비용 0 |
| 병행 검증 | 초기 2주 기존 POC Excel 결과와 자동 diff |

**거버넌스**: 거래처별 `owner` 지정 / 규칙 변경은 PR + owner 승인 / 프롬프트 버전 캐시 키 포함

---

## 12. 디렉터리 구조

```
po2sap/
├── design.md  process.md  rules.md(현업용, 추후)
├── .env.example
├── backend/app/
│   ├── main.py  config.py
│   ├── api/{routes_masters,routes_batch,routes_send}.py
│   ├── domain/{models.py, sap_row.py, batch.py}       # RawPO / SapRow(33) / Batch(다중파일)
│   ├── extraction/
│   │   ├── preprocess.py
│   │   ├── providers/{base,anthropic_direct,bedrock,vertex,gateway,mock,factory}.py
│   │   ├── model_registry.py  schema_builder.py  prompt.py
│   │   └── grounding.py
│   ├── rules/
│   │   ├── loader.py  schema.py  engine.py
│   │   ├── primitives.py  decision_table.py  expr.py  reftable.py
│   │   └── preview.py                # ★ YAML → 규칙 미리보기 생성
│   ├── mapping/row_builder.py        # EnrichedPO → SapRow[] (33필드)
│   ├── validation/validator.py
│   ├── transport/{eai_client.py, payload.py}
│   ├── storage/{batch_repo.py, audit_log.py, llm_cache.py}
│   └── utils/normalize.py
├── backend/tests/{fixtures,golden,test_rules_spec,test_decision_tables,test_extraction_golden}
├── masters/                          # §5.7
├── frontend/src/
│   ├── pages/{UploadPage, ReviewPage}.tsx
│   ├── components/{CustomerPicker, RulePreviewCard, FileDropzone,
│   │               SapGrid, IssuePanel, SendModal}.tsx
│   └── types/sapRow.ts
├── scripts/{validate_masters.py, xlsx2csv_msc_ref.py, new_customer.py, mock_eai_server.py}
└── storage/                          # gitignore
```

---

## 13. 배포 / 환경

| 환경 | LLM | EAI | 용도 |
|---|---|---|---|
| local | `mock` | 모의 서버 | 프론트/규칙 개발 (비용 0) |
| dev | 개발용 키 | 모의 서버 | 파싱 튜닝 |
| **사내 서버** | **사내 계정** | 실 EAI | UAT → 운영 |

**환경 차이는 `.env`뿐. 코드·이미지 동일.**
이관 절차: 배포 → `.env` 작성 → `/api/health` 확인 → **골든 테스트 전량 실행** → 병행 검증 → 전환

| 항목 | 방침 |
|---|---|
| 배포 | Docker Compose (backend + nginx) / Windows면 uvicorn + NSSM |
| 시크릿 | `.env` Git 제외 |
| 로그 | 구조화 JSON. **원문/단가 미기록** |
| 보존 | 원본 1년 / 배치 1년 / 감사 JSONL 5년 |
| 인증 | 1차 사내망(무인증) → 2차 JWT/SSO |

---

## 14. 로드맵

### 1주 MVP (상세는 `process.md` §7)

| Day | 작업 |
|---|---|
| D1 | 백엔드 스켈레톤, 전처리, Claude 추출(구조화 출력) |
| D2 | 규칙엔진 + MSC YAML + 33필드 행 생성 + 검증 |
| D3 | 프론트: 거래처 선택·규칙카드·다중 업로드 + 통합 그리드 |
| D4 | **일괄 전송 + 모의 EAI + 결과 모달 → 엔드투엔드 관통** |
| D5 | KL·YGJP **YAML만 추가** 검증 + 데모 |

### 이후

| 단계 | 내용 |
|---|---|
| 2주차 | 3사 정확도 튜닝, 골든 테스트 구축, 기존 Excel 결과와 병행 검증 |
| 3~4주차 | 사내 서버 이관, 실 EAI 연동, UAT |
| 이후 | 거래처 확장(설정 작업), 원문 대조 뷰, 근거 툴팁, 마스터 조회 UI, (필요 시) 자동판별·이력 화면 |

---

## 15. 미확정 항목

| # | 항목 | 시점 |
|---|---|---|
| 1 | EAI 엔드포인트 URL / 최상위 형태(`rows` vs 배열) | D4 전 |
| 2 | SAP 공통 고정값 (AUART/VKORG/VTWEG/LGORT/ZTERM/INCO1/2) | D2 (임시값 가능) |
| 3 | 확장 거래처 명단·우선순위 (약 20곳) | 2차 |
| 4 | YGJP 브랜드 448/449/450 구분 키 | YGJP 적용 시 |
| 5 | 거래처별 숨길 컬럼 | 운영 후 조정 |
| 6 | 사내 서버 인터넷 아웃바운드 허용 | 이관 시점 |
| 7 | 변경 발주(Change PO) | 범위 제외 |
