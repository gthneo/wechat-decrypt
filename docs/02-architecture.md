# 02 · 技术架构

## 1. 总体分层

```
┌────────────────────────────────────────────────────────┐
│                    用户层                               │
│  浏览器 (Web UI)    Claude Code (MCP)    命令行         │
└─────────┬─────────────────┬─────────────────┬─────────┘
          │ SSE + HTTP      │ stdio (MCP)     │ CLI
┌─────────▼─────────────────▼─────────────────▼─────────┐
│                 服务层                                  │
│  monitor_web.py    mcp_server.py    main.py             │
│  (Web UI + SSE)    (MCP stdio)      (一键入口)          │
└─────────┬───────────────────────────────────────────┬─┘
          │                                           │
┌─────────▼───────────────────────────────────────────▼─┐
│                解密 & 解析层                            │
│  decrypt_db.py   decode_image.py   _parse_rich_content │
│  (SQLCipher 4)   (图片 .dat)       (AppMsg XML)        │
└─────────┬──────────────────────────────────────────┬──┘
          │                                          │
┌─────────▼──────────────────────────────────────────▼──┐
│               密钥提取层                                │
│  find_all_keys.py (分发)                                │
│  ├─ find_all_keys_windows.py   (ReadProcessMemory)      │
│  ├─ find_all_keys_linux.py     (/proc/<pid>/mem)        │
│  └─ find_all_keys_macos.c      (Mach VM API, C)         │
│  find_image_key*.py  (V2 图片 AES key 扫描)             │
└─────────┬──────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────┐
│               数据源层                                   │
│  运行中的微信进程内存 + 磁盘上的 SQLCipher 4 数据库      │
│  (message_*.db, contact.db, session.db, emoticon.db,    │
│   message_resource.db, …)                               │
└────────────────────────────────────────────────────────┘
```

## 2. 关键文件职责

| 文件 | 角色 |
|---|---|
| `main.py` | 一键启动入口：加载 config、校验微信进程、提取密钥、分发到 web / decrypt |
| `config.py` | 配置加载器 + 平台自动检测 `db_dir` |
| `find_all_keys.py` | 平台分发 (Windows/Linux)，macOS 走 C 程序 |
| `key_scan_common.py` | 跨平台共用的扫描 / 校验逻辑 |
| `key_utils.py` | 过滤 `all_keys.json` 元数据 (`_db_dir` 等) |
| `decrypt_db.py` | 全量解密所有 DB 到 `decrypted/` |
| `monitor_web.py` | Web UI + SSE + 实时监听 + 富媒体解析 + 持久化 |
| `monitor.py` | 命令行版实时监听 (不含 Web UI) |
| `mcp_server.py` | MCP stdio server，只读工具集 |
| `decode_image.py` | `.dat` 图片解密 (XOR / V1 / V2) |
| `find_image_key*.py` | 实时扫描微信进程内存提取 V2 图片 AES key |

## 3. 控制流：`main.py` 的四步

1. **加载配置** `config.load_config()` 自动检测 `db_dir`，首次运行写 `config.json`。
2. **校验微信进程** `find_all_keys.get_pids()` 返回进程列表，空则退出。
3. **确保密钥** `ensure_keys(keys_file, db_dir)`:
   - 若 `all_keys.json` 存在且 `_db_dir` 与当前匹配，直接复用。
   - 否则调用平台对应的内存扫描器提取。
4. **分发**
   - `python main.py` (默认) → `monitor_web.main()` 启动 Web UI
   - `python main.py decrypt` → `decrypt_db.main()` 一次性解密

## 4. SQLCipher 4 参数 (硬约束)

所有解密路径都必须保持一致，一处改全部改：

| 参数 | 值 |
|---|---|
| Page size | 4096 |
| Reserve | 80 (IV 16 + HMAC-SHA512 64) |
| 对称加密 | AES-256-CBC |
| KDF | PBKDF2-HMAC-SHA512 @ 256,000 iters → `enc_key` (32B) |
| MAC key | PBKDF2-HMAC-SHA512(enc_key, salt⊕0x3a, 2 iters, 32B) |
| 内存中的 raw key | `x'<64hex enc_key><32hex salt>'` |

每个 DB 有独立 salt，所以 `all_keys.json` 是 per-DB 的字典，key 为相对路径 (如 `message/message_0.db`)。

## 5. 实时监听内部机制 (`monitor_web.py`)

### 5.1 轮询 & 增量解密

```
每 30 ms:
  wal_mtime, db_mtime = stat(session.db-wal, session.db)
  若 mtime 变化:
    ① 全量解密 session.db → DECRYPTED_SESSION (内存中的 SQLite)
    ② 把所有 WAL frame patch 到该副本
    ③ query_state() 读出 SessionTable
    ④ 对比 prev_state 找出新消息
```

**为什么用 mtime 而不是文件大小**: WeChat 使用 SQLite WAL，WAL 文件**预分配固定 4 MB**，写操作不会改变文件大小，只有 mtime 会变。

### 5.2 WAL frame salt 校验

每个 WAL frame header 携带当前 checkpoint 周期的 salt。旧周期遗留在文件里的 frame 会被识别并跳过，避免把过期帧 patch 到新数据库。

### 5.3 并发解密安全

`MonitorDBCache` 使用 per-key `Lock`，**禁止**两个线程同时解密同一个 DB——否则输出文件会互相覆盖导致页面损坏。

### 5.4 隐藏消息回填

`session.db` 的 `SessionTable` 对每个会话只保留最后一条消息的摘要。如果用户秒内连发文字 + 图片，中间那条会被覆盖。`_check_hidden_messages` 开独立线程到 `message_<N>.db` 的 `Msg_<md5(username)>` 表里按时间窗口补查，把被覆盖的消息补推到前端。

### 5.5 消息分类与去重

| 类别 (`category`) | 判据 |
|---|---|
| `direct` | 不是 `@chatroom`、不是 `gh_*` 开头 |
| `group` | `@chatroom` 且 `contact.chat_room_notify = 1` |
| `group_muted` | `@chatroom` 且 `contact.chat_room_notify = 0` |
| `sub` | `gh_*` 且 `(contact.verify_flag & 24) != 24` → 订阅号 |
| `svc` | `gh_*` 且 `(contact.verify_flag & 24) == 24` → 服务号 |

去重：`SKIP_USERNAMES`（`brandsessionholder`、`brandservicesessionholder`、`notification_messages`、`notifymessage`）以及所有以 `@placeholder_` 开头的 username 都直接跳过——它们是微信折叠伪会话，消息已在真实会话里出现过。

### 5.6 持久化

`messages_log`（最多 500 条）由后台线程 `_persist_worker` 监听 `_persist_dirty` 事件，dirty flag 置位后 sleep 0.5 s 合并写入，再把整份 snapshot 原子写到 `decrypted/_messages_log.jsonl` (`write → .tmp → rename`)。触发点：
- 新消息进 `messages_log`
- `_async_resolve_image` 解密完成
- `_async_resolve_rich` 解析完成

启动时 `_load_persisted_messages()` 从 JSONL 恢复最后 500 条，前端 `/api/history` 直接吐出去，Tab 计数通过 `addMsg → bumpCat` 自动重建。

## 6. 图片 `.dat` 三种格式

| 格式 | 出现时期 | Magic | 解密方式 | 密钥来源 |
|---|---|---|---|---|
| 旧 XOR | ~2025-07 及更早 | 无 | 单字节 XOR | 自动检测（对比 magic bytes） |
| V1 | 过渡期 | `07 08 V1 08 07` | AES-128-ECB + XOR | 固定 key `cfcd208495d565ef` |
| V2 | 2025-08+ | `07 08 V2 08 07` | AES-128-ECB + XOR | 从微信进程内存实时扫描 |

V2 结构：`[6B sig][4B aes_size LE][4B xor_size LE][1B pad]` + `[AES-ECB 区][raw 区][XOR 区]`。

V2 的 AES key 只在微信**正在渲染图片**时短暂驻留内存，所以 `find_image_key_monitor.py` 是"持续扫描并等待命中"，扫到就写入 `config.json`。

## 7. MCP Server (`mcp_server.py`)

和 monitor_web 共享密钥加载、DBCache、`_parse_rich_content`，但只暴露**只读**工具:

| Tool | 功能 |
|---|---|
| `get_recent_sessions(limit)` | 最近会话列表（含未读数、摘要） |
| `get_chat_history(chat_name, limit, offset, start_time, end_time)` | 指定聊天的消息历史 |
| `search_messages(keyword, chat_name, start_time, end_time, limit, offset)` | 全库/单聊/多聊 + 时间范围 + 分页搜索 |
| `get_contacts(query, limit)` | 搜索/列出联系人 |
| `get_contact_tags()` | 联系人标签及成员数量 |
| `get_tag_members(tag_name)` | 指定标签下的联系人 |
| `get_new_messages()` | 自上次调用以来的新消息 |

消息表命名契约：`Msg_<md5(username)>`。生产代码和测试 fixture 共享这个命名规则，便于在不依赖真实微信环境的条件下做单元测试。

## 8. 数据流一览：「一条新消息」

```
微信收到消息
    ↓
写 session.db-wal (mtime 更新)
    ↓
monitor_web 轮询命中 (< 30 ms)
    ↓
full_decrypt(session.db) + patch 所有 WAL frame   ~30–70 ms
    ↓
query_state() 对比 prev_state → 新消息列表
    ↓
filter: should_skip_username / category 分类 / is_muted
    ↓
组装 msg_data + append messages_log + _persist_dirty.set()
    ↓
broadcast_sse(msg_data)  ← 浏览器端 addMsg(..., true)
    ↓
(异步) _async_resolve_image / _async_resolve_rich
    └─→ msg_data 更新 + 再次 _persist_dirty.set()
        + SSE image_update / rich_update 事件推送
```

端到端延迟典型值 ~100 ms。
