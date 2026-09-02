@echo off
REM ===================================================================
REM  POSTester 빌드 스크립트 (Windows 전용)
REM
REM  사용법: 이 파일을 더블클릭하거나, 명령 프롬프트에서 build.bat 실행
REM  결과물: dist\POSTester.exe
REM
REM  파이썬 3.10 이상이 설치되어 있어야 합니다.
REM  https://www.python.org/downloads/  (설치 시 "Add python.exe to PATH" 체크)
REM ===================================================================
setlocal
chcp 65001 > nul
cd /d "%~dp0\.."

echo.
echo ============================================
echo   POSTester 빌드
echo ============================================
echo.

REM --- 1. 파이썬 확인 -------------------------------------------------
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] 파이썬을 찾을 수 없습니다.
    echo        https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요.
    echo        설치할 때 "Add python.exe to PATH" 를 반드시 체크하세요.
    goto :fail
)
for /f "tokens=*" %%v in ('python --version') do echo [1/5] %%v 확인

REM --- 2. 가상환경 ----------------------------------------------------
if not exist ".venv" (
    echo [2/5] 가상환경 만드는 중...
    python -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [2/5] 기존 가상환경 사용
)
call .venv\Scripts\activate.bat

REM --- 3. 의존성 ------------------------------------------------------
echo [3/5] 필요한 패키지 설치 중... (처음 한 번은 몇 분 걸립니다)
python -m pip install --upgrade pip --quiet
python -m pip install --quiet -r requirements-build.txt
if errorlevel 1 goto :fail

REM --- 4. 아이콘 ------------------------------------------------------
echo [4/5] 아이콘 준비 중...
if not exist "build\icon.ico" (
    python build\make_icon.py
    if errorlevel 1 goto :fail
) else (
    echo       build\icon.ico 이미 있음
)

REM --- 5. 빌드 --------------------------------------------------------
echo [5/5] exe 빌드 중... (2~4분 걸립니다)
if exist "dist\POSTester.exe" del /q "dist\POSTester.exe"
python -m PyInstaller --clean --noconfirm build\POSTester.spec
if errorlevel 1 goto :fail

if not exist "dist\POSTester.exe" (
    echo [오류] 빌드는 끝났지만 dist\POSTester.exe 가 없습니다.
    goto :fail
)

echo.
echo ============================================
echo   빌드 완료
echo ============================================
for %%f in ("dist\POSTester.exe") do echo   파일: %%~ff
for %%f in ("dist\POSTester.exe") do set /a SIZE_MB=%%~zf/1048576
for %%f in ("dist\POSTester.exe") do echo   크기: %%~zf 바이트 (약 %SIZE_MB% MB)
echo.
echo   이 파일 하나만 USB 에 복사하면 됩니다.
echo   파이썬이 없는 PC 에서도 그대로 실행됩니다.
echo.
pause
exit /b 0

:fail
echo.
echo ============================================
echo   빌드 실패
echo ============================================
echo   위의 오류 메시지를 확인하세요.
echo.
pause
exit /b 1
