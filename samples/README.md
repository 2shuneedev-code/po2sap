# samples/ — 실물 자료 반입 규칙

> 발주서 원본 · 기존 운영 결과지(정답지)를 두는 곳.
> **원본은 Git 에 올리지 않는다** (`.gitignore` 가 전부 제외한다).
> 테스트에 쓰는 것은 **마스킹 후** `backend/tests/fixtures/` 로 옮긴다.

---

## 1. 폴더 구조

```
samples/
├── README.md                    ← 이 파일 (Git 포함)
├── .gitignore                   ← 아래 원본 전부 제외
│
├── MSC/
│   ├── raw/                     받은 발주서 원본 — **HTM**
│   └── expected/                기존 운영 결과 (정답지, 있으면)
│
├── KL/
│   ├── raw/                     **PDF**
│   └── expected/
│
└── YGJP/
    ├── raw/                     **PDF**
    └── expected/
```

**형식을 헷갈리지 말 것**: MSC = **HTM**, KL = **PDF**, YGJP = **PDF**.
(거래처별 형식의 원천은 `masters/customers/{code}.yaml` 의 `meta.file_types` 다.)

`raw/` 와 `expected/` 는 **파일명 스템을 맞춘다** (`P7988114.htm` ↔ `P7988114.xlsx`).

> 형식이 달라도 **업로드가 막히지는 않는다.** 예상과 다르면 경고만 뜬다 —
> 거래처가 평소와 다른 형식으로 한 번 보내는 일은 실제로 일어난다.

---

## 2. 무엇에 쓰는가

| 파일 | 용도 |
|---|---|
| `<사>/raw/*` | 문서 구조 확인 → `masters/customers/<사>.yaml` 의 `extraction.hints` 교정 |
| `<사>/expected/*` | **정답지.** 규칙엔진 출력이 기존 운영 결과와 같은지 대조 |

> `expected/` 가 가장 가치가 큽니다. 기존 결과가 있으면 브랜드코드·ZPKRE2 같은
> 규칙 적용 결과를 **추측이 아니라 대조로** 맞출 수 있습니다. 없으면 `raw/` 만이라도 됩니다.

전송 필드의 이름·순서·자릿수는 이미 `masters/_base/sap_defaults.yaml` 에 확정되어 있다
(현재 36개). 양식이 바뀌면 그 파일만 고친다.

---

## 3. 실물 검증 절차

### 3-1. 사전 점검 — **LLM 호출 없음. 비용 0**

```bash
python scripts/check_sample.py samples/MSC/raw/P7988114.HTM --customer MSC
```

`hints` 가 "이 라벨 아래 이 값이 있다"고 주장하는 것들이 **실제 문서에 있는지** 대조한다.
안 맞으면 Claude 를 불러봐야 헛돈만 쓴다. 못 찾은 라벨이 있으면 `--text` 로 원문을 보고
`hints` 를 고친 뒤 다시 돌린다.

```bash
python scripts/check_sample.py <파일> --customer MSC --text   # 원문까지
```

### 3-2. 실제 파싱 — **여기서 처음 과금된다**

`.env` 에 키를 넣고 프로바이더를 바꾼다.

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
```

```bash
python scripts/parse_one.py samples/MSC/raw/P7988114.HTM --customer MSC --rows
```

결과가 `storage/llm_cache/` 에 저장된다. **이후로는 같은 파일을 무료로 반복 재생**할 수 있다
(`LLM_PROVIDER=mock`). 규칙을 고치고 다시 돌려도 추가 비용이 없다.

### 3-3. 정답지와 대조

`expected/` 가 있으면 `--rows` 출력과 한 줄씩 비교한다. 어긋나는 필드는
**코드가 아니라 `masters/customers/<사>.yaml` 을 고쳐서** 맞춘다 (원칙 P2).

```bash
python scripts/validate_masters.py --customer MSC   # 고친 뒤 반드시
```

### 3-4. 전송까지 관통

```bash
python scripts/mock_eai_server.py          # 다른 터미널에서
cd backend && uvicorn app.main:app --reload
```

업로드 → 검수 → 전송을 모의 서버로 끝까지 확인한다. 실제 EAI(`eai-dev`)로 보내는 것은
그다음이다.

### 3-5. 픽스처로 승격 (선택)

회귀 테스트에 넣고 싶으면 **마스킹본**을 `backend/tests/fixtures/<사>/` 에,
LLM 응답을 `backend/tests/fixtures/llm_cache/{거래처}__{파일명}.json` 에 둔다.
그러면 새 클론에서도 키 없이 재생된다.

---

## 4. 보안 — 반입 전 확인

| 항목 | 방침 |
|---|---|
| Git | `samples/` 원본은 **전부 제외.** 이 README 와 `.gitignore` 만 커밋된다 |
| 확인 | push 전 `git ls-files samples/` 가 **2개**인지 본다 (CI 도 검사한다) |
| 외부 전송 | 파싱하면 **원문 텍스트가 Claude API 로 나간다.** 실물 사용은 사전 승인이 필요하다 |
| 승인 전 | 단가·담당자명·주소를 가린 **마스킹본**으로 진행한다 (구조 확인은 마스킹본으로 충분) |
| 픽스처 | `backend/tests/fixtures/` 는 Git 에 포함된다. **마스킹본만** 옮긴다 |
| 로그 | 원문·단가는 기록하지 않는다 (`design.md` §8.1) |

> **3-1 사전 점검은 파일이 밖으로 나가지 않는다.** 승인이 아직이라면 여기까지는
> 지금 바로 할 수 있다.

---

## 5. 지금 필요한 것 (우선순위)

```
1. MSC/raw/*.htm         2~3부     ← 제일 급함. 복수 출하처 문서가 하나 있으면 좋다
2. MSC/expected/*        위와 짝이 맞는 것
3. KL/raw/*.pdf  ·  YGJP/raw/*.pdf
```

**하나도 검증된 적이 없다.** 지금까지 쓴 것은 합성 픽스처
(`backend/tests/fixtures/msc/PO-SAMPLE-0001.htm`) 뿐이고, 이것은 `hints` 서술을 보고
만든 것이라 "hints 가 맞다"는 증거가 되지 못한다. 실물 1부가 들어오는 순간
3-1 → 3-2 로 확인할 수 있다.
