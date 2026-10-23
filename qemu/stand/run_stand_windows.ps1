# Windows launcher for the two-model stand (Mini 2 + MIDI).
# Usage:  powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model mini
#         powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model midi
param([ValidateSet("mini", "midi")][string]$Model = "mini")
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Run = Join-Path $Dir "run"
New-Item -ItemType Directory -Force -Path $Run | Out-Null

if (Get-Command python -ErrorAction SilentlyContinue) {
    $PyExe = "python"; $PyArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = "py"; $PyArgs = @("-3")
} else {
    throw "Python not found. Install Python 3.10+."
}

# Preflight before touching a running stand: images, initramfs and QEMU.
# The check prints the missing files and the exact install command.
Write-Host "[stand] preflight $Model"
$check = & $PyExe @PyArgs (Join-Path $Dir "tools\start_windows.py") --model $Model --check
if ($LASTEXITCODE -ne 0) {
    $check | ForEach-Object { Write-Host $_ }
    Write-Host "[stand] model data is missing. Install it with:" -ForegroundColor Yellow
    Write-Host "  python `"$Dir\tools\install_data_windows.py`" --model $Model"
    exit 1
}

$pidFile = Join-Path $Run "viewer.pid"
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($old) { try { Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue } catch {} }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 400

$viewerScript = Join-Path $Dir "viewer\server_windows.py"
$viewer = Start-Process -FilePath $PyExe -ArgumentList (@($PyArgs) + @("`"$viewerScript`"")) `
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
    Get-Content (Join-Path $Run "viewer.log.err") -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "[stand] boot $Model"
$body = @{ model = $Model } | ConvertTo-Json -Compress
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/boot" -Method Post `
        -ContentType "application/json" -Body $body -TimeoutSec 120
} catch {
    $detail = $null
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        try { $detail = $_.ErrorDetails.Message | ConvertFrom-Json } catch {}
    }
    Write-Host "[stand] boot FAILED" -ForegroundColor Red
    if ($detail) {
        Write-Host "  $($detail.error)"
        if ($detail.hint) { Write-Host "  install: $($detail.hint)" }
    } else {
        Write-Host "  $($_.Exception.Message)"
    }
    Get-Content (Join-Path $Run "viewer.log") -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}
if (-not $resp.ok) {
    Write-Host "[stand] boot FAILED: $($resp.error)" -ForegroundColor Red
    if ($resp.hint) { Write-Host "  install: $($resp.hint)" }
    exit 1
}

Write-Host "[stand] OK -> http://127.0.0.1:8765/" -ForegroundColor Green
Start-Process "http://127.0.0.1:8765/"
