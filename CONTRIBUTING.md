# 저장소 · 개발 가이드

> 브랜치 · 커밋 · CI · 원격 환경 규칙.
> 작업 순서와 에이전트 루프는 **`CLAUDE.md`**, 무엇을 만들지는 **`NEXT.md`** 를 본다.
> v2 · 2026-09-11 (브랜치 전략 B 확정 반영)

---

## 1. 커밋되는 것 / 안 되는 것

| | 대상 |
|---|---|
| ✅ 커밋 | `*.md` `masters/` `contracts/` `backend/` `frontend/` `scripts/` `.claude/` `.env.example` |
| ✅ 커밋 | `backend/tests/fixtures/` — **마스킹된** 샘플 + LLM 응답 캐시 |
| ❌ 제외 | `.env` (API 키 · EAI URL) |
| ❌ 제외 | `samples/` **원본 전부** — 실물 발주서 · 거래처 단가는 대외비 |
| ❌ 제외 | `storage/` `node_modules/` `.venv/` |

### 🚨 push 전 필수 확인

```powershell
git ls-files samples/
# → .gitignore, README.md  2개만 나와야 정상. 3개 이상이면 중단.
```

`samples/` 는 한 번 올라가면 이력에서 지우기 어렵다. **습관으로 만들 것.**

### 마스킹 픽스처 — 원격/CI 에서 테스트하려면

`samples/` 를 빼면 CI 에 재료가 없다. 그래서 아래를 커밋한다.

```
backend/tests/
├── fixtures/
│   ├── msc/P7988114.masked.htm      단가·담당자명·주소를 가린 발주서
│   ├── kl/4507628839.masked.txt
│   └── llm_cache/<hash>.json        Claude 응답 캐시 (LLM_PROVIDER=mock 재생용)
└── golden/
    └── msc_P7988114.json            기대 결과 (전송 필드 전량)
```

- 마스킹 대상: **단가 · 금액 · 담당자명 · 전화 · 이메일 · 상세주소**
- 유지 대상: 품번 · 수량 · 브랜드 · 창고명 (규칙 검증에 필요)
- `LLM_PROVIDER=mock` 이면 **API 키 없이 · 비용 0 · 오프라인**으로 전량 재생된다

---

## 2. 브랜치 — 단일 작업 브랜치 (확정)

```
main          항상 동작하는 상태. reviewer 통과분만 들어온다
└── developer   ★ 모든 구현이 여기서 일어난다
```

| 상황 | 명령 |
|---|---|
| 평소 작업 | `developer` 에서 커밋 → `git push` |
| 마일스톤 완료(D2, D3 …) | `git checkout main` → `git merge --ff-only developer` → `git push` → `git checkout developer` |
| main 이 앞서갔을 때 | `git checkout developer` → `git rebase main` |

**왜 단일 브랜치인가**: 작업자가 에이전트 1명이고 작업 단위가 작다.
`feat/*` 를 파생하면 관리 비용만 늘고 얻는 게 없다.
백엔드·프론트를 **동시에 두 명이** 굴리게 되면 그때 `feat/be-*` `feat/fe-*` 로 나눈다.

> ⚠ **GitHub Desktop 주의**
> 브랜치를 전환하면 변경사항을 **조용히 stash** 한다. 파일이 사라졌다고 놀라지 말고
> `git stash list` 부터 확인할 것. (2026-09-11 에 문서 정리본이 이렇게 사라졌다)
> "Discard changes / 변경 취소" 는 **복구 불가**다. 작업 후에는 즉시 커밋한다.

---

## 3. 커밋 규칙

```
feat:  기능        fix:   버그       rules: 거래처 규칙(YAML) 변경
docs:  문서        chore: 설정       test:  테스트
```

**작업 1개 = 커밋 1개.** `NEXT.md §3` 의 번호 하나가 작업 1개다.

**`rules:` 커밋은 본문에 근거를 남긴다.** Git 이력이 곧 규칙 변경 대장이다.

```
rules(MSC): 출하처 RENO 의 ZPKRE2 기본값 O → R

근거: 2026-09-10 물류팀 확인 (요청자 홍길동)
영향: MSC RENO 향 전 오더
```

---

## 4. 파일 소유권

| 영역 | 소유 |
|---|---|
| `backend/**` `frontend/**` `scripts/**` | developer |
| `masters/*.yaml` `masters/refs/**` | developer (규칙 값) — 단 **스키마 변경은 architect** |
| `design.md` `process.md` `masters/SCHEMA.md` `contracts/**` `CLAUDE.md` | **architect** |
| `NEXT.md` | architect (상태 갱신) |

`contracts/` 는 백엔드·프론트 양쪽이 의존한다. 변경하려면 **먼저 문서를 고치고** 양쪽이 따라간다.

---

## 5. CI (푸시마다 자동)

`.github/workflows/ci.yml`

| 단계 | 내용 | 비용 |
|---|---|---|
| 1 | **대외비 검사** — `git ls-files samples/` 가 2개 초과면 실패 | 0 |
| 2 | `python scripts/validate_masters.py` — 스키마 · 필드 커버리지 · `todo` 리포트 | 0 |
| 3 | `pytest` — 규칙 스펙 · 결정표 정합성 · 골든 테스트 | 0 (mock) |
| 4 | **하드코딩 검사** — 거래처명·필드 개수가 코드에 박혔는지 grep | 0 |
| 5 | `npm run build` — 프론트 타입체크 + 빌드 | 0 |

**실패 조건**: 대외비 파일 포함 · 전송 필드 미선언 · 없는 규칙 참조 ·
`expr` 화이트리스트 위반 · 골든 결과 불일치 · 거래처명/필드수 하드코딩.

> 1번과 4번은 로컬 `pre-commit` 훅으로도 걸 수 있으나, 훅은 우회 가능하므로 **CI 가 최종 방어선**이다.

---

## 6. 원격 개발 환경 (로컬 없이)

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
