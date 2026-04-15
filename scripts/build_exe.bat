@echo off
REM 构建 wechat-decrypt.exe (单文件 Windows 可执行)
setlocal

cd /d "%~dp0\.."

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [*] PyInstaller not found, installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo [!] Failed to install PyInstaller
        exit /b 1
    )
)

echo [*] Building wechat-decrypt.exe ...
pyinstaller --clean --noconfirm scripts/wechat-decrypt.spec

if exist dist\wechat-decrypt.exe (
    echo.
    echo === Build complete ===
    echo dist\wechat-decrypt.exe
    for %%A in (dist\wechat-decrypt.exe) do echo Size: %%~zA bytes
) else (
    echo [!] Build failed — dist\wechat-decrypt.exe not found
    exit /b 1
)
