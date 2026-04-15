#!/usr/bin/env bash
# 一键安装: 建立 .venv 虚拟环境, 安装依赖
set -e

cd "$(dirname "$0")"

echo "=== WeChat Decrypt installer ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 not found. Please install Python 3.10+"
    exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[+] Python $PYVER"

if [ ! -d .venv ]; then
    echo "[*] Creating .venv ..."
    python3 -m venv .venv
fi

echo "[*] Installing dependencies ..."
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

if [ ! -f config.json ]; then
    echo "[*] Creating config.json from template"
    cp config.example.json config.json
    echo "[!] Please edit config.json to set your db_dir if auto-detect fails"
fi

echo
echo "=== Install complete ==="
echo "Run ./run.sh to start the Web UI (needs sudo or CAP_SYS_PTRACE on Linux)."
