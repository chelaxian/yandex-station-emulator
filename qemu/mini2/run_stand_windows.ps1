# Windows port of run_stand.sh: viewer + LED bridge + host helper + QEMU.
# Usage:  powershell -ExecutionPolicy Bypass -File run_stand_windows.ps1
# UTF-8 console: python children print UTF-8, PS defaults to CP866/1251
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$Dir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Run   = Join-Path $Dir "run"
New-Item -ItemType Directory -Force -Path $Run | Out-Null

# resolve python (python.exe preferred, py -3 fallback)
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PyExe = "python"; $PyArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = "py"; $PyArgs = @("-3")
} else {
    throw "Python not found. Install Python 3.10+ (setup_windows.ps1 does it)."
}

function Stop-ByPidFile([string]$Name) {
    $f = Join-Path $Run $Name
    if (Test-Path $f) {
        $p = Get-Content $f -ErrorAction SilentlyContinue
        if ($p) { try { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue } catch {} }
        Remove-Item $f -Force -ErrorAction SilentlyContinue
    }
}

# stop previous stand
foreach ($n in "viewer.pid","led_bridge.pid","host-helper.pid","hardware-rpc.pid",
               "watchdog.pid","console_tail.pid","qemu.pid","start.pid") {
    Stop-ByPidFile $n
}
try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'server_windows\.py|led_bridge_windows\.py|host_helper\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}
Start-Sleep -Milliseconds 600

function Start-Hidden([string[]]$Cmd, [string]$Log) {
    $p = Start-Process -FilePath $Cmd[0] -ArgumentList ($Cmd[1..($Cmd.Count-1)]) `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
    return $p.Id
}

function Start-Py([string]$Script, [string]$Log) {
    return Start-Hidden (@($PyExe) + $PyArgs + @($Script)) $Log
}

# viewer (HTTP + SSE + QEMU control)
Set-Content (Join-Path $Run "viewer.pid") (Start-Py (Join-Path $Dir "viewer\server_windows.py") (Join-Path $Run "viewer.log"))

# wait for the panel
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
        $ok = $true; break
    } catch { Start-Sleep -Milliseconds 250 }
}
if (-not $ok) {
    Write-Host "[stand] viewer FAILED" -ForegroundColor Red
    Get-Content (Join-Path $Run "viewer.log") -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}

# LED bridge: started by server_windows.py (ensure_led_bridge) - starting a
# second copy here would fight over TCP 19095 and overwrite the pid file.

# host helper (mic PCM 19093 + PEM/epoch HTTP 19094)
Set-Content (Join-Path $Run "host-helper.pid") (Start-Py (Join-Path $Dir "tools\host_helper.py") (Join-Path $Run "host-helper.log"))

# boot QEMU if it is not up yet
try {
    $st = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/qemu" -TimeoutSec 2
    if (-not $st.up) {
        Write-Host "[stand] qemu boot"
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/qemu" -Method Post `
            -ContentType "application/json" -Body '{"action":"boot"}' -TimeoutSec 45
    } else {
        Write-Host "[stand] qemu already up"
    }
} catch { Write-Host "[stand] boot request failed: $_" }

Write-Host "[stand] OK -> http://127.0.0.1:8765/" -ForegroundColor Green
