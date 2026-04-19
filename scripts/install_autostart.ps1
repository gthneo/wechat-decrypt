# 把 wechat-decrypt 三件套注册成 Windows 任务计划, 开机自启
# 用法 (以管理员身份启动 PowerShell):
#   cd C:\Users\Lenovo\as\freegthdatefromwechat
#   .\scripts\install_autostart.ps1
#
# 注销:
#   .\scripts\install_autostart.ps1 -Uninstall
#
# 只装 monitor (不需要配置 UI 和网络 MCP):
#   .\scripts\install_autostart.ps1 -MonitorOnly

param(
    [switch]$Uninstall,
    [switch]$MonitorOnly
)

$ErrorActionPreference = "Stop"

# 自动判当前仓库根目录 (脚本所在目录的上级)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir
$PythonExe = "python"   # 或改成 venv 里的 python.exe 完整路径
$User      = $env:USERNAME

Write-Host "=== wechat-decrypt autostart installer ==="
Write-Host "Repo root:   $RepoRoot"
Write-Host "Python:      $PythonExe"
Write-Host "User:        $User"
Write-Host ""

function Remove-TaskIfExists {
    param([string]$Name)
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  removing existing task: $Name"
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
}

function Register-DecryptTask {
    param(
        [string]$Name,
        [string[]]$Args,
        [bool]$NeedAdmin = $false
    )
    Remove-TaskIfExists -Name $Name

    $action = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument ($Args -join " ") `
        -WorkingDirectory $RepoRoot

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$User"

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)

    $principalArgs = @{
        UserId    = "$env:USERDOMAIN\$User"
        LogonType = "Interactive"
    }
    if ($NeedAdmin) {
        $principalArgs["RunLevel"] = "Highest"
    }
    $principal = New-ScheduledTaskPrincipal @principalArgs

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "  + registered: $Name"
}

if ($Uninstall) {
    Write-Host "Uninstalling..."
    Remove-TaskIfExists -Name "wechat-decrypt-monitor"
    Remove-TaskIfExists -Name "wechat-decrypt-config"
    Write-Host "Done."
    exit 0
}

# monitor 需要管理员 (读微信进程内存)
Register-DecryptTask `
    -Name "wechat-decrypt-monitor" `
    -Args @("main.py") `
    -NeedAdmin $true

if (-not $MonitorOnly) {
    # config_web 只绑 loopback, 不需要管理员
    # 它会管 mcp_server 子进程 — 所以注册 config 就等于自动托管 mcp_server
    Register-DecryptTask `
        -Name "wechat-decrypt-config" `
        -Args @("main.py", "config-web") `
        -NeedAdmin $false
}

Write-Host ""
Write-Host "=== Installed. Behavior ==="
Write-Host "- wechat-decrypt-monitor  runs at logon as Administrator (reads WeChat memory)"
if (-not $MonitorOnly) {
    Write-Host "- wechat-decrypt-config   runs at logon as your user (loopback UI only)"
    Write-Host "  Click Start in the config UI to spawn mcp_server (auto-managed subprocess)"
}
Write-Host ""
Write-Host "To start immediately without logoff/logon:"
Write-Host "  Start-ScheduledTask -TaskName 'wechat-decrypt-monitor'"
if (-not $MonitorOnly) {
    Write-Host "  Start-ScheduledTask -TaskName 'wechat-decrypt-config'"
}
Write-Host ""
Write-Host "To uninstall:  .\scripts\install_autostart.ps1 -Uninstall"
