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
pip install -r backend\requirements-dev.txt   # 운영 서버는 requirements.txt 만
copy .env.example .env

pytest                                        # 키 없이 전 파이프라인이 돈다
streamlit run po2sap.py                       # → http://localhost:8501
```

브라우저는 자동으로 열리지 않는다 (`.streamlit/config.toml` 의 `headless=true`).
끄면 첫 실행에 이메일을 묻고 **입력을 기다리며 멈춘다** — 서버에서 화면이 안 뜬다.

사내 공개: `streamlit run po2sap.py --server.address 0.0.0.0 --server.port 8501`

---

## Claude API 주소 · 키 설정

`.env` 하나로 끝난다. **코드는 환경마다 같다.**

### 어느 모드로 쓸지

| `LLM_PROVIDER` | 언제 | 필요한 것 |
|---|---|---|
| `mock` | 개발 · CI · 데모 | **없음.** 저장된 응답을 재생한다 (비용 0, 오프라인) |
| `anthropic` | Claude API 를 직접 부를 때 | `LLM_API_KEY` |
| `gateway` | 사내 LLM 게이트웨이를 거칠 때 | `LLM_API_KEY` + `LLM_BASE_URL` |

`anthropic` 과 `gateway` 는 **같은 코드**를 쓴다. 주소만 다르다.

### 직접 호출

```ini
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_BASE_URL=                      # 비우면 https://api.anthropic.com
```

### 사내 게이트웨이

Anthropic 호환 엔드포인트를 전제한다.

```ini
LLM_PROVIDER=gateway
LLM_API_KEY=사내에서-발급받은-키
LLM_BASE_URL=https://llm-gw.yg1.solutions
```

> 끝에 `/v1` 을 붙이지 않는다 — SDK 가 붙인다. `.../v1` 로 적으면 `/v1/v1/messages`
> 로 요청이 나가 404 가 난다.

### 사내 프록시 · SSL 검사 장비

```ini
LLM_PROXY=http://proxy.사내:8080
LLM_CA_BUNDLE=C:\certs\사내CA.pem
```

> ⚠ **`.env` 에 `HTTPS_PROXY` 를 적는 것으로는 안 된다.** `.env` 는 설정 객체로만
> 읽히고 `os.environ` 으로 나가지 않아서 HTTP 클라이언트가 그 값을 영영 못 본다.
> 위 두 키를 써야 실제로 전달된다. `LLM_CA_BUNDLE` 경로가 없으면 시작할 때
> 오류를 낸다 — 인증서 없이 조용히 검증을 건너뛰지 않는다.

### 모델

```ini
LLM_MODEL_EXTRACT=claude-opus-5     # 추출 본선
LLM_MODEL_FALLBACK=claude-sonnet-5  # 예비
```

사내 계정이 쓸 수 있는 모델로 맞춘다. **모델을 바꾸면 추출 정확도가 달라지므로
골든 테스트를 전량 다시 돌린다.**

### 확인 — 돈 쓰기 전에 여기서 막는다

```powershell
python scripts\check_llm.py
```

프로바이더·주소·모델·프록시·CA 를 그대로 찍고, **모델 조회**로 키·권한·모델 ID
세 가지를 한 번에 확인한다. 메시지를 보내지 않으므로 **비용 0**이다.
키는 앞뒤만 남기고 가려서 찍는다 — 터미널 기록이 그대로 유출이 되지 않게.

실패하면 흔한 원인(키 오타·모델 미허용·사내 CA·사내 프록시)을 함께 띄운다.
화면 좌하단 **설정 확인** 패널과 `/api/health` 도 같은 것을 본다.

### 비용 없이 실물로 한 번 돌려보기

```powershell
# 1) 사전 점검 — hints 의 라벨이 진짜 문서에 있는지 대조 (LLM 호출 없음)
python scripts\check_sample.py <발주서> --customer MSC

# 2) 맞으면 LLM_PROVIDER=anthropic 으로 1회 파싱
#    결과가 storage\llm_cache\ 에 남는다
python scripts\parse_one.py <발주서> --customer MSC --rows

# 3) 다시 LLM_PROVIDER=mock 으로 되돌리면 같은 파일을 무료로 재생한다
```

---

## 진행 상황

- [x] 설계 — 규칙 아키텍처 · API 계약 · 거래처 YAML · 문서 정리
- [x] D1 전처리 · Claude 추출 · 환각 차단 · 마스터 로더 · CLI
- [x] D2 규칙엔진 · 행 생성 · 검증
- [x] D3 화면 (스트림릿) — P/O 변환 · 브랜드 매핑
- [x] D4 EAI 전송 · 모의 서버 · 감사 로그
- [x] 마스터 도구 — 거래처 엑셀 · SAP 브랜드 마스터 · 매핑 초벌
- [ ] **D5 실물 발주서 검증** ← 남은 것. 절차는 `samples/README.md` §3

상세는 [`NEXT.md`](./NEXT.md).
