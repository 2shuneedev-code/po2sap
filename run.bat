@echo off
rem ============================================================
rem   po2sap - 화면 실행 (사내 공개)
rem   이 창을 닫으면 화면도 함께 꺼집니다.
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [오류] 가상환경이 없습니다. setup.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [오류] .env 파일이 없습니다. setup.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

set "PORT=8501"
if not "%~1"=="" set "PORT=%~1"

echo.
echo ============================================================
echo   po2sap  발주서 변환 화면
echo ============================================================
echo.
echo   이 PC 에서      http://localhost:%PORT%
rem 순수 리터럴 검색 - 한국어 윈도우의 "IPv4 주소 . . . : 192.168.0.10" 도 잡는다.
rem   /r 과 /c: 를 섞으면 동작이 애매해져 쓰지 않는다.
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=* delims= " %%B in ("%%A") do echo   사내에서       http://%%B:%PORT%
)
echo.
echo   끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo ============================================================
echo.

findstr /i /c:"EAI_ENDPOINT=http://127.0.0.1" ".env" >nul 2>&1
if not errorlevel 1 (
    echo [안내] EAI 주소가 모의 서버로 되어 있습니다.
    echo        전송까지 시험하려면 다른 창에서 run-mock-eai.bat 도 실행하세요.
    echo.
)

.venv\Scripts\python.exe -m streamlit run po2sap.py --server.address 0.0.0.0 --server.port %PORT%

echo.
echo 화면이 종료되었습니다.
pause
