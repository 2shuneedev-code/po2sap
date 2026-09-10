# PO2SAP

발주서(PDF/HTM) → Claude 파싱 → 스프레드시트 검수 → EAI(JSON) 전송 → SAP CBO 적재

> **재개 지점: [`NEXT.md`](./NEXT.md)** ← PC 껐다 켠 뒤엔 여기부터

---

## 문서 지도

| 문서 | 내용 | 최신? |
|---|---|---|
| [`NEXT.md`](./NEXT.md) | **현재 상태 · 확정 결정 · 다음 할 일** | ✅ |
| [`masters/SCHEMA.md`](./masters/SCHEMA.md) | **규칙 관리 아키텍처 = 백엔드 구현 명세** | ✅ |
| [`contracts/api-contract.md`](./contracts/api-contract.md) | **백엔드↔프론트 API 계약** | ✅ |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Git · 브랜치 · CI · Codespaces | ✅ |
| [`design.md`](./design.md) | 시스템 설계 (기술스택·파싱·배포) | ⚠ 일부 낡음 |
| [`process.md`](./process.md) | 업무 프로세스 · 화면 정의 | ⚠ 일부 낡음 |
| `samples/PO변환_비즈니스로직_명세서.md` | 기존 POC 로직 명세 (참고 원본) | — |

> ⚠ 표시 문서의 "33필드 / MSC=PDF / 오더 분할 불필요" 기술은 낡았다.
> **`masters/` 와 `contracts/` 가 최신 기준이다.**

---

## 구조

```
masters/                    규칙 (코드 수정 없이 YAML 만 고침)
├── SCHEMA.md                 스키마 정의 = 규칙 관리 아키텍처
├── _base/sap_defaults.yaml   공통 고정값 + 전송 필드 36개
├── customers/*.yaml          거래처 1곳 = 파일 1개 (MSC/KL/YGJP/_template)
└── refs/*.csv                참조표 (없어도 동작)

contracts/                  백엔드↔프론트 접점
├── api-contract.md           엔드포인트 8종
└── examples/*.json           프론트용 목 데이터 5종

backend/app/
├── extraction/             파싱 (Claude) — "읽기"만 담당            [D1 완료]
│   ├── providers/            LLM 추상화 (mock/anthropic/gateway)
│   └── grounding.py          환각 차단 · 합계 검증 · 신뢰도
├── masters/                마스터 로더
├── rules/                  규칙엔진                                 [미착수]
├── mapping/                36필드 행 생성                            [미착수]
└── transport/              EAI 전송                                  [미착수]

frontend/                   React + TS + Vite                        [미착수]
samples/                    실물 발주서 — Git 제외 (대외비)
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

- [x] 설계 — 규칙 아키텍처 · API 계약 · 거래처 3곳 YAML
- [x] D1 전처리 · Claude 추출 · 환각 차단 · 마스터 로더 · CLI
- [ ] **D2 규칙엔진 · 36필드 행 생성 · 검증**  ← 백엔드 트랙
- [ ] **D3 프론트엔드 (거래처 선택 · 규칙 카드 · 36컬럼 그리드)**  ← 프론트 트랙 (병렬)
- [ ] D4 EAI 전송 · 모의 서버 · 결과 모달
- [ ] D5 KL/YGJP 실물 검증 · 데모
