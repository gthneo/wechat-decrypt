"""
构建源码发行包: dist/wechat-decrypt-<version>.zip

用法:
    python scripts/build_release.py           # 版本号取当前日期
    python scripts/build_release.py 1.2.0     # 手动指定版本

发行包内容:
    - 所有 *.py 源码
    - find_all_keys_macos.c
    - requirements.txt
    - config.example.json
    - README.md / USAGE.md
    - docs/*.md
    - install.bat / install.sh / run.bat / run.sh / run_decrypt.bat / run_decrypt.sh
    - tests/ 目录

排除:
    - config.json / all_keys.json (用户私有)
    - decrypted/ / decoded_images/ (用户数据)
    - __pycache__/ / *.pyc
    - .claude/ / .git/ / dist/
    - _messages_log.jsonl
"""
import datetime
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

INCLUDE_FILES = [
    "config.py",
    "decode_image.py",
    "decrypt_db.py",
    "find_all_keys.py",
    "find_all_keys_linux.py",
    "find_all_keys_windows.py",
    "find_all_keys_macos.c",
    "find_image_key.py",
    "find_image_key_monitor.py",
    "find_image_key.c",
    "key_scan_common.py",
    "key_utils.py",
    "latency_test.py",
    "main.py",
    "mcp_server.py",
    "monitor.py",
    "monitor_web.py",
    "decrypt_images.c",
    "requirements.txt",
    "config.example.json",
    "README.md",
    "USAGE.md",
    "CLAUDE.md",
]

INCLUDE_DIRS = [
    "docs",
    "tests",
]

# 这些脚本文件会由 build_release.py 在发行包里生成 / 同步
LAUNCHER_FILES = [
    "install.bat",
    "install.sh",
    "run.bat",
    "run.sh",
    "run_decrypt.bat",
    "run_decrypt.sh",
]


def resolve_version(argv):
    if len(argv) >= 2:
        return argv[1]
    return datetime.date.today().strftime("%Y.%m.%d")


def log(msg):
    print(f"[build] {msg}", flush=True)


def should_skip(path):
    """在打包 tests/ 等目录时跳过明显不该进发行包的文件"""
    base = os.path.basename(path)
    if base.startswith("."):
        return True
    if base == "__pycache__":
        return True
    if base.endswith(".pyc"):
        return True
    return False


def collect_files():
    """返回 [(abs_path, arc_path), ...]"""
    files = []

    # 顶层文件
    for rel in INCLUDE_FILES:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            log(f"  [skip] 缺失: {rel}")
            continue
        files.append((src, rel))

    # 目录递归
    for d in INCLUDE_DIRS:
        src_dir = os.path.join(ROOT, d)
        if not os.path.isdir(src_dir):
            log(f"  [skip] 缺失目录: {d}")
            continue
        for dirpath, dirnames, filenames in os.walk(src_dir):
            dirnames[:] = [x for x in dirnames if not should_skip(x)]
            for fn in filenames:
                if should_skip(fn):
                    continue
                abs_p = os.path.join(dirpath, fn)
                arc_p = os.path.relpath(abs_p, ROOT).replace(os.sep, "/")
                files.append((abs_p, arc_p))

    # 启动脚本 (由 build 本身负责生成到 scripts/launchers/)
    launcher_dir = os.path.join(ROOT, "scripts", "launchers")
    for fn in LAUNCHER_FILES:
        src = os.path.join(launcher_dir, fn)
        if not os.path.exists(src):
            log(f"  [skip] 缺失启动脚本: {fn}")
            continue
        files.append((src, fn))

    return files


def build_zip(version):
    os.makedirs(DIST, exist_ok=True)
    zip_name = f"wechat-decrypt-{version}.zip"
    zip_path = os.path.join(DIST, zip_name)
    if os.path.exists(zip_path):
        os.unlink(zip_path)

    files = collect_files()
    log(f"打包 {len(files)} 个文件 -> {zip_path}")

    prefix = f"wechat-decrypt-{version}"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for abs_p, arc_p in files:
            zf.write(abs_p, f"{prefix}/{arc_p}")

    size_kb = os.path.getsize(zip_path) / 1024
    log(f"完成: {zip_path} ({size_kb:.1f} KB)")
    return zip_path


def main():
    version = resolve_version(sys.argv)
    log(f"version = {version}")
    log(f"root    = {ROOT}")
    zip_path = build_zip(version)
    log("OK")
    return zip_path


if __name__ == "__main__":
    main()
