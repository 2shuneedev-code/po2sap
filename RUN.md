# 실행 방법 — 화면 띄우기

> 명령어 전체 목록은 `CLAUDE.md` §3. 이 문서는 **화면을 띄워 실물 발주서를 넣어 보는 절차**만 다룬다.

---

## 1. 가장 쉬운 방법 (윈도우 더블클릭)

| 순서 | 파일 | 하는 일 |
|---|---|---|
| 최초 1회 | `setup.bat` | 가상환경 · 라이브러리 · `.env` 생성 |
| 매번 | `check.bat` | API 연결 · 마스터 검증 (비용 0) |
| 매번 | `run.bat` | 화면 실행 → 창에 뜬 주소를 브라우저에 직접 입력 |
| 전송 시험 시 | `run-mock-eai.bat` | 모의 EAI (**다른 창에서** 함께 켜 둔다) |

브라우저는 **자동으로 열리지 않는다.** `http://localhost:8501` 을 직접 연다.

---

## 2. 터미널에서 (PowerShell)

```powershell
cd C:\vibe-coding\po2sap
.\.venv\Scripts\Activate.ps1

python scripts/check_llm.py            # 키·모델 ID 확인 (메시지 전송 없음 = 비용 0)
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

## 4. 실제 Claude API 로 시험할 때

`.env` 에서 이 줄들만 확인한다.

```ini
LLM_PROVIDER=anthropic         # mock 이면 저장된 응답만 재생 (비용 0)
LLM_API_KEY=sk-ant-...         # 채팅·커밋에 절대 붙이지 않는다
LLM_MODEL_EXTRACT=claude-opus-5
LLM_EFFORT=medium
EAI_ENDPOINT=http://127.0.0.1:9000/po2sap/order   # 모의 서버. 실서버로 바꾸지 않는다
```

순서 — **돈이 드는 단계는 마지막**에:

```powershell
python scripts/check_llm.py                                         # 1. 연결 (무료)
python scripts/check_sample.py samples/<파일> --customer <코드>       # 2. hints 대조 (무료)
python scripts/parse_one.py samples/<파일> --customer <코드> --text-only   # 3. 전처리 (무료)
python scripts/parse_one.py samples/<파일> --customer <코드> --rows  # 4. 실제 호출 (과금)
streamlit run po2sap.py                                             # 5. 화면에서 검수→전송
```

- 같은 문서는 두 번째부터 **응답 캐시**가 재생된다 (재호출·재과금 없음)
- 모델을 `claude-opus-5-5` 로 바꾸면 **지금 코드로는 모든 추출이 400** 이다
  (강제 `tool_choice` 미지원). 코드 수정 후에 바꾼다
- 사람 앞에서 시연할 때는 라이브 호출 대신 `pin_fixture.py` 로 박은 픽스처를 쓴다
