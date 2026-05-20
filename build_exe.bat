@echo off
title Build Dalda Outlet Matcher EXE
cd /d "%~dp0"

echo ============================================================
echo  Building standalone Dalda Outlet Matcher (no pip needed)
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

if not exist "Census Database\Dalda Census Data Base V2.csv" (
    echo ERROR: Census Database folder or CSV missing.
    pause
    exit /b 1
)

echo [1/4] Creating clean build environment...
if exist build_venv rmdir /s /q build_venv
python -m venv build_venv
call build_venv\Scripts\activate.bat

echo [2/4] Installing only required packages...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
    echo pip install failed.
    pause
    exit /b 1
)

echo [3/4] Running PyInstaller (5-15 minutes)...
python -m PyInstaller --noconfirm dalda_matcher.spec
if errorlevel 1 (
    echo Build FAILED.
    call deactivate
    pause
    exit /b 1
)

call deactivate

echo [4/4] Packaging release folder...
set OUT=release\Dalda Outlet Matcher
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

xcopy /E /I /Y "dist\Dalda Outlet Matcher\*" "%OUT%\" >nul
xcopy /E /I /Y "Census Database" "%OUT%\Census Database\" >nul
copy /Y "README.md" "%OUT%\" >nul 2>nul
copy /Y "BUILD_EXE.md" "%OUT%\" >nul 2>nul

echo.
echo ============================================================
echo  DONE
echo ============================================================
echo  Copy this ENTIRE folder to USB / office PC:
echo    %CD%\release\Dalda Outlet Matcher
echo.
echo  Double-click: Dalda Outlet Matcher.exe
echo  No internet required on that PC.
echo ============================================================
pause
