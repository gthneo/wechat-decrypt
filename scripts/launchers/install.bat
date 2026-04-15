@echo off
REM 一键安装: 建立 .venv 虚拟环境, 安装依赖
setlocal

cd /d "%~dp0"

echo === WeChat Decrypt installer ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python not found. Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [+] Python %PYVER%

if not exist .venv (
    echo [*] Creating .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] Failed to create venv
        pause
        exit /b 1
    )
)

echo [*] Installing dependencies ...
".venv\Scripts\pip.exe" install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo [!] pip install failed
    pause
    exit /b 1
)

if not exist config.json (
    echo [*] Creating config.json from template
    copy /y config.example.json config.json >nul
    echo [!] Please edit config.json to set your db_dir if auto-detect fails
)

echo.
echo === Install complete ===
echo Run run.bat to start the Web UI.
pause
