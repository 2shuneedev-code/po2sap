# 다음에 이어서 하기

> 최종 갱신 2026-09-11 · 설계 완료 · **문서 정리 완료** · 구현 착수 직전
> **재개할 때 이 파일부터 읽으면 된다.**

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
