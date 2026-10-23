param([switch]$Fresh,[int]$Port=8780)
$ErrorActionPreference='Stop'
$quoteRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $quoteRoot
if ($Port -lt 1024 -or $Port -gt 65535) {throw '端口须介于 1024 与 65535'}
$quotePointer=Join-Path $quoteRoot 'tmp\quote-demo-current.txt'
$quoteData=if (!$Fresh -and (Test-Path -LiteralPath $quotePointer)) {(Get-Content -LiteralPath $quotePointer -Raw).Trim()} else {''}
if ($quoteData) {
    $quoteResolved=[IO.Path]::GetFullPath($quoteData)
    $quoteAllowed=[IO.Path]::GetFullPath((Join-Path $quoteRoot 'tmp'))+[IO.Path]::DirectorySeparatorChar
    if (!$quoteResolved.StartsWith($quoteAllowed,[StringComparison]::OrdinalIgnoreCase) -or !(Split-Path -Leaf $quoteResolved).StartsWith('quote-demo-')) {throw '演示目录不在允许范围'}
}
if (!$quoteData -or !(Test-Path -LiteralPath (Join-Path $quoteData 'store.db'))) {
    $quoteData=Join-Path $quoteRoot ('tmp\quote-demo-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $quoteData | Out-Null
    Set-Content -LiteralPath $quotePointer -Value $quoteData
    $env:DEMO_RESUME='0'
} else {$env:DEMO_RESUME='1'}
$env:E2E_DATA_DIR=$quoteData
Write-Host "演示客服：http://localhost:$Port/staff"
Write-Host "隔离演示账号文件：$quoteData\login.json"
Write-Host '所有价格和 SKU 均为演示测试数据；新建演示库的报价有效期为 24 小时。过期后可用 -Fresh 重建。'
& (Join-Path $quoteRoot '.venv\Scripts\python.exe') -m uvicorn scripts.quote_demo_server:app --host 127.0.0.1 --port $Port
