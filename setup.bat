@echo off
rem ============================================================
rem   po2sap - 최초 1회 설치
rem   이 파일을 더블클릭하면 파이썬 가상환경과 라이브러리를 준비합니다.
rem ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   po2sap 설치
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [오류] 파이썬이 설치되어 있지 않습니다.
    echo.
    echo        https://www.python.org/downloads/ 에서 받아 설치하세요.
    echo        설치할 때 "Add python.exe to PATH" 를 반드시 체크하세요.
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    echo 가상환경이 이미 있습니다. 라이브러리만 갱신합니다.
) else (
    echo 가상환경을 만듭니다 ^(.venv^) ...
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경을 만들지 못했습니다.
        pause
        exit /b 1
    )
)

echo.
echo 라이브러리를 설치합니다. 몇 분 걸릴 수 있습니다 ...
echo.
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo [오류] 라이브러리 설치가 실패했습니다.
    echo        사내망이면 프록시 설정이 필요할 수 있습니다.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo .env 파일이 없어 .env.example 에서 복사합니다.
    copy /y ".env.example" ".env" >nul
    echo.
    echo [확인 필요] 메모장으로 .env 를 열어 아래를 채우세요.
    echo.
    echo    LLM_PROVIDER          mock ^(무료 재생^) 또는 anthropic
    echo    LLM_API_KEY           anthropic 일 때만
    echo    MASTER_EDIT_PASSWORD  브랜드 매핑을 고칠 때 물어볼 암호
    echo    EAI_ENDPOINT          전송 받을 주소
    echo.
)

echo.
echo ============================================================
echo   설치가 끝났습니다.
echo.
echo   다음: check.bat 으로 설정을 점검한 뒤 run.bat 으로 실행하세요.
echo ============================================================
echo.
pause
