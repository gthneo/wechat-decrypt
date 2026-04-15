# 03 · 测试用例清单

本项目的测试分两层:

1. **自动化单元测试** — `tests/test_mcp_server_search.py`，围绕 `mcp_server.py` 的搜索与历史查询主路径，使用 `_FakeCache` 桩 + 临时 SQLite 构造，不依赖任何真实微信环境。
2. **手工验收用例** — 需要有运行中的微信 4.x 才能执行，覆盖端到端路径。

## 1. 自动化单元测试

### 运行方式

```bash
python -m unittest tests.test_mcp_server_search              # 全量
python -m unittest tests.test_mcp_server_search -v           # 带用例名
python -m unittest tests.test_mcp_server_search.SearchMessagesTests.test_search_messages_single_chat_uses_offset_and_returns_page   # 单个
```

### 覆盖范围

20 个用例，当前全部通过。

| # | 用例名 | 断言内容 |
|---|---|---|
| 1 | `test_get_chat_history_allows_large_limit_values` | `limit` 放宽时能读取 > 500 条 |
| 2 | `test_get_chat_history_does_not_truncate_long_messages` | 长文本不被截断 |
| 3 | `test_get_chat_history_keeps_partial_results_when_formatting_fails` | 格式化异常不丢已查到的消息 |
| 4 | `test_get_chat_history_large_limit_reads_all_rows_across_shards` | 跨 message_0 / message_1 分片合并 |
| 5 | `test_get_chat_history_merges_sharded_message_tables` | 同 username 多 DB 合并去重 |
| 6 | `test_get_chat_history_uses_bounded_sql_pagination` | SQL 层分页，不是内存 slice |
| 7 | `test_get_new_messages_closes_connection_when_query_fails` | 异常路径 connection 关闭 |
| 8 | `test_get_recent_sessions_closes_connection_when_query_fails` | 异常路径 connection 关闭 |
| 9 | `test_page_search_entries_returns_chronological_results_with_offset` | 分页顺序正确 |
| 10 | `test_search_messages_all_messages_merges_global_results_before_paging` | 全库搜索全局排序后再分页 |
| 11 | `test_search_messages_all_messages_respects_time_range` | 全库搜索尊重时间过滤 |
| 12 | `test_search_messages_all_messages_uses_bounded_sql_pagination` | 全库搜索 SQL 分页 |
| 13 | `test_search_messages_keeps_partial_results_when_later_batch_fails` | 分批失败保留已成功的批次 |
| 14 | `test_search_messages_multiple_chats_applies_global_pagination` | 多聊联合搜索时分页在全局层面 |
| 15 | `test_search_messages_multiple_chats_respects_time_range` | 多聊联合搜索尊重时间过滤 |
| 16 | `test_search_messages_single_chat_merges_sharded_message_tables` | 单聊跨分片搜索合并 |
| 17 | `test_search_messages_single_chat_respects_time_range` | 单聊尊重时间过滤 |
| 18 | `test_search_messages_single_chat_uses_offset_and_returns_page` | 单聊分页 offset 正确 |
| 19 | `test_validate_pagination_allows_large_limit_when_limit_is_unbounded` | 未设上限时允许大 limit |
| 20 | `test_validate_pagination_rejects_large_limit` | 有上限时拒绝过大 limit |

### 测试环境要求

- Python 3.10+
- `pip install -r requirements.txt` (pycryptodome / zstandard / mcp — 测试里不需要真实加密，但 `mcp_server.py` import 时会加载)
- **无需运行微信**，也无需 `decrypted/` 数据。

### 新增用例的模式

所有测试都通过 `_FakeCache` 桩 + `_create_message_db` 临时 SQLite 构造，模式如下:

```python
def test_xxx(self):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "message_0.db")
        _create_message_db(path, {
            "wxid_alice": [(1001, 1700000000, "hello")],
        })
        cache = _FakeCache({"message/message_0.db": path})
        with patch.object(mcp_server, "_db_cache", cache):
            result = mcp_server.search_messages("hello")
            self.assertIn("hello", result)
```

**关键契约**: 消息表名必须是 `Msg_<md5(username)>`，这是生产代码和测试 fixture 共享的约定。

## 2. 手工验收用例

以下用例需要:
- 运行中的微信 4.x（Windows/Linux/macOS 任一）
- 正确的 `config.json`
- 管理员或 root 权限

### 2.1 密钥提取 (G1)

| 编号 | 操作 | 期望结果 |
|---|---|---|
| M-1.1 | 管理员终端执行 `python find_all_keys.py` | 几秒内输出找到的 DB 数量，生成 `all_keys.json` |
| M-1.2 | 切换到第二个微信账号再执行一次 | `all_keys.json._db_dir` 被识别为不一致，触发重提取 |
| M-1.3 | 微信未启动时执行 | 明确报错 "未检测到微信进程"，不崩溃 |

### 2.2 全量解密 (G2)

| 编号 | 操作 | 期望结果 |
|---|---|---|
| M-2.1 | `python main.py decrypt` | `decrypted/` 下生成 ~26 个 DB，`contact.db`、`session.db`、`message_*.db` 等都能用标准 SQLite 客户端打开 |
| M-2.2 | 反复执行 `decrypt` | 幂等，第二次仍然成功（不会因为残留文件失败） |
| M-2.3 | 用 `sqlite3 decrypted/contact/contact.db "SELECT COUNT(*) FROM contact"` | 返回真实联系人数量 |

### 2.3 实时监听 Web UI (G3)

| 编号 | 操作 | 期望结果 |
|---|---|---|
| M-3.1 | `python main.py`，打开 `http://localhost:5678` | 页面加载，状态栏 "SSE 实时" 绿灯 |
| M-3.2 | 给自己发一条文本 | 200 ms 内在 Web UI 出现，带动画高亮 |
| M-3.3 | 一秒内连发文字 + 图片 | 两条都出现，`_check_hidden_messages` 把被覆盖的文字回填 |
| M-3.4 | 在群里收一条新消息 | 进入 "群聊" tab，tab 计数 +1 |
| M-3.5 | 在一个被静音的群收消息 | 进入 "静音群" tab，消息条以半透明显示 |
| M-3.6 | 收到订阅号推送 | 进入 "订阅号" tab，chat 名字橙色 |
| M-3.7 | 收到服务号推送 | 进入 "服务号" tab，chat 名字绿色 |
| M-3.8 | 点击 tab 切换 | 对应类别以外的消息即时隐藏/显示 |
| M-3.9 | 重启 `main.py`，刷新页面 | 历史消息恢复，tab 计数重建，日志含 `[persist] 已恢复 N 条历史消息` |

### 2.4 富媒体渲染 (G4)

| 编号 | 场景 | 期望 |
|---|---|---|
| M-4.1 | 别人发文字 | 原文渲染，WeChat 表情 `[呲牙]` 被替换成 emoji |
| M-4.2 | 别人发链接卡片（公众号文章） | 标题 + 描述 + 来源卡片渲染 |
| M-4.3 | 别人发文件 | 文件名 + 扩展名 + 大小 |
| M-4.4 | 别人发引用回复 | 引用原文（带发送人）+ 回复正文 |
| M-4.5 | 别人发小程序卡片 | 绿色 🟢 + 小程序名 + 来源 |
| M-4.6 | 别人发视频号 | 📺 + 频道昵称 + desc + 根据 feedType 显示 🎬/🖼️/🔴 badge |
| M-4.7 | 别人发聊天记录（合并转发） | 📋 + 标题 + 前 4 条 item + "共 N 条" |
| M-4.8 | 别人发一张图片 | 预览图内联显示，点击放大 |
| M-4.9 | 别人发一条语音 / 视频 | 占位条显示时长 |

### 2.5 图片 .dat 解密 (G5)

| 编号 | 场景 | 期望 |
|---|---|---|
| M-5.1 | 收到旧 XOR 格式的图 | `decode_image.detect_xor_key` 自动识别 PNG/JPG magic，正常解密 |
| M-5.2 | 收到 V1 格式的图 | 使用固定 key 解密成功 |
| M-5.3 | 收到 V2 格式的图，`config.json.image_aes_key` 已提取 | 成功解密 |
| M-5.4 | 收到 V2 格式的图，`image_aes_key` 缺失 | Web UI 显示 "新加密格式暂不支持预览"，不崩溃；运行 `python find_image_key_monitor.py` 后重启能恢复 |
| M-5.5 | 收到 HEVC/wxgf 图 | `_convert_hevc_to_jpeg` 转成 JPEG 显示（需装 pillow-heif） |

### 2.6 MCP Server (G6)

| 编号 | 操作 | 期望 |
|---|---|---|
| M-6.1 | `claude mcp add wechat -- python <path>/mcp_server.py` | 注册成功 |
| M-6.2 | Claude Code 对话 "看看最近的会话" | 调用 `get_recent_sessions`，返回最近 N 个会话 |
| M-6.3 | Claude Code 对话 "搜一下包含 xyz 的消息" | 调用 `search_messages`，返回命中 |
| M-6.4 | `get_chat_history` 用 `limit=500` | 返回 500 条按时间倒序 |
| M-6.5 | `search_messages` 传多个 `chat_name` | 联合搜索多个聊天对象 |
| M-6.6 | `get_contact_tags()` → `get_tag_members(tag_name)` | 能列出指定标签下的联系人 |

### 2.7 分类与去重 (G7)

| 编号 | 场景 | 期望 |
|---|---|---|
| M-7.1 | 订阅号折叠入口收到消息 | `brandsessionholder` 伪会话被跳过，真实订阅号会话里出现 |
| M-7.2 | 服务号折叠入口收到消息 | `brandservicesessionholder` 伪会话被跳过 |
| M-7.3 | 群消息 | `is_group=true`，category=`group` 或 `group_muted` |
| M-7.4 | 设置某群为免打扰，再收消息 | category 切到 `group_muted`，Web UI 半透明显示 |
| M-7.5 | 订阅号 gh_xxx 推送 | `(verify_flag & 24) != 24` → category=`sub` |
| M-7.6 | 服务号 gh_xxx 推送 | `(verify_flag & 24) == 24` → category=`svc` |

### 2.8 持久化 (G8)

| 编号 | 操作 | 期望 |
|---|---|---|
| M-8.1 | 收到几条消息后 `Ctrl+C` 退出 | `decrypted/_messages_log.jsonl` 存在，行数与看到的消息一致 |
| M-8.2 | 重新 `python main.py` | 启动日志打印 `[persist] 已恢复 N 条历史消息` |
| M-8.3 | 刷新 Web UI | 历史消息、tab 计数、图片预览都恢复 |
| M-8.4 | 删除 `_messages_log.jsonl` 后启动 | 正常启动，日志里没有恢复行 |

### 2.9 部署 (G9)

| 编号 | 操作 | 期望 |
|---|---|---|
| M-9.1 | 在干净目录解压 `wechat-decrypt-<ver>.zip` | 目录结构完整，含 `install.bat`、`run.bat`、`docs/` |
| M-9.2 | 双击 `install.bat` | 创建 `.venv`，安装 requirements |
| M-9.3 | 双击 `run.bat` | 以管理员权限重启自己，启动 `python main.py` |
| M-9.4 | (可选) `wechat-decrypt.exe` | 直接运行，不需要 Python 环境 |

## 3. 已知限制

- `_check_hidden_messages` 的 `rich_content` key 和 Web UI 的 `m.rich` 不一致，回填的富媒体历史消息在前端不会以卡片形式渲染（会降级成文字）。
- PyInstaller 构建出的 .exe 扫描进程内存，有可能被 Windows Defender / 360 等杀毒误报。建议发布源码 zip 作为默认形态。
- macOS 的密钥扫描器是 C 程序，需要本地 `cc` 编译，不在 Python 一键流程里。
