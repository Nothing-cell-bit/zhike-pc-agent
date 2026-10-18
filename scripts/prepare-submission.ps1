param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m unittest scripts.test_submission
    if ($LASTEXITCODE -ne 0) { throw 'Submission tool tests failed.' }
    & $pythonPath scripts/prepare_submission.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed. Review the error above.' }
    if (!$NoOpen) { Start-Process (Join-Path $projectRoot 'output\submission\index.html') }
} finally { Pop-Location }
