# Windows launcher for the two-model stand (Mini 2 + MIDI).
# Usage:  powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model mini
#         powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model midi
param([ValidateSet("mini", "midi")][string]$Model = "mini")
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Run = Join-Path $Dir "run"
New-Item -ItemType Directory -Force -Path $Run | Out-Null

if (Get-Command python -ErrorAction SilentlyContinue) {
    $PyExe = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = "py"
} else {
    throw "Python not found. Install Python 3.10+."
}

$pidFile = Join-Path $Run "viewer.pid"
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($old) { try { Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue } catch {} }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 400

$viewer = Start-Process -FilePath $PyExe -ArgumentList (Join-Path $Dir "viewer\server_windows.py") `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Run "viewer.log") `
    -RedirectStandardError (Join-Path $Run "viewer.log.err")
Set-Content $pidFile $viewer.Id

$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/state" -TimeoutSec 1; $ok = $true; break }
    catch { Start-Sleep -Milliseconds 250 }
}
if (-not $ok) {
    Write-Host "[stand] viewer FAILED" -ForegroundColor Red
    Get-Content (Join-Path $Run "viewer.log") -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "[stand] boot $Model"
$body = @{ model = $Model } | ConvertTo-Json -Compress
$null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/boot" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 90
Write-Host "[stand] OK -> http://127.0.0.1:8765/" -ForegroundColor Green
Start-Process "http://127.0.0.1:8765/"
