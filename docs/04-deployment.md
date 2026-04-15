# 04 · 部署手册

## 1. 环境要求

### 公共

- **Python 3.10+** (如果使用源码发行包)
- **微信 4.x** 正在运行且已登录
- 磁盘空间 500 MB+ (解密副本 + 图片缓存)

### Windows

- Windows 10 / 11
- **管理员终端**（读取进程内存 + `/proc` 等效 API）
- `D:\xwechat_files\<wxid>\db_storage` 或默认微信数据目录

### Linux

- 64-bit Linux
- `root` 或拥有 `CAP_SYS_PTRACE`（读取 `/proc/<pid>/mem`）
- `~/Documents/xwechat_files/<wxid>/db_storage`

### macOS

- Apple Silicon / Intel
- Xcode Command Line Tools (`xcode-select --install`)
- 微信已 ad-hoc 签名: `sudo codesign --force --deep --sign - /Applications/WeChat.app`
- `sudo` 权限
- 注意: macOS 没有 Python 实现，只能用编译后的 `find_all_keys_macos`

## 2. 两种部署形态

### 形态 A: 源码发行包 (推荐)

文件: `wechat-decrypt-<ver>.zip`

优点: 体积小（~几百 KB），更新方便，不会被杀毒软件误报。

内容:

```
wechat-decrypt-<ver>/
├── *.py                    # 全部 Python 源码
├── find_all_keys_macos.c   # macOS 扫描器 C 源码
├── requirements.txt
├── config.example.json
├── install.bat / install.sh       # 一键建 venv + pip install
├── run.bat / run.sh               # 一键启动 (Windows 会自动请求管理员)
├── run_decrypt.bat / run_decrypt.sh   # 一次性全量解密
├── README.md
├── USAGE.md
└── docs/
    ├── 01-objectives.md
    ├── 02-architecture.md
    ├── 03-test-cases.md
    ├── 04-deployment.md
    └── 05-operations.md
```

### 形态 B: 单文件可执行 (可选)

文件: `wechat-decrypt.exe` (Windows only，~60 MB)

优点: 用户无需 Python。  
缺点: 体积大、可能被杀毒软件误报（扫描进程内存）、更新需要重新下载。

## 3. 部署步骤

### 3.1 源码发行包 · Windows

```cmd
:: 1. 解压
:: 2. 双击 install.bat (首次)
install.bat

:: 3. 以管理员方式启动
run.bat
```

`install.bat` 做的事:
- 检查 `python --version` ≥ 3.10
- 建 `.venv` 虚拟环境
- `pip install -r requirements.txt`
- 提示用户复制 `config.example.json` 到 `config.json` 并填 `db_dir`

`run.bat` 做的事:
- 检测是否以管理员运行，不是则自提权重启
- `.venv\Scripts\activate`
- `python main.py`

### 3.2 源码发行包 · Linux

```bash
# 1. 解压
unzip wechat-decrypt-<ver>.zip
cd wechat-decrypt-<ver>

# 2. 安装
./install.sh

# 3. 启动（需要 sudo 或 CAP_SYS_PTRACE）
sudo ./run.sh
```

### 3.3 源码发行包 · macOS

macOS 的密钥扫描器是 C，不在 Python 流程里。

```bash
# 1. 解压 + 安装 Python 依赖
unzip wechat-decrypt-<ver>.zip
cd wechat-decrypt-<ver>
./install.sh

# 2. 编译 macOS 扫描器
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation

# 3. 先用 C 程序提取密钥
sudo ./find_all_keys_macos      # 输出 all_keys.json

# 4. 再用 Python 启动监听器或解密器
./run.sh                        # 或 ./run_decrypt.sh
```

### 3.4 单文件可执行 · Windows

```cmd
:: 1. 右键"以管理员身份运行"
wechat-decrypt.exe

:: 或命令行:
wechat-decrypt.exe decrypt
```

> .exe 与源码行为一致，但首次启动会较慢（解包临时目录 + 导入模块）。  
> 杀毒软件误报请在软件白名单里放行。

## 4. 配置 `config.json`

**首次启动会自动生成**，也可以手动复制 `config.example.json`:

```json
{
    "db_dir": "D:\\xwechat_files\\wxid_xxxx\\db_storage",
    "keys_file": "all_keys.json",
    "decrypted_dir": "decrypted",
    "decoded_image_dir": "decoded_images",
    "wechat_process": "Weixin.exe",
    "image_aes_key": null,
    "image_xor_key": 136
}
```

| 字段 | 说明 |
|---|---|
| `db_dir` | 当前登录微信账号的 `db_storage` 目录 |
| `keys_file` | SQLCipher 密钥文件输出路径 |
| `decrypted_dir` | 解密后数据库的存放目录 |
| `decoded_image_dir` | 图片缓存目录 |
| `wechat_process` | 进程名 (Windows: `Weixin.exe`, Linux: `wechat`, macOS: `WeChat`) |
| `image_aes_key` | V2 图片 AES key (由 `find_image_key_monitor.py` 自动写入) |
| `image_xor_key` | V2 图片 XOR 字节 (默认 0x88，微信更新后可能变化) |

切换微信账号后 `db_dir` 会变，`ensure_keys()` 会检测到并触发重新提取。

## 5. 集成 MCP Server 到 Claude Code

完成部署后，让 Claude 直接读取微信数据:

```bash
# 使用 .venv 里的 python
claude mcp add wechat -- <install_dir>/.venv/Scripts/python.exe <install_dir>/mcp_server.py
```

或手动编辑 `~/.claude.json`:

```json
{
  "mcpServers": {
    "wechat": {
      "type": "stdio",
      "command": "C:/Users/you/wechat-decrypt/.venv/Scripts/python.exe",
      "args": ["C:/Users/you/wechat-decrypt/mcp_server.py"]
    }
  }
}
```

前置条件: `all_keys.json` 已存在（先跑一次 `run.bat` 或 `run_decrypt.bat` 把密钥提取出来）。

## 6. 升级流程

### 源码发行包

```bash
# 停掉正在运行的 main.py (Ctrl+C)
# 备份现有目录
mv wechat-decrypt wechat-decrypt.old

# 解压新版本
unzip wechat-decrypt-<new-ver>.zip
mv wechat-decrypt-<new-ver> wechat-decrypt

# 复用旧的 config.json / all_keys.json / .venv
cp wechat-decrypt.old/config.json wechat-decrypt/
cp wechat-decrypt.old/all_keys.json wechat-decrypt/
cp -r wechat-decrypt.old/.venv wechat-decrypt/         # (可选, 快)
cp -r wechat-decrypt.old/decrypted wechat-decrypt/     # (可选, 保留历史)

# 如果 requirements.txt 有更新:
cd wechat-decrypt && .venv/Scripts/pip install -r requirements.txt

./run.bat
```

### 单文件 .exe

直接替换 .exe 文件即可。`config.json` / `all_keys.json` 是同目录的外部文件，不受影响。

## 7. 卸载

```bash
# 1. 关闭 main.py
# 2. 可选: 从 Claude Code 移除 MCP
claude mcp remove wechat

# 3. 删除整个目录
rm -rf wechat-decrypt/
```

`config.json`、`all_keys.json`、`decrypted/`、`decoded_images/` 都在安装目录内，不会散落到系统其他位置。
