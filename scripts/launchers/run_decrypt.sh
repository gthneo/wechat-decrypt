#!/usr/bin/env bash
# 一次性全量解密
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[!] .venv not found. Please run install.sh first."
    exit 1
fi

exec ./.venv/bin/python main.py decrypt
