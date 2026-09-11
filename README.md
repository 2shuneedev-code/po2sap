# PO2SAP

발주서(PDF/HTM) → Claude 추출 → 규칙엔진 → 스프레드시트 검수 → EAI(JSON) 전송 → SAP CBO 적재

> **재개 지점: [`NEXT.md`](./NEXT.md)** ← 현재 상태 · 다음 할 일

---

## 📌 개발자는 이 4개만 읽는다

| 순서 | 파일 | 역할 |
|---|---|---|
| 1 | [`NEXT.md`](./NEXT.md) | **지금 어디까지 왔고 다음에 뭘 하는가** · 확정된 결정 · 미결 항목 |
| 2 | [`design.md`](./design.md) | 기술 스택 · 전체 아키텍처 · 파싱 설계 · 디렉토리 · 배포 |
| 3 | [`masters/SCHEMA.md`](./masters/SCHEMA.md) | **백엔드 구현 명세** — 규칙 스키마 · 엔진 7단계 파이프라인 · 검증 규칙 |
| 4 | [`contracts/api-contract.md`](./contracts/api-contract.md) | **프론트 구현 명세** — 엔드포인트 8종 · 요청/응답 전문 |

보조: [`process.md`](./process.md) 화면 정의(프론트 필수) · [`CONTRIBUTING.md`](./CONTRIBUTING.md) Git·브랜치·CI

### 트랙별 필독

| 트랙 | 읽을 것 | 만질 것 |
|---|---|---|
| **백엔드** `feat/be-rules` | `masters/SCHEMA.md` ★ → `design.md` §3·§5·§6 → `masters/customers/*.yaml` → `contracts/api-contract.md` | `backend/**` `masters/**` `scripts/**` |
| **프론트** `feat/fe-grid` | `contracts/api-contract.md` ★ → `contracts/examples/*.json` → `process.md` §4 | `frontend/**` |

`contracts/` 는 **공용**이다. 변경은 양쪽 합의 후 단독 PR.

---

## 🚫 참고하지 말 것 (낡음/보류)

| 파일 | 상태 |
|---|---|
| `rules.md` | ❄ **폐기.** D6에 YAML에서 자동 생성될 예정. 지금은 빈 껍데기 |
| `master-admin.md` | ❄ **보류(D6).** 마스터 관리 화면 설계. 현재 구현 대상 아님 |
| `samples/PO변환_비즈니스로직_명세서.md` | 📎 기존 POC 로직 원본. **대조 근거로만** 참고 (파서 코드는 이식하지 않음) |

> 2026-09-11 정리 완료: `design.md`·`process.md` 의 "33필드 / MSC=PDF / 오더 분할 불필요" 오류는 **모두 수정됐다.**
> 이제 문서 간 모순이 없다. 발견하면 즉시 SSOT 쪽으로 고친다.

---

## 단일 원천(SSOT) 규칙

**같은 내용을 두 곳에 쓰지 않는다.** 어긋나면 오더가 잘못 생성된다.

| 주제 | 유일한 원천 | 다른 문서에서는 |
|---|---|---|
| 전송 필드 목록·개수·한글명·max_len | `masters/_base/sap_defaults.yaml` | "전송 필드 전량"이라고만 쓴다 |
| 공통 SAP 고정값 | `masters/_base/sap_defaults.yaml` | 값을 복사하지 않는다 |
| 거래처별 규칙 값 | `masters/customers/{code}.yaml` | 예시로만 인용 |
| 규칙 스키마·엔진 동작 | `masters/SCHEMA.md` | 참조 링크만 |
| API 요청/응답·상태값 | `contracts/api-contract.md` | 참조 링크만 |
| 진행 상태·일정·미결 | `NEXT.md` | 쓰지 않는다 |

> ⚠ **필드 개수를 코드에 하드코딩 금지.** 36이 34가 되어도 코드·화면은 그대로 동작해야 한다.

---

## 구조

```
masters/                    규칙 (코드 수정 없이 YAML 만 고침)
├── SCHEMA.md ★               스키마 정의 = 백엔드 구현 명세
├── _base/sap_defaults.yaml   공통 고정값 + 전송 필드 스펙
├── customers/*.yaml          거래처 1곳 = 파일 1개 (MSC/KL/YGJP/_template)
└── refs/*.csv                참조표 (없어도 동작)

contracts/ ★                백엔드↔프론트 유일 접점
├── api-contract.md           엔드포인트 8종
└── examples/*.json           프론트용 목 데이터 5종

backend/app/
├── extraction/             Claude 추출 — "읽기"만 담당            [D1 완료]
│   ├── providers/            LLM 추상화 (mock/anthropic/cache)
│   └── grounding.py          환각 차단 · 합계 검증 · 신뢰도
├── masters/                마스터 로더                            [D1 완료]
├── rules/                  규칙엔진                               [미착수]
├── mapping/                전송 필드 행 생성                       [미착수]
├── validation/             검증                                   [미착수]
└── transport/              EAI 전송                               [미착수]

frontend/                   React 18 + TS + Vite + AG Grid         [미착수]
samples/                    실물 발주서 — Git 제외 (대외비)
storage/                    런타임 산출물 — Git 제외
```

**설계 원칙**: Claude 는 원문 값을 **읽기만** 하고, SAP 코드는 `masters/` 의 규칙이
**결정적으로** 정한다. 섞으면 재현성과 감사가 무너진다.

---

## 설치 · 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env

# 전처리만 확인 (LLM 호출 없음 = 무료)
python scripts\parse_one.py <발주서> --customer MSC --text-only

# API 서버
cd backend && uvicorn app.main:app --reload   # → /api/health
```

`.env` 의 `LLM_PROVIDER=mock` 이면 **API 키 없이 · 비용 0 · 오프라인**으로
저장된 응답을 재생한다 (프론트 개발 · CI 용).

사내 서버 이관 시 **코드는 그대로 두고 `.env` 만 교체**한다.
이관 후 `/api/health` 확인 → 골든 테스트 전량 실행.

---

## 진행 상황

- [x] 설계 — 규칙 아키텍처 · API 계약 · 거래처 3곳 YAML · **문서 정리**
- [x] D1 전처리 · Claude 추출 · 환각 차단 · 마스터 로더 · CLI
- [ ] **D2 규칙엔진 · 행 생성 · 검증**  ← 백엔드 트랙
- [ ] **D3 프론트엔드 (거래처 선택 · 규칙 카드 · 통합 그리드)**  ← 프론트 트랙 (병렬)
- [ ] D4 EAI 전송 · 모의 서버 · 결과 모달
- [ ] D5 KL/YGJP 실물 검증 · 데모

상세는 [`NEXT.md`](./NEXT.md).
