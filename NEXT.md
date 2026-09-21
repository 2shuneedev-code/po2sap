# 다음에 이어서 하기

> 최종 갱신 2026-09-21 · **§2-A 구조 단순화 요구사항이 최우선이다**
> **재개할 때 이 파일부터 읽으면 된다.** 아래 §1 의 진척 표기는 2026-09-11
> 시점이라 낡았다 — 백엔드·프론트·전송은 그 뒤로 구현이 끝났다 (CLAUDE.md §4).

---

## 1. 지금 어디까지 왔나

```
[설계]      ██████████ 완료
[문서정리]  ██████████ 완료  (낡은 33필드/MSC=PDF/분할없음 기술 전량 수정)
[Git]       ██████████ init · 초기커밋 · remote · developer 브랜치
[백엔드 D1] ████████░░ 추출 파이프라인만 (규칙엔진 없음)
[백엔드 D2] ░░░░░░░░░░ 미착수  ← 여기부터
[프론트]    ░░░░░░░░░░ 미착수  ← 병렬로 여기부터
```

현재 브랜치 **`developer`** · remote `github.com/2shuneedev-code/po2sap.git`
초기 커밋 `19795dc` — 추적 파일 49개. **`samples/` 는 2개만 추적됨(정상, 2026-09-11 검증).**

### 완료된 산출물

| 파일 | 역할 |
|---|---|
| `masters/SCHEMA.md` ★ | **규칙 관리 아키텍처 = 백엔드 구현 명세서** |
| `masters/_base/sap_defaults.yaml` | 공통 고정값 + 전송 필드 스펙 (현재 36) |
| `masters/customers/{msc,kl,ygjp,_template}.yaml` | 거래처 3곳 규칙 전량 선언 |
| `contracts/api-contract.md` ★ | **백엔드↔프론트 유일한 접점** |
| `contracts/examples/*.json` | 프론트용 목 데이터 5종 |
| `design.md` v1.0 | 기술 스택 · 아키텍처 · 파싱 · 디렉토리 · 배포 |
| `process.md` v1.0 | 업무 흐름 · **화면 정의(프론트 명세)** |
| `README.md` | 진입점 · 트랙별 필독 파일 · SSOT 규칙 |
| `CONTRIBUTING.md` | Git · 브랜치 · CI · Codespaces |
| `backend/app/{extraction,masters,domain}` | D1 코드 |

### 개발자가 읽을 파일 (이게 전부)

```
공통    NEXT.md → design.md
백엔드  masters/SCHEMA.md ★  +  masters/customers/*.yaml
프론트  contracts/api-contract.md ★  +  contracts/examples/*.json  +  process.md §4
```

**읽지 말 것**: `rules.md`(폐기) · `master-admin.md`(D6 보류)

---

## 2. 확정된 결정 (다시 논의하지 말 것)

| 항목 | 결정 |
|---|---|
| 파일 형식 | MSC=**HTM**, KL=**PDF**, YGJP=PDF. **업로드 차단 안 함** (안내만) |
| 품번 | `Your Item Number` → **MATNR** / `Our Item Number` → 거래처품번(참조표 키) |
| KDMAT | **범위 제외** (양식에 없음) |
| 전송 필드 | **36개** (기존 33 + IHREZ_E · VGBEL · VGPOS). 나중에 축소 예정. **개수 하드코딩 금지** |
| 공통 고정값 | AUART=`ZEXP` · VKORG=`1000` · VTWEG=`""` · KUNNR1=KUNNR3=거래처코드 |
| BSTKD | `{PO번호}({출하처도시})` — 출하처 없으면 PO번호만 |
| MSC 분할 | **1 Shipment 블록 = 1 오더.** 화면은 한 그리드 통합, BSTKD·KUNNR2 만 다름 |
| ZPKRE1/2·EMPST | 코드값 아님. **자유 텍스트 비고** (예: `"C,Blue RING"`) |
| 미확정 값 | YAML 에 `todo:` 달고 **그냥 진행.** 값 때문에 개발 멈추지 않는다 |
| MSC_REF | `optional: true` 슬롯. **파일 없어도 정상 동작** |
| 관리 UI | **현재 불필요.** 도입 기준은 `masters/SCHEMA.md` §6.1 |
| 진행 방식 | 백엔드/프론트 **병렬**. 접점은 `contracts/` 뿐 |

---

## 2-A. 구조 단순화 요구사항 (2026-09-21 사장님 지시) ★ 최우선

> **아키텍트가 먼저 읽고 설계를 갱신한다.** 아래는 사장님이 말씀하신 내용
> 그대로이며, 해석·추측을 덧붙이지 않았다. 판단이 필요한 자리는 §2-B 에 모았다.

### ① 고객–브랜드 마스터

- **별도 CSV 로 관리 — 현행 유지** (`masters/refs/brand_keys.csv` 계열)
- 그 고객의 브랜드가 **1개면** `ZBRAND` 에 **기본값으로 자동 표시**
- 브랜드가 **2개 이상이면 공란**, 검수 화면에서 **드롭다운으로 선택**한다.
  드롭다운에는 **그 고객의 브랜드만** 뜬다
- 그 밖에 별도 로직이 가능한 곳(MSC 처럼)은 **별도 로직으로 관리 — 이게 예외다**

> 지금은 원문 문구 → 코드 대조(`csv_map`)가 **기본**이고 그게 안 맞으면 막혔다.
> 앞으로는 **고객당 브랜드 수**가 기본 판정이고, 문구 대조는 예외 쪽으로 간다.

### ② 고객–shipping type–shipping condition 마스터

- **별도 CSV 로 관리** (브랜드와 같은 방식)
- **1 : 1 : 1 구조**
- 마스터에 값이 없으면 **공란으로 둔다 (수기 입력 예정)** — 추측해 채우지 않는다

### ③ 엑셀 템플릿 = **전송 필드 목록의 원천** (산출물이 아니다) ★

2026-09-21 확인된 내용:

- **EAI 전송(HTTPS/JSON)은 무조건 한다.** 종착점은 그대로다
- **엑셀 파일로 받는 기능은 필요 없다.** 내보내기 버튼 만들지 말 것
- **특정 경로에 `SALES ORDER` 템플릿을 저장**해 두고 불러온다
- 템플릿의 **2행에 SAP 필드명**이 있다. **화면의 스프레드시트 컬럼이 이걸 바라본다**
- 그 **필드명 + 값**으로 JSON 을 만들어 HTTPS 로 전송한다
- **필드명으로 움직인다** (열 위치가 아니라)
- **조건이 없으면 그냥 공란으로 둔다**
- 현행 36개에서 미사용·불필요를 빼면 **약 15개**가 된다
- 화면 스프레드시트에서 **복사·붙여넣기가 되어야 한다**

> 즉 엑셀은 **출력물이 아니라 입력물**이다. 현업이 템플릿을 고치면
> 화면 컬럼과 전송 JSON 이 코드 수정 없이 따라 바뀌는 구조를 원하신다.

### ④ KUNNR1 · KUNNR2 · KUNNR3

- 셋 다 **기본값은 `KUNNR` 과 동일한 값**
- **단 조건이 생기면 그것을 따른다** (MSC 의 출하처 분기처럼)

---

## 2-C. 범위 축소 (2026-09-21 2차 지시) ★★ **§2-A·§2-B 보다 이것이 우선**

> 사장님 말씀: **"우리가 첨에 넘 거창하게 잡았어"**
> `design-simplification.md` 의 상당 부분이 이 지시로 **범위 밖**이 된다.
> 착수 전에 이 절부터 읽고, 설계안은 참고만 한다.

### 새 흐름

```
SALES ORDER 템플릿 (현업 확정본을 사장님이 templates 폴더에 올린다)
   1행 = 디스크립션
   2행 = SAP 필드명
        ↓
   Claude API 가 **1행·2행을 보고 발주서 값을 유사한 필드에 매핑**한다
        ↓
   규칙엔진은 **아래 6개만** 변환한다
        ↓
   스프레드시트에 깔아준다 → 검수 → JSON → HTTPS → EAI
```

### 규칙엔진이 담당하는 것 — **이게 전부다**

| 필드 | 근거 |
|---|---|
| `KUNNR1` · `KUNNR2` · `KUNNR3` | 기본은 `KUNNR` 과 동일, 조건 있으면 그것 (§2-A ④) |
| 운송수단 (`VSART`) | `refs/shipping.csv` 조회 |
| 출하조건 (`ZSHCO`) | `refs/shipping.csv` 조회 |
| `BSTKD` | 고객발주번호 (2026-09-21 확인 — `BSTNK` 이 아니라 `BSTKD` 다) |
| `POSEX` | PO 품목번호 |

브랜드(`ZBRAND`)는 규칙이 아니라 **마스터**다 — 1개면 기본값, 2개 이상이면
공란 + 드롭다운 (§2-A ①).

**나머지 필드는 전부 Claude 가 템플릿 1행·2행을 보고 채운다.**
거래처 YAML 에 필드별 `from: doc, path: ...` 를 일일이 선언하지 않는다.

### 이 지시가 P1 을 어디까지 푸는가 — **분명히 해 둘 것**

`CLAUDE.md` P1 은 "Claude 는 원문 값만 추출하고, 매핑은 규칙엔진이 한다"였다.
이제 **필드 매칭은 Claude 가 한다.** 다만 경계는 그대로다:

- Claude 가 하는 것: **"이 값이 어느 칸에 들어가는가"** (템플릿이 칸 이름과
  설명을 주므로 자연어 매칭이다)
- 규칙엔진이 하는 것: **코드 결정** — 위 표의 6개 + 브랜드 마스터 조회.
  SAP 코드를 Claude 가 추측해 만드는 일은 **여전히 없다**
- 안전망: **검수 화면이 최종 진실(P5)** 이고, 각 값에 근거(evidence)가 남는다

P1 문장을 이 경계에 맞게 고쳐야 한다. **architect 가 CLAUDE.md §1 교체문을 쓴다.**

### `design-simplification.md` 에서 범위 밖이 되는 것

- `profiles/standard.yaml` 의 필드별 `from/path` 선언 대부분 — **지운다**
- SSOT 3분할은 유지하되 훨씬 얇아진다 (거래처 YAML 이 맡는 게 6개뿐)
- 필드 36 → 15 논의 — **하지 않는다.** 현업이 템플릿에서 정하고 사장님이 올린다
- `csv_choice`(브랜드) · `refs/shipping.csv` 는 **그대로 유효**

---

## 2-B. 아키텍트가 설계에서 풀어야 할 것

> ✅ **해결됨 (2026-09-21)** — "엑셀이 산출물인가"는 아니다. **전송은 무조건
> EAI(HTTPS/JSON)** 이고, 엑셀 템플릿은 **필드 목록의 원천**이다. §2-A ③ 참조.

1. **SSOT 충돌을 어떻게 풀 것인가.** CLAUDE.md §2 는 전송 필드 목록·개수·
   max_len 의 유일한 원천을 `_base/sap_defaults.yaml` 로 못 박았는데, 이제
   **필드 목록과 순서는 템플릿 2행**이 정한다. 권고안:
   · 템플릿 2행 = **어떤 필드를 어떤 순서로** 보낼지
   · `sap_defaults.yaml` = 각 필드의 **규격**(max_len · required · format)
   · 템플릿에만 있고 YAML 에 없는 필드 → 경고. YAML 에만 있는 필드 → 안 보냄
   결정하면 **CLAUDE.md §2 표를 같이 고친다.**
2. **템플릿을 직접 읽을 것인가, 가져오기 스크립트를 둘 것인가.** 현업이 고치면
   바로 반영되길 원하시므로 직접 읽기가 의도에 가깝다. 다만 템플릿이 깨지면
   화면 전체가 멎으므로 **읽기 실패 시 동작**을 정해야 한다.
3. **템플릿 위치와 Git 포함 여부.** 입력물이므로 `masters/templates/` 같은
   추적 대상이 자연스럽다 (생성물인 거래처마스터.xlsx 와는 성격이 다르다).
4. **브랜드 1개 자동 표시의 "1개" 기준.** `brand_master.csv` 에서 그 `kunnr`
   행이 1건이면인지, 매핑된 것이 1건이면인지.
5. **스프레드시트 복사·붙여넣기** — 2026-09-21 브라우저로 확인한 결과:
   · **복사는 된다 (확인됨).** 범위 선택 → Ctrl+C 하면 탭 구분·여러 행으로
     나온다 — 엑셀에 그대로 붙여넣어지는 형식이다
   · **붙여넣기는 판정하지 못했다.** 두 가지 방법으로 시도했으나 표에 반영되지
     않았다. 다만 **헤드리스 브라우저는 붙여넣기 시험 자체가 신뢰할 수 없어**
     앱 문제인지 시험 문제인지 구분이 안 된다. **안 된다고 단정하지 않는다** —
     실제 브라우저에서 사람이 셀 클릭 후 Ctrl+V 로 1초면 판가름난다

---

## 3. 다음에 할 일 (순서대로)

### ① 문서 정리 커밋 — 지금 바로

> ⚠ 2026-09-11 에 Git GUI 의 "변경 취소(Discard)" 로 이 정리가 한 번 날아갔다.
> **작업 후에는 즉시 커밋한다.**

```powershell
cd C:\vibe_coding\po2sap
git add README.md NEXT.md design.md process.md rules.md
git commit -m "docs: 낡은 설계문서 정리 - SSOT 확립, MSC=HTM, 오더 분할 반영"
git push
```

### ② 두 트랙 동시 착수

**백엔드** `feat/be-rules` — 명세는 `masters/SCHEMA.md`
```
1. backend/app/rules/schema.py         SCHEMA.md §4 → Pydantic 모델
2. backend/app/rules/engine.py         SCHEMA.md §2 의 7단계 파이프라인
3. backend/app/rules/{decision_table,primitives,expr,reftable}.py
4. backend/app/mapping/row_builder.py  전송 필드 행 생성 (_base 기준)
5. backend/app/validation/validator.py
6. scripts/validate_masters.py         SCHEMA.md §7 검증 9종
7. backend/app/api/routes_batch.py     contracts §4~7
```

**프론트** `feat/fe-grid` — 명세는 `contracts/api-contract.md`, 화면은 `process.md` §4
```
1. Vite + React + TS 셋업 (VITE_API_MODE=mock 이면 examples/ 직접 import)
2. CustomerPicker + RulePreviewCard   ← preview_msc.json 그대로 렌더
3. FileDropzone (다중 업로드)
4. SapGrid  ← batch_msc.json.  전 컬럼 · pinned · hidden · 전 셀 편집
              Ctrl+Z · Ctrl+D · 엑셀 붙여넣기 · 열 일괄채우기
5. IssuePanel (🔴🟡🔵) + 합계바 + 파일/그룹 필터
6. SendModal (전송 확인 → 결과)
```

### ③ 관통 확인
모의 EAI 서버 + 실제 파싱 1회 → 결과가 `storage/llm_cache/` 에 저장되면
이후 `LLM_PROVIDER=mock` 으로 무료·오프라인 반복 가능.

---

## 4. Git 안전 수칙

| 수칙 | 명령 |
|---|---|
| **push 전 대외비 확인** | `git ls-files samples/` → **2개**(`.gitignore`, `README.md`) 가 아니면 중단 |
| 작업 후 즉시 커밋 | GUI 의 "Discard/변경 취소" 는 **복구 불가** |
| 문서 소유 | `design.md` `process.md` `masters/SCHEMA.md` = architect. 코드는 트랙별 |
| `contracts/` 변경 | 양쪽 합의 후 **단독 PR** |

> 상세는 `CONTRIBUTING.md`.

---

## 5. 미결 (답 오면 YAML 한 줄씩 수정, 개발은 무관)

| # | 항목 | 영향 |
|---|---|---|
| 1 | MSC_REF 참조표 실물 | MSC ZPKRE2 추가비고. 없어도 기본값으로 동작 |
| 2 | KL 의 KUNNR2 · ZSHCO | `kl.yaml` 의 `todo:` |
| 3 | YGJP 브랜드 448/449/450 원문 구분 키 | `ygjp.yaml` 의 `todo:` |
| 4 | EAI 엔드포인트 URL · 최상위 형태 | 모의 서버로 진행 가능 |
| 5 | 현업 협의 후 불필요 필드 제거 | `_base/sap_defaults.yaml` 만 수정 |
| 6 | 확장 거래처 명단·우선순위 (약 20곳) | 2차 |
| 7 | 사내 서버 인터넷 아웃바운드 허용 | 이관 시점 |

---

## 6. 재개할 때 붙여넣을 말

```
NEXT.md 읽고 이어서 진행.
```
