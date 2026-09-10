# 저장소 · 병렬 개발 가이드

> 백엔드 / 프론트엔드 **두 트랙을 동시에** 굴리기 위한 규칙.
> 접점은 `contracts/api-contract.md` 하나뿐이다.

---

## 1. 저장소 초기화

```powershell
cd C:\vibe_coding\po2sap
git init -b main
git add .
git commit -m "chore: 설계 · 규칙 마스터 · API 계약 초기 커밋"
git remote add origin <원격 URL>
git push -u origin main
```

### 1.1 커밋되는 것 / 안 되는 것

| | 대상 |
|---|---|
| ✅ 커밋 | `design.md` `process.md` `masters/` `contracts/` `backend/` `frontend/` `scripts/` `.env.example` |
| ✅ 커밋 | `backend/tests/fixtures/` — **마스킹된** 샘플 + LLM 응답 캐시 |
| ❌ 제외 | `.env` (API 키·EAI URL) |
| ❌ 제외 | `samples/` **전부** — 실물 발주서·거래처 단가는 대외비 |
| ❌ 제외 | `storage/` `node_modules/` `.venv/` |

> **`samples/` 를 절대 커밋하지 마라.** 한 번 올라가면 이력에서 지우기 어렵다.
> 푸시 전 `git status` 로 확인할 것.

### 1.2 원격에서도 돌아가게 하려면 — 마스킹 픽스처

`samples/` 를 빼면 원격/CI 에서 테스트할 재료가 없다. 그래서 아래를 커밋한다.

```
backend/tests/
├── fixtures/
│   ├── msc/P7988114.masked.htm      단가·담당자명·주소를 가린 발주서
│   ├── kl/4507628839.masked.txt
│   └── llm_cache/<hash>.json        Claude 응답 캐시 (LLM_PROVIDER=mock 재생용)
└── golden/
    └── msc_P7988114.json            기대 결과 36필드 행
```

- 마스킹 대상: **단가 · 금액 · 담당자명 · 전화 · 이메일 · 상세주소**
- 유지 대상: 품번 · 수량 · 브랜드 · 창고명 (규칙 검증에 필요)
- `LLM_PROVIDER=mock` 이면 **API 키 없이 · 비용 0 · 오프라인**으로 전량 재생된다

---

## 2. 브랜치 · 충돌 방지

```
main                 항상 동작하는 상태
├── feat/be-rules    백엔드 트랙
└── feat/fe-grid     프론트 트랙
```

**파일 소유권을 나눈다. 남의 영역을 건드리지 않으면 충돌이 안 난다.**

| 영역 | 소유 |
|---|---|
| `backend/**` `masters/**` `scripts/**` | 백엔드 트랙 |
| `frontend/**` | 프론트 트랙 |
| `contracts/**` | **공용 — 양쪽 합의 후 별도 PR** |
| `design.md` `process.md` `masters/SCHEMA.md` | architect |

`contracts/` 변경은 반드시 단독 PR 로 올리고 양쪽이 즉시 rebase 한다.

---

## 3. 원격 개발 환경 (로컬 없이)

`.devcontainer/devcontainer.json` 을 두면 **GitHub Codespaces 에서 브라우저만으로** 돌아간다.

```jsonc
{
  "name": "po2sap",
  "image": "mcr.microsoft.com/devcontainers/python:3.11",
  "features": { "ghcr.io/devcontainers/features/node:1": { "version": "20" } },
  "postCreateCommand": "pip install -r backend/requirements.txt && cd frontend && npm install",
  "forwardPorts": [8000, 5173],
  "secrets": { "LLM_API_KEY": {}, "EAI_ENDPOINT": {} }
}
```

- 비밀은 **Codespaces Secrets** 에 넣는다. `.env` 를 커밋하지 않는다
- `LLM_PROVIDER=mock` 이면 키 없이도 전 기능이 돈다 (캐시 재생)

---

## 4. CI (푸시마다 자동)

`.github/workflows/ci.yml`

| 단계 | 내용 | 비용 |
|---|---|---|
| 1 | `python scripts/validate_masters.py` — 스키마·필드 커버리지·todo 리포트 | 0 |
| 2 | `pytest` — 규칙 스펙 · 결정표 정합성 · 골든 테스트 | 0 (mock) |
| 3 | `npm run build` — 프론트 타입체크 + 빌드 | 0 |

**실패 조건**: 전송 필드 미선언 · 없는 규칙 참조 · expr 화이트리스트 위반 · 골든 결과 불일치.

---

## 5. 커밋 규칙

```
feat:  기능        fix:   버그       rules: 거래처 규칙(YAML) 변경
docs:  문서        chore: 설정       test:  테스트
```

**`rules:` 커밋은 본문에 근거를 남긴다.** Git 이력이 곧 규칙 변경 대장이다.

```
rules(MSC): 출하처 RENO 의 ZPKRE2 기본값 O → R

근거: 2026-09-10 물류팀 확인 (요청자 홍길동)
영향: MSC RENO 향 전 오더
```
