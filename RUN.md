# 실행 방법 — 화면 띄우기

> 명령어 전체 목록은 `CLAUDE.md` §3. 이 문서는 **화면을 띄워 실물 발주서를 넣어 보는 절차**와 **사내 서버 설치·서버에서 개발하기**(§5·§6)를 다룬다.

---

## 1. 가장 쉬운 방법 (윈도우 더블클릭)

| 순서 | 파일 | 하는 일 |
|---|---|---|
| 최초 1회 | `setup.bat` | 가상환경 · 라이브러리 · `.env` 생성 |
| 매번 | `run.bat` | 화면 실행 → 창에 뜬 주소를 브라우저에 직접 입력 |
| 전송 시험 시 | `run-mock-eai.bat` | 모의 EAI (**다른 창에서** 함께 켜 둔다) |

브라우저는 **자동으로 열리지 않는다.** `http://localhost:8501` 을 직접 연다.

---

## 2. 터미널에서 (PowerShell)

```powershell
cd C:\vibe-coding\po2sap
.\.venv\Scripts\Activate.ps1

streamlit run po2sap.py                # → http://localhost:8501
```

전송까지 시험하려면 **다른 터미널**에서:

```powershell
.\.venv\Scripts\python.exe scripts/mock_eai_server.py
```

---

## 3. localhost 가 안 열릴 때

| 증상 | 원인 | 해결 |
|---|---|---|
| `python po2sap.py` 로 실행했더니 경고 몇 줄 뜨고 끝남 | 스트림릿 앱은 **`python` 으로 직접 실행하면 서버가 안 뜬다** (`missing ScriptRunContext` 경고만 나오고 종료) | `streamlit run po2sap.py` 또는 `run.bat` |
| `streamlit` 명령을 못 찾음 | 가상환경이 안 켜짐 | `.\.venv\Scripts\Activate.ps1` 후 다시, 또는 `.\.venv\Scripts\python.exe -m streamlit run po2sap.py` |
| 브라우저가 안 열림 | 의도된 설정 (`.streamlit/config.toml` 의 `headless = true`) | 주소를 직접 입력. **이 설정은 끄지 않는다** — 끄면 서버에서 이메일 입력을 기다리며 멈춘다 |
| `http://0.0.0.0:8501` 로 접속이 안 됨 | `0.0.0.0` 은 "모든 주소에서 받는다"는 뜻이지 접속 주소가 아니다 | 이 PC 에서는 `http://localhost:8501`, 다른 PC 에서는 `http://<이 PC의 IP>:8501` |
| `Port 8501 is already in use` | 이미 하나 떠 있음 | 그 창을 닫거나 `run.bat 8502` / `--server.port 8502` |
| 다른 PC 에서만 안 열림 | 윈도우 방화벽 | 8501 인바운드 허용, 또는 사내 IT 요청 |
| 화면이 떴는데 빨간 트레이스백 | 코드·마스터 오류 | 터미널 로그 확인, `python scripts/validate_masters.py` |

**정상 기동 확인** — 터미널에 아래가 나오면 서버는 떠 있는 것이다.

```
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
```

또는 `curl http://localhost:8501/_stcore/health` → `ok`

---

## 4. 실제 Claude API 로 시험

`.env`:

```ini
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL_EXTRACT=claude-opus-5
LLM_EFFORT=medium
```

바로 돌린다:

```powershell
python scripts/parse_one.py samples/<파일> --customer <코드> --rows   # 단건, 36필드 출력
streamlit run po2sap.py                                             # 화면에서 업로드→검수→전송
```

- 같은 문서를 다시 넣으면 응답 캐시가 재생된다. 새로 부르고 싶으면 `LLM_PROMPT_VERSION` 을 올린다
- `claude-opus-5-5` 는 지금 코드로는 400 이다 (강제 `tool_choice` 미지원) — 코드 수정 후에 바꾼다

---

## 5. 사내 서버 설치 (신규 윈도우 서버)

> 설정 항목의 뜻은 `.env.example` 의 주석이 원천이다. 여기서는 순서만 적는다.

**미리 받아 둘 것 (IT)** — 아웃바운드 `api.anthropic.com`·`pypi.org`·`files.pythonhosted.org`·`github.com` (443),
EAI 주소까지의 경로, 사내 프록시·CA(.pem) 가 있으면 그 정보, 서버 고정 IP · 8501 인바운드.

| 순서 | 할 일 | 비고 |
|---|---|---|
| 1 | [Python 3.12](https://www.python.org/downloads/) 설치 | **"Add python.exe to PATH" 체크**. 설치 후 PowerShell 을 새로 연다 |
| 2 | [Git for Windows](https://git-scm.com/download/win) 설치 | 기본값 그대로. `git --version` 이 안 되면 창을 새로 연다 |
| 3 | `cd C:\` → `git clone https://github.com/2shuneedev-code/po2sap.git` | 서버는 **`main`** 을 따라간다 |
| 4 | `cd po2sap` → `.\setup.bat` | PowerShell 에서는 앞에 `.\` 가 필요하다. pip 이 프록시에 막히면 cmd 에서 `set HTTPS_PROXY=...` 후 실행 |
| 5 | `notepad .env` | `.env.example` 을 복사한 그대로 쓰고 값만 채운다. 개발 PC 의 낡은 `.env` 를 가져오지 않는다 |
| 6 | `.\check.bat` | API 연결(비용 0) · 마스터 검증 |
| 7 | `.\run.bat` → 다른 PC 에서 `http://서버IP:8501` | 안 열리면 §3 방화벽 |

`.env` 에서 최소한 채울 것: `LLM_PROVIDER` · `LLM_API_KEY` · `MASTER_EDIT_PASSWORD` · `EAI_ENDPOINT`.
프록시·사내 CA 는 `LLM_PROXY` · `LLM_CA_BUNDLE` · `EAI_CA_BUNDLE` 에 넣는다 (`HTTPS_PROXY` 는 앱이 읽지 않는다).
`MASTER_GIT_AUTOPUSH=true` 는 서버 Git 에 푸시 권한(PAT)을 넣은 뒤에 켠다.

**Git 에 없어서 따로 옮길 것** — `samples/`(대외비. 공유폴더·원격 데스크톱 복사로. **Git 으로 올리지 않는다**),
`storage/llm_cache/`(선택. 이미 읽은 문서를 다시 넣을 때 비용 0).

### 상시 실행 (재부팅·로그아웃에도 유지)

`run.bat` 은 창을 닫거나 로그아웃하면 같이 꺼진다. 작업 스케줄러에 등록한다.

| 탭 | 설정 |
|---|---|
| 일반 | "사용자의 로그온 여부에 관계없이 실행" · "가장 높은 수준의 권한으로 실행" |
| 트리거 | 시작할 때 |
| 동작 | 프로그램 `C:\po2sap\.venv\Scripts\python.exe` · 인수 `-m streamlit run po2sap.py --server.address 0.0.0.0 --server.port 8501` · **시작 위치 `C:\po2sap`** (빠뜨리면 `.env`·`masters/` 를 못 찾는다) |
| 설정 | "다음 시간 이상 작업이 실행되면 중지" **해제** (기본 3일) |

### 업데이트

1. 작업 중지 → 2. `git status` 로 현업이 고친 마스터가 있으면 화면의 Git 동기화로 먼저 푸시
→ 3. `git pull` → 4. `.\setup.bat` (라이브러리만 갱신) → 5. `.\check.bat` → 6. 작업 시작

서버에서 `git checkout .` · `git clean` 은 쓰지 않는다 (CLAUDE.md §5). 백업 대상은 `.env` 와 `storage/`.

---

## 6. 서버에서 개발하기 (Claude Code)

개발 PC 에서 서버 파일을 원격으로 고치지 않는다 — 테스트가 PC 의 파이썬으로 돌아 서버 환경과 어긋난다.
**서버에 Claude Code 를 설치해 서버 안에서 작업한다.**

### 폴더 두 개 — 운영은 직접 고치지 않는다

```
C:\po2sap       운영  8501  현업이 쓰는 화면. 여기서 수정하지 않는다
C:\po2sap-dev   개발  8502  Claude 로 수정·확인
```

운영 폴더를 바로 고치면 반쯤 고친 상태가 현업 화면에 그대로 보이고, 틀린 규칙으로 오더가 나갈 수 있다.

### 설치 (최초 1회)

```powershell
irm https://claude.ai/install.ps1 | iex          # Claude Code. 설치 후 창을 새로 연다

cd C:\
git clone https://github.com/2shuneedev-code/po2sap.git po2sap-dev
cd po2sap-dev
.\setup.bat
copy ..\po2sap\.env .env
xcopy /e /i ..\po2sap\samples samples
notepad .env    # ★ EAI_ENDPOINT 를 모의 서버(http://127.0.0.1:9000/po2sap/order)로 바꾼다
```

- 개발 쪽 `.env` 의 `EAI_ENDPOINT` 를 모의 서버로 두지 않으면 **시험 중에 진짜 오더가 나간다**
- 개발 쪽은 `MASTER_GIT_AUTOPUSH=false` 로 둔다. 마스터의 원천은 운영 화면이다
- `CLAUDE.md` · `.claude/agents/` 는 저장소에 있어 따라온다. 개발 PC 의 Claude 기억
  (`%USERPROFILE%\.claude\projects\<경로>\memory\`)은 따라오지 않으니 필요하면 복사한다

### 작업 흐름

```powershell
cd C:\po2sap-dev
git pull                     # 현업이 운영 화면에서 고친 마스터를 받는다
claude                       # 수정
pytest                       # 확인
.\run.bat 8502               # 화면 확인 (모의 EAI 는 run-mock-eai.bat)
git push origin HEAD:main    # 올린다
```

그다음 §5 "업데이트" 절차로 운영 폴더(`C:\po2sap`)에 반영한다.

**핸드폰·다른 PC 에서 이어 하기** — 서버의 Claude Code 에서 `/remote-control` 을 켜고
Claude 앱(Code 탭)에서 그 세션을 연다. 서버의 Claude Code 창을 닫으면 세션도 끝난다.
