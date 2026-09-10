# samples/ — 원본 자료 반입 규칙

> 발주서 원본 · 엑셀 레이아웃 템플릿 · 기존 POC 결과(정답지)를 두는 곳.
> **원본은 Git에 올리지 않는다** (`.gitignore`). 테스트에 쓰는 것은 마스킹 후
> `backend/tests/fixtures/` 로 옮긴다.

---

## 1. 폴더 구조

```
samples/
├── README.md                    ← 이 파일 (Git 포함)
├── .gitignore                   ← 아래 원본 전부 제외
│
├── templates/                   ★ SAP S/O 업로드 엑셀 레이아웃
│   ├── SAP_SO_UPLOAD.xlsx           받은 원본 그대로
│   └── _dump/                       기계가 읽는 형태 (아래 §3)
│       └── SAP_SO_UPLOAD.csv
│
├── MSC/
│   ├── raw/                         받은 발주서 원본 (PDF)
│   │   ├── MSC_001.pdf
│   │   └── MSC_002.pdf
│   └── expected/                    기존 POC가 뽑은 Excel 결과 = 정답지
│       ├── MSC_001.xlsx
│       └── _dump/MSC_001.csv
│
├── KL/{raw,expected}                HTM
└── YGJP/{raw,expected}              PDF
```

`raw/` 와 `expected/` 는 **파일명 스템을 맞춘다** (`MSC_001.pdf` ↔ `MSC_001.xlsx`).
이 짝이 맞아야 골든 테스트가 자동으로 연결된다.

---

## 2. 각 파일을 어디에 쓰는가

| 파일 | 용도 | 산출물 |
|---|---|---|
| `templates/SAP_SO_UPLOAD.xlsx` | 33필드의 **정확한 이름·순서·자릿수·날짜형식** 확정 | `masters/_base/sap_defaults.yaml` 의 필드 스펙 교정 |
| `<사>/raw/*.pdf\|htm` | 문서 구조 분석 → 거래처 YAML 의 `extraction.hints` 작성 | `masters/customers/<사>.yaml` |
| `<사>/expected/*.xlsx` | **정답지.** 규칙엔진 출력이 기존 운영 결과와 같은지 대조 | `backend/tests/golden/<사>_001.json` |

> `expected/` 가 가장 가치가 큽니다. 기존 POC Excel 결과가 있으면
> 브랜드코드·ZPKRE2 같은 규칙 적용 결과를 **추측이 아니라 대조로** 맞출 수 있습니다.
> 없으면 raw 만이라도 됩니다.

---

## 3. 엑셀은 CSV 덤프가 필요하다

`.xlsx` 는 바이너리라 그대로 읽지 못한다. 둘 중 하나:

- **(간편)** 엑셀에서 열어 → `다른 이름으로 저장` → **CSV UTF-8** → 같은 폴더 `_dump/` 에 저장
- **(자동)** `python scripts/dump_xlsx.py samples/templates/SAP_SO_UPLOAD.xlsx`
  → 시트별로 `_dump/<시트명>.csv` 생성 *(D2에서 구현)*

PDF · HTM 은 덤프 불필요 (그대로 읽음).

---

## 4. 보안 — 반입 전 확인

| 항목 | 방침 |
|---|---|
| Git | `samples/` 원본은 **전부 제외**. 이 README 와 `.gitignore` 만 커밋 |
| 외부 전송 | 파싱 시 **원문 텍스트가 Claude API 로 나간다.** 실물 발주서 사용은 사전 승인 필요 |
| 승인 전 | 단가·거래처 담당자명·주소를 가린 **마스킹본**으로 진행 (구조 분석은 마스킹본으로 충분) |
| 테스트 픽스처 | `backend/tests/fixtures/` 로 옮기는 것은 **반드시 마스킹본만** (Git 포함되므로) |
| 로그 | 원문·단가는 기록하지 않음 (`design.md` §13) |

---

## 5. 지금 필요한 것 (우선순위)

```
1. templates/SAP_SO_UPLOAD.xlsx      ← 33필드 스펙 확정. 제일 급함
2. MSC/raw/*.pdf         2~3부
3. MSC/expected/*.xlsx   위와 짝이 맞는 것
4. KL/raw/*.htm  ·  YGJP/raw/*.pdf   (D5 확장 검증용)
```
