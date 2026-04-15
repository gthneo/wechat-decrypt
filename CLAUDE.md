# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

WeChat 4.x local database decryptor for Windows / Linux / macOS. Extracts SQLCipher 4 keys from a running WeChat process's memory, decrypts all local DBs, and serves a real-time message stream over a Web UI + SSE, plus an MCP server for Claude integrations.

## Common Commands

```bash
pip install -r requirements.txt

python main.py           # extract keys + start Web UI at http://localhost:5678
python main.py decrypt   # extract keys + one-shot decrypt of all DBs → decrypted/

python find_all_keys.py              # key extraction only (Windows/Linux dispatcher)
python find_image_key_monitor.py     # live-scan image AES key (for V2 .dat decryption)
python decrypt_db.py                 # decrypt all DBs using existing all_keys.json

python mcp_server.py                 # MCP stdio server for Claude Code integration

# macOS key scanner is a C program, not Python:
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation
sudo ./find_all_keys_macos
```

Tests (unittest, no pytest required):

```bash
python -m unittest tests.test_mcp_server_search        # run the test file
python -m unittest tests.test_mcp_server_search.ClassName.test_method   # single test
```

Windows requires **admin terminal** to read process memory; Linux needs root or `CAP_SYS_PTRACE`.

## Architecture

### Control flow: `main.py` → key extraction → consumer

`main.py` is the single entry point. It (1) loads `config.json` via `config.load_config()` (auto-detects `db_dir` on first run), (2) verifies WeChat is running via `find_all_keys.get_pids()`, (3) calls `ensure_keys()` which either reuses `all_keys.json` or re-runs extraction, then (4) dispatches to `monitor_web.main` (default) or `decrypt_db.main` (`decrypt` subcommand).

`all_keys.json` stores a `_db_dir` sentinel; if the configured `db_dir` changes (account switch), keys are invalidated and re-extracted. Always route key reads through `key_utils.strip_key_metadata` / `get_key_info` — do not iterate the JSON directly, since metadata keys (leading `_`) must be filtered.

### Platform dispatch

`find_all_keys.py` is a thin dispatcher that lazy-imports `find_all_keys_windows` or `find_all_keys_linux` based on `platform.system()`. macOS has no Python implementation — `find_all_keys_macos.c` (Mach VM API) is the only supported path there. `key_scan_common.py` holds shared scan/verify helpers; per-platform files only implement the memory read.

### SQLCipher 4 parameters (load-bearing constants)

Every decrypt path hard-codes these; they must stay in sync across `decrypt_db.py`, `monitor_web.py`, `mcp_server.py`:

- Page size 4096, reserve 80 (= IV 16 + HMAC-SHA512 64)
- AES-256-CBC, PBKDF2-HMAC-SHA512 @ 256,000 iters for enc_key
- MAC key = PBKDF2-HMAC-SHA512(enc_key, salt ⊕ 0x3a, iters=2, dklen=32)
- Raw key in memory: `x'<64hex enc_key><32hex salt>'`; each DB has its own salt, so keys are stored per-DB (keyed by relative path like `message/message_0.db`).

### Real-time monitor (`monitor_web.py`)

Polls WAL/DB **mtime** every 30 ms (WAL files are pre-allocated 4 MB, so size never changes). On change: full re-decrypt of the DB + WAL frame patching into an in-memory SQLite. WAL frames carry the current salt; stale frames from a prior checkpoint cycle are skipped by salt mismatch. `MonitorDBCache` holds decrypted snapshots with per-key locks (required — concurrent decrypts of the same DB corrupt the output). An SSE handler pushes new rows to browsers; messages also accumulate in `messages_log` (capped at `MAX_LOG`).

`session.db` only keeps the last message per conversation, so `_check_hidden_messages` asynchronously cross-references the message DBs to recover same-second siblings. Image previews decrypt `.dat` via `decode_image.py` which handles all three formats (legacy XOR, V1 fixed-key AES+XOR, V2 AES-128-ECB+XOR using `image_aes_key` from `config.json`).

### MCP server (`mcp_server.py`)

Shares the same decryption + key lookup code as the monitor but exposes read-only tools (`get_recent_sessions`, `get_chat_history`, `search_messages`, `get_contacts`, `get_contact_tags`, `get_tag_members`, `get_new_messages`) over stdio. Tests in `tests/test_mcp_server_search.py` stub the decrypt cache with `_FakeCache` and build minimal SQLite fixtures — follow that pattern to avoid requiring a live WeChat install. Message tables are named `Msg_<md5(username)>`; this naming is a contract between production code and test fixtures.

### `.dat` image format detection

`decode_image.py` auto-detects by magic bytes:

| Format | Magic | Key source |
|--------|-------|------------|
| Legacy XOR | (none) | detected by comparing known header bytes |
| V1 | `07 08 V1 08 07` | fixed `cfcd208495d565ef` |
| V2 | `07 08 V2 08 07` | `image_aes_key` in `config.json`, extracted by `find_image_key*.py` |

V2 header: `[6B sig][4B aes_size LE][4B xor_size LE][1B pad]`, then `[AES-ECB region][raw region][XOR region]`. The AES key is only resident in memory while WeChat is actively viewing an image — `find_image_key_monitor.py` exists because scans often need to race that window.

## Config

`config.json` is git-ignored and created on first run. Key fields: `db_dir` (the `db_storage` dir for a specific wxid), `keys_file`, `decrypted_dir`, `decoded_image_dir`, `wechat_process`, `image_aes_key`, `image_xor_key` (default `0x88`). `config.example.json` is the template. The auto-detector in `config.py` uses platform-specific defaults — when adding a platform, extend `_auto_detect_db_dir_*` rather than hard-coding paths in callers.
