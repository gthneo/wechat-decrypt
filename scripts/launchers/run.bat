@echo off
REM 一键启动: Web UI (自动以管理员运行)
setlocal

cd /d "%~dp0"

REM 检查是否已经是管理员
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

".venv\Scripts\python.exe" main.py
pause
