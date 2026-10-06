# 거래처별 하드코딩 로직 정리 (MSC / KL / YGJP)

> 기준 파일: `app.py`, `parsers/*.py`, `generators/*.py`

---

## 0. 세 고객에 공통으로 적용되는 고정값

**S/O 업로드** (`generators/so_upload.py`)

| 필드 | 값 |
|---|---|
| AUART | `ZEXP` |
| VKORG | `1000` |
| KUNNR1, KUNNR3 | 고객코드 (없으면 기본값 `100249`) |
| BSTKD | `PO번호(Location)`. Location이 없으면 `PO번호`만 들어감 |
| ZBRAND | 아이템별 brand가 우선이고, 없으면 헤더 brand |
| MATNR / KWMENG | `your_item` / `qty` |
| POSEX | 아이템에 `posex` 값이 있을 때만 기입 |

**사전점검** (`generators/pre_check.py`)

- Sales Org는 `1000`, Unit은 `PC`로 고정
- 8번째 열 헤더를 `"Your Code"`로 덮어씀

**공통으로 비어 있는 컬럼**

- PRICE, WAERK, VDATU, ZTERM, INCO, ETDAT 등은 어떤 고객에서도 채우지 않음
- 단가는 파싱되지만 S/O 파일에는 들어가지 않음

---

## 1. MSC (MSC Industrial Supply, 고객코드 `100249`)

**입력 형식:** HTM/HTML (`parsers/htm_msc.py`)

| 항목 | 하드코딩 로직 |
|---|---|
| PO 번호 | `<title>`에 있는 첫 번째 숫자 |
| 브랜드 (ZBRAND) | 헤더의 `ORDERED FROM` 텍스트에서 키워드를 순서대로 찾음: HERTEL→`38`, INTERSTATE→`127`, ACCUPRO→`205`, CLASS C→`428`. 매칭되지 않으면 빈 값 |
| Location | SHIP TO 텍스트에 ATLANTA / ELKHART / HARRISBURG / RENO 중 하나가 있는지로 판단 |
| 멀티 SHIP TO | SHIP TO에 `CHECK COMPLETE`가 있으면 `<p class="req">` 섹션마다 location을 따로 잡고, 각 섹션의 3번째 `potbl`을 아이템 테이블로 읽음 |
| 일반형 | `potbl[2]`를 아이템 테이블로 읽음. 열 순서: qty / our_item / your_item / desc / price |
| 날짜 | `potbl[0]`의 1행에서 주문일과 선적일을 읽음 (원문 그대로) |
| POSEX | 기입하지 않음 |

**S/O 업로드 전용 값**

| Location | KUNNR2 | ZPKRE2 (기본) |
|---|---|---|
| ELKHART | 100249 | C |
| HARRISBURG | 319677 | N |
| RENO | 319678 | O |
| ATLANTA | 319679 | A |

- ZSHCO는 `A`, VSART는 `04`로 고정
- **MSC_REF.xlsx 연동:** `our_item`이 REF 파일의 A열과 일치하면 ZPKRE2를 `기본값,B열,C열` 형태로 이어 붙임 (예: `C,X,Y`)

---

## 2. KL (Kennametal, 고객코드 `107525`)

**입력 형식:** PDF (`parsers/pdf_kl.py`)

| 항목 | 하드코딩 로직 |
|---|---|
| 브랜드 (ZBRAND) | **`2` (OEM)로 고정** |
| PO 번호 | `Document No. 4507628839 / 040`에서 `/` 앞부분만 사용 |
| 주문일 | `Date 2026.05.11`을 `20260511`로 변환 |
| 아이템 인식 | `0dddd Kennametal Mat. No.: nnn  qty PC price value` 패턴 |
| POSEX | 아이템 번호 `00001`을 정수 `1`로 변환 |
| MATNR (`your_item`) | **항상 빈 값** (주석: "SAP 자재코드 매칭 불가") |
| Your Code (`our_item`) | Kennametal Mat. No. |
| 품명 | 아이템 헤더 바로 다음 줄 |
| Brand 원문 | `Brand:` 줄의 값. ZPKRE2와 EMPST 판단에 사용 |

**S/O 업로드 전용 값**

- Brand 원문에 `WIDIA GTD`가 있으면 ZPKRE2와 EMPST에 `WGT`
- Brand 원문에 `KENNAMETAL`이 있으면 `KMT`, 둘 다 없으면 빈 값
- VSART는 `04`로 고정
- KUNNR2와 ZSHCO는 기입하지 않음

---

## 3. YGJP (YG-1 JAPAN, 고객코드 `3200`)

**입력 형식:** PDF (`parsers/pdf_ygjp.py`). 출력 파일이 하나 더 있음 (PO정리 Excel, `generators/ygjp_po.py`)

| 항목 | 하드코딩 로직 |
|---|---|
| PO 번호 | `01-{Created On YYYYMMDD}-{Purchase Order ID}` |
| 통화 | 헤더에 `JPY`로 저장됨. S/O 파일에는 들어가지 않음 |
| 브랜드 | `Total Quantities:` 이후 줄 중에서 BRAND_MAP의 25개 텍스트(YG BRAND→`1` … NEW CENTURY BRAND(COMINIX)→`507`)와 **정확히 일치하는** 줄 |
| PACKING SPEC | 브랜드 줄의 바로 다음 줄 |
| REMARK | `#N 텍스트`는 라인 N에 매핑. `#`이 없는 첫 줄은 기본 remark로 전체 라인에 적용 (2페이지 내용이 섞이지 않도록 첫 줄만 사용) |
| 하단 스킵 | `signature`, `approval`, `yg-1 japan`, `yg-1 co`, `total `로 시작하는 줄 |
| 테이블 | 헤더 행에 `NO`와 `PRODUCT`가 있는 테이블만 읽고, 컬럼은 키워드로 매핑 |
| 매핑 | Product ID→MATNR, Your Code→our_item, Dimensions→desc |
| 제외 조건 | Product ID가 없거나 수량이 0인 라인 |

**YGJP 브랜드 코드표 (BRAND_MAP)**

| 브랜드 텍스트 | 코드 | 브랜드 텍스트 | 코드 |
|---|---|---|---|
| YG BRAND | 1 | YAMA-K | 439 |
| YAMAKATSU BRAND | 142 | NIKKO KIZAI 별도 | 448 |
| YSK BRAND | 181 | YG BRAND 별도 | 449 |
| YMKT BRAND | 183 | YAMAKATSU 별도 | 450 |
| YCS BRAND | 209 | KUMAZAWA | 465 |
| NIKKO KIZAI BRAND | 227 | YG BRAND (COMINIX) | 471 |
| SUGIMOTO BRAND | 245 | SAKUSAKU BRAND | 476 |
| KURODA BRAND | 248 | YG BRAND (SAKUSAKU) | 477 |
| SAKANOSHITA BRAND | 249 | YG BRAND (YGT Y) | 480 |
| DAIWA SHOKAI | 250 | YG BRAND (CHUO KOKI) | 481 |
| TOSA KIKO BRAND | 411 | YG BRAND (IBIDEN) | 482 |
| CHUO KOKI BRAND | 412 | NEW CENTURY BRAND(COMINIX) | 507 |
| SIAM YAMAKATSU BRAND | 435 | | |

**S/O 업로드 전용 값**

- KUNNR2는 `319854`, VSART는 `04`로 고정
- ZSHCO는 브랜드가 `471`(YG BRAND (COMINIX)) 또는 `507`(NEW CENTURY BRAND(COMINIX))이면 `A`, 그 외에는 `L`

**PO정리 Excel**

- 템플릿에서 `PO NO` 헤더가 있는 행을 찾아 컬럼명 기준으로 값을 채움

---

## 4. 한눈에 비교 (S/O 고객별 분기)

| | MSC | KL | YGJP |
|---|---|---|---|
| KUNNR2 | Location별 4개 | – | 319854 |
| ZBRAND | Ordered From 키워드 | 2 고정 | PDF 하단 브랜드 텍스트 |
| ZSHCO | A | – | 471/507이면 A, 그 외 L |
| ZPKRE2 | Location 코드 + REF | WGT / KMT | – |
| EMPST | – | WGT / KMT | – |
| VSART | 04 | 04 | 04 |
| POSEX | – | O | O |
| BSTKD | PO(Location) | PO | PO |
| MATNR | O | **빈 값** | O |

---

## ⚠️ 확인이 필요한 부분

1. **KL의 MATNR이 항상 빈 값.** 사전점검의 Material 열과 S/O의 MATNR이 모두 비어 있음. 파일 상단 docstring에는 "our_item = MFG. Cat. No. (YG-1 자재번호)"라고 적혀 있지만, 실제 코드는 Kennametal Mat. No.를 넣음. `mfg_cat`은 파싱만 하고 쓰지 않음 (`parsers/pdf_kl.py`). 의도한 동작인지 확인 필요
2. **KL 브랜드 58이 처리되지 않음.** `generators/so_upload.py`의 주석에는 "KL: 2/58 아이템 레벨"이라고 되어 있지만, 실제로는 `2`만 고정으로 들어감
3. **MSC에서 키워드나 도시 이름이 매칭되지 않으면 경고가 없음.** ZBRAND, KUNNR2, ZPKRE2가 빈 칸인 채로 파일이 생성됨
4. **YGJP 브랜드는 공백 정규화 후 완전히 일치해야만 인식됨.** 표기가 조금만 달라도 브랜드, PACKING SPEC, REMARK가 전부 빈 값이 됨
5. **`parsers/pdf_yg1.py`는 사용되지 않는 코드.** `PARSER_MAP`에 등록되어 있지 않음 (EUR, PO 번호에 `PO` 접두사 형식)
