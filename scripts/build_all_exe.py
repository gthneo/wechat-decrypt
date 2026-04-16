"""
Build three standalone exes via PyInstaller:
  - wechat-decrypt-mcp.exe      (mcp_server.py — stdio & network SSE)
  - wechat-decrypt-config.exe   (config_web.py — local config UI)
  - wechat-decrypt-monitor.exe  (main.py — monitor / decrypt / config-web dispatcher)

Usage:
    python scripts/build_all_exe.py

Artifacts land in dist/. Intermediate build/ is wiped each run.
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

HIDDEN_IMPORTS = [
    # Platform dispatch
    "find_all_keys_windows", "find_all_keys_linux",
    # Crypto
    "Crypto.Cipher.AES", "Crypto.Util.Padding",
    "zstandard",
    # MCP SDK
    "mcp", "mcp.server", "mcp.server.fastmcp",
    "mcp.server.transport_security",
    "mcp.server.stdio", "mcp.server.sse", "mcp.server.streamable_http",
    # Web stack
    "starlette", "starlette.middleware.base",
    "uvicorn", "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto", "uvicorn.lifespan.on",
    # Timezone on Windows
    "tzdata",
]

TARGETS = [
    ("wechat-decrypt-mcp", "mcp_server.py"),
    ("wechat-decrypt-config", "config_web.py"),
    ("wechat-decrypt-monitor", "main.py"),
]


def build_one(name, entry):
    print(f"\n=== Building {name}.exe ===")
    t0 = time.time()
    cfg_example_abs = os.path.join(ROOT, "config.example.json")
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--console",
        "--noupx",
        "--name", name,
        "--add-data", f"{cfg_example_abs}{os.pathsep}.",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    for h in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", h])
    cmd.append(os.path.join(ROOT, entry))

    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"[!] {name} build failed (rc={result.returncode}, {elapsed:.1f}s)")
        return False

    exe_path = os.path.join(DIST, f"{name}.exe")
    if not os.path.exists(exe_path):
        print(f"[!] expected exe not found: {exe_path}")
        return False

    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"[+] {name}.exe  {size_mb:.1f} MB  ({elapsed:.1f}s)")
    return True


def main():
    os.chdir(ROOT)

    # Clean stale artifacts
    if os.path.isdir(os.path.join(ROOT, "build")):
        shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
    for name, _ in TARGETS:
        exe = os.path.join(DIST, f"{name}.exe")
        if os.path.exists(exe):
            os.unlink(exe)

    try:
        subprocess.run(["pyinstaller", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("[*] Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    ok_count = 0
    for name, entry in TARGETS:
        if build_one(name, entry):
            ok_count += 1

    print()
    print(f"=== Build summary: {ok_count}/{len(TARGETS)} succeeded ===")
    for name, _ in TARGETS:
        exe = os.path.join(DIST, f"{name}.exe")
        if os.path.exists(exe):
            size_mb = os.path.getsize(exe) / (1024 * 1024)
            print(f"  OK   {exe}  {size_mb:.1f} MB")
        else:
            print(f"  FAIL {exe}  MISSING")

    return 0 if ok_count == len(TARGETS) else 1


if __name__ == "__main__":
    sys.exit(main())
