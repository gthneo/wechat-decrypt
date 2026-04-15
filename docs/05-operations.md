# 05 · 运维手册

## 1. 日常启动 / 停止

```bash
# 启动 (前台进程, Ctrl+C 停止)
run.bat                  # Windows
./run.sh                 # Linux / macOS

# 后台运行 (Linux)
nohup ./run.sh > monitor.log 2>&1 &
echo $! > monitor.pid
```

停止:

```bash
# Windows: 关掉终端窗口或 Ctrl+C
# Linux:
kill $(cat monitor.pid)
```

## 2. 关键文件与目录

| 路径 | 作用 | 可否手动删除 |
|---|---|---|
| `config.json` | 配置 | 否（除非想重新自动检测） |
| `all_keys.json` | SQLCipher 密钥 | 可，删除后下次启动会重新提取 |
| `decrypted/` | 解密 DB 副本 | 可，下次启动重建 |
| `decrypted/_messages_log.jsonl` | Web UI 历史消息持久化 | 可，清空后 Web UI 从 0 开始 |
| `decrypted/_monitor_cache/` | MonitorDBCache 的中间文件 | 可，启动时会清理损坏项 |
| `decoded_images/` | 图片缓存 | 可，较大时可清理，下次按需重解密 |

## 3. 日志阅读

启动日志典型结构:

```
============================================================
  WeChat Decrypt
============================================================
[+] Weixin.exe PID=15020 (393MB)
[+] 微信进程运行中
[+] 已有 25 个数据库密钥
[*] 启动 Web UI...
加载联系人...
已加载 58299 个联系人, 1847 个静音群, 订阅号 232/服务号 252
[persist] 已恢复 387 条历史消息
[init] DB 2896 页/312ms + WAL 4 页/2ms
[monitor] 跟踪 1856 个会话
[monitor] mtime轮询模式 (每30ms)
=> http://localhost:5678
```

运行时典型日志:

```
  [perf] decrypt=2896页/305.2ms, query=12.1ms
[08:27:57 延迟=0.2s] [项目群] 张三: 今天开会吗?  (2896pg/305ms)
  [img] 尝试 orig(412KB): 319aa4...t.dat
  [img] 解密成功: 319aa4...jpg (187KB)
  [img] 异步解密成功: 319aa4...jpg
  [rich] channels 解析成功
  [hidden] 检查 项目群 prev_ts=... curr_ts=... type=3
  [hidden] 缓存查到 12 条
  [hidden] 找到 0 条隐藏消息
```

关键前缀:
- `[+]` 正常进度
- `[*]` 正在进行
- `[!]` 警告
- `[perf]` 解密耗时统计
- `[img]` 图片解密
- `[rich]` 富媒体解析
- `[hidden]` 被覆盖消息回填
- `[persist]` 持久化读写
- `[ERROR]` 错误

## 4. 故障排查

### 4.1 启动报错 `ModuleNotFoundError: No module named 'Crypto'`

依赖没装。`pip install -r requirements.txt`（或 `install.bat`）。

### 4.2 启动报错 `未检测到微信进程`

- 微信没运行 / 进程名不对 (`wechat_process` 字段和实际 `Weixin.exe` / `wechat` / `WeChat` 不一致)
- Windows 上没以管理员启动，无权 enumerate 进程

### 4.3 `密钥文件对应的目录已变更，需要重新提取`

切换了微信账号。`all_keys.json` 里的 `_db_dir` 与当前 `config.json.db_dir` 不匹配，触发重新提取，正常。

### 4.4 启动报错 `未能提取到任何密钥`

- `config.json.db_dir` 指向了**不是当前登录账号**的目录
- 或微信版本过新，key 在内存中的布局改变
- 解决: 确认 `db_dir` 是 **当前正在使用的 wxid** 下的 `db_storage`

### 4.5 Web UI 显示 `[图片 - 新加密格式暂不支持预览]`

- V2 AES key 缺失或过期（微信重启后 key 可能变）
- 解决: 先让微信主动渲染一张图片（点开看大图），然后运行:
  ```bash
  python find_image_key_monitor.py
  ```
  扫描到后自动写入 `config.json`，**重启 `main.py` 才生效**（key 是启动时读到全局变量的）。

### 4.6 Web UI 没有任何消息

- SSE 连接断了：右上角状态栏会变 "重连..."，自动重连即可
- 微信完全没有新消息到达：`_check_hidden_messages` 不会凭空制造消息
- `decrypted/_messages_log.jsonl` 被删了但页面没刷新：刷新浏览器

### 4.7 同一条消息在 Web UI 出现两次

通常是折叠伪会话没被跳过。检查 `monitor_web.py` 里的 `SKIP_USERNAMES` 集合是否包含引起重复的 username。当前已跳过:

- `@placeholder_*`
- `brandsessionholder` (订阅号折叠)
- `brandservicesessionholder` (服务号折叠)
- `notification_messages` / `notifymessage`

如果出现新的伪会话（如微信更新后新增），把它加入 `SKIP_USERNAMES` 即可。

### 4.8 `[perf] decrypt=2896页/XXXms` 数值突然飙到 1000+ ms

- 磁盘慢 / DB 很大
- 缓存被清理后第一次全量解密
- 如果持续变慢，检查 `decrypted/_monitor_cache/` 是否堆积过多

### 4.9 CPU 占用偏高

- 30 ms 轮询正常占用低 (<3%)
- 如果飙到 20%+，通常是 WAL 文件异常在反复触发全量解密。重启 `main.py`，让它重新初始化状态

### 4.10 MCP Server 在 Claude Code 里无响应

- 确认 `all_keys.json` 存在
- 确认 MCP 注册时用的是发行包里的 `.venv/Scripts/python.exe`，而不是系统 Python（否则依赖没装）
- `claude mcp list` 看状态；`claude mcp logs wechat` 查错误

## 5. 监控指标

Web UI 状态栏实时显示:

- `SSE 实时` / `重连...` — SSE 连接状态
- `N 消息` — 进程启动后收到的消息总数
- `2896 页 / 305ms` — 最近一次全量解密的性能

自定义监控可以轮询 `/api/history?since=<ts>` 得到增量消息数量。

## 6. 定期维护

| 频率 | 操作 | 目的 |
|---|---|---|
| 每次微信大更新后 | 重启 `main.py`，必要时跑 `find_image_key_monitor.py` | 刷新 V2 图片 key |
| 每月 | 清理 `decoded_images/` 下老旧 | 控制磁盘 |
| 每月 | 重建 `decrypted/_monitor_cache/` (停 main → 删 → 重启) | 避免过期缓存 |
| 每次改 `SKIP_USERNAMES` 或分类逻辑 | 跑 `python -m unittest tests.test_mcp_server_search` + 对照 `docs/03-test-cases.md` 手工用例 | 回归测试 |

## 7. 日志轮转 (Linux 后台运行场景)

如果用 `nohup ./run.sh > monitor.log 2>&1 &` 跑，日志会无限增长。建议:

```bash
# /etc/logrotate.d/wechat-decrypt
/path/to/wechat-decrypt/monitor.log {
    daily
    rotate 7
    compress
    missingok
    copytruncate
}
```

## 8. 数据安全与隐私

- `config.json`、`all_keys.json`、`decrypted/`、`decoded_images/`、`_messages_log.jsonl` **全部是你的私人数据**，不要提交到 git、不要上传公共云盘
- 发行包里的 `.gitignore` 已排除这些路径，但自行压缩备份时请手动确认
- 如果要备份到外部存储，建议加密（如 VeraCrypt 容器、LUKS、BitLocker）

## 9. 紧急回滚

如果新版本有严重 bug:

```bash
# 1. 停掉当前 main.py
# 2. 切回上一个发行包目录
cd wechat-decrypt.old     # 或旧版本目录
./run.bat                 # 复用原来的 config.json / all_keys.json
```

源码发行包之间是平级目录，互不影响，可以保留多个版本并排放。
