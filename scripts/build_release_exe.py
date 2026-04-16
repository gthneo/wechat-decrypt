"""
Bundle the three exes + config + docs + launcher scripts into a single
release zip for non-developer users.

Usage:
    python scripts/build_release_exe.py                # version = today's date
    python scripts/build_release_exe.py 1.2.0          # pinned version

Prerequisites:
    python scripts/build_all_exe.py     # must have succeeded first

Artifact:
    dist/wechat-decrypt-release-<version>.zip

Layout inside the zip:
    wechat-decrypt-release-<version>/
    ├── wechat-decrypt-mcp.exe
    ├── wechat-decrypt-config.exe
    ├── wechat-decrypt-monitor.exe
    ├── config.example.json
    ├── README-FIRST.txt
    ├── start-config.bat
    ├── start-monitor.bat
    └── docs/
        ├── README-network.md
        ├── 04-deployment.md
        └── 05-operations.md
"""
import datetime
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

REQUIRED_EXES = [
    "wechat-decrypt-mcp.exe",
    "wechat-decrypt-config.exe",
    "wechat-decrypt-monitor.exe",
]

DOCS_TO_INCLUDE = [
    "docs/README-network.md",
    "docs/04-deployment.md",
    "docs/05-operations.md",
]

README_FIRST = """wechat-decrypt release package
==============================

这是 wechat-decrypt 的可执行发行包。包含三个独立的 exe:

  wechat-decrypt-monitor.exe   实时消息监听 + Web UI (默认功能)
  wechat-decrypt-config.exe    本地网络 MCP 配置界面 (127.0.0.1:5679)
  wechat-decrypt-mcp.exe       MCP 服务 (stdio 或 SSE 两种模式)

首次使用
-------

1. 把整个目录(含三个 exe + config.example.json + docs)放到一个工作目录
   例如 C:\\tools\\wechat-decrypt\\

2. 复制 config.example.json 为 config.json, 按需编辑, 或者让 monitor
   首次启动时自动检测微信数据目录:

       wechat-decrypt-monitor.exe

3. 确保以管理员身份运行终端(提取微信密钥需要读取进程内存)

4. 以下是常用操作:

   实时监听新消息 + Web UI (http://localhost:5678):
       wechat-decrypt-monitor.exe

   一次性全量解密所有数据库到 decrypted/:
       wechat-decrypt-monitor.exe decrypt

   启动网络 MCP 的配置 UI (http://127.0.0.1:5679):
       wechat-decrypt-monitor.exe config-web
   或:
       wechat-decrypt-config.exe

   作为 stdio MCP 服务被 Claude Desktop 调用时, 不需要手动运行;
   在 Claude Desktop 配置里指向 wechat-decrypt-mcp.exe 即可。

网络 MCP (暴露给局域网里的 Agent)
--------------------------------

详见 docs/README-network.md

重要安全提醒
-----------

- config.json 包含路径和网络配置, auth_token 非公开, 不要提交到 git
- all_keys.json 是 SQLCipher 密钥, 泄露等同于对方能解密你的聊天记录
- decrypted/ 下是解密后的 SQLite 数据库, 等同于你的聊天原文
- 所有这些文件都与 .exe 同目录, 请做好本地访问控制

杀毒软件误报
-----------

本工具扫描微信进程内存以提取 SQLCipher 密钥, 与"密码窃取"行为在技术上
相似, 可能被 Windows Defender / 360 / 火绒等误报为病毒。本工具是开源的
(源码见 README-network.md 末尾的仓库链接), 请加入杀软白名单后再运行。

支持
----

源代码: https://github.com/gthneo/wechat-decrypt
问题反馈: 同上的 Issues 区
"""

START_CONFIG_BAT = """@echo off
REM 启动本地配置 UI (http://127.0.0.1:5679)
REM 需要先有 config.json (第一次从 config.example.json 复制即可)
cd /d "%~dp0"
if not exist config.json (
    echo [*] 从模板创建 config.json
    copy /y config.example.json config.json >nul
)
wechat-decrypt-config.exe
pause
"""

START_MONITOR_BAT = """@echo off
REM 启动实时 Web UI + 监听 (http://localhost:5678)
REM 需要管理员权限
cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
    echo [*] 需要管理员权限, 正在提权...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && wechat-decrypt-monitor.exe && pause' -Verb RunAs"
    exit /b
)

wechat-decrypt-monitor.exe
pause
"""


def resolve_version(argv):
    if len(argv) >= 2:
        return argv[1]
    return datetime.date.today().strftime("%Y.%m.%d")


def log(msg):
    print(f"[release] {msg}", flush=True)


def check_prereqs():
    missing = []
    for exe in REQUIRED_EXES:
        if not os.path.isfile(os.path.join(DIST, exe)):
            missing.append(exe)
    if missing:
        log("缺少以下 exe, 请先跑 scripts/build_all_exe.py:")
        for m in missing:
            log(f"  - dist/{m}")
        return False
    return True


def build_zip(version):
    zip_name = f"wechat-decrypt-release-{version}.zip"
    zip_path = os.path.join(DIST, zip_name)
    if os.path.exists(zip_path):
        os.unlink(zip_path)

    prefix = f"wechat-decrypt-release-{version}"

    log(f"目标: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # exes
        for exe in REQUIRED_EXES:
            src = os.path.join(DIST, exe)
            zf.write(src, f"{prefix}/{exe}")
            log(f"  + {exe}  ({os.path.getsize(src) / 1024 / 1024:.1f} MB)")

        # config template
        cfg_example = os.path.join(ROOT, "config.example.json")
        zf.write(cfg_example, f"{prefix}/config.example.json")
        log("  + config.example.json")

        # docs
        for rel in DOCS_TO_INCLUDE:
            src = os.path.join(ROOT, rel)
            if not os.path.exists(src):
                log(f"  [skip] 缺失: {rel}")
                continue
            zf.write(src, f"{prefix}/{rel}")
            log(f"  + {rel}")

        # generated text files
        zf.writestr(f"{prefix}/README-FIRST.txt", README_FIRST)
        log("  + README-FIRST.txt (generated)")

        zf.writestr(f"{prefix}/start-config.bat", START_CONFIG_BAT)
        zf.writestr(f"{prefix}/start-monitor.bat", START_MONITOR_BAT)
        log("  + start-config.bat / start-monitor.bat (generated)")

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    log(f"完成: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def main():
    version = resolve_version(sys.argv)
    log(f"version = {version}")
    if not check_prereqs():
        sys.exit(1)
    build_zip(version)
    log("OK")


if __name__ == "__main__":
    main()
