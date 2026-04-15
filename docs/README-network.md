# 网络 MCP — 把 mcp_server 暴露给局域网里的 Agent

默认情况下 `mcp_server.py` 用 stdio 传输，只能被本机的 MCP Client (Claude Desktop / Claude Code) 通过标准输入输出调用。

从这次改动起它还能以 **SSE** 或 **streamable-http** 的方式监听一个 TCP 端口, 供**另一台机器**上的 Agent 远程调用. 所有主机名 / IP / 端口 / token 都走 `config.json` 和本地配置 UI, **绝不写死在源码里**.

---

## 1. 一键启动 — 用本地配置 UI 配所有东西

```bash
python main.py config-web
# 或
python config_web.py
```

配置 UI **只绑 `127.0.0.1:5679`**, 外部无法访问. 浏览器打开 <http://127.0.0.1:5679/>, 有四个面板:

1. **① MCP Service** — transport (`sse`/`streamable-http`/`stdio`), bind host/port, start/stop mcp server 按钮 (管理 `mcp_server.py` 子进程), token 生成/复制, TLS 开关
2. **② Allowed Clients** — 增删改允许接入的客户端, 每条记录**同时有 IP 和 Domain 两个字段**, 任一匹配即放行; 每行有 "Test IP" 和 "Test Domain" 两个探测按钮, 可以分别验证 IP 路径和域名路径能不能打通
3. **③ Probe External Gateway** — 单独的 URL 探测 (e.g. 用来 ping openclaw 网关)
4. **④ mcp_access.log (tail)** — 最后 100 行访问日志, 每 5 秒刷新

点 **Save Config** 把当前页面的值写回 `config.json` (原子写入, 不会覆盖无关字段). 点 **Start** 让 `mcp_server.py` 作为子进程跑起来 (stdout 丢弃, stderr 保留到进程日志). **改 config 后需要 Restart MCP 让 mcp_server 读到新配置**.

---

## 2. `config.json` 里的 `network` 段

所有网络相关配置都在这一段里, 老配置没有此段照常 load:

```json
{
    "network": {
        "enabled": false,
        "transport": "sse",
        "bind_host": "0.0.0.0",
        "bind_port": 8765,
        "public_url": "",
        "auth_token": "",
        "tls": { "enabled": false, "cert": "", "key": "" },
        "allow_clients": [
            {
                "label": "openclaw-178",
                "ip": "192.168.31.178",
                "domain": "AIcats178.lan",
                "enabled": true
            }
        ],
        "rate_limit_per_min": 120
    }
}
```

| 字段 | 作用 |
|---|---|
| `enabled` | `false` (默认) 时 `mcp_server.py` 走 stdio, `true` 时走下面的 `transport` |
| `transport` | `sse` / `streamable-http` / `stdio` — 建议 `sse` (兼容性最好) |
| `bind_host` / `bind_port` | 监听地址; `0.0.0.0` 表示所有接口 |
| `public_url` | 仅显示给 UI, 不影响路由逻辑 |
| `auth_token` | Bearer 鉴权 token; **留空 = 不校验 token** |
| `tls.enabled` | 启用后必须同时填 `tls.cert` + `tls.key` (PEM 格式路径) |
| `allow_clients[]` | 允许入站的客户端清单; 每条**同时有 ip 和 domain**, 任一命中即放行 |
| `rate_limit_per_min` | 每个 (ip, host) 组合每分钟最多请求数 (默认 120) |

---

## 3. 允许客户端的 "IP 和 Domain 双路径"

这是本次改动的关键点. 客户端清单里每一条像:

```json
{ "label": "openclaw-178", "ip": "192.168.31.178", "domain": "AIcats178.lan", "enabled": true }
```

服务端匹配规则:

1. **拿请求方的源 IP** → 看是不是在 `allow_clients[].ip` 集合里
2. **拿 HTTP `Host` 头的主机名部分 (小写)** → 看是不是在 `allow_clients[].domain` 集合里
3. **任意一个命中即放行**

这样一个客户端既可以通过 IP 直连 (`curl http://192.168.31.178:8765/sse`), 也可以通过本地 `hosts` / DNS 解析的域名访问 (`curl http://aicats178.lan:8765/sse`), 两条路径都工作, 配置里**写一次**即可.

**如果 `allow_clients` 里没有任何 `enabled=true` 的条目, 将接受所有 IP/域名的请求** (只受 `auth_token` 和 `rate_limit` 约束). 这等同于"**裸跑**", 生产环境不建议.

---

## 4. 鉴权 + 限流

- **`auth_token` 非空时**: 请求必须带 `Authorization: Bearer <token>`, 否则返回 `401`. 使用 `secrets.compare_digest` 做定时不敏感比较
- **`rate_limit_per_min`**: 每分钟每 `(ip, host)` 组合最多 N 次请求, 超限返回 `429`. 滑动窗口实现
- **访问日志**: `logs/mcp_access.log` 每行一个事件, 格式 `<ISO 时间> <EVENT> ip=<ip> host=<host> <detail>`, 事件类型有 `ALLOW` / `DENY_IP` / `DENY_NOAUTH` / `DENY_BADTOKEN` / `DENY_RATE`

---

## 5. `/health` 免鉴权健康端点

不管 `auth_token` / `allow_clients` 配成什么, `GET /health` 都会无条件返回:

```json
{ "ok": true, "version": "0.6.0-network", "ts": 1776099999 }
```

这个端点**故意不做任何鉴权**, 因为它专门给配置 UI 的 "Test IP" / "Test Domain" 按钮和外部 uptime 监控使用. 它**不返回任何敏感数据**.

同时 MCP 层面也有一个 `health()` tool, 鉴权 + 白名单都要过, 返回同样的 JSON, 用于 Agent 侧自检.

---

## 6. 在另一台机器 (openclaw) 上接入

假设 mcp_server 跑在 `192.168.31.193:8765`, `auth_token = <your-generated-token>`, openclaw 在 `192.168.31.178` 上.

### 连通性自检 (.178 → .193)

```bash
curl http://192.168.31.193:8765/health
# 期望: {"ok":true,"version":"0.6.0-network","ts":...}
```

### SSE 握手

```bash
curl -N -H "Authorization: Bearer <your-generated-token>" \
     http://192.168.31.193:8765/sse
# 期望: 建立 SSE 连接, 收到 event: endpoint / data: ...
```

### 如果用域名

前提: openclaw 机器的 `/etc/hosts` 或 DNS 能解析 `mcp-backend.lan → 192.168.31.193`.

```bash
curl -H "Host: mcp-backend.lan" http://192.168.31.193:8765/health
curl -H "Host: mcp-backend.lan" -H "Authorization: Bearer <token>" http://192.168.31.193:8765/sse
```

两种访问都能通过, **只要在 config 里把 IP 和 domain 都填上**.

### MCP Client 配置 (openclaw 作为 Client)

如果 openclaw 用的是 mcp SDK >= 1.0, 它支持 `sse` 传输:

```json
{
  "mcpServers": {
    "wechat-remote": {
      "type": "sse",
      "url": "http://192.168.31.193:8765/sse",
      "headers": {
        "Authorization": "Bearer <your-generated-token>"
      }
    }
  }
}
```

---

## 7. 运维与安全建议

### 必做

1. **生成一个真正的 `auth_token`** (UI 上点 Generate). 留空在局域网里也不安全.
2. **配 `allow_clients`**, 不要裸跑.
3. **`config_web.py` 绑 loopback 的限制不可修改**. 写进源码了, 任何情况下 config UI 都不对外.

### 选做但推荐

4. **TLS**: 用自签证书即可 (`openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes`), 填到 `tls.cert` / `tls.key`, 勾 `tls.enabled` → 变成 `https://... :8765/sse`
5. **定期旋转 `auth_token`**: UI 上 Generate + Copy 新 token, openclaw 侧同步更新, 重启 mcp_server
6. **日志滚动**: `logs/mcp_access.log` 长期运行会变大, Windows 可以用 `logrotate` / 任务计划定时截断, Linux 用 `logrotate` 即可

### 绝对不能

- 把 `auth_token` 明文 commit 进 git (`.gitignore` 已经排除 `config.json`)
- 把 `config_web.py` 绑到 `0.0.0.0` (会让任何人无鉴权改你的 MCP 配置 — 权限比 MCP 本身还大)
- 在 `bind_host=0.0.0.0` + 无 `auth_token` + 无 `allow_clients` 的状态下长期运行

---

## 8. 故障排查

| 症状 | 可能原因 |
|---|---|
| `python config_web.py` 端口 5679 被占 | 改 `CONFIG_WEB_PORT` (代码里写死的, 故意不暴露到 config 防止误配) |
| UI 里 Start 后立刻 Stop (rc≠0) | 看 `tail logs/mcp_access.log` + config UI 上 "Refresh" 按钮旁的状态行; 常见是 `network.enabled=false` 或 `bind_port` 被其它进程占用 |
| curl /health 返回 `connection refused` | mcp_server 没跑 / `bind_host` 不对 / 防火墙拦截 |
| curl /health 返回 200 但 /sse 返回 403 | IP 或 Host 不在 `allow_clients` 白名单里 |
| curl /sse 返回 401 | 忘带 `Authorization: Bearer` 或 token 写错 |
| curl /sse 返回 429 | 超过 `rate_limit_per_min` — 调大或自查客户端是否在 busy loop |
| 上面都没事但 MCP Client 那边就是连不上 | Client 用的是 `streamable-http` 而 server 是 `sse`, 或反过来 |

---

## 9. 和其它组件的关系

| 组件 | 端口 | 绑定 | 数据 |
|---|---|---|---|
| `main.py` → `monitor_web.py` | 5678 | 0.0.0.0 (默认) | 实时 Web UI + SSE 消息流 |
| `main.py config-web` → `config_web.py` | 5679 | **127.0.0.1 only** | 配置管理 UI (只你自己能访问) |
| `mcp_server.py` (stdio) | — | — | 本地 Claude Desktop / Claude Code |
| `mcp_server.py` (sse/http) | 8765 (默认) | 看 `bind_host` | 远端 Agent 调 MCP 工具 |

**三者解耦**: `config_web` 管 `mcp_server` 子进程，不干扰 `monitor_web`；`mcp_server` 可以和 `monitor_web` 并行跑 (它们都读同一份解密库, 只是缓存目录不同).
