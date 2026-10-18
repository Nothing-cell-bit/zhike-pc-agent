param([switch]$Build, [switch]$Lan)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 创建虚拟环境并安装 requirements.txt。' }
if ($Build -or !(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
    Push-Location (Join-Path $projectRoot 'frontend')
    try { npm run build; if ($LASTEXITCODE -ne 0) { throw '前端构建失败' } }
    finally { Pop-Location }
}
$bindAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
Write-Host '客户入口：http://127.0.0.1:8765/  客服入口：http://127.0.0.1:8765/staff'
if ($Lan) { Write-Host '局域网手机使用本机局域网 IP 的 8765 端口。请仅在可信网络使用。' }
& $pythonPath -m uvicorn backend.main:app --host $bindAddress --port 8765
