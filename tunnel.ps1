# 隧道管理脚本：一键重启并显示最新公网 URL
# 用法：右键"使用 PowerShell 运行"，或
#   powershell -ExecutionPolicy Bypass -File tunnel.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 已在跑就先停掉
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# 前置检查：网站本身必须活着，否则隧道开了也是 502
try {
    Invoke-WebRequest -Uri "http://localhost:8080" -UseBasicParsing -TimeoutSec 5 | Out-Null
} catch {
    Write-Host "!! 本地 8080 没有响应，先执行: docker compose up -d" -ForegroundColor Red
    pause
    exit 1
}

# 清掉旧日志再启动，避免读到上一次的 URL
Remove-Item "$root/cf_out.log", "$root/cf_err.log" -ErrorAction SilentlyContinue
Start-Process -FilePath "$root/cloudflared.exe" `
    -ArgumentList "tunnel --url http://localhost:8080" `
    -RedirectStandardOutput "$root/cf_out.log" `
    -RedirectStandardError "$root/cf_err.log" `
    -WindowStyle Hidden

# 等 CF 分配 URL
$url = $null
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    $match = Select-String -Path "$root/cf_err.log" -Pattern "https://\S+trycloudflare.com" -ErrorAction SilentlyContinue |
        Select-Object -Last 1
    if ($match) { $url = $match.Matches.Value; break }
}

if ($url) {
    Write-Host ""
    Write-Host "公网地址（发给任何人）：$url" -ForegroundColor Green
    Set-Clipboard -Value $url
    Write-Host "已复制到剪贴板。" -ForegroundColor Green
    Write-Host "注意：本窗口可以关，cloudflared 进程会继续在后台运行；"
    Write-Host "电脑休眠/关机后网站下线，重新开机后需再跑一次本脚本（URL 会变）。"
} else {
    Write-Host "未能获取 URL，请查看 cf_err.log 排查。" -ForegroundColor Red
}
