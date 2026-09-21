@echo off
rem ============================================================
rem   po2sap - 모의 EAI 서버 (시험용)
rem   실제 EAI 없이 전송 구간까지 관통해 볼 때만 씁니다.
rem   실서버로 전송할 때는 이 파일을 실행하지 마세요.
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [오류] 가상환경이 없습니다. setup.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   모의 EAI 서버  http://127.0.0.1:9000/po2sap/order
echo.
echo   받은 전송 내용은 storage\mock_eai\ 에 쌓입니다.
echo   끄려면 Ctrl+C 를 누르거나 창을 닫으세요.
echo ============================================================
echo.

.venv\Scripts\python.exe scripts\mock_eai_server.py

echo.
pause
