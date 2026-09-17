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
pip install -r backend/requirements-dev.txt         # 운영 서버는 requirements.txt 만
cp .env.example .env                                # Windows: copy .env.example .env

# 실물 사전 점검 — hints 의 라벨이 진짜 문서에 있는지 대조 (LLM 호출 없음 = 무료)
python scripts/check_sample.py <발주서> --customer MSC
python scripts/check_sample.py <발주서> --customer MSC --text   # 원문까지

# 전처리만 확인 (LLM 호출 없음 = 무료)
python scripts/parse_one.py <발주서> --customer MSC --text-only

# 단건 파싱
python scripts/parse_one.py <발주서> --customer MSC

# 규칙엔진까지 — 전송 행 36필드를 그대로 출력
python scripts/parse_one.py <발주서> --customer MSC --rows

# API 서버
cd backend && uvicorn app.main:app --reload        # → /api/health

# 모의 EAI (전송 구간을 실서버 없이 관통)
python scripts/mock_eai_server.py
python scripts/mock_eai_server.py --fail 500       # 재시도 확인

# 마스터 검증 (CI 1단계) — SCHEMA.md §7 의 9종 검사. LLM 호출 없음 = 비용 0
python scripts/validate_masters.py
python scripts/validate_masters.py --customer MSC   # 한 곳만
python scripts/validate_masters.py --quiet          # 오류만

# 화면 (사내 서버에서 이것만 띄우면 된다)
streamlit run po2sap.py                                    # → http://localhost:8501
streamlit run po2sap.py --server.address 0.0.0.0 --server.port 8501   # 사내 공개
# 브라우저는 자동으로 안 열린다 (.streamlit/config.toml 의 headless=true).
# 끄면 첫 실행에 이메일을 묻고 **입력을 기다리며 멈춘다** — 서버에서 화면이 안 뜬다.

# 화면 실동작 확인 — 스트림릿·모의 EAI 를 띄운 뒤. LLM 호출 없음 = 비용 0
npm i -D playwright && node ui/e2e/flow.mjs       # 업로드→검수→전송 관통
node ui/e2e/brandflow.mjs                         # 브랜드 매핑 표

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
├── domain/       RawPO · SapRow · RowIssue · BuildResult        [완료]
├── rules/        규칙엔진 ②~⑦ — engine · expr · decision_table       [완료]
│                 mapping_rules · matching · primitives · reftable
├── tests/        pytest 159종 + 픽스처 + 골든 2종               [완료]
├── mapping/      전송 필드 행 생성 (row_builder)                [완료]
├── validation/   필수값·길이·checks                             [완료]
├── storage/      배치 저장 (파싱 원본 스냅샷) · 감사 로그        [완료]
├── transport/    EAI 전송 (payload · eai_client)                [완료]
└── api/          routes_masters · routes_brands · routes_batches [완료]
                  batch_service.py — 업로드→파싱→행 조립

ui/               ★ 스트림릿 화면 — 사내 서버에서 이것만 띄운다      [완료]
├── service.py      backend/app 모듈을 **직접** 부른다 (HTTP 경유 없음)
├── views/
│   ├── convert.py    P/O 변환 — 업로드 → 전송표 → 검수 → 전송
│   ├── brands.py     브랜드 매핑 — 참조표와 같은 모양의 표 하나
│   ├── picker.py     좌측 거래처(430곳) 검색·정렬
│   └── rules.py      규칙 카드 — build_preview 응답을 모양 그대로
└── e2e/            브라우저 실동작 확인 (flow · brandflow · st)
po2sap.py         스트림릿 진입점
scripts/          parse_one.py · check_sample.py · validate_masters.py
                  mock_eai_server.py
.github/          CI: 마스터 검증 → pytest → ruff → samples/·키 유출 확인
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
| `.env` 커밋 | API 키·EAI URL. CI 가 `.env` 추적과 `sk-ant-` 패턴을 검사한다 |
| 채팅·이슈·커밋에 API 키 붙여넣기 | 기록이 남는 곳에 한 번 들어가면 그 키는 끝이다. **폐기하고 재발급**한다 |
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
| 변환 실패를 빈값으로 넘기기 | 날짜를 못 읽었는데 `""`로 전송되면 아무도 모른다. `FormatError`를 올려 검증이 잡게 한다 |
| 가짜 값으로 채운 참조표에 표시 생략 | 우연히 키가 맞으면 조용히 틀린 값이 나간다. 전 행에 `note`를 단다 |
| 엔진 코드에 전송 필드 이름 나열 | `_base`의 순서가 곧 필드 목록이다. `field_order`를 받아 돈다 |
| 화면에 거래처별 분기 코드 | `build_preview` 응답을 모양 그대로 그린다. `kind` 로 아이콘만 고른다 |
| 전송 로직을 화면에 따로 구현 | 되돌릴 수 없는 동작이다. 화면·API 가 `send_service.send_batch` 하나를 쓴다 |
| 규칙 없는 거래처의 업로드 허용 | 빈 값이 그대로 전송된다. `CatalogEntry.ready` 가 False 면 막는다 |
| 스트림릿 화면 패키지를 `app/` 로 | `backend/app` 이 이미 `app` 으로 임포트된다. 이름이 겹쳐 테스트가 깨진다 (→ `ui/`) |
| `st.*(icon=...)` 에 이모지 아닌 글자 | 스트림릿이 예외를 던져 **화면 전체가 트레이스백**이 된다. `test_ui_icons.py` 가 잡는다 |
| 검수 요청 값을 그대로 저장 | 서버 스냅샷에 병합한다. 모르는 행은 거부, 모르는 컬럼은 무시 (계약 §6.1) |
| 행 누락을 삭제로 해석 | 삭제는 `deleted: true` 명시뿐이다. 통신 유실과 구분되지 않는다 |
| `EAI_ENDPOINT` 기본값을 실서버로 | `.env`를 깜빡한 채 진짜 오더가 나간다. 기본은 빈 값이고 전송이 거부한다 |
| 평문 http로 전송 | 루프백(모의 서버)에서만 허용. 그 외는 보내기 전에 400 |
| 4xx를 재시도 | 같은 요청은 또 거부된다. 5xx·타임아웃만 재시도 |
| 감사 로그에 품번·단가 기록 | 5년 보존 파일이 그대로 대외비가 된다. 오더 키(`BSTKD`)와 해시만 (design §8.1) |
| 테스트에서 실제 LLM 호출 | 픽스처로 재생한다. `conftest.py` 가 `LLM_PROVIDER=mock` 을 강제한다 |
| 픽스처를 해시로 주소 지정 | 프롬프트·모델이 바뀌면 전부 미아가 된다. `{거래처}__{파일명}` 을 쓴다 |
| 예상과 다른 파일 형식을 차단 | 거래처가 한 번씩 다른 형식으로 보낸다. 경고만 띄우고 읽어본다 (계약 §1) |
| 사전 점검 없이 실물 파싱 | `check_sample.py`로 hints 앵커부터 대조한다. 안 맞으면 API 비용만 나간다 |
| `temperature`·`top_p` 전송 | 현행 모델은 샘플링 파라미터를 받지 않고 400 을 낸다. 재현성은 응답 캐시가 보장한다 |
| `/api/health`에서 실제 메시지 전송 | 화면·모니터링이 주기적으로 부른다. 모델 조회로 키·권한·모델 ID 를 확인한다 |

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
> - **검수→전송 서버측 대조** — 서버가 파싱 직후 값을 스냅샷으로 들고, 요청은
>   거기에 병합된다. 모르는 `row_id` 는 요청 전체를 거부하고, 모르는 컬럼은 무시하며,
>   행 삭제는 명시 플래그다(누락 ≠ 삭제). `edited` 는 서버가 원본과 대조해 계산한다.
>   규약은 계약 §6.1.
> - 빌드·테스트 골격 — `pyproject.toml` · `backend/tests/` · 픽스처 · CI.
>   **새 클론에서 `.env`·API 키 없이 `pytest` 가 전 파이프라인을 돌린다.**
>   캐시 키에서 hints 를 뺐고(규칙 튜닝이 캐시를 깨지 않는다),
>   픽스처는 `{거래처}__{파일명}` 으로 찾는다(프롬프트가 바뀌어도 재생된다).

**치명 — 없음.** 검수→전송 서버측 대조는 해결됐다 (위 ✅ 참조).
감사 레코드 스키마는 EAI 전송을 붙일 때 함께 정한다.

**중요**

- **CBO 업서트 키가 미확정인데 "중복 전송 무해"를 전제하고 있다** (MSC·YGJP는 `POSEX: const ""`라 행 식별자 없음). 키가 없으면 재전송이 덮어쓰기가 아니라 **중복 적재**다. 감사 로그가 `send`/`resend`를 구분하므로 사후 추적은 된다
- **EAI 응답 본문 규격이 백지다.** 판정을 HTTP 상태 코드에만 걸었다 — "200인데 본문에 실패가 적힌" 경우를 못 잡는다 (계약 §7.1)
- `prompt.py`·`schema_builder.py`가 LLM에게 날짜 변환을 지시한다 (P1 위반)
- **실물 발주서로 한 번도 검증한 적이 없다.** 지금 픽스처는 `hints` 서술을 보고 만든
  합성 문서라 "hints 가 맞다"는 증거가 못 된다. 절차는 `samples/README.md` §3

**문서 모순 (SSOT 쪽으로 고칠 것)**: "33필드" 표기가 `master-admin.md`에 남아 있다(정답 36). `master-admin.md:145`의 `AUART=ZOR`(정답 `ZEXP`). — `samples/README.md`의 MSC/KL 형식 뒤바뀜은 2026-09-15 수정됨.
