# Stop the Windows stand: QEMU, viewer, LED bridge, host helper.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\stop_windows.ps1
# UTF-8 console: python children print UTF-8, PS defaults to CP866/1251
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Run  = Join-Path $Repo "qemu\mini2\run"

# graceful stop through the viewer (kills QEMU + tail)
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/qemu" -Method Post `
        -ContentType "application/json" -Body '{"action":"stop"}' -TimeoutSec 10
    Write-Host "[stop] qemu stopped"
} catch { Write-Host "[stop] viewer not reachable: $_" }

foreach ($n in "viewer.pid","led_bridge.pid","host-helper.pid","hardware-rpc.pid","watchdog.pid") {
    $f = Join-Path $Run $n
    if (Test-Path $f) {
        $p = Get-Content $f -ErrorAction SilentlyContinue
        if ($p) { try { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue } catch {} }
        Remove-Item $f -Force -ErrorAction SilentlyContinue
    }
}
try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'server_windows\.py|led_bridge_windows\.py|host_helper\.py|hardware_rpc\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}
Write-Host "[stop] done"
