# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for wechat-decrypt.

用法 (Windows):
    pip install pyinstaller
    pyinstaller --clean scripts/wechat-decrypt.spec

产物:
    dist/wechat-decrypt.exe  — 单文件可执行

注意:
    - 产物扫描进程内存，可能被杀毒软件误报，请自行加白名单
    - .exe 与 main.py 行为一致: `wechat-decrypt.exe` 启动 Web UI,
      `wechat-decrypt.exe decrypt` 做一次性解密
    - config.json / all_keys.json / decrypted/ 仍然是 .exe 同目录的外部文件
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # 模板配置文件, 运行时可被 config.py 读取
        (os.path.join(ROOT, 'config.example.json'), '.'),
    ],
    hiddenimports=[
        # 显式列出动态/条件导入的子模块, 否则 PyInstaller 静态分析可能漏掉
        'find_all_keys_windows',
        'find_all_keys_linux',
        'Crypto.Cipher.AES',
        'Crypto.Util.Padding',
        'zstandard',
        'mcp',
        'mcp.server',
        'mcp.server.stdio',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本项目不需要 GUI / 科学计算栈
        'tkinter',
        'matplotlib',
        'numpy',
        'PIL.ImageTk',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='wechat-decrypt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX 压缩会进一步触发 AV 误报, 关掉
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,            # 命令行程序
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=os.path.join(ROOT, 'assets', 'icon.ico'),   # 如有图标可打开
)
