@echo off
REM 一次性全量解密 (不启动 Web UI)
setlocal

cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
    echo [*] Need administrator privileges, re-launching...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
    exit /b
)

if not exist .venv (
    echo [!] .venv not found. Please run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py decrypt
pause
