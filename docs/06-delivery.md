# 06 · 跨机交付与部署手册

本文档是把 `wechat-decrypt` 从开发机搬到**另一台机器**的完整操作手册。两种典型场景:

- **场景 A** · **服务端**: 把 wechat-decrypt 装到一台新的 Windows 机器上，让它负责解密微信数据 + 提供 MCP 服务
- **场景 B** · **客户端**: 装好 wechat-decrypt 服务端已有, 现在要在另一台 (Linux/macOS/Windows 都行) 机器上让 AI agent / MCP client 连过来调工具

本手册按场景展开, 每一步都给**可复制粘贴**的命令。

---

## 场景 A · 服务端全新部署 (Windows 机)

### A.0 前置清单

- [ ] 目标机器操作系统: Windows 10 / 11 (x64)
- [ ] **微信 4.x** 已经安装, 已登录你自己的账号
- [ ] 有**管理员权限** (提取 SQLCipher 密钥必须读取 Weixin.exe 进程内存)
- [ ] 磁盘可用 ≥ 10 GB (解密后 SQLite 副本 + 缓存)
- [ ] 拿到 `wechat-decrypt-release-<version>.zip` (由开发机用 `scripts/build_release_exe.py` 构建出)

### A.1 解压 + 目录准备

把 zip 解压到一个**固定目录** — 这就是整个系统的运行目录, 之后不要再移动。

```powershell
# PowerShell, 管理员
mkdir C:\tools\wechat-decrypt
Expand-Archive wechat-decrypt-release-2026.04.16.zip -DestinationPath C:\tools\wechat-decrypt
cd C:\tools\wechat-decrypt\wechat-decrypt-release-2026.04.16
dir
```

期望看到:
```
wechat-decrypt-mcp.exe
wechat-decrypt-config.exe
wechat-decrypt-monitor.exe
config.example.json
README-FIRST.txt
start-config.bat
start-monitor.bat
docs\
```

### A.2 创建 `config.json`

```powershell
copy config.example.json config.json
```

编辑 `config.json`，把 `db_dir` 改成当前微信账号的数据目录。通常路径形如:

```
C:\Users\<你的Windows用户>\xwechat_files\<微信ID>_<后缀>\db_storage
```

在 Windows 微信客户端里: **设置 → 文件管理** 里能直接看到 "数据存储位置", 就是上面的 `xwechat_files\<wxid>` 那一段, 在后面加 `\db_storage` 就是完整 `db_dir` 值。

如果**不知道怎么填**, 可以先随便填 (或直接保留 `your_wxid`), 第一次启动 `wechat-decrypt-monitor.exe` 时它会**自动检测**并列出候选目录让你选。

### A.3 **加杀毒白名单** (关键, 否则 exe 会被拦)

wechat-decrypt 要扫描微信进程内存, 和"密码窃取木马"在行为层面相似, 会被 Windows Defender / 360 / 火绒 等报毒。在启动前先把目录加入白名单:

**Windows Defender** (以管理员在 PowerShell 执行):
```powershell
Add-MpPreference -ExclusionPath "C:\tools\wechat-decrypt"
Add-MpPreference -ExclusionProcess "wechat-decrypt-mcp.exe"
Add-MpPreference -ExclusionProcess "wechat-decrypt-monitor.exe"
Add-MpPreference -ExclusionProcess "wechat-decrypt-config.exe"
```

**360 / 火绒**: 主界面 → 设置 → 信任区 → 添加目录 → 选 `C:\tools\wechat-decrypt`

### A.4 第一次启动: 密钥提取

用**管理员权限**跑:

```powershell
cd C:\tools\wechat-decrypt\wechat-decrypt-release-2026.04.16
.\wechat-decrypt-monitor.exe
```

期望的第一次启动流程:

```
============================================================
  WeChat Decrypt
============================================================
[+] 自动检测到微信数据目录: C:\Users\xxx\xwechat_files\xxx\db_storage
[+] Weixin.exe PID=12345
[+] 微信进程运行中
[*] 密钥文件不存在，正在从微信进程提取...
  OK: contact\contact.db (32MB)
  OK: session\session.db (2.5MB)
  OK: message\message_0.db (167MB)
  ...
[*] 启动 Web UI...
=> http://localhost:5678
Ctrl+C 停止
```

打开浏览器 `http://localhost:5678`, 应该能看到实时消息监听界面, 发条微信消息看会不会实时显示。如果能, **密钥提取成功 + 本地基础链路通**。

> 如果报 `未能提取到任何密钥` → `db_dir` 填错了, 或选了不对应的微信账号. 进入 config.json 把 db_dir 改成运行中那个账号的目录。

### A.5 一次性全量解密 (可选但推荐)

停掉 monitor (Ctrl+C), 跑一次性全量解密把所有 SQLite 副本生成到 `decrypted\`:

```powershell
.\wechat-decrypt-monitor.exe decrypt
```

大库 (几 GB) 要 5–15 分钟。完成后 `decrypted\` 下 ~26 个 SQLite 文件可用任意客户端直接打开。

### A.6 配置网络 MCP (让其它机器能远程调)

#### A.6.1 启动 config UI

**新开一个** PowerShell (保留之前 monitor 运行), 跑:

```powershell
cd C:\tools\wechat-decrypt\wechat-decrypt-release-2026.04.16
.\wechat-decrypt-config.exe
```

UI 开在 `http://127.0.0.1:5679` (**只绑 loopback**, 外网看不到). 浏览器打开它。

#### A.6.2 配置字段

四个必填动作:

1. **勾选 `network.enabled`** ☑
2. **`bind_host`**: 留默认 `0.0.0.0` (所有网卡) 或改成某个具体 IP
3. **`bind_port`**: 默认 `8765` 就行, 除非端口冲突
4. **`auth_token`**: 点旁边的 **`Generate`** 按钮 → 自动填 43 字符的随机 token → 点 **`Copy`** 复制到剪贴板 (**立刻用密码管理器存起来**)

**Allowed Clients** 表格里 **+ Add client**, 填**对方机器**的信息:

| Label | IP | Domain | Enabled |
|---|---|---|---|
| my-openclaw-box | 192.168.x.y | `openclaw.lan` *(可选)* | ☑ |

> IP + Domain 任一命中即放行. Domain 字段匹配 HTTP Host 头, 不是对方机器的 hostname — 是对方**连你 server 用的主机名**。如果对方只用 IP 直连, domain 字段可留空.

最下面点 **`Save Config`**. 然后顶部点 **`Start`**, 状态变成 `● running (pid XXXX)`.

#### A.6.3 验证 server 本机

```powershell
# 本机自测
curl.exe http://127.0.0.1:8765/health
# 期望: {"ok":true,"version":"0.6.0-network","ts":...}

# 再带 token 测 /sse (需要 Bearer)
# $TOKEN 先从剪贴板粘贴成变量
curl.exe --max-time 3 -H "Authorization: Bearer $env:TOKEN" http://127.0.0.1:8765/sse
# 期望: event: endpoint / data: /messages/?session_id=<hex>
```

见到 `event: endpoint` 就证明鉴权 + 中间件工作正常.

#### A.6.4 打开 Windows 防火墙 8765 入站

```powershell
# PowerShell 管理员
New-NetFirewallRule -DisplayName "wechat-mcp 8765" `
    -Direction Inbound -Protocol TCP -LocalPort 8765 `
    -Action Allow -Profile Private
```

> `-Profile Private` 只对家庭/办公网络生效, 公共网络不开; 更严格可用 `-RemoteAddress 192.168.31.0/24` 限制来源网段.

#### A.6.5 从其它机器测连通

在**对方机器** (.178, .150, 随便哪台) 上:

```bash
curl http://<server-ip>:8765/health
# 期望: {"ok":true,"version":"0.6.0-network","ts":...}
```

如果不通, 依次排查: 
- `Connection refused` → `0.0.0.0` 绑对了吗, mcp_server 还活着吗, 防火墙加规则了吗
- 超时 → 两台机器在不在同一子网
- 403 → 对方 IP 没加 allow_clients

### A.7 装成开机自启 (可选)

把 monitor 和 config 注册成 Windows 任务计划, 开机自动起:

```powershell
# 以管理员跑
$path = "C:\tools\wechat-decrypt\wechat-decrypt-release-2026.04.16"

# monitor 开机启动 (需要管理员身份, 因为要读微信进程内存)
schtasks /Create /SC ONLOGON /RL HIGHEST /TN "wechat-decrypt-monitor" `
    /TR "`"$path\wechat-decrypt-monitor.exe`"" /RU $env:USERNAME

# config 开机启动 (不需要管理员, 因为只绑 loopback)
schtasks /Create /SC ONLOGON /TN "wechat-decrypt-config" `
    /TR "`"$path\wechat-decrypt-config.exe`"" /RU $env:USERNAME
```

重启机器后, monitor 和 config UI 会自动跑起来. mcp_server 需要你在 config UI 里点一次 Start (或继续用 config 的持久化: 实际上 start 按钮触发的子进程不会自动恢复, 要真永久自启需要把 mcp_server 也做成任务计划, 或者改 config_web 源码让它启动时自动 start).

---

## 场景 B · 客户端接入 (异机 Agent)

### B.0 选你的 MCP client

先判断你要用的客户端是否**原生支持 SSE transport**. 判断方法: 看它的 MCP config 格式长什么样.

| 客户端 | 原生 SSE 支持 | 接入方式 |
|---|---|---|
| Claude Desktop (最新版) | ✅ | 直接填 `type: "sse"` |
| Claude Code | ✅ | `claude mcp add --transport sse ...` 或 JSON |
| OpenClaw | ❌ | **必须用 mcp-proxy 桥** |
| 其它不确定的 | 翻它的 `mcp set` 或 config 示例看 |

### B.1 路径 1 · 原生 SSE (Claude Desktop / Claude Code)

#### B.1.1 Claude Desktop

编辑配置文件:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

加一条:

```json
{
  "mcpServers": {
    "wechat": {
      "type": "sse",
      "url": "http://<server-ip>:8765/sse",
      "headers": {
        "Authorization": "Bearer <your-token>"
      }
    }
  }
}
```

重启 Claude Desktop。在新对话里应能看到 wechat MCP 提供的 11 个工具。

#### B.1.2 Claude Code

```bash
claude mcp add wechat \
    --transport sse \
    --url http://<server-ip>:8765/sse \
    --header "Authorization=Bearer <your-token>"
```

或者直接编辑 `~/.claude.json`, 加入和 Claude Desktop 一样的 JSON。

### B.2 路径 2 · stdio-only 客户端 · 用 mcp-proxy 桥

适用 OpenClaw 以及其它不支持 SSE 的 MCP 客户端。

#### B.2.1 装 mcp-proxy

```bash
# 需要 python3.8+
pip3 install --user mcp-proxy

# 装到:
#   Linux/macOS: ~/.local/bin/mcp-proxy
#   Windows:     %APPDATA%\Python\Python<ver>\Scripts\mcp-proxy.exe

# 验证可用
~/.local/bin/mcp-proxy --help | head -5
```

#### B.2.2 客户端配置 (OpenClaw 为例)

```bash
# 先把 token 存变量 (不进 history)
read -s -p "wechat MCP token: " TOKEN && echo

# 注册 MCP
openclaw mcp set wechat "$(cat <<EOF
{
  "command": "/home/$USER/.local/bin/mcp-proxy",
  "args": [
    "http://<server-ip>:8765/sse",
    "--transport", "sse",
    "-H", "Authorization", "Bearer $TOKEN"
  ]
}
EOF
)"

# 确认写入
openclaw mcp list
# 期望: - wechat

# 重启 gateway 让它读新配置
pkill -TERM -f openclaw-gateway
nohup openclaw gateway > ~/.openclaw/logs/gateway.out.log 2>&1 &
disown

# 退出当前 TUI session, 重开一次
# (旧 session 的 agent 工具列表已固化, 要重开才看得到新 MCP)
openclaw tui
```

在 TUI 发测试命令:
```
call the health tool from the wechat MCP
```

期望 agent 返回:
```json
{"ok":true,"version":"0.6.0-network","ts":...}
```

#### B.2.3 用 env 变量隐藏 token

把 `Bearer $TOKEN` 写死在 openclaw.json 里存的是明文. 如果你的客户端支持 env var 插值, 优先用:

```bash
# 在 ~/.bashrc 或 systemd 服务 env 文件加
export WECHAT_MCP_TOKEN="<your-token>"

# 配置里改成引用
{
  "args": [
    ...,
    "-H", "Authorization", "Bearer ${WECHAT_MCP_TOKEN}"
  ]
}
```

注意: **不是所有客户端都支持 env var 插值** — openclaw (2026.4.14) 不支持, 要写明文. 这种情况下至少保证 `~/.openclaw/openclaw.json` 的权限是 600 (只有自己能读).

### B.3 路径 3 · 自定义 Python / Node 客户端

如果你要写自己的客户端调用 wechat MCP, 用 MCP SDK 的 SSE client 即可:

**Python**:
```python
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async with sse_client(
    "http://<server-ip>:8765/sse",
    headers={"Authorization": f"Bearer {token}"}
) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        # 现在可以 session.call_tool("health", {}) 等等
```

**Node** (`@modelcontextprotocol/sdk`):
```javascript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

const transport = new SSEClientTransport(
  new URL("http://<server-ip>:8765/sse"),
  { requestInit: { headers: { "Authorization": `Bearer ${token}` } } }
);
const client = new Client({ name: "my-app", version: "1.0.0" });
await client.connect(transport);
const tools = await client.listTools();
```

---

## 场景 A + B 共同的安全清单

- [ ] **`config.json` 不进 git** — 里面有 `auth_token`, 已被 `.gitignore` 排除
- [ ] **token 定期轮换** — 每 30-90 天在 config UI 点 Generate → Save → Restart, 对应客户端也同步更新
- [ ] **如果暴露到互联网** (不是局域网) — 强烈建议开 TLS, 在 config UI 里勾 `tls.enabled` 并填自签证书路径
- [ ] **服务端只开必要端口** — Windows 防火墙 `-Profile Private` 或 `-RemoteAddress <subnet>` 限制
- [ ] **所有用户凭据永远走环境变量或密码管理器**, 不要明文贴到 chat / git / log / Slack
- [ ] **定期检查 `logs/mcp_access.log`** 有没有异常 IP 出现 (不在 allow_clients 里的 DENY_*)
- [ ] **服务端那台机器的 `decrypted/` 目录** 等同于聊天原文, 权限要锁到只有自己

---

## 交付清单 (开发机给运维/接手人)

开发机做完本地测试后给接手人:

### 必给
- [ ] `dist/wechat-decrypt-release-<date>.zip` (三个 exe + config + docs 全在里面)
- [ ] 这份 `docs/06-delivery.md` (本文档) 单独拎出来也行
- [ ] `docs/README-network.md` (网络 MCP 详细参考)
- [ ] 一份"机器信息表": 目标 server IP / 端口 / hostname, 以及待接入的 client IP

### 按需给
- [ ] token 通过安全渠道 (密码管理器共享 / 1Password vault / 线下口头) 交付, **不通过 IM/邮件明文发**
- [ ] 如果 server 机器不是接手人自己的: SSH/RDP 访问凭据 (走安全渠道)

### 不要给
- [ ] 你开发机上的 `config.json` / `all_keys.json` / `decrypted/` — 每台机器都要独立提取密钥, 解密自己的数据库
- [ ] 任何包含 `%APPDATA%\Tencent\xwechat\config\*.ini` 路径副本的文件

---

## 故障排查快速查表

| 现象 | 最可能原因 | 处理 |
|---|---|---|
| 启动 monitor 弹杀毒告警 | 没加白名单 | A.3 步骤 |
| `未能提取到任何密钥` | `db_dir` 指错账号 | 改 config.json 或删掉它重跑让自动检测 |
| 本机 /health 通, 跨机超时 | 防火墙 | A.6.4 开入站 8765 |
| 跨机 /health 通, /sse 返回 403 | allow_clients 漏配对方 IP | config UI 加 IP → Save → Restart |
| 跨机 /sse 返回 401 | Bearer 缺失或 token 错 | 检查客户端 header |
| OpenClaw 说 "找不到 wechat MCP" | 没用 mcp-proxy 桥 / gateway 没重启 / TUI 没重开 | B.2.2 全流程 |
| agent 调用 wechat 有时成功有时失败 | token 在服务端内存过期 | mcp_server Restart (config UI) |
| Empty reply from server | DNS rebinding 防护 (老版本) | 升级到最新版 (0.6.0-network+), 已默认关了 |

---

## 附录 · 目录布局建议

**服务端** (.193 这种):
```
C:\tools\wechat-decrypt\
└── wechat-decrypt-release-<date>\
    ├── wechat-decrypt-mcp.exe
    ├── wechat-decrypt-config.exe
    ├── wechat-decrypt-monitor.exe
    ├── config.json            ← 你编辑这个 (从 config.example.json 复制)
    ├── all_keys.json          ← 首次启动后自动生成
    ├── decrypted\             ← SQLite 解密副本 (敏感)
    ├── decoded_images\        ← 图片缓存
    ├── logs\                  ← mcp_access.log + gateway 日志
    └── docs\
```

**客户端** (openclaw 这种):
```
/home/<user>/.local/bin/mcp-proxy        ← pip install --user 装的
/home/<user>/.openclaw/openclaw.json     ← MCP 配置文件
/home/<user>/.bashrc                     ← WECHAT_MCP_TOKEN env (推荐)
```

---

## 附录 · 最小验证序列 (30 秒)

装完服务端 + 客户端后, 跑这 6 条验证一遍:

```bash
# 1. 服务端本机 /health
curl.exe http://127.0.0.1:8765/health

# 2. 客户端跨机 /health
curl http://<server-ip>:8765/health

# 3. 客户端跨机 /sse 带 Bearer (应立刻返回 event: endpoint)
curl -H "Authorization: Bearer $TOKEN" --max-time 3 http://<server-ip>:8765/sse

# 4. 如果用 mcp-proxy: 直接跑 initialize 握手
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0.1"}}}' | \
  ~/.local/bin/mcp-proxy http://<server-ip>:8765/sse --transport sse -H Authorization "Bearer $TOKEN"

# 5. agent 调 health tool (在 client UI 里发)
# "用 wechat MCP 的 health tool 自检一下"

# 6. 服务端查访问日志 (应能看到每次 agent 调用的 ALLOW 记录)
# Windows: Get-Content C:\tools\wechat-decrypt\...\logs\mcp_access.log -Tail 20
```

6 条全绿 → 交付完成.
