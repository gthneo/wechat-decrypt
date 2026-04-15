"""
配置 Web UI  —  运维本地管理 MCP network 配置 + 启停 mcp_server 子进程

绑定地址: 127.0.0.1:5679 (写死 loopback, 外部无法访问)
启动: python config_web.py  |  python main.py config-web

功能面板 (单页):
  1) MCP 服务  —  transport/host/port, start/stop, 状态, token 生成/复制/旋转, TLS
  2) 允许的客户端  —  IP + Domain 双列表 CRUD, 独立探测两列
  3) 探测与诊断  —  远端 openclaw gateway 探测
  4) 运行日志    —  tail logs/mcp_access.log 最后 N 行
"""
import copy
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from config import (
    CONFIG_FILE,
    _APP_DIR,
    _fill_network_defaults,
    generate_token,
    load_config,
    resolve_allowed_clients,
    save_config,
)


CONFIG_WEB_HOST = "127.0.0.1"
CONFIG_WEB_PORT = 5679
LOG_TAIL_LINES = 100
MCP_ACCESS_LOG = os.path.join(_APP_DIR, "logs", "mcp_access.log")


# ========== MCP subprocess 管理 ==========

class MCPProcessManager:
    """管理一个 mcp_server.py 子进程 (SSE/streamable-http 模式).

    生命周期完全独立于 config_web, start/stop 按钮不会重启 config_web 自己.
    """

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self._log_buf = []  # 最近 stderr 行
        self._reader = None

    def is_running(self):
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def status(self):
        with self._lock:
            if self._proc is None:
                return {"running": False, "pid": None, "returncode": None}
            rc = self._proc.poll()
            return {
                "running": rc is None,
                "pid": self._proc.pid,
                "returncode": rc,
            }

    def start(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return {"ok": True, "pid": self._proc.pid, "note": "already running"}
            py = sys.executable
            script = os.path.join(_APP_DIR, "mcp_server.py")
            if not os.path.exists(script):
                return {"ok": False, "error": f"mcp_server.py not found at {script}"}

            # Windows 下要 CREATE_NEW_PROCESS_GROUP 才能独立 Ctrl+C
            creationflags = 0
            if sys.platform.startswith("win"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            try:
                self._proc = subprocess.Popen(
                    [py, "-u", script],
                    cwd=_APP_DIR,
                    stdout=subprocess.DEVNULL,   # stdio 不需要, network 模式 stdout 也没用
                    stderr=subprocess.PIPE,
                    creationflags=creationflags,
                )
            except OSError as e:
                return {"ok": False, "error": str(e)}

            # 后台读 stderr 存到 _log_buf
            self._log_buf = []

            def _pump():
                proc = self._proc
                if proc is None or proc.stderr is None:
                    return
                for line in proc.stderr:
                    try:
                        s = line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        s = repr(line)
                    self._log_buf.append(s)
                    if len(self._log_buf) > 500:
                        self._log_buf = self._log_buf[-500:]

            self._reader = threading.Thread(target=_pump, daemon=True)
            self._reader.start()

            # 给子进程一点启动时间, 方便前端立即 status
            time.sleep(0.2)

            return {"ok": True, "pid": self._proc.pid}

    def stop(self):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return {"ok": True, "note": "not running"}
            try:
                self._proc.terminate()
            except OSError as e:
                return {"ok": False, "error": str(e)}
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
            return {"ok": True}

    def restart(self):
        self.stop()
        return self.start()

    def tail_stderr(self, n=50):
        with self._lock:
            return list(self._log_buf[-n:])


_mcp_manager = MCPProcessManager()


# ========== HTTP 辅助 ==========

def _tail_file(path, n):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                read_size = min(block, size)
                size -= read_size
                f.seek(size)
                data = f.read(read_size) + data
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[-n:]
    except OSError:
        return []


def _http_probe(url, timeout=3):
    """GET 一次 URL, 返回 (ok, status, ms, detail)"""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wechat-decrypt-config-web"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(1024)
            ms = int((time.perf_counter() - t0) * 1000)
            return {
                "ok": 200 <= r.status < 300,
                "status": r.status,
                "ms": ms,
                "body": body.decode("utf-8", errors="replace")[:200],
            }
    except urllib.error.HTTPError as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "status": e.code, "ms": ms, "body": str(e)}
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "status": None, "ms": ms, "body": str(e)}


# ========== HTTP Handler ==========

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"><title>wechat-decrypt config</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:#0a0a0f;color:#e0e0e0;padding:20px;max-width:1100px;margin:0 auto}
h1{font-size:22px;margin-bottom:6px;background:linear-gradient(90deg,#4fc3f7,#81c784);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{color:#666;font-size:12px;margin-bottom:20px}
.card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:16px;margin-bottom:18px}
.card h2{font-size:15px;color:#bbb;margin-bottom:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px}
.row{display:grid;grid-template-columns:160px 1fr;gap:10px;align-items:center;margin-bottom:8px}
label{color:#999;font-size:13px}
input[type=text],input[type=number],select{background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);color:#ccc;padding:6px 10px;border-radius:4px;font-size:13px;font-family:inherit;width:100%}
input[type=checkbox]{accent-color:#4fc3f7;width:16px;height:16px}
.btn{background:#1a1a2e;border:1px solid rgba(79,195,247,.3);color:#4fc3f7;padding:6px 14px;border-radius:4px;font-size:12px;cursor:pointer;margin-right:6px}
.btn:hover{background:rgba(79,195,247,.1)}
.btn.warn{border-color:rgba(255,213,79,.3);color:#ffd54f}
.btn.danger{border-color:rgba(244,67,54,.3);color:#ef9a9a}
.btn.primary{background:#0d47a1;border-color:#0d47a1;color:#fff}
.btn.primary:hover{background:#1565c0}
.status-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.status-dot.on{background:#4caf50;box-shadow:0 0 6px #4caf50}
.status-dot.off{background:#616161}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid rgba(255,255,255,.06)}
th{color:#777;font-weight:500;text-transform:uppercase;font-size:10px;letter-spacing:1px}
td input[type=text]{padding:4px 6px}
.probe-result{font-family:"SF Mono",Consolas,monospace;font-size:11px;color:#999}
.probe-result.ok{color:#81c784}
.probe-result.err{color:#ef5350}
pre.log{background:#000;padding:10px;border-radius:6px;max-height:300px;overflow-y:auto;font-size:11px;font-family:Consolas,monospace;color:#9e9e9e;white-space:pre-wrap;word-break:break-all}
.toast{position:fixed;top:20px;right:20px;background:#1a1a2e;border:1px solid rgba(79,195,247,.3);color:#4fc3f7;padding:10px 16px;border-radius:6px;font-size:13px;display:none}
.toast.show{display:block;animation:fadein .3s}
@keyframes fadein{from{opacity:0;transform:translateY(-10px)}to{opacity:1}}
.hint{font-size:11px;color:#555;margin-top:4px}
.token-box{display:flex;gap:6px;align-items:center}
.token-box input{font-family:"SF Mono",Consolas,monospace;font-size:12px}
</style></head><body>
<h1>wechat-decrypt &nbsp;·&nbsp; network config</h1>
<div class="sub">Bound to 127.0.0.1:5679 only — not accessible from network</div>

<div class="card">
<h2>① MCP Service</h2>
<div class="row"><label>Service status</label><div><span id="status-dot" class="status-dot off"></span><span id="status-text">checking...</span> &nbsp; <button class="btn primary" onclick="api('/api/mcp/start','POST')">Start</button><button class="btn warn" onclick="api('/api/mcp/stop','POST')">Stop</button><button class="btn" onclick="api('/api/mcp/restart','POST')">Restart</button><button class="btn" onclick="refreshStatus()">Refresh</button></div></div>
<div class="row"><label>network.enabled</label><div><input type="checkbox" id="net-enabled"> <span class="hint">unchecked = stdio-only (Claude Desktop 默认)</span></div></div>
<div class="row"><label>transport</label><select id="net-transport"><option value="sse">sse</option><option value="streamable-http">streamable-http</option><option value="stdio">stdio</option></select></div>
<div class="row"><label>bind host</label><input type="text" id="net-host" placeholder="0.0.0.0"></div>
<div class="row"><label>bind port</label><input type="number" id="net-port" min="1" max="65535"></div>
<div class="row"><label>public_url</label><input type="text" id="net-public-url" placeholder="http://example.lan:8765 (仅显示)"></div>
<div class="row"><label>auth_token</label><div class="token-box"><input type="text" id="net-token" placeholder="空串 = 禁用鉴权"><button class="btn" onclick="rotateToken()">Generate</button><button class="btn" onclick="copyToken()">Copy</button></div></div>
<div class="row"><label>rate limit / min</label><input type="number" id="net-rate" min="1" max="100000"></div>
<div class="row"><label>TLS enabled</label><div><input type="checkbox" id="tls-enabled"> cert: <input type="text" id="tls-cert" style="width:300px"> key: <input type="text" id="tls-key" style="width:300px"></div></div>
</div>

<div class="card">
<h2>② Allowed Clients (IP + Domain 任一命中即放行)</h2>
<table id="clients-tbl"><thead><tr><th>Enabled</th><th>Label</th><th>IP</th><th>Domain</th><th>Test IP</th><th>Test Domain</th><th></th></tr></thead><tbody></tbody></table>
<div style="margin-top:8px"><button class="btn" onclick="addClient()">+ Add client</button></div>
<div class="hint">"Test IP" 和 "Test Domain" 列分别用填的 IP / 域名去请求 http://&lt;addr&gt;:&lt;bind_port&gt;/health, 两列独立验证, 都通才算双路径都 OK</div>
</div>

<div class="card">
<h2>③ Probe External Gateway</h2>
<div class="row"><label>Target URL</label><input type="text" id="probe-url" placeholder="http://openclaw-host:18789/health"></div>
<div class="row"><label></label><div><button class="btn" onclick="probeUrl()">Probe</button> <span id="probe-result" class="probe-result"></span></div></div>
</div>

<div class="card">
<h2>④ mcp_access.log (tail)</h2>
<div style="margin-bottom:8px"><button class="btn" onclick="refreshLog()">Refresh</button></div>
<pre class="log" id="log-box">(empty)</pre>
</div>

<div style="display:flex;gap:10px;margin:20px 0"><button class="btn primary" onclick="saveCfg()">Save Config</button><button class="btn" onclick="loadCfg()">Reload from disk</button></div>

<div class="toast" id="toast"></div>

<script>
let CFG = null;

function toast(s, bad){
  const t=document.getElementById('toast');
  t.textContent=s; t.style.borderColor=bad?'#ef5350':'rgba(79,195,247,.3)'; t.style.color=bad?'#ef9a9a':'#4fc3f7';
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 3000);
}

async function api(path, method, body){
  const opts={method:method||'GET',headers:{'Content-Type':'application/json'}};
  if(body) opts.body=JSON.stringify(body);
  const r=await fetch(path, opts);
  const j=await r.json();
  if(!r.ok) toast(j.error||'error', true);
  else if(path.endsWith('/start')||path.endsWith('/stop')||path.endsWith('/restart')) toast('OK'), refreshStatus();
  return j;
}

function loadCfg(){
  fetch('/api/config').then(r=>r.json()).then(c=>{
    CFG=c;
    const n=c.network||{};
    document.getElementById('net-enabled').checked=!!n.enabled;
    document.getElementById('net-transport').value=n.transport||'sse';
    document.getElementById('net-host').value=n.bind_host||'0.0.0.0';
    document.getElementById('net-port').value=n.bind_port||8765;
    document.getElementById('net-public-url').value=n.public_url||'';
    document.getElementById('net-token').value=n.auth_token||'';
    document.getElementById('net-rate').value=n.rate_limit_per_min||120;
    const tls=n.tls||{};
    document.getElementById('tls-enabled').checked=!!tls.enabled;
    document.getElementById('tls-cert').value=tls.cert||'';
    document.getElementById('tls-key').value=tls.key||'';
    renderClients(n.allow_clients||[]);
  });
}

function renderClients(list){
  const tbody=document.querySelector('#clients-tbl tbody');
  tbody.innerHTML='';
  list.forEach((c, i)=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><input type="checkbox" ${c.enabled?'checked':''} data-i="${i}" data-f="enabled"></td>
      <td><input type="text" value="${esc(c.label||'')}" data-i="${i}" data-f="label"></td>
      <td><input type="text" value="${esc(c.ip||'')}" data-i="${i}" data-f="ip"></td>
      <td><input type="text" value="${esc(c.domain||'')}" data-i="${i}" data-f="domain"></td>
      <td><span class="probe-result" id="pi-${i}">-</span></td>
      <td><span class="probe-result" id="pd-${i}">-</span></td>
      <td><button class="btn" onclick="testClient(${i},'ip')">⟳IP</button><button class="btn" onclick="testClient(${i},'domain')">⟳Dom</button><button class="btn danger" onclick="delClient(${i})">×</button></td>`;
    tbody.appendChild(tr);
  });
}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML.replace(/"/g,'&quot;')}

function collectClients(){
  const rows=document.querySelectorAll('#clients-tbl tbody tr');
  const list=[];
  rows.forEach((tr, i)=>{
    const inputs=tr.querySelectorAll('input');
    const c={};
    inputs.forEach(inp=>{
      const f=inp.dataset.f;
      if(f==='enabled') c[f]=inp.checked;
      else c[f]=inp.value;
    });
    list.push(c);
  });
  return list;
}

function collectCfg(){
  CFG.network=CFG.network||{};
  const n=CFG.network;
  n.enabled=document.getElementById('net-enabled').checked;
  n.transport=document.getElementById('net-transport').value;
  n.bind_host=document.getElementById('net-host').value;
  n.bind_port=parseInt(document.getElementById('net-port').value||'8765',10);
  n.public_url=document.getElementById('net-public-url').value;
  n.auth_token=document.getElementById('net-token').value;
  n.rate_limit_per_min=parseInt(document.getElementById('net-rate').value||'120',10);
  n.tls=n.tls||{};
  n.tls.enabled=document.getElementById('tls-enabled').checked;
  n.tls.cert=document.getElementById('tls-cert').value;
  n.tls.key=document.getElementById('tls-key').value;
  n.allow_clients=collectClients();
  return CFG;
}

function saveCfg(){
  const c=collectCfg();
  api('/api/config','POST',c).then(j=>{
    if(j.ok) toast('Saved → '+(j.path||''));
  });
}

function addClient(){
  if(!CFG) return;
  CFG.network=CFG.network||{};
  CFG.network.allow_clients=CFG.network.allow_clients||[];
  CFG.network.allow_clients.push({label:'', ip:'', domain:'', enabled:true});
  renderClients(CFG.network.allow_clients);
}
function delClient(i){
  CFG.network.allow_clients=collectClients();
  CFG.network.allow_clients.splice(i,1);
  renderClients(CFG.network.allow_clients);
}
function testClient(i, kind){
  const cli=collectClients()[i];
  const addr = kind==='ip' ? cli.ip : cli.domain;
  if(!addr){document.getElementById(kind==='ip'?`pi-${i}`:`pd-${i}`).textContent='(空)';return;}
  const port=document.getElementById('net-port').value||'8765';
  const url=`http://${addr}:${port}/health`;
  const el=document.getElementById(kind==='ip'?`pi-${i}`:`pd-${i}`);
  el.textContent='…';
  api('/api/probe','POST',{url}).then(j=>{
    if(j.ok){el.textContent=`✓ ${j.ms}ms`; el.className='probe-result ok';}
    else {el.textContent=`✗ ${j.status||''} ${(j.body||'').slice(0,40)}`; el.className='probe-result err';}
  });
}

function probeUrl(){
  const url=document.getElementById('probe-url').value.trim();
  if(!url) return;
  const el=document.getElementById('probe-result');
  el.textContent='…';
  api('/api/probe','POST',{url}).then(j=>{
    if(j.ok){el.textContent=`✓ ${j.status} ${j.ms}ms  ${j.body.slice(0,80)}`; el.className='probe-result ok';}
    else {el.textContent=`✗ ${j.status||''} ${(j.body||'').slice(0,80)}`; el.className='probe-result err';}
  });
}

function refreshStatus(){
  fetch('/api/mcp/status').then(r=>r.json()).then(s=>{
    const dot=document.getElementById('status-dot');
    const t=document.getElementById('status-text');
    if(s.running){dot.className='status-dot on';t.textContent=`running (pid ${s.pid})`;}
    else{dot.className='status-dot off';t.textContent=`stopped`+(s.returncode!=null?` (rc=${s.returncode})`:'');}
  });
}

function refreshLog(){
  fetch('/api/log').then(r=>r.json()).then(j=>{
    const box=document.getElementById('log-box');
    box.textContent=(j.lines||[]).join('\\n') || '(empty)';
    box.scrollTop=box.scrollHeight;
  });
}

function rotateToken(){
  api('/api/token/rotate','POST').then(j=>{
    if(j.token) {document.getElementById('net-token').value=j.token; toast('New token generated');}
  });
}
function copyToken(){
  const t=document.getElementById('net-token').value;
  if(!t){toast('Token is empty',true);return;}
  navigator.clipboard.writeText(t).then(()=>toast('Token copied to clipboard'));
}

loadCfg(); refreshStatus(); refreshLog();
setInterval(refreshStatus, 3000);
setInterval(refreshLog, 5000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            ln = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            ln = 0
        if ln <= 0:
            return {}
        data = self.rfile.read(ln)
        try:
            return json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/config":
            cfg = load_config()
            self._send_json(cfg)
            return
        if self.path == "/api/mcp/status":
            self._send_json(_mcp_manager.status())
            return
        if self.path == "/api/log":
            lines = _tail_file(MCP_ACCESS_LOG, LOG_TAIL_LINES)
            self._send_json({"lines": lines})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/config":
            body = self._read_json()
            if not isinstance(body, dict):
                return self._send_json({"error": "invalid body"}, 400)
            # 合并: 保留原有字段, 只覆盖发来的 top-level keys
            current = load_config()
            current.update({k: v for k, v in body.items() if k != "_comment_network"})
            _fill_network_defaults(current)
            try:
                path = save_config(current)
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)
            return self._send_json({"ok": True, "path": path})
        if self.path == "/api/mcp/start":
            return self._send_json(_mcp_manager.start())
        if self.path == "/api/mcp/stop":
            return self._send_json(_mcp_manager.stop())
        if self.path == "/api/mcp/restart":
            return self._send_json(_mcp_manager.restart())
        if self.path == "/api/token/rotate":
            token = generate_token()
            return self._send_json({"token": token})
        if self.path == "/api/probe":
            body = self._read_json()
            url = body.get("url", "")
            if not url:
                return self._send_json({"error": "url required"}, 400)
            return self._send_json(_http_probe(url))
        self.send_error(404)


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    # 强制绑定 loopback, 任何 CLI 覆盖都不允许
    host = CONFIG_WEB_HOST
    port = CONFIG_WEB_PORT
    server = ThreadedServer((host, port), Handler)
    print(f"[config_web] http://{host}:{port}/ (loopback only)", flush=True)
    print(f"[config_web] config file: {CONFIG_FILE}", flush=True)
    print(f"[config_web] Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[config_web] stopping...", flush=True)
        _mcp_manager.stop()


if __name__ == "__main__":
    main()
