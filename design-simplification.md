# 구조 단순화 설계 — 템플릿 주도 필드 · 브랜드/출하 마스터 · KUNNR 기본값

> 요구사항 원본: `NEXT.md` §2-A (2026-09-21 지시) · 미결 목록: `NEXT.md` §2-B
> 이 문서는 **설계안**이다. 코드는 developer 가 §12 순서로 구현한다.
> 작성 2026-09-21 · architect
>
> ### 이 문서의 범위
> `NEXT.md` §2-A 의 네 가지(① 고객–브랜드 · ② 고객–출하 마스터 · ③ 엑셀 템플릿 ·
> ④ KUNNR 기본값)를 어떻게 구현할지, 그리고 §2-B 다섯 가지 미결의 **결론**.
>
> 기존 문서를 고쳐야 하는 부분은 **§10(design.md) · §11(CLAUDE.md · SCHEMA.md · 계약)**
> 에 "이렇게 고친다"는 문장으로 모아 두었다. 이 문서가 SSOT 가 되는 주제는 없다 —
> 반영이 끝나면 각 SSOT 문서가 진실이고 이 문서는 **결정 근거 기록**으로 남는다.

---

## 0. 결정 요약

번호는 `design.md` §0 의 D1~D11 에 이어 붙인다 (§10 에서 그대로 옮긴다).

| # | 결정 | 한 줄 요약 |
|---|---|---|
| **D12** | **전송 필드의 목록·순서는 엑셀 템플릿 2행이 정한다** | `_base/sap_defaults.yaml` 은 **규격(label·max_len·type)** 만 맡는다 |
| **D13** | **템플릿은 직접 읽는다** (가져오기 스크립트 없음) | 현업이 고치면 다음 요청에 반영. 단 **읽기 실패는 절대 화면을 멈추지 않는다** |
| **D14** | 템플릿 위치 `masters/templates/SALES ORDER.xlsx` · **Git 추적** | 입력물이다. 생성물인 `masters/거래처마스터.xlsx` 와 성격이 반대다 |
| **D15** | **브랜드 판정의 기본은 "그 고객의 브랜드 수"** | 1건이면 자동 채움, 2건 이상이면 공란 + 드롭다운. **문구 대조(`csv_map`)는 예외** |
| **D16** | "1개" 기준 = **`brand_master.csv` 의 그 `kunnr` 행 수** | 매핑(`brand_keys.csv`) 진척도가 아니라 **SAP 이 허용한 선택지** 수다 |
| **D17** | **고객–VSART–ZSHCO 는 참조표 1:1:1** (`refs/shipping.csv`) | 행이 없으면 **공란**. 추측해 채우지 않는다 |
| **D18** | **KUNNR1 = KUNNR2 = KUNNR3 = 고객코드가 기본** | 조건이 있는 거래처(MSC 출하처 분기 등)만 덮어쓴다 |
| **D19** | 전송 필드 36 → 약 15 **축소는 템플릿 편집으로 현업이 한다** | 코드·YAML 을 고치지 않는다. §7 은 **후보 제안일 뿐 확정이 아니다** |

**뒤집는 기존 결정 두 개** (왜 바꾸는지는 §4.1 · §6.1 에 적었다):

| 뒤집는 것 | 어디에 있었나 | 왜 |
|---|---|---|
| 브랜드는 `csv_map`(원문 문구 대조)이 기본이고 안 맞으면 막힌다 | `profiles/generic.yaml` · `customers/{msc,ygjp}.yaml` | 78곳 × 원문 문구를 사람이 다 채울 때까지 아무것도 못 한다. 실제로 301건이 "자동 초벌"로 채워져 있고 그건 확인된 값이 아니다 |
| 공용 프로필은 모르는 값을 **비워 둔다** — "출하처를 판매처로 넣는 식" 금지 | `CLAUDE.md` §5 · `profiles/generic.yaml` 머리말 | 사장님 지시(§2-A ④). KUNNR **한정**으로 예외를 연다. 그 밖의 필드에 대한 금지는 그대로 유지한다 |

---

## 1. 무엇이 어떻게 달라지나 (한 장)

```
            [지금]                              [바뀐 뒤]

필드 목록   _base/sap_defaults.yaml (36)   →   SALES ORDER.xlsx 2행 (현업이 정함)
필드 규격   _base/sap_defaults.yaml         →   그대로 (_base 가 계속 원천)
브랜드      brand_keys.csv 문구 대조        →   brand_master.csv 후보 수로 판정
            (안 맞으면 🔴/🟡)                     1건=자동 · N건=드롭다운
                                                문구 대조는 **예외 규칙**으로 얹는다
VSART/ZSHCO 거래처 YAML 고정값              →   refs/shipping.csv (1:1:1), 없으면 공란
KUNNR2      공란 + todo                     →   고객코드(기본) · 조건 있으면 덮어씀
```

**엔진 코드는 거의 바뀌지 않는다.** 이미 `field_order = list(field_specs)` 로 돌고 있어서
(`backend/app/rules/engine.py:74`), 로더가 `field_specs` 를 템플릿 순서로 갈아끼우면
행 생성·검증·그리드·전송 페이로드가 **전부 따라온다.** 새로 만드는 코드는
① 템플릿 리더 ② 규칙 `kind: csv_choice` ③ 드롭다운 후보 전달 통로, 이 셋뿐이다.

---

## 2. SSOT 충돌 해소 ★ (`NEXT.md` §2-B 1)

### 2.1 책임 분리

| 주제 | 유일한 원천 | 누가 읽나 | 없거나 어긋나면 |
|---|---|---|---|
| 전송 필드 **목록과 순서** | `masters/templates/SALES ORDER.xlsx` **2행** | 로더가 읽어 `field_specs` 를 재구성 | `_base` 순서로 폴백 + 배너(§3.4) |
| 전송 필드 **규격** — `label` · `sheet` · `max_len` · `type` | `masters/_base/sap_defaults.yaml` `field_specs` | 화면 헤더 · 길이 검증 · 계약 §3 | 규격 없는 필드는 **이름만으로** 통과(§3.5) |
| 전 거래처 **공통 고정값** (AUART·VKORG·VTWEG·LGORT·ZTERM) | `masters/_base/sap_defaults.yaml` `sap_defaults` | `fields.*.from: base` | 변경 없음 |
| 필드별 **값을 어떻게 채우는가** | `profiles/*.yaml` + `customers/*.yaml` 의 `fields` | 규칙엔진 ⑥ FIELDS | 변경 없음 |

> 한 문장으로: **템플릿은 "무엇을 어떤 순서로 보낼지", `_base` 는 "그 필드가 어떤 규격인지",
> 거래처 YAML 은 "그 값을 어떻게 채울지"를 각각 맡는다.** 셋은 겹치지 않는다.

### 2.2 유효 필드 목록 = 교집합 규칙

로더가 계산하는 결과를 **유효 필드 목록(effective field list)** 이라 부른다.
이후 `columns` · 그리드 · 검증 · 전송 페이로드는 **전부 이 목록**을 쓴다.

| 경우 | 유효 목록에 | 규격 | 값 매핑 | 알림 |
|---|---|---|---|---|
| 템플릿 ○ · `_base` ○ | **들어간다** (템플릿 순서) | `_base` 것 | 거래처 YAML | — |
| 템플릿 ○ · `_base` ✗ | **들어간다** | `label` = 필드명, `max_len` 없음 | **없으면 로더가 `{from: const, value: ""}` 를 끼운다** | 🟡 배치 노트 1건 + `validate_masters` 경고 |
| 템플릿 ✗ · `_base` ○ | **빠진다** (전송 안 함) | — | 선언이 남아 있어도 무해 | `validate_masters` 리포트("미사용 선언") |
| 템플릿을 못 읽음 | `_base` 36개 전량 | `_base` | 그대로 | 🟡 화면 배너 + `/api/health` |

**템플릿에만 있는 필드에 `{from: const, value: ""}` 를 자동으로 끼우는 이유**:
끼우지 않으면 `row_builder` 가 행마다 `FIELD_NOT_DECLARED` 🔴 를 달고
(`backend/app/mapping/row_builder.py:40`) **전송이 통째로 막힌다.** 현업이 템플릿에
열 하나를 추가한 순간 업무가 서는 것은 이 시스템의 본업(발주서를 표로 옮기기)에
반한다. 빈 값으로 보내고 **배치 노트로 한 번** 알린다.

또한 자동 선언에는 `required` 를 달지 않는다 — `required: warn` 을 달면 49행짜리
배치에서 같은 경고가 49개 쌓여 진짜 경고가 묻힌다. 알림은 **배치당 1건**이다.

### 2.3 `CLAUDE.md` §2 표를 이렇게 고친다 (문장 그대로)

현재 첫 행:

```
| 전송 필드 목록·개수·max_len | `masters/_base/sap_defaults.yaml` | "전송 필드 전량"이라고만 쓴다 |
```

**아래 두 행으로 교체한다.**

```
| 전송 필드 **목록·순서** | `masters/templates/SALES ORDER.xlsx` **2행** | "전송 필드 전량"이라고만 쓴다. 개수를 세지 않는다 |
| 전송 필드 **규격** (label·sheet·max_len·type) | `masters/_base/sap_defaults.yaml` 의 `field_specs` | 규격만 적는다. **어떤 필드를 보낼지는 템플릿이 정한다** |
```

그리고 같은 표에 **아래 두 행을 새로 넣는다.**

```
| 고객별 브랜드 후보 (SAP 등록분) | `masters/refs/brand_master.csv` | 읽기 전용. `import_brand_master.py` 로만 교체한다 |
| 고객별 운송수단·출하조건 (VSART·ZSHCO) | `masters/refs/shipping.csv` | 1 고객 = 1 행. 행이 없으면 **공란**이다 |
```

§2 표 바로 아래 굵은 문장도 교체한다.

```
현재: **전송 필드 개수를 코드에 하드코딩하지 않는다.** 현재 36개지만 34가 되어도 코드·화면은 그대로 동작해야 한다.

교체: **전송 필드 개수를 코드에 하드코딩하지 않는다.** 목록과 순서는 `SALES ORDER` 템플릿 2행이 정하고, 코드는 그 순서를 받아 돈다. 36이 15가 되어도 코드·화면·전송은 그대로 동작해야 한다. 템플릿을 읽지 못하면 `_base` 순서로 폴백하되 **조용히 넘어가지 않는다** (화면 배너 · `/api/health`).
```

§5 금지 목록에는 **세 행을 추가한다.**

```
| 전송 필드 목록을 `_base` 에서 세기 | 목록은 템플릿 2행이 정한다. `_base` 는 규격만 맡는다 |
| 템플릿 읽기 실패에 예외를 올리기 | 엑셀 한 칸 때문에 화면 전체가 트레이스백이 된다. `_base` 로 폴백하고 배너로 알린다 |
| 템플릿에만 있는 필드에 🔴 를 달기 | 현업이 열 하나 추가한 순간 전송이 막힌다. 빈 값으로 보내고 배치 노트 1건으로 알린다 |
```

§5 의 기존 행 하나는 **문구를 고친다** (§6.1 참조).

```
현재: | 공용 프로필이 모르는 값을 **추측해 채우기** | 출하처를 판매처로 넣는 식. 그럴듯하면 사람이 확인 없이 넘긴다. **비워 두고 `required: warn`** — 빈 칸은 눈에 띈다 |

교체: | 공용 프로필이 모르는 값을 **추측해 채우기** | 그럴듯하면 사람이 확인 없이 넘긴다. **비워 두고 `required: warn`** — 빈 칸은 눈에 띈다. **단 KUNNR1/2/3 은 예외다**: 셋 다 고객코드가 기본값이고(2026-09-21 지시), 다른 거래처는 조건을 건다 |
```

§3 명령어에는 한 줄 추가한다.

```bash
# 전송 필드 템플릿 점검 — 2행에서 무엇을 읽었는지 · _base 와 무엇이 다른지 (LLM 호출 없음 = 비용 0)
python scripts/check_template.py
```

---

## 3. 템플릿 읽기 설계 (`NEXT.md` §2-B 2·3)

### 3.1 위치와 Git

| 항목 | 값 |
|---|---|
| 경로 | `masters/templates/SALES ORDER.xlsx` |
| Git | **추적한다.** 입력물이고, 이것이 바뀌면 전송 내용이 바뀌므로 이력이 남아야 한다 |
| 덮어쓰기 | 현업이 파일 그대로 교체. 화면의 Git 동기화(`gitsync`)가 `add`·`commit`·`push` 한다 |
| `.env` 재정의 | `FIELD_TEMPLATE=` (절대/상대 경로) · `FIELD_TEMPLATE_SHEET=` (기본: 첫 시트) |

`.gitignore` 의 `masters/*.xlsx` 는 **`masters/` 직속 파일만** 가린다 —
`masters/templates/SALES ORDER.xlsx` 는 추적된다. 다만 나중에 누가 패턴을
`masters/**/*.xlsx` 로 넓힐 수 있으니 `.gitignore` 에 의도를 한 줄 남긴다.

```
# 거래처 마스터 엑셀 — 생성물이다 (masters/ 직속만 가린다)
masters/*.xlsx
# ↑ masters/templates/ 는 **입력물**이다. 전송 필드 목록의 원천이므로 추적한다.
```

> ⚠ 커밋 전 확인: 템플릿에 거래처 실데이터(단가·품번)가 남은 시트가 있으면 지우고
> 헤더만 남긴다. `samples/` 가 대외비인 이유와 같다.

### 3.2 무엇을 읽나

| 항목 | 규약 |
|---|---|
| 시트 | `FIELD_TEMPLATE_SHEET` 가 있으면 그 이름, 없으면 **첫 시트** |
| 행 | **2행** 고정 (1행은 사람이 보는 설명행 — 읽지 않는다) |
| 열 범위 | A열부터 오른쪽으로. **빈 칸 5칸 연속**이면 거기서 끝 (병합·잔여 서식 때문에 used range 를 믿지 않는다) |
| 정규화 | `strip()` → 내부 공백·개행 제거 → **대문자**. `SALES ORDER TYPE` 같은 1행 라벨이 섞여 들어오는 것을 막기 위해 `[A-Z][A-Z0-9_]*` 패턴만 필드명으로 인정한다 |
| 빈 칸 | 건너뛴다 (끝으로 치지 않는다 — 위 5칸 규칙으로만 종료) |
| 중복 이름 | **첫 번째만** 채택하고 경고. 뒤쪽은 어차피 같은 키로 덮어써져 의미가 없다 |
| 순서 | **읽은 순서가 곧 전송 순서**다. 열 위치가 아니라 이름으로 움직이되, 순서는 왼→오른쪽 그대로 |

### 3.3 캐시

`backend/app/masters/loader.py` 의 `_load_yaml` 과 같은 방식 — **`(경로, mtime, size)` 를
캐시 키로 삼는다.** 현업이 파일을 고치면 다음 요청에서 자동으로 다시 읽고,
고치지 않았으면 openpyxl 을 다시 돌리지 않는다. 서버 재시작이 필요 없다.

### 3.4 읽기 실패 시 동작 ★ — 화면은 절대 멎지 않는다

리더는 **예외를 올리지 않는다.** 언제나 아래 구조를 돌려준다.

```
TemplateStatus
  ok: bool
  source: "template" | "memory" | "base"      # 무엇을 썼는지
  path: str
  reason: str          # ok=false 일 때 사람이 읽을 한국어 한 문장
  fields: list[str]    # 유효 필드 목록 (항상 비어 있지 않다)
```

| 상황 | `source` | 동작 |
|---|---|---|
| 정상 | `template` | 2행 목록 사용 |
| 파일 없음 | `base` | `_base` 순서 사용 + 배너 |
| 열기 실패 (손상·암호·xls 구형) | `base` 또는 `memory` | 이전에 성공한 목록이 **이 프로세스 메모리에 있으면** 그것을 유지, 없으면 `_base` |
| 잠김(현업이 엑셀로 열어둠, `PermissionError`) | `memory` → `base` | 위와 같다. `~$*.xlsx` 임시 파일은 아예 보지 않는다 |
| 2행이 비었거나 인식된 필드 0개 | `base` | `_base` + 배너 ("2행에서 필드명을 찾지 못했습니다") |

**`memory` 폴백을 두는 이유**: 검수 도중 현업이 템플릿을 엑셀로 열면 그 순간
컬럼 수가 36으로 튀어 그리드가 통째로 바뀐다. 이미 읽어 둔 목록을 유지하는 편이
덜 놀랍다. 단 `source` 가 `template` 이 아니면 **항상 배너를 띄운다** — 조용히
낡은 목록을 쓰는 것이 가장 나쁘다.

### 3.5 노출 지점 (조용히 넘어가지 않기)

| 어디 | 무엇을 |
|---|---|
| `GET /api/masters/fields` | 응답에 `"template": { "ok": "true", "source": "template", "path": "...", "reason": "" }` |
| `GET /api/health` | `"template"` 블록 동일. 모니터링·`check.bat` 이 본다 |
| 스트림릿 화면 상단 | `ok=false` 면 `st.warning(icon="⚠️")` 배너 한 줄 |
| `scripts/check_template.py` | 2행에서 읽은 목록 · `_base` 와의 차집합 양방향 · 중복 · 폴백 사유 |
| `scripts/validate_masters.py` | 검사 12~14 (§3.6) |

### 3.6 검증 추가 (`masters/SCHEMA.md` §7 에 등재)

| # | 검사 | 실패 시 |
|---|---|---|
| 12 | 템플릿을 읽었는가 (`source == "template"`) | **경고** — 오류로 올리면 템플릿 없는 CI 가 전부 죽는다 |
| 13 | 템플릿에만 있고 `_base` 에 규격이 없는 필드 | 경고 + 목록 |
| 14 | `_base` 에만 있고 템플릿에 없는 필드(= 안 보내는 필드) | 리포트 + 목록 |
| 15 | 유효 필드 목록이 거래처 파일(병합 결과)에 **전부 선언**됐는가 | **오류** — 기존 검사 1을 유효 목록 기준으로 바꾼 것 |

> 검사 1 은 `_base` 36개를 기준으로 삼았다. 이제 기준이 유효 목록이므로 **검사 1 의
> 문구를 "유효 필드 목록"으로 고치고** 검사 15 는 따로 두지 않는다 (§11.2).

---

## 4. 브랜드 판정 단순화 (`NEXT.md` §2-A ① · §2-B 4)

### 4.1 왜 바꾸나

지금 구조는 **원문 문구 → 코드** 대조(`csv_map`)가 유일한 경로다. 그 표를 사람이
채우기 전에는 브랜드가 안 나오고, MSC·YGJP 외에는 `seed_brand_keys.py` 가
**SAP 브랜드명을 그대로 문구로 박은 자동 초벌 301건**이 들어가 있다. 이건
확인된 값이 아니고(`ACCUPRO BRAND` vs 실제 `ACCUPRO`), 우연히 걸리면
**조용히 틀린 코드가 전송된다.**

사장님 지시의 핵심은 판정 근거를 바꾸는 것이다 — **"그 고객이 SAP 에서 쓸 수 있는
브랜드가 몇 개인가"** 가 기본이고, 문구 대조는 그걸로 안 되는 곳의 예외다.
78곳 중 브랜드가 1개인 고객은 그 자리에서 끝나고, 여러 개인 고객은 사람이 고른다.
**추측이 끼어들 자리가 없다.**

### 4.2 "1개"의 기준 — `brand_master.csv` 의 그 `kunnr` 행 수 ★

| 후보 | 채택 | 이유 |
|---|---|---|
| `brand_master.csv` 의 `kunnr` 행 수 | ✅ | SAP 이 **그 고객에게 허용한 선택지**가 곧 후보다. 사람 작업과 무관하게 정해져 있다 |
| `brand_keys.csv` 의 매핑된 행 수 | ✗ | 사람이 어디까지 채웠는지를 뜻할 뿐이다. 4개짜리 고객에서 1개만 채워졌을 때 그 1개가 자동으로 박히면 **틀린 값을 확인 없이 넘긴다** |

### 4.3 스키마 — 새 규칙 `kind: csv_choice`

거래처 이름은 어디에도 없다(P2). 전 고객이 **같은 선언**을 쓰고, 다른 것은
`filter_column` 이 보는 `meta.customer_no` 뿐이다.

```yaml
rules:
  brand_pick:
    kind: csv_choice
    label: "브랜드 후보"
    description: |
      SAP 브랜드 마스터에서 이 고객에게 등록된 브랜드를 후보로 삼는다.
      후보가 1건이면 그 값이 기본값이고, 2건 이상이면 공란 + 검수 화면 드롭다운이다.
    table_file: refs/brand_master.csv
    filter_column: kunnr          # meta.customer_no 와 같은 행만 후보
    value_column: zbrand
    label_column: zbrant          # 드롭다운에 함께 보일 이름
    when_single: auto             # auto(기본) = 후보 1건이면 채운다 | empty = 안 채운다
    when_multi: empty             # empty(기본) = 공란 | error
    on_no_candidates:
      action: warn                # 브랜드가 0건인 고객 — 업로드는 catalog 가 이미 막는다
      message: "이 고객에게 등록된 브랜드가 없습니다"
```

| 키 | 필수 | 내용 |
|---|---|---|
| `table_file` | ✅ | 후보 목록이 든 CSV (`masters/` 기준 상대경로) |
| `filter_column` | ✅ | 이 컬럼이 `meta.customer_no` 와 같은 행만 후보다 |
| `value_column` | ✅ | 후보 값(코드) |
| `label_column` | | 드롭다운 표시용 이름. 없으면 값만 보여준다 |
| `when_single` | | `auto`(기본) · `empty` |
| `when_multi` | | `empty`(기본) · `error` |
| `on_no_candidates` | | `{action: warn\|error\|empty, message}` · 기본 `warn` |

**반환**: 값(문자열) + **후보 목록**. 후보 목록은 컨텍스트 경로로 참조하지 않는다
(값이 아니라 화면 재료다). 필드와는 아래 `choices_from` 으로 잇는다.

### 4.4 필드 옵션 `choices_from` (신규)

```yaml
fields:
  ZBRAND:
    from: rule
    rule: brand_pick
    choices_from: brand_pick      # 이 필드의 드롭다운 후보를 대는 규칙
    required: warn
```

| 항목 | 규약 |
|---|---|
| 영향 범위 | **화면뿐이다.** 전송 값은 `from` 이 정한 그대로 |
| 검증 | 최종 값이 비어 있지 않은데 후보에 **없으면** 🟡 `NOT_IN_CHOICES`. 🔴 로 올리지 않는다 — 사람이 고른 값이 최종 진실이다(P5) |
| 후보 수집 | 오더 단위마다 평가하되 **배치 단위로 합집합**을 만들어 계약 §5 의 `choices` 로 내린다 |

> 후보가 행마다 달라지는 경우(결정표가 후보를 가르는 식)는 지금 없다 —
> `filter_column` 이 고객코드라 배치 안에서 상수다. 행마다 달라야 할 요구가
> 생기면 그때 행 단위 `_choices` 를 계약에 추가한다. `todo:` 로 남긴다.

### 4.5 예외(별도 로직)는 규칙을 하나 **얹는다**

MSC 처럼 원문 문구로 가려야 하는 곳은 기존 `csv_map` 을 **이름만 바꿔** 남기고,
필드에서 둘을 잇는다. 규칙끼리는 서로 참조할 수 없지만(SCHEMA §2), **필드의
`expr` 은 규칙 결과 여러 개를 조합할 수 있다.**

```yaml
# customers/msc.yaml
rules:
  brand_by_text:                  # ← 기존 brand_code 를 이름만 바꾼 것
    kind: csv_map
    source: header.brand_text
    table_file: refs/brand_keys.csv
    filter_column: kunnr
    key_column: text
    mode_column: match
    value_column: zbrand
    case_insensitive: true
    value_check: { table_file: refs/brand_master.csv, value_column: zbrand, filter_column: kunnr }
    on_no_match: { action: empty }      # ★ error 아님 — 못 맞히면 후보 쪽으로 넘긴다

fields:
  ZBRAND:
    from: expr
    expr: 'coalesce(brand_by_text, brand_pick)'
    choices_from: brand_pick
    explain: "발주서 문구로 먼저 가리고, 못 가리면 이 고객의 브랜드 후보로 채웁니다"
    required: true
```

| 거래처 | 브랜드 판정 |
|---|---|
| 전용 규칙 없는 곳(75곳) · 공용 프로필 | `brand_pick` 만 — 1건이면 자동, N건이면 드롭다운 |
| MSC · YGJP | `brand_by_text` → 실패 시 `brand_pick` |
| KL | `{from: const, value: "2"}` 그대로 (브랜드 고정. 후보 판정도 필요 없다) |

**`on_no_match: {action: empty}` 로 내리는 이유**: 지금은 `error` 라 문구를 못 맞히면
행이 🔴 가 되어 전송이 막힌다. 이제 뒤에 후보 경로가 있으므로 **막을 이유가 없다.**
후보로도 못 채우면 `required` 가 걸러준다.

### 4.6 공통 규칙을 **프로필로 올린다** (스키마 변경)

`brand_pick` 과 §5 의 `shipping` 은 전 거래처가 똑같이 쓴다. 78개 파일에 복사할 수
없으므로 `profiles/standard.yaml` 에 올린다. 지금 SCHEMA §1.1 은 프로필에
`fields` 와 `grid` 만 허용한다 — **`rules` 를 허용하도록 고친다**(§11.2).

```yaml
# profiles/standard.yaml (발췌)
rules:
  brand_pick:  { kind: csv_choice, ... }     # §4.3
  shipping:    { kind: lookup,     ... }     # §5.2

fields:
  ZBRAND: { from: rule, rule: brand_pick, choices_from: brand_pick, required: warn }
```

병합은 항목 단위 교체(SCHEMA §1)라, 거래처가 `rules.brand_by_text` 를 더해도
프로필의 `brand_pick` 은 그대로 남는다. 안전하다.

### 4.7 `brand_keys.csv` 와 브랜드 매핑 화면은 **그대로 둔다**

| 항목 | 새 위치 |
|---|---|
| `refs/brand_keys.csv` | **예외 거래처 전용**이 된다. 기본 경로에서 빠진다 |
| `/api/brands/*` · 브랜드 매핑 탭 | 유지. 예외 거래처의 문구를 채우는 화면이다 |
| 자동 초벌 301건 | **기본 경로에서 빠지므로 위험이 내려간다.** `validate_masters` 의 TODO 리포트는 **`csv_map` 을 실제로 쓰는 거래처의 행만** 띄우도록 좁힌다 — 나머지는 아무 데도 쓰이지 않는 행에 대한 경고라 노이즈다 |
| `seed_brand_keys.py` | **기본 실행에서 뺀다.** 예외 거래처를 만들 때만 쓴다 |
| `catalog.CatalogEntry.ready` | 그대로 — 브랜드가 0건인 고객은 업로드를 막는다. 이제 `ready` 는 "후보가 있다"와 정확히 같은 뜻이 된다 |

### 4.8 화면 (드롭다운)

- `choices` 에 있는 컬럼은 `st.column_config.SelectboxColumn(options=[...])`.
- **`options` 에는 빈 문자열과 "현재 값"을 반드시 포함한다.** 목록에 없는 값이 셀에
  들어 있으면 스트림릿이 예외를 던져 화면 전체가 트레이스백이 된다 (같은 부류의
  사고를 `test_ui_icons.py` 가 막고 있다 — 여기도 테스트를 둔다).
- 표시는 `"205 · ACCUPRO BRAND"`, 저장은 코드만. 변환은 화면에서 한다.
- ⚠ **드롭다운 컬럼은 붙여넣기가 막힐 수 있다.** §8.2 의 확인 결과에 따라
  `SelectboxColumn` / `TextColumn + help 에 후보 나열` 중 하나로 확정한다.
  화면이 `choices` 를 어떻게 그릴지는 화면의 판단이고, **계약은 후보 목록만 내린다.**

---

## 5. 고객–운송수단–출하조건 마스터 (`NEXT.md` §2-A ②)

### 5.1 CSV 스키마 — `masters/refs/shipping.csv`

```csv
kunnr,vsart,zshco,note
100249,04,A,MSC — 기존 운영 확인분
107525,04,,KL — ZSHCO 미확정 (공란으로 둔다)
3200,04,,YGJP — ZSHCO 는 브랜드 조건 분기라 거래처 YAML 이 정한다
```

| 컬럼 | 내용 |
|---|---|
| `kunnr` | 고객코드. **1 고객 = 1 행 (1:1:1)** |
| `vsart` | 운송수단 (SAP `VSART`) |
| `zshco` | 출하조건 (SAP `ZSHCO`) |
| `note` | 자유 메모. 값이 있으면 `validate_masters` 리포트에 뜬다 (SCHEMA §1 의 `note` 규약과 동일) |

**값이 없으면 공란이다. 비슷한 고객 것을 베껴 넣지 않는다.** 위 3행은 추측이 아니라
현행 YAML 에 이미 확정값으로 적혀 있던 것을 옮긴 것이다(MSC `ZSHCO: "A"`,
전 거래처 `VSART: "04"`). KL 의 ZSHCO 는 지금도 `todo:` 이므로 **빈 칸 그대로** 둔다.

> `04`·`A` 의 앞자리 0 과 대소문자를 보존해야 하므로 CSV 는 전부 문자열로 읽는다
> (`reftable` 이 이미 그렇게 동작한다).

### 5.2 규칙 — 기존 `kind: lookup` 을 그대로 쓴다

새 `kind` 가 필요 없다. `profiles/standard.yaml` 에 한 번만 올린다.

```yaml
rules:
  shipping:
    kind: lookup
    label: "운송수단 · 출하조건"
    description: "고객코드로 refs/shipping.csv 를 조회한다. 행이 없으면 공란이다."
    table_file: refs/shipping.csv
    optional: true                 # 파일이 없어도 정상 동작한다
    key: meta.customer_no
    key_column: kunnr
    return: [vsart, zshco]
    on_no_match: { action: empty }   # ★ 공란. 경고도 띄우지 않는다 — 대부분의 고객이 여기다

fields:
  VSART: { from: expr, expr: 'shipping.vsart', required: warn,
           explain: "고객–운송수단 마스터(refs/shipping.csv)에서 가져옵니다" }
  ZSHCO: { from: expr, expr: 'shipping.zshco', required: warn,
           explain: "고객–출하조건 마스터(refs/shipping.csv)에서 가져옵니다" }
```

| 지금 | 바뀐 뒤 |
|---|---|
| `standard.yaml` `VSART: {from: const, value: "04"}` — 전 거래처 04 로 **박혀 있다** | 마스터 조회. 행이 없으면 공란 |
| `standard.yaml` `ZSHCO: {from: const, value: "", todo: ...}` | 마스터 조회 |
| `msc.yaml` `ZSHCO: {from: const, value: "A"}` | **삭제** — `shipping.csv` 100249 행이 대신한다 |
| `kl.yaml` `ZSHCO: {from: const, value: "", todo:}` | **삭제** — 마스터의 빈 칸이 곧 공란이다 |
| `ygjp.yaml` `ZSHCO: {from: expr, expr: 'if(in(brand_code,...))'}` | **유지**(예외). `brand_code` → `brand_by_text`/`ZBRAND` 참조로 이름만 맞춘다 |

**우선순위**: 거래처 YAML 의 명시 선언 > `shipping.csv` > 공란.
병합이 거래처 우선이라 자동으로 그렇게 된다 — 규칙을 따로 만들 필요가 없다.

### 5.3 검증 추가

| # | 검사 | 실패 시 |
|---|---|---|
| 16 | `shipping.csv` 에 같은 `kunnr` 가 두 번 나오는가 (1:1:1 위반) | **오류** — 어느 행이 이길지 알 수 없다 |
| 17 | `vsart`·`zshco` 가 둘 다 빈 행 | 리포트 (지워도 되는 행이다) |

> 값 자체의 유효성(SAP 에 등록된 VSART 인가)은 **검사하지 않는다.** 브랜드와 달리
> 코드 마스터를 받은 적이 없다. 받으면 `value_check` 와 같은 방식을 붙인다 — `todo:`.

### 5.4 관리 화면

브랜드 매핑 탭과 **같은 모양의 표 하나**를 추가하는 것이 자연스럽다 —
고객 한 줄, `VSART`·`ZSHCO` 두 칸. 다만 지금 당장 필요한지는 현업 판단이다.
**이번 범위에 넣지 않는다** (`SCHEMA.md` §6.1 의 도입 기준을 그대로 적용).
당분간 CSV 를 직접 고치고 Git 이력으로 남긴다. → `todo: 현업 편집 빈도 확인 후 결정`

---

## 6. KUNNR1 · KUNNR2 · KUNNR3 (`NEXT.md` §2-A ④)

### 6.1 무엇이 달라지나

```yaml
# profiles/standard.yaml
KUNNR1: { from: expr, expr: 'meta.customer_no', required: true }
KUNNR2: { from: expr, expr: 'meta.customer_no', required: warn,
          explain: "기본은 판매처와 같습니다. 출하처가 다른 거래처는 규칙이 덮어씁니다" }
KUNNR3: { from: expr, expr: 'meta.customer_no', required: true }
```

| 파일 | 지금 | 바뀐 뒤 | 비고 |
|---|---|---|---|
| `profiles/standard.yaml` | `KUNNR2: {from: const, value: "", todo: "거래처 파일에서 덮어쓸 것"}` | 위 선언 | **todo 가 사라진다** |
| `profiles/generic.yaml` | `KUNNR2: {from: const, value: "", required: warn, todo: ...}` | **선언을 지운다** (프로필 기본을 그대로 받는다) | |
| `customers/msc.yaml` | `KUNNR2: {from: table, table: ship_to_routing}` | **그대로** | 조건이 있는 예외 |
| `customers/kl.yaml` | `KUNNR2: {from: const, value: "107525", todo: "확인 필요"}` | **선언을 지운다** | 고객코드와 같은 값이다. 프로필 기본이 같은 값을 낸다 |
| `customers/ygjp.yaml` | `KUNNR2: {from: const, value: "319854"}` | **그대로** | 고객코드(3200)와 다르다 = 조건 |

`KUNNR2` 를 `required: warn` 으로 두는 이유: 값은 항상 채워지지만 **사람이 검수 중
지웠을 때 막지 않기 위해서다.** 빈 출하처를 보내는 것이 맞는 경우가 있을 수 있고,
그 판단은 검수자의 몫이다(P5). 대신 노랗게 보인다.

### 6.2 이것이 기존 금지 규정을 뒤집는다는 점

`CLAUDE.md` §5 는 "출하처를 판매처로 넣는 식"을 **명시적으로 금지**하고 있었고,
`profiles/generic.yaml` 머리말에도 같은 말이 적혀 있다. 이번 지시는 그 금지를
**KUNNR 한정으로** 푸는 것이다.

- 근거: 대다수 거래처에서 판매처 = 출하처 = 최종고객이고, **다르면 조건을 건다**(MSC).
  "모르는 값"이 아니라 "기본값이 있는 값"이라는 판단이다.
- 범위: **KUNNR1/2/3 에만 적용한다.** ZSHCO·VSART·ZBRAND 등 나머지 필드는
  금지 그대로 — 모르면 공란이다(§5.1 · §4.2).
- 문서: §2.3 의 §5 금지 목록 교체문과 `profiles/generic.yaml` 머리말을 함께 고친다.

---

## 7. 전송 필드 36 → 약 15 (제안만 · **확정 아님**)

> ⚠ **확정은 현업이 템플릿에서 한다.** 아래는 "지금 값이 채워지는 필드"를 기계적으로
> 센 것이고, SAP CBO 가 키로 요구하는 필드가 섞여 있을 수 있다. **이 표를 근거로
> `_base` 를 지우지 마라.** 현업·SAP 담당 확인 전까지 `_base` 는 36개 그대로 둔다.

### 7.1 값이 실제로 채워지는 필드 (16)

| 필드 | 채우는 곳 |
|---|---|
| AUART · VKORG | `_base` 공통 고정값 |
| KUNNR1 · KUNNR2 · KUNNR3 | §6 |
| BSTKD | 거래처별 발주번호 조합 |
| ZBRAND | §4 |
| ZSHCO · VSART | §5 |
| MATNR · KWMENG | 발주서 |
| ZPKRE2 · EMPST | 거래처별 비고 |
| WAERK | YGJP 만 (`JPY`) |
| POSEX | KL 만 (문서 인쇄 품목번호) |
| VTWEG | 공통 고정값이지만 **값이 `""`** |

### 7.2 뺄 후보 (20) — 전 거래처에서 `const ""`

```
VBELN  VDATU  ZTERM  INCO1  INCO2  ZPKRE1  MAKTX  LGORT  ETDAT  BATCH
VALTY  PRICE  BSTDK_E  DELCO  BSTKD_E  AUGRU  VKAUS  IHREZ_E  VGBEL  VGPOS
```

근거: `profiles/standard.yaml` 의 "미사용" 블록 그대로이며, 어느 거래처 파일도
덮어쓰지 않는다. 즉 **지금도 전부 빈 문자열로 전송되고 있다.**

### 7.3 현업에게 물어야 할 것

| 질문 | 왜 |
|---|---|
| `VTWEG` 를 빼도 되나 | 판매조직/유통경로는 SAP 오더의 키 조합이다. 값이 `""` 여도 **키 자리로 필요할 수 있다** |
| `VDATU` · `ETDAT`(납기) 를 정말 안 쓰나 | 발주서에 납기가 있는데 지금 안 보내고 있다. 의도인지 누락인지 확인이 필요하다 |
| `PRICE` · `WAERK` 를 안 보내도 되나 | YGJP 만 통화를 보낸다. 단가를 안 보내는 것이 정책인지 확인 |
| `POSEX` 가 없어도 CBO 가 행을 식별하나 | **미해결 갭이다** — MSC·YGJP 는 `POSEX: const ""` 라 행 식별자가 없고, 업서트 키가 없으면 재전송이 중복 적재가 된다 (`CLAUDE.md` §8) |

→ 확인 결과를 `NEXT.md` §5 미결 5번에 반영하고, **템플릿에서 열을 지우는 것으로** 끝낸다.

---

## 8. `NEXT.md` §2-B 미결 — 결론

| # | 미결 | 결론 | 근거 |
|---|---|---|---|
| 1 | SSOT 충돌 | **§2.1 의 3분할.** 템플릿=목록·순서 / `_base`=규격 / 거래처 YAML=값 | 권고안 그대로 채택. 충돌 지점은 §2.2 의 4경우로 전부 닫았다 |
| 2 | 직접 읽기 vs 가져오기 스크립트 | **직접 읽기.** 가져오기 스크립트는 만들지 않는다 | 현업이 고치면 바로 반영되길 원하신다. 실패 시 위험은 §3.4 폴백으로 닫는다. 대신 **점검 전용** `check_template.py` 를 둔다(읽기만, 비용 0) |
| 3 | 위치·Git | **`masters/templates/SALES ORDER.xlsx` · 추적한다** | 입력물이고 바뀌면 전송이 바뀐다. `.gitignore` 수정 불필요(§3.1) |
| 4 | "1개"의 기준 | **`brand_master.csv` 의 `kunnr` 행 수** | §4.2 |
| 5 | 복사·붙여넣기 | **미확인 — 브라우저로 확인해야 한다.** 절차·대안은 §8.2 | 문서로 단정할 수 없는 항목이다 |

### 8.1 (2번 보강) `check_template.py` 가 하는 일

```
$ python scripts/check_template.py
템플릿  masters/templates/SALES ORDER.xlsx  (시트: SALES ORDER, 2행)
읽은 필드 15개
  AUART VKORG KUNNR1 KUNNR2 KUNNR3 BSTKD ZBRAND ZSHCO MATNR KWMENG ZPKRE2 EMPST VSART WAERK POSEX
_base 에 규격이 없는 필드  : 없음
_base 에만 있고 안 보내는 필드: VBELN VDATU ZTERM ... (20개)
거래처별 선언 누락          : 없음
```
LLM 호출 없음 = 비용 0. `check.bat` 에 넣어 사내 서버에서 더블클릭으로 돈다.

### 8.2 (5번) 붙여넣기 확인 절차와 대안

**확인** — `ui/e2e/flow.mjs` 옆에 `ui/e2e/paste.mjs` 를 만들어 브라우저로 돌린다.

1. 모의 EAI + 스트림릿 기동 (`LLM_PROVIDER=mock` — 비용 0)
2. 엑셀에서 3행 × 2열을 복사한 것과 동일한 클립보드 페이로드
   (`text/plain`, 탭 구분 + 개행)를 `navigator.clipboard.writeText` 로 심는다
3. 그리드의 셀 하나를 클릭하고 `Ctrl+V`
4. **기대**: 3행 × 2열이 한 번에 채워진다 → 추가 작업 없음
5. 드롭다운(`SelectboxColumn`) 컬럼에 대해 같은 것을 한 번 더 — 여기가 막힐 가능성이 크다

**대안 (4·5 가 실패했을 때만 만든다)**

| 대안 | 내용 | 비용 |
|---|---|---|
| A | 드롭다운을 **쓰지 않고** `TextColumn` + `help` 에 후보를 나열 + 후보 밖 값에 🟡 | 작다. §4.4 검증이 이미 그 일을 한다 |
| B | 그리드 위에 **"열 일괄 채우기"** 한 줄 (컬럼 선택 + 값 + [채우기]) | 작다. 붙여넣기의 실제 용도 대부분이 이것이다 |
| C | "붙여넣기 상자" — textarea 에 TSV 를 붙이면 컬럼 매핑 후 반영 | 중간. A·B 로 안 될 때만 |

> 결론: **A·B 를 기본 대안으로 준비하고 C 는 보류.** 드롭다운과 붙여넣기가 충돌하면
> **붙여넣기를 살린다** — 드롭다운은 편의지만 대량 입력은 업무 속도 그 자체다.

---

## 9. 계약(`contracts/api-contract.md`) 변경

> 계약은 공용이다. **양쪽 합의 후 단독 PR.** 아래가 그 PR 의 전부다.

### 9.1 §3 `GET /api/masters/fields` — 템플릿 상태 추가

```json
{
  "fields": [ { "name": "AUART", "label": "오더유형", "sheet": "SALES ORDER TYPE", "max_len": 4 } ],
  "template": { "ok": "true", "source": "template",
                "path": "masters/templates/SALES ORDER.xlsx", "reason": "" }
}
```
`source` 는 `template` | `memory` | `base`. `ok` 가 `"false"` 면 화면이 배너를 띄운다.
`fields` 의 **순서가 곧 전송 순서**라는 문장을 "`_base` 의 순서 그대로"에서
"**유효 필드 목록 순서 그대로**"로 고친다.

### 9.2 §5 `GET /api/batches/{id}` — `choices` · `notes` 추가

```json
{
  "columns": ["AUART", "..."],
  "choices": { "ZBRAND": [ { "value": "205", "label": "ACCUPRO BRAND" } ] },
  "notes":   [ "템플릿에 있으나 규칙에 없는 필드: ZZTEST — 빈 값으로 전송됩니다" ],
  "grid":    { "pinned": [], "hidden": [], "width": {} }
}
```

| 키 | 규약 |
|---|---|
| `choices` | 필드명 → 후보 목록. **없는 필드는 키 자체가 없다** (빈 배열을 내리지 않는다 — "후보 없음"과 "후보 개념 없음"은 다르다) |
| `notes` | 배치 단위 안내 문구. 행 `issues` 와 구분된다. 비면 `[]` |

### 9.3 §6.1 병합 규약 — "모르는 컬럼" 의 기준

```
현재: | 모르는 컬럼 | **무시한다.** 전송 필드 목록은 `_base` 가 정한다 — 화면이 컬럼을 새로 만들 수 없다 |

교체: | 모르는 컬럼 | **무시한다.** 전송 필드 목록은 **템플릿 2행이 정한 유효 필드 목록**이다 — 화면이 컬럼을 새로 만들 수 없다 |
```

### 9.4 §8 `GET /api/health` — `template` 블록 추가

§9.1 과 같은 구조를 `"template"` 키로 넣는다.

### 9.5 예제 파일

`contracts/examples/fields.json` · `batch_msc.json` 을 위 형태로 갱신한다.
**프론트가 이 파일로 화면을 만든다** — 계약 문서만 고치고 예제를 두면 어긋난다.

---

## 10. `design.md` 반영 사항

> `design.md` 는 architect 소유다. 아래를 **그 문서 안에서** 고친다. 이 문서를 참조 링크로 걸지 않는다
> (SSOT 는 `design.md` 쪽이다. 이 문서는 근거 기록이다).

| 절 | 무엇을 |
|---|---|
| 머리말 SSOT 표 | `\| 전송 필드 목록 · 공통 고정값 \| **masters/_base/sap_defaults.yaml** \|` 행을 **두 행으로 쪼갠다** — ① `전송 필드 목록·순서` → `masters/templates/SALES ORDER.xlsx` 2행 ② `전송 필드 규격 · 공통 고정값` → `masters/_base/sap_defaults.yaml` |
| §0 핵심 설계 결론 | 이 문서 §0 의 **D12~D19 를 표에 그대로 덧붙인다.** D4("거래처별 전송 필드 전량 선언 강제")의 요약을 "필드 수는 `_base` 가 정한다 (현재 36)" → "**필드 목록은 템플릿이 정한다**" 로 고친다 |
| §2.3 저장소 표 | `참조표 \| CSV (Git) \| masters/refs/*.csv` 아래에 `전송 필드 템플릿 \| XLSX (Git) \| masters/templates/SALES ORDER.xlsx — **없으면 _base 로 폴백**` 을 추가 |
| §4 규칙 마스터 | `Excel/Sheets 마스터 \| △ 단순 룩업표(참조표)만 CSV로` 를 `○ **전송 필드 목록은 엑셀 템플릿이 원천**(D12). 룩업표는 CSV` 로 고친다 |
| §5 전송 | "`_base` 의 전송 필드 전량 포함(현재 36)" → "**유효 필드 목록 전량 포함**(템플릿 2행이 정한다)". 바로 아래 "필드 수 \| **코드에 하드코딩 금지.** `_base/sap_defaults.yaml` 이 유일한 원천" 행의 원천을 **템플릿**으로 고친다 |
| §6 검증 | `길이 초과 \| 🔴 \| field_specs.*.max_len` 옆에 "**규격이 없는(템플릿에만 있는) 필드는 길이 검사를 하지 않는다**" 를 덧붙인다. 표에 🟡 행 하나 추가: `후보 밖 값 \| 🟡 \| choices_from 이 있는 필드에 후보에 없는 값` |
| §7 디렉터리 | `masters/` 아래에 `templates/SALES ORDER.xlsx  ← 전송 필드 목록의 원천` · `refs/shipping.csv` 를 넣는다. `backend/app/masters/` 에 `template.py` 추가 |
| §10 미확정 항목 | ① 전송 필드 15개 확정(§7.3 의 질문 4개) ② `shipping.csv` 의 KL ZSHCO ③ 붙여넣기 브라우저 확인(§8.2) ④ VSART/ZSHCO 코드 마스터 유무 — 네 가지를 추가 |

---

## 11. 그 밖의 문서 반영 사항

### 11.1 `CLAUDE.md`

§2.3 에 **문장 그대로** 적어 두었다 (표 2행 교체 + 2행 추가, 굵은 문장 교체,
§5 금지 3행 추가 + 1행 문구 교체, §3 명령어 1줄 추가).
§4 구조 트리에도 `masters/templates/` · `refs/shipping.csv` · `backend/app/masters/template.py` 를 넣는다.

### 11.2 `masters/SCHEMA.md` (architect 소유)

| 절 | 무엇을 |
|---|---|
| §1 계층 구조 | 트리에 `templates/SALES ORDER.xlsx  ← 전송 필드 목록·순서의 원천` 과 `refs/shipping.csv` 추가 |
| §1.1 프로필 | "`fields` 와 `grid` 만 있다" → "**`rules` · `fields` · `grid` 를 가진다.** 전 거래처가 똑같이 쓰는 규칙(브랜드 후보·출하 마스터)은 여기 올린다. `meta`·`extraction` 은 없다" (§4.6) |
| §4.5 `rules` | `kind` 표에 **`csv_choice`** 한 줄 추가 + 전용 옵션 표(§4.3) |
| §4.6 `fields` | 머리말 "`_base/sap_defaults.yaml` 의 필드 전부가 선언되어야 한다(현재 36개)" → "**유효 필드 목록**(템플릿 2행)의 필드 전부가 선언되어야 한다. 템플릿에만 있는 필드는 로더가 빈 값으로 채우고 배치 노트로 알린다". 공통 옵션에 **`choices_from`** 추가 |
| §4.6 앞 | **§4.6a "유효 필드 목록"** 절을 새로 넣고 §2.1·§2.2 의 교집합 규칙·폴백 표를 옮긴다. ★ 이 절이 그 주제의 SSOT 가 된다 |
| §7 검증 | 검사 1 의 문구를 "유효 필드 목록 기준"으로 고치고, 검사 12~17(§3.6 · §5.3)을 등재 |

### 11.3 `process.md` §4 (화면 정의)

- 검수 화면에 **드롭다운 컬럼**이 생긴다는 것 (§4.8)
- 화면 상단 **템플릿 배너** (§3.5)
- 배치 **노트** 표시 위치 (계약 §9.2 의 `notes`)

### 11.4 `masters/profiles/generic.yaml` 머리말

"추측해서 채우지는 않는다" 단락에 **"단 KUNNR1/2/3 은 예외다(§2-A ④, 2026-09-21)"**
한 줄을 덧붙인다. 머리말과 실제 선언이 어긋나면 다음 사람이 선언을 되돌린다.

---

## 12. developer 작업 순서 ★

전제: 브랜치 `feat/be-rules`(백엔드·마스터·스크립트) · `contracts/**` 는 단독 PR.
**각 작업 단위가 끝날 때마다 커밋한다.** `rules:` 커밋은 본문에 근거(일자·지시자·영향 범위)를 남긴다.

### W0 — 계약 먼저 (단독 PR · 양쪽 합의)

| 파일 | 작업 |
|---|---|
| `contracts/api-contract.md` | §9.1~§9.4 반영 |
| `contracts/examples/fields.json` | `template` 블록 추가 |
| `contracts/examples/batch_msc.json` | `choices` · `notes` 추가 |

> 먼저 하는 이유: 화면과 백엔드가 이 파일을 동시에 본다. 나중에 고치면 둘 다 다시 고친다.

### W1 — 템플릿 리더 (§3)

| 순서 | 파일 | 작업 |
|---|---|---|
| 1 | `masters/templates/SALES ORDER.xlsx` | 실물 배치 (거래처 데이터 없는지 확인 후 커밋) |
| 2 | `.gitignore` | §3.1 의 주석 한 줄 |
| 3 | `backend/app/config.py` | `field_template: Path` · `field_template_sheet: str` 추가 |
| 4 | `backend/app/masters/template.py` | **신규.** `TemplateStatus` · `load_field_order(path, sheet)` · `(경로,mtime,size)` 캐시 · **예외를 올리지 않는다** |
| 5 | `backend/app/masters/loader.py` | `_apply_extends` 뒤에 `_apply_template()` — `field_specs` 를 템플릿 순서로 재구성 + 미선언 필드에 `{from: const, value: ""}` 주입 + `data["_template"] = status` |
| 6 | `backend/app/preview.py` | `field_list` 가 유효 목록을 쓰도록 (이미 `field_specs` 경유라 대부분 자동) |
| 7 | `backend/app/api/routes_masters.py` · `main.py` | `/api/masters/fields` · `/api/health` 에 `template` 블록 |
| 8 | `scripts/check_template.py` | **신규** (§8.1) · `use_utf8()` 잊지 말 것 |
| 9 | `check.bat` | `check_template.py` 호출 추가 (cp949 + CRLF) |
| 10 | `backend/tests/test_template.py` | **신규** — 정상 / 파일 없음 / 손상 / 2행 공백 / 중복 이름 / 템플릿에만 있는 필드가 🔴 를 만들지 않는지. **`_base` 개수를 박지 않는다** |

> ⚠ 기존 테스트 중 `list(base["field_specs"])` 를 기대값으로 쓰는 것
> (`test_engine.py:40` · `test_send.py:126` · `test_api_masters.py:46`)은
> **템플릿이 있으면 깨진다.** `conftest` 가 테스트용 마스터 사본을 쓰도록 하거나
> 기대값을 "유효 목록"에서 끌어오도록 고친다 — 개수·이름을 박지 않는다.

### W2 — 출하 마스터 (§5) · 가장 작고 위험이 낮다

| 순서 | 파일 | 작업 |
|---|---|---|
| 1 | `masters/refs/shipping.csv` | **신규** (§5.1 의 3행) |
| 2 | `masters/profiles/standard.yaml` | `rules.shipping` 추가 · `VSART`/`ZSHCO` 를 `expr` 로 |
| 3 | `masters/customers/msc.yaml` · `kl.yaml` | `ZSHCO` 선언 삭제 |
| 4 | `masters/customers/ygjp.yaml` | `ZSHCO` 유지(예외). 규칙 이름 변경에 맞춰 식 정리 |
| 5 | `scripts/validate_masters.py` | 검사 16·17 |
| 6 | `python scripts/validate_masters.py` + `pytest` | 골든 2종의 VSART·ZSHCO 가 그대로인지 확인 |

### W3 — 브랜드 단순화 (§4)

| 순서 | 파일 | 작업 |
|---|---|---|
| 1 | `backend/app/rules/mapping_rules.py` | `kind: csv_choice` 구현 · `RuleOutcome` 에 `choices` 추가 |
| 2 | `backend/app/rules/engine.py` | 후보를 배치 단위로 모아 `BuildResult.choices` |
| 3 | `backend/app/domain/models.py` | `BuildResult.choices` · `Batch.choices` · `Batch.notes` |
| 4 | `backend/app/mapping/row_builder.py` · `validation/validator.py` | `choices_from` 필드 옵션 · 🟡 `NOT_IN_CHOICES` |
| 5 | `masters/profiles/standard.yaml` | `rules.brand_pick` · `ZBRAND` 선언 |
| 6 | `masters/profiles/generic.yaml` | `rules.brand_code`(csv_map) **삭제** — 프로필의 `brand_pick` 을 그대로 쓴다 |
| 7 | `masters/customers/msc.yaml` · `ygjp.yaml` | `brand_code` → `brand_by_text` 로 이름 변경 · `on_no_match: {action: empty}` · `ZBRAND` 를 `coalesce` 식으로 |
| 8 | `backend/app/preview.py` | `csv_choice` 규칙 카드 (후보 표) |
| 9 | `backend/app/api/routes_batches.py` · `batch_service.py` | 계약 §9.2 의 `choices`·`notes` 를 응답에 |
| 10 | `scripts/validate_masters.py` | `csv_choice` 스키마 검사 · TODO 리포트 범위 축소(§4.7) |
| 11 | `backend/tests/` | `csv_choice` 1건/N건/0건 · `coalesce` 체인 · `NOT_IN_CHOICES`. **개수를 참조표에서 끌어온다** |

### W4 — KUNNR 기본값 (§6) · YAML 만

| 순서 | 파일 |
|---|---|
| 1 | `masters/profiles/standard.yaml` — `KUNNR2` 선언 교체 |
| 2 | `masters/profiles/generic.yaml` — `KUNNR2` 선언 삭제 + 머리말 한 줄(§11.4) |
| 3 | `masters/customers/kl.yaml` — `KUNNR2` 선언 삭제 |
| 4 | `python scripts/validate_masters.py` · `pytest` (골든 diff 확인) |

### W5 — 화면 (§4.8 · §3.5)

| 순서 | 파일 | 작업 |
|---|---|---|
| 1 | `ui/service.py` | `choices` · `notes` · `template` 상태 전달 |
| 2 | `ui/views/convert.py` | 드롭다운 컬럼 · 템플릿 배너 · 배치 노트. **필드 이름을 하드코딩하지 않는다** |
| 3 | `ui/e2e/paste.mjs` | **신규** (§8.2 의 확인) |
| 4 | `backend/tests/test_ui_*.py` | 후보에 없는 값이 셀에 있어도 예외가 안 나는지 (§4.8) |

### W6 — 문서 (architect 가 한다)

`design.md`(§10) · `masters/SCHEMA.md`(§11.2) · `CLAUDE.md`(§2.3·§11.1) ·
`process.md`(§11.3) · `NEXT.md`(§2-B 를 "해결됨"으로 닫고 §5 에 새 미결 옮김).

### W7 — 관통 확인

```bash
python scripts/check_template.py
python scripts/validate_masters.py
pytest && ruff check backend scripts
python scripts/mock_eai_server.py &
streamlit run po2sap.py            # 업로드 → 드롭다운 → 붙여넣기 → 전송
node ui/e2e/flow.mjs && node ui/e2e/paste.mjs
```
전송 페이로드의 **키 순서가 템플릿 2행 순서와 같은지** 눈으로 확인한다.

---

## 13. 남은 `todo:`

| # | 항목 | 어디에 적어 둘 것인가 |
|---|---|---|
| 1 | 전송 필드 15개 **확정** (§7.3 의 질문 4개) | `NEXT.md` §5-5 |
| 2 | `shipping.csv` 의 KL `ZSHCO` | `masters/refs/shipping.csv` 의 `note` |
| 3 | VSART/ZSHCO **코드 마스터**를 SAP 에서 받을 수 있나 (받으면 `value_check`) | `NEXT.md` §5 |
| 4 | `st.data_editor` 붙여넣기 · 드롭다운 동시 동작 (§8.2) | `NEXT.md` §5 |
| 5 | 행마다 후보가 달라지는 요구 (§4.4) | `SCHEMA.md` §4.6a 각주 |
| 6 | 출하 마스터 **관리 화면** 필요 여부 (§5.4) | `SCHEMA.md` §6.1 기준 재적용 |
| 7 | CBO **업서트 키** — `POSEX` 를 빼도 되는가와 직결 (§7.3) | `CLAUDE.md` §8 (이미 등재) |
| 8 | 템플릿 **1행**을 `label` 로 쓸 수 있나 (지금은 `_base` 의 한글 label 사용) | `SCHEMA.md` §4.6a |
