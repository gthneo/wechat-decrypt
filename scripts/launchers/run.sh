#!/usr/bin/env bash
# 一键启动: Web UI (Linux/macOS 下建议用 sudo 运行)
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[!] .venv not found. Please run install.sh first."
    exit 1
fi

exec ./.venv/bin/python main.py
