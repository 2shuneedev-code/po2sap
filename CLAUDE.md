# CLAUDE.md — po2sap 작업 규약

발주서(PDF/HTM) → Claude 추출 → 규칙엔진 → 통합 그리드 검수 → EAI(HTTPS/JSON) 전송 → SAP CBO 적재.

**세션 시작 시 `NEXT.md` → `design.md` 순으로 읽는다.** 백엔드 작업이면 `masters/SCHEMA.md`, 프론트 작업이면 `contracts/api-contract.md`를 추가로 읽는다.

---

## 1. 절대 원칙

| # | 원칙 | 구체적으로 |
|---|---|---|
| P1 | **읽기와 판단의 분리** | Claude는 문서의 **원문 값만** 추출한다. SAP 코드(ZBRAND·KUNNR2·ZSHCO·VSART), 참조표 조회, 날짜 형식 변환은 **규칙엔진이** 결정한다 |
| P2 | **규칙은 데이터, 엔진은 코드** | `backend/` 어디에도 거래처 이름(MSC/KL/YGJP)이 등장하면 안 된다. 분기는 전부 `masters/*.yaml` |
| P3 | **SSOT 단일 기재** | 같은 내용을 두 문서에 쓰지 않는다. 아래 §2 표를 따른다 |
| P4 | **미확정 값은 `todo:`** | 값이 안 정해져도 개발은 멈추지 않는다. YAML에 `todo:` 달고 진행 |
| P5 | **검수 화면이 최종 진실** | 사람이 확정한 값이 그대로 전송된다 |

> P1을 어기면 재현성과 감사가 무너진다. "HARRISBURG"를 읽는 건 LLM, `KUNNR2=319677`을 정하는 건 결정표다.

---

## 2. SSOT — 어느 파일이 진실인가

| 주제 | 유일한 원천 | 다른 곳에서는 |
|---|---|---|
| 전송 필드 목록·개수·max_len | `masters/_base/sap_defaults.yaml` | "전송 필드 전량"이라고만 쓴다 |
| 거래처 공통 필드 매핑 | `masters/profiles/standard.yaml` | 거래처 파일은 **다른 것만** 적는다 |
| 규칙 스키마 · 엔진 7단계 | `masters/SCHEMA.md` | 참조 링크만 |
| **추출 표준 키** | `masters/SCHEMA.md` §3.1 | 코드가 여기에 맞춘다 (반대 아님) |
| 거래처별 규칙 값 | `masters/customers/{code}.yaml` | 예시로만 인용 |
| 브랜드 매핑 (원문 → 코드) | `masters/refs/brand_keys.csv` | YAML에 `entries`로 다시 두지 않는다 |
| API 요청/응답·상태값 | `contracts/api-contract.md` | 참조 링크만 |
| 업무 흐름·화면 정의 | `process.md` §4 | — |
| 진행 상태·일정·미결 | `NEXT.md` | 쓰지 않는다 |

**전송 필드 개수를 코드에 하드코딩하지 않는다.** 현재 36개지만 34가 되어도 코드·화면은 그대로 동작해야 한다.

---

## 3. 명령어

```bash
# 셋업
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cp .env.example .env

# 전처리만 확인 (LLM 호출 없음 = 무료)
python scripts/parse_one.py <발주서> --customer MSC --text-only

# 단건 파싱
python scripts/parse_one.py <발주서> --customer MSC

# API 서버
cd backend && uvicorn app.main:app --reload        # → /api/health

# 마스터 검증 (CI 1단계) — SCHEMA.md §7 의 9종 검사. LLM 호출 없음 = 비용 0
python scripts/validate_masters.py
python scripts/validate_masters.py --customer MSC   # 한 곳만
python scripts/validate_masters.py --quiet          # 오류만

# 테스트 (CI 2단계) — LLM 호출 없음. 픽스처 재생이라 키 불필요
pytest
pytest backend/tests/test_masters.py   # 검증기 역테스트만
ruff check backend scripts
```

`.env`의 `LLM_PROVIDER=mock`이면 API 키 없이·비용 0·오프라인으로 저장된 응답을 재생한다.
**환경 차이는 `.env`뿐이다.** 사내 이관 시 코드는 그대로 두고 `.env`만 교체한다.

---

## 4. 구조와 구현 상태

```
masters/          ★ 규칙의 단일 원천 (코드 수정 없이 YAML만 고침)
├── _base/          전송 필드 스펙 36개 + 공통 고정값
├── profiles/       standard.yaml — 대부분의 거래처가 쓰는 필드 매핑
├── customers/      거래처 1곳 = 파일 1개. 프로필과 **다른 것만**
└── refs/           참조표 CSV
    ├── brand_master.csv   SAP 원본 430곳/1,207행 (읽기 전용, 재추출로 교체)
    └── brand_keys.csv     발주서 원문 → 브랜드 코드 (사람이 채운다)
contracts/        ★ 백엔드↔프론트 유일 접점 (변경은 양쪽 합의 후 단독 PR)

backend/app/
├── extraction/   Claude 추출 — "읽기"만 담당                    [완료]
│   ├── providers/  mock | anthropic_direct | gateway | cache
│   └── grounding.py  환각 차단 · 합계 검증 · 신뢰도
├── masters/      마스터 로더 · brands.py(참조표 읽기/쓰기)       [완료]
├── domain/       RawPO / SapRow / Batch                         [부분]
├── rules/        규칙엔진 (SCHEMA.md §2의 7단계)                [expr 파서만]
├── tests/        pytest 104종 + 픽스처 + 골든                    [완료]
├── mapping/      전송 필드 행 생성                              [미착수]
├── validation/   검증                                           [미착수]
├── transport/    EAI 전송                                       [미착수]
└── api/          라우트 — routes_brands.py (브랜드 매핑 콘솔)     [부분]

frontend/         React 18 + TS + Vite + AG Grid                 [미착수 — 디렉터리 없음]
scripts/          parse_one.py · validate_masters.py. mock_eai_server 미작성
.github/          CI: 마스터 검증 → pytest → ruff → samples/ 유출 확인
samples/          실물 발주서 — Git 제외 (대외비)
storage/          런타임 산출물 — Git 제외
```

**엔진 파이프라인 7단계**: `EXTRACT → SPLIT → CONTEXT → TABLES → RULES → FIELDS → VALIDATE`
상세는 `masters/SCHEMA.md` §2. 이 파일에 다시 쓰지 않는다.

---

## 5. 절대 하지 말 것

| 금지 | 이유 |
|---|---|
| **`samples/` 커밋** | 실물 발주서·거래처 단가는 대외비. 한 번 올라가면 이력에서 못 지운다. push 전 `git ls-files samples/`가 **2개**(`.gitignore`, `README.md`)인지 확인 |
| `.env` 커밋 | API 키·EAI URL |
| 코드에 거래처 이름 하드코딩 | P2 위반 |
| 전송 필드 개수 하드코딩 | `_base`가 유일한 원천 |
| 거래처 파일에 36필드 전량 나열 | 프로필과 다른 것만 적는다. 거래처 수만큼 유지 비용이 늘어난다 |
| 프로필 필드를 일부만 덮어쓰기 | 항목은 **통째로 교체**된다 (SCHEMA §1). 필요한 키를 전부 다시 적는다 |
| LLM에게 코드값/형식변환 지시 | P1 위반. `hints`에 "YYYYMMDD로 바꿔라" 같은 지시 금지 |
| SSOT 아닌 문서에 값 복사 | 어긋나면 오더가 잘못 생성된다 |
| `rules.md` / `master-admin.md` 참조 | 폐기·보류 문서. 낡은 값(AUART=ZOR, 33필드)이 남아 있다 |
| 코드 목록 판정에 `contains()` | 부분 문자열 검사라 오판한다. `in(value, list)` 를 쓴다 (SCHEMA §4.7.3) |
| 마스터 YAML 수정 후 검증 생략 | `python scripts/validate_masters.py` 를 돌린다 |
| 대량 매핑표를 YAML `entries`에 나열 | 커지면 `csv_map`으로 참조표에 둔다 (SCHEMA §4.5) |
| SAP에 없는 코드를 매핑 | `value_check`가 막는다. 전송해도 SAP이 거부한다 |
| 라우트에서 `get_settings()` 직접 호출 | `Depends(get_settings)`를 쓴다. 안 그러면 테스트가 실제 `masters/`를 덮어쓴다 |
| 참조표를 통째로 다시 쓰기 | 행 순서가 판정 우선순위다. `brands.set_keys()`가 자리를 보존한다 |
| 테스트에서 실제 LLM 호출 | 픽스처로 재생한다. `conftest.py` 가 `LLM_PROVIDER=mock` 을 강제한다 |
| 픽스처를 해시로 주소 지정 | 프롬프트·모델이 바뀌면 전부 미아가 된다. `{거래처}__{파일명}` 을 쓴다 |

---

## 6. Git

- 브랜치: `main` / `feat/be-rules`(백엔드) / `feat/fe-grid`(프론트)
- 파일 소유권: `backend/**` `masters/**` `scripts/**` = 백엔드 · `frontend/**` = 프론트 · `contracts/**` = 공용(단독 PR) · `design.md` `process.md` `masters/SCHEMA.md` = architect
- 커밋 접두: `feat` `fix` `rules` `docs` `chore` `test`
- **`rules:` 커밋은 본문에 근거(일자·확인자·영향 범위)를 남긴다.** Git 이력이 곧 규칙 변경 대장이다.
- 작업 후 즉시 커밋한다 (GUI의 "변경 취소"로 정리분이 한 번 날아간 적 있음)

---

## 7. 서브에이전트

`.claude/agents/`에 정의되어 있고 메인 세션이 호출한다.

| 에이전트 | 언제 |
|---|---|
| `architect` | 설계 결정·요구사항 분석·설계문서 작성 |
| `developer` | 코드 구현 |
| `reviewer` | 코드 작성/수정 직후 품질·보안 검토 |
| `tester` | 파싱 정확도·전송 검증 |

---

## 8. 알려진 미해결 갭 (2026-09-14 아키텍트 검토)

> **`README.md`의 "이제 문서 간 모순이 없다"는 현재 사실이 아니다.** 아래를 전제로 작업할 것.

> ✅ **해결됨 (2026-09-14)**
> - 추출 스키마 `shipments[]` 추가 및 표준 키 SSOT 정렬 — `masters/SCHEMA.md`
>   §2.1(SPLIT 규약) · §3.1(표준 키) · §4.2(`extra_fields`)가 원천이고
>   `schema_builder.py` · `models.py` 가 거기에 맞춰져 있다.
> - expr 문법 명세(§4.7) · 파서(`backend/app/rules/expr.py`) · `validate_masters.py`.
>   **마스터를 고쳤으면 검증기를 돌린다.** YGJP ZSHCO 분기식 오류도 이때 잡혀 수정됐다.
> - 빌드·테스트 골격 — `pyproject.toml` · `backend/tests/` 73종 · 픽스처 · CI.
>   **새 클론에서 `.env`·API 키 없이 `pytest` 가 전 파이프라인을 돌린다.**
>   캐시 키에서 hints 를 뺐고(규칙 튜닝이 캐시를 깨지 않는다),
>   픽스처는 `{거래처}__{파일명}` 으로 찾는다(프롬프트가 바뀌어도 재생된다).

**치명 — D2 착수 전 해결 필요**

1. **검수→전송에 서버측 대조가 없다** — 파싱 원본 스냅샷·행 삭제 규약·감사 레코드 스키마 미정의

**중요**

- CBO 업서트 키가 미확정인데 "중복 전송 무해"를 전제하고 있다 (MSC·YGJP는 `POSEX: const ""`라 행 식별자 없음)
- `.env.example`·`config.py`의 `EAI_ENDPOINT`가 `http://` — 요구사항은 HTTPS. auth 헤더 규약 미정의
- `extractor.py`는 확장자 불일치를 `ValueError`로 차단하는데 문서 3곳은 "차단 안 함"
- `prompt.py`·`schema_builder.py`가 LLM에게 날짜 변환을 지시한다 (P1 위반)
- `masters/refs/msc_ref.csv`가 더미 데이터인데 DUMMY 표시가 없다

**문서 모순 (SSOT 쪽으로 고칠 것)**: `samples/README.md`는 KL=HTM/MSC=PDF로 **거꾸로** 적혀 있다(정답: MSC=HTM, KL=PDF). "33필드" 표기 4곳(정답 36). `master-admin.md:145`의 `AUART=ZOR`(정답 `ZEXP`).
