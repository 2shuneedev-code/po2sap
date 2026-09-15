# PO2SAP 시스템 설계서

> 거래처 선택 → PDF/HTM 업로드 → Claude 추출 → 규칙엔진 → 통합 스프레드시트 검수 → EAI(HTTPS/JSON) 일괄 전송 → SAP CBO 적재
>
> 버전 **v1.0** · 2026-09-11 · **낡은 v0.5 전면 재작성**
>
> ### 이 문서의 범위
> 기술 스택 · 전체 아키텍처 · 파싱 설계 · 저장소 · 배포. **여기서 끝나는 이야기만 쓴다.**
>
> | 주제 | 단일 원천(SSOT) |
> |---|---|
> | 규칙 스키마 · 엔진 파이프라인 | **`masters/SCHEMA.md`** |
> | 전송 필드 목록 · 공통 고정값 | **`masters/_base/sap_defaults.yaml`** |
> | 거래처별 규칙 실제 값 | **`masters/customers/*.yaml`** |
> | API 요청/응답 형태 | **`contracts/api-contract.md`** |
> | 업무 흐름 · 화면 | **`process.md`** |
>
> 위 주제는 이 문서에 **중복 기재하지 않는다.** (v0.5에서 중복 때문에 33/36 필드가 어긋났다.)

---

## 0. 핵심 설계 결론

| # | 결정 | 요약 |
|---|---|---|
| D1 | **LLM은 '읽기', 규칙엔진은 '판단'** | Claude는 원문 값만 추출. SAP 코드는 **절대 LLM이 정하지 않음** |
| D2 | 파싱 = Claude API + 거래처별 **추출 힌트(YAML)** | 거래처 추가 시 파서 코드 0줄 |
| D3 | 분기 로직 = **결정표(Decision Table)** | 설정이 곧 화면 (규칙 미리보기 카드와 동일 원천) |
| D4 | 거래처별 **전송 필드 전량 선언 강제** | 누락 시 CI 실패. 필드 수는 `_base` 가 정한다 (현재 36) |
| D5 | **거래처 선택 후 업로드** | 자동판별 오판 리스크 제거 + 규칙을 사전에 현업에 노출 |
| D6 | 검수 = **다중 파일 통합 평면 그리드** | 헤더성 필드도 품목마다 다를 수 있음 |
| D7 | 전송 = **`rows` 배열 일괄, 인증·멱등키 없음** | 중복 전송 무해 → 재전송이 단순 |
| D8 | **DB 없음** — YAML 마스터 + 파일 저장 + Git | 승격 트리거는 §4 |
| D9 | LLM 결과는 **근거(evidence) 강제 + 자동 검증** | 환각 차단 4중 (§3.4) |
| D10 | **LLM 프로바이더 추상화** | 사내 계정 전환 시 코드 0줄, `.env`만 교체 |
| D11 | **1 문서 → N 오더 분할 존재** | MSC는 `Shipment` 블록마다 별개 오더 (`split.by: shipment`) |

> D11은 v0.5의 "오더 분할 불필요"를 **뒤집은 것이다.** MSC 실물 발주서 1부에 출하처가 여러 개 있고,
> 기존 운영 결과지도 출하처별로 분리되어 있다 (`samples/MSC/…(ELKHART).csv` 등).

---

## 1. 설계 원칙

| # | 원칙 |
|---|---|
| P1 | **읽기와 판단의 분리** — Claude는 추출, 규칙엔진은 코드 결정 |
| P2 | **규칙은 데이터, 엔진은 코드** — 거래처 이름이 코드에 등장하지 않는다 |
| P3 | **설정 파일 = 현업 화면** — 규칙 카드·결정표를 YAML에서 자동 렌더링 |
| P4 | **거래처 추가 = 설정 작성** — 정상 케이스는 코드 0줄 |
| P5 | **검수 화면이 최종 진실** — 사람이 확정한 값이 그대로 전송된다 |
| P6 | **모든 값에 근거를 남긴다** — 규칙 경로 + 원문 위치 |
| P7 | **외부 의존은 교체 가능하게** — LLM 프로바이더, EAI 엔드포인트 |
| P8 | **값이 미정이어도 개발은 멈추지 않는다** — YAML 에 `todo:` 달고 진행 |

---

## 2. 기술 스택

### 2.1 백엔드 — Python 3.11 + FastAPI

| 항목 | 선정 | 근거 |
|---|---|---|
| 언어/프레임워크 | **Python 3.11 + FastAPI** | Anthropic SDK, Pydantic v2, OpenAPI 자동 생성 |
| 검증 | **Pydantic v2** | 추출 스키마 · 마스터 YAML · 전송 페이로드를 동일 엔진으로 |
| 파싱 | **Claude API** (Tool Use 구조화 출력) + 프로바이더 추상화 | §3 |
| PDF 전처리 | **pypdf / pdfplumber** | 텍스트 레이어 판정, 근거 검증용 원문 확보 |
| HTM 전처리 | **BeautifulSoup4 + lxml** | 깨진 HTM 복구 (MSC 발주서가 HTM) |
| HTTP | **httpx + tenacity** | 비동기, 프록시/사설 CA, 백오프 |
| 비동기 실행 | **FastAPI BackgroundTasks** | 파일별 병렬 파싱 + 프론트 폴링 |
| 설정 | **pydantic-settings** | `.env` = 환경 전환의 단일 창구 |

> 큐(Celery/Redis)를 쓰지 않는 이유: 동시 사용자 한 자리 수, 작업이 수십 초. **폴링으로 충분하다.**

### 2.2 프론트엔드 — React 18 + TypeScript + Vite

| 항목 | 선정 | 근거 |
|---|---|---|
| **그리드** | **AG Grid Community (MIT)** ★ | 36컬럼 × 수백 행 가상 스크롤, 인라인 편집, 셀 색상, **Excel 붙여넣기**, `Ctrl+D`, 컬럼 고정/숨김 — 전부 무료 |
| 프레임워크 | React 18 + TS + Vite | 빠른 HMR, 타입으로 계약 고정 |
| 상태 | TanStack Query + Zustand | **서버 상태(폴링)와 편집 상태를 분리** — 폴링이 사용자 입력을 덮지 않게 |
| UI | Mantine | 드롭존 · 모달 · 알림 |

> 그리드는 이 시스템의 본체다. 여기서 자체 구현하면 Excel 붙여넣기·가상 스크롤에서 반드시 막힌다.

### 2.3 저장소 — DB 없이

| 데이터 | 방식 | 경로 |
|---|---|---|
| 거래처 마스터 | YAML (Git) | `masters/customers/{code}.yaml` |
| 참조표 | CSV (Git) | `masters/refs/*.csv` — **없어도 정상 동작** |
| 업로드 원본 | 파일 | `storage/uploads/{batch_id}/` |
| 배치 상태 | JSON | `storage/batches/{batch_id}/batch.json` |
| LLM 응답 캐시 | 파일(해시 키) | `storage/llm_cache/` |
| 전송 감사 로그 | JSONL | `storage/audit/{YYYY-MM}/` |

`batch_id` 는 **서버 내부 식별자**다. 전송 페이로드에 포함하지 않는다.

**DB 승격 트리거**: ① 동시 사용자 5명 초과 ② 이력 검색/통계 요구 ③ 참조표 1,000행 초과 ④ 배치 10,000건 초과

---

## 3. 파싱 아키텍처 (Claude API)

### 3.1 절대 원칙

| 구분 | 내용 |
|---|---|
| ✅ **LLM에게 시킴 (읽기)** | PO번호, 발주일, 납기일, 출하처 **원문 텍스트**, 품번, 품명, 수량, 단가, 통화, 브랜드 **원문 문구** |
| ❌ **절대 안 시킴 (판단)** | ZBRAND(38/127/205…), KUNNR2(319677…), ZPKRE2 비고, ZSHCO(A/L), VSART, 참조표 조회, 날짜 형식 변환 |

> LLM이 "HARRISBURG"를 읽으면 → `KUNNR2=319677` 은 **결정표**가 정한다.
> SAP 코드가 틀리면 오더가 잘못 생성되므로 재현성·감사·즉시 반영이 필요하다.

### 3.2 파이프라인

```
거래처 선택 → 파일 업로드 (N개)
  ┌─ 파일별 병렬 ────────────────────────────────────────────┐
  │ ① 전처리    HTM: BS4 정리 → 텍스트 / PDF: 레이어 판정    │
  │ ② 추출      공통 프롬프트(캐시) + 거래처 hints + Tool Use │
  │ ③ 근거 검증  evidence 원문 대조 · 합계 교차검증           │
  │      ▼ RawPO (원문 값만)                                  │
  │ ④ 규칙엔진   SCHEMA.md §2 의 7단계 (분할·결정표·규칙·필드) │
  │      ▼ SapRow[] (전송 필드 × 품목 수)                     │
  └──────────────────────────────────────────────────────────┘
 ⑤ 전 파일 행 병합 → 통합 그리드 (파일 출처는 `_file` 메타로 유지)
 ⑥ 검증 → issues[] (🔴/🟡)
```

④의 상세는 **`masters/SCHEMA.md` §2**. 이 문서에 다시 쓰지 않는다.

### 3.3 LLM 호출 설계

| 항목 | 설정 |
|---|---|
| 출력 강제 | **Tool Use** (`extract_purchase_order` 단일 툴, `tool_choice` 고정) |
| temperature | **0** |
| 모델 | 역할 별칭(`extract` / `extract_fallback`) → 실제 ID는 `.env` 주입 |
| 프롬프트 캐싱 | 공통 시스템 프롬프트 + 스키마 캐시, 거래처 힌트만 가변 |
| 페이지 | `extraction.page_limit` 초과 시 청크 분할 후 라인 병합 |
| 응답 캐시 | `sha256(파일) + 프롬프트버전 + 거래처 + 모델ID` |
| 병렬 | 파일 단위 동시 실행 (`LLM_MAX_CONCURRENCY`) |
| 재시도 | 120s 타임아웃, 429·5xx만 3회 백오프 |

**추출 스키마의 키 이름은 `masters/SCHEMA.md` §3.1 표준 키를 따른다.**
모든 값은 `{value, evidence, page, confidence}` 4종 세트를 강제한다.
`evidence` 는 원문에서 **그대로 복사한 문자열**이어야 한다.

> ★ 헤더성 값(출하처·브랜드·납기)은 **품목마다 다를 수 있으므로** line 레벨에도 같은 키를 둔다.
> line 값이 비면 header 값으로 폴백한다 (`fallback_source`).

### 3.4 환각 차단 4중 장치 ★

| # | 장치 | 동작 |
|---|---|---|
| 1 | **근거 그라운딩** | `evidence` 가 실제 원문에 있는지 코드로 대조. 없으면 🔴 |
| 2 | **합계 교차검증** | 문서 기재 합계(행수/수량/금액)와 산술 대조 → 불일치 시 🔴 "라인 누락 가능" |
| 3 | **신뢰도 임계** | `confidence < 0.9` → 🟡, 필수 필드 `< 0.7` → 🔴 |
| 4 | **사람 검수** | 위 3개를 통과해도 전송 전 반드시 검수 |

### 3.5 LLM 프로바이더 추상화 (사내 계정 전환)

```python
class LLMProvider(Protocol):
    def extract(self, *, system, tools, content, model_alias, max_tokens) -> ToolCallResult: ...
    def health(self) -> ProviderHealth: ...
# anthropic_direct / bedrock / vertex / gateway / mock
```

```bash
LLM_PROVIDER=anthropic     # anthropic | bedrock | vertex | gateway | mock
LLM_API_KEY=...            # ← 사내 계정 키로 교체하는 지점
LLM_BASE_URL=
LLM_MODEL_EXTRACT=...      # 역할 별칭 → 실제 모델 ID
LLM_MODEL_FALLBACK=...
HTTPS_PROXY=               # 사내 프록시
REQUESTS_CA_BUNDLE=        # 사내 SSL 검사 장비 대응
LLM_MAX_CONCURRENCY=4
LLM_PROMPT_VERSION=v1
```

| 전환 시 체크 | 내용 |
|---|---|
| `.env` 교체 | `LLM_API_KEY`, `LLM_MODEL_*` |
| 방화벽 | 사내 서버 → 인터넷 아웃바운드 허용. **폐쇄망이면 gateway/bedrock 전환** |
| 프록시/CA | 사내 SSL 검사 장비가 있으면 인증서 번들 지정 |
| **골든 테스트 전량 실행** ★ | 모델이 바뀌면 추출 정확도가 달라진다 |

> `LLM_PROVIDER=mock` — 저장된 응답 재생. **프론트 개발·CI는 API 키 없이 비용 0.**

---

## 4. 규칙 마스터 — 결론만

| 후보 | 판정 |
|---|---|
| 코드 하드코딩 | ✗ 배포 없이 변경 불가, 거래처 50곳에서 if문 지옥 |
| **YAML 마스터 + Git 리뷰 + 스키마 검증** | ✅ **채택** — 결정표 표현, diff 리뷰, 화면 자동 렌더링 |
| Excel/Sheets 마스터 | △ 단순 룩업표(참조표)만 CSV로 |
| DB | 보류 (§2.3 승격 트리거) |
| 관리 UI | **현재 불필요** — 판단 기준은 `masters/SCHEMA.md` §6.1, 설계안은 `master-admin.md`(D6 보류) |

**스키마 정의 · 파이프라인 · 프리미티브 · 신규 거래처 추가 절차는 전부 `masters/SCHEMA.md`.**
거래처 3곳의 실제 규칙 값은 `masters/customers/{msc,kl,ygjp}.yaml` 이 원본이며,
기존 POC 로직과의 대조 근거는 `samples/PO변환_비즈니스로직_명세서.md` 다.

---

## 5. 전송 (EAI)

```
POST {EAI_ENDPOINT}
Content-Type: application/json; charset=utf-8
{ "rows": [ { <전송 필드 전량>, ... } ] }
```

| 규약 | 내용 |
|---|---|
| 구조 | **`rows` 배열만.** 1행 = 1품목, **`_base` 의 전송 필드 전량 포함**(현재 36) |
| 필드 수 | **코드에 하드코딩 금지.** `_base/sap_defaults.yaml` 이 유일한 원천 |
| 다중 파일 | 전 파일의 행이 같은 배열에 병합. 파일 구분자 없음 (`BSTKD` 로 구분) |
| 날짜 | `"YYYYMMDD"` 문자열 |
| 수량/금액 | **문자열 decimal** (`"25.000"`) — 부동소수 오차 방지 |
| 코드값 | 문자열, 앞자리 0 보존 (`"04"`, `"000010"`) |
| 빈 값 | `""` (null 미사용) |
| 최상위 형태 | `PAYLOAD_ROOT=rows|array` 설정으로 전환 가능 |

| 정책 | 내용 |
|---|---|
| 주소 | 개발 `https://eai-dev.yg1.solutions:5443/po2sap/order` · 운영 `https://eai-prd…` **`.env` 만 교체** |
| 전송 계층 | **HTTPS 강제.** 평문 http 는 루프백(모의 서버)에서만 허용 |
| 인증 | **없음** (사내망). `EAI_AUTH_MODE=none|apikey|basic` 설정만 유지 |
| 멱등키 | **없음** — 중복 전송 허용 (SAP에서 덮어씀) |
| 전송 단위 | **배치 전체 일괄** |
| 재시도 | 5xx/타임아웃 3회 백오프 → 실패 시 [재전송] |
| 대용량 | `EAI_MAX_ROWS_PER_REQUEST` (기본 무제한) |

응답 형태와 상태 전이는 `contracts/api-contract.md` §7.

---

## 6. 검증 (전송 차단 기준)

| 종류 | 판정 | 예 |
|---|---|---|
| 필수값 누락 | 🔴 | `fields.*.required: true` 인 필드가 빈 값 |
| 규칙/결정표 매칭 실패 | 🔴 | `on_no_match.action: error` |
| 형식 오류 | 🔴 | 날짜 파싱 실패, 수량 비숫자 |
| 길이 초과 | 🔴 | `field_specs.*.max_len` |
| 합계 불일치 | 🔴 | 문서 기재 합계 ≠ 추출 합계 |
| 참조표 미등록 | 🟡 | `on_no_match.action: warn` |
| 낮은 신뢰도 | 🟡 | `confidence < 0.9` |

**전 파일 통틀어 🔴 0건이어야 [전체 전송] 활성화.**

---

## 7. 디렉터리 구조

```
po2sap/
├── README.md               ← 진입점 · 문서 지도
├── NEXT.md                 ← 현재 상태 · 다음 할 일
├── design.md               ← 이 문서 (기술 설계)
├── process.md              ← 업무 흐름 · 화면
├── CONTRIBUTING.md         ← Git · 브랜치 · CI
├── master-admin.md         ← ❄ D6 보류 (마스터 관리 화면 설계)
│
├── masters/                ★ 규칙의 단일 원천
│   ├── SCHEMA.md             스키마 정의 = 백엔드 구현 명세
│   ├── _base/sap_defaults.yaml
│   ├── customers/{msc,kl,ygjp,_template}.yaml
│   └── refs/*.csv
│
├── contracts/              ★ 백엔드↔프론트 유일 접점
│   ├── api-contract.md
│   └── examples/*.json       프론트 목 데이터
│
├── backend/app/
│   ├── main.py  config.py
│   ├── api/{routes_masters,routes_batch,routes_send}.py
│   ├── domain/models.py                    RawPO / SapRow / Batch
│   ├── extraction/                         [D1 완료]
│   │   ├── preprocess.py  schema_builder.py  prompt.py  grounding.py
│   │   ├── extractor.py
│   │   └── providers/{base,anthropic_direct,mock,cache,factory}.py
│   ├── masters/loader.py                   [D1 완료]
│   ├── rules/                              [D2] schema · engine · primitives
│   │   ├── decision_table.py  expr.py  reftable.py
│   │   └── preview.py                      YAML → 규칙 카드 생성
│   ├── mapping/row_builder.py              [D2] 전송 필드 행 생성
│   ├── validation/validator.py             [D2]
│   ├── transport/{eai_client,payload}.py    [D4]
│   └── storage/{batch_repo,audit_log}.py
├── backend/tests/{fixtures,golden}/
│
├── frontend/src/                           [D3]
│   ├── pages/{UploadPage,ReviewPage}.tsx
│   ├── components/{CustomerPicker,RulePreviewCard,FileDropzone,
│   │               SapGrid,IssuePanel,SendModal}.tsx
│   └── types/sapRow.ts
│
├── scripts/{parse_one,validate_masters,mock_eai_server}.py
├── samples/                ← 대외비. Git 제외
└── storage/                ← Git 제외
```

---

## 8. 배포 / 환경

| 환경 | LLM | EAI | 용도 |
|---|---|---|---|
| local | `mock` | 모의 서버 | 프론트·규칙 개발 (비용 0) |
| dev | 개발용 키 | 모의 서버 | 파싱 튜닝 |
| **사내 서버** | 사내 계정 | 실 EAI | UAT → 운영 |

**환경 차이는 `.env` 뿐. 코드·이미지는 동일.**
이관 절차: 배포 → `.env` 작성 → `/api/health` 확인 → **골든 테스트 전량 실행** → 병행 검증 → 전환

| 항목 | 방침 |
|---|---|
| 배포 | Docker Compose (backend + nginx) / Windows면 uvicorn + NSSM |
| 시크릿 | `.env` Git 제외 |
| 로그 | 구조화 JSON. **원문·단가 미기록** (감사 레코드는 아래 §8.1) |
| 보존 | 원본 1년 / 배치 1년 / 감사 JSONL 5년 |
| 인증 | 1차 사내망(무인증) → 2차 JWT/SSO |

### 8.1 감사 레코드 — `storage/audit/{YYYY-MM}/send.jsonl`

**한 줄 = 전송 시도 1회.** 재시도로 성공해도 시도 횟수가 그대로 남는다.

```json
{"ts":"2026-09-15T12:03:11+09:00","batch_id":"b_20260915_0001","customer":"MSC",
 "action":"send","chunk":"1/1","endpoint":"https://eai-dev…/po2sap/order",
 "auth_mode":"none","verify_tls":true,"row_count":49,
 "orders":["7988114(ELKHART)","7988114(RENO)"],
 "payload_sha256":"c9c32c…","attempts":1,"http_status":200,"duration_ms":412,
 "result":"ok","message":"전송되었습니다.","response_excerpt":"{\"result\":\"OK\"}"}
```

| 키 | 남기는 이유 |
|---|---|
| `action` | `send` / `resend` — 중복 적재 가능성을 사후에 되짚는다 |
| `orders` | `BSTKD` 목록. **오더를 식별할 키만** 남긴다 |
| `payload_sha256` | 같은 내용을 보냈는지 대조. 값 자체는 남기지 않는다 |
| `verify_tls` · `auth_mode` | 어떤 보안 설정으로 나갔는지 |
| `response_excerpt` | EAI 응답 규격이 확정되지 않아 **원문 발췌를 남긴다.** 규격을 정하는 근거가 된다 |

**품번·품명·단가·금액은 남기지 않는다.** 되짚기에 필요한 것은 오더 키와 해시뿐이고,
값까지 남기면 5년 보존되는 파일이 그대로 대외비가 된다.

---

## 9. 테스트 & 거버넌스

| 종류 | 내용 |
|---|---|
| **규칙 스펙 테스트** ★ | 마스터의 모든 매핑 행 전수 검증 |
| 결정표 정합성 | 도달 불가 행 · 중복 조건 · 기본행 누락 (`validate_masters.py`) |
| 필드 커버리지 | 거래처별 전송 필드 전량 선언 — **CI 실패 조건** |
| **골든 테스트** ★ | 샘플 → 기대 행 고정 비교. 프롬프트·모델·계정 변경 시 회귀 검출 |
| 다중 파일 병합 | 파일 순서 · 행번호 · POSEX 재부여 |
| 오프라인 | `LLM_PROVIDER=mock` → CI 비용 0 |
| 병행 검증 | 초기 2주 기존 운영 결과지(`samples/MSC/*.csv`)와 자동 diff |

**거버넌스**: 거래처별 `meta.owner` 지정 / 규칙 변경은 PR + owner 승인 / Git 이력 = 규칙 변경 대장

---

## 10. 미확정 항목

`NEXT.md §4` 에서 관리한다. **이 문서에 중복 기재하지 않는다.**
공통 원칙: 미확정 값은 YAML 에 `todo:` 를 달고 개발을 계속한다.
