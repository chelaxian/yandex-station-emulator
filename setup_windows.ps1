# Windows setup for the Yandex Station Mini 2 emulator (port of setup_macos.sh).
# Usage:  powershell -ExecutionPolicy Bypass -File setup_windows.ps1
# Requires: Windows 10/11 x64, ~4 GB free disk space, internet access.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

if (-not ([Environment]::Is64BitOperatingSystem)) { throw "Requires a 64-bit Windows." }

# ------------------------------------------------------------- python
function Get-PyExe { return [pscustomobject]@{ Exe = "python"; Args = @() } }
$py = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $py = [pscustomobject]@{ Exe = "python"; Args = @() }
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $py = [pscustomobject]@{ Exe = "py"; Args = @("-3") }
}
if (-not $py) {
    Write-Host "[setup] installing Python 3.12 via winget…"
    winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $py = [pscustomobject]@{ Exe = "python"; Args = @() }
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $py = [pscustomobject]@{ Exe = "py"; Args = @("-3") }
    }
    if (-not $py) { throw "Python install failed. Install manually from python.org and re-run." }
}
function Invoke-Py([string[]]$ScriptArgs) {
    & $py.Exe (@($py.Args) + $ScriptArgs)
    if ($LASTEXITCODE -ne 0) { throw "python failed: $ScriptArgs" }
}

# --------------------------------------------------------------- qemu
# QEMU_BIN env var wins; common install dirs are probed so QEMU can live on
# any drive (D:\qemu etc.) — useful when C: is out of space.
$qemu = $env:QEMU_BIN
if ($qemu -and -not (Test-Path $qemu)) { throw "QEMU_BIN указан, но файла нет: $qemu" }
if (-not $qemu) { $qemu = Get-Command qemu-system-aarch64.exe -ErrorAction SilentlyContinue }
if (-not $qemu) {
    $drives = @("C:", "D:", "E:")
    foreach ($d in $drives) {
        foreach ($c in @("$d\Program Files\qemu\qemu-system-aarch64.exe", "$d\qemu\qemu-system-aarch64.exe", "$d\Program Files\qemu64\qemu-system-aarch64.exe")) {
            if (Test-Path $c) { $qemu = $c; break }
        }
        if ($qemu) { break }
    }
}
if ($qemu) { $env:QEMU_BIN = "$qemu" }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $qemu) {
    if (-not $isAdmin) {
        Write-Warning "Установщику QEMU нужны права администратора (он ставится в Program Files)."
        Write-Warning "Открой PowerShell от имени администратора и запусти setup_windows.ps1 ещё раз."
    }
    Write-Host "[setup] installing QEMU via winget (SoftwareFreedomConservancy.QEMU)…"
    winget install --id SoftwareFreedomConservancy.QEMU --exact --accept-package-agreements --accept-source-agreements
    $env:Path += ";C:\Program Files\qemu"
    $qemu = Get-Command qemu-system-aarch64.exe -ErrorAction SilentlyContinue
    if (-not $qemu -and (Test-Path "C:\Program Files\qemu\qemu-system-aarch64.exe")) { $qemu = "C:\Program Files\qemu\qemu-system-aarch64.exe" }
    if (-not $qemu) {
        Write-Warning "QEMU не установился (winget exit code 2 = нет прав администратора)."
        Write-Warning "Варианты:"
        Write-Warning "  1) Запусти PowerShell от имени АДМИНИСТРАТОРА и повтори этот скрипт"
        Write-Warning "  2) Или скачай установщик с https://qemu.weilnetz.de/w64/ и запусти вручную (с правами админа),"
        Write-Warning "     затем перезапусти PowerShell и повтори этот скрипт"
        throw "QEMU install failed — нужен запуск с правами администратора"
    }
}
Write-Host "[setup] QEMU: $qemu"

# --------------------------------------------- python deps (mic capture)
try { Invoke-Py @("-m", "pip", "install", "--quiet", "sounddevice") }
catch { Write-Warning "sounddevice not installed — microphone will be unavailable (pip install sounddevice)." }

# ------------------------------------------------------------- runtime
if (-not (Test-Path "assets\runtime-manifest.json")) {
    throw "assets/ not found — clone the full repository first (git clone --recursive is not needed; assets are regular git files)."
}
Write-Host "[setup] verifying and unpacking the runtime (~3 GB)…"
Invoke-Py @("scripts\install_runtime_windows.py")

# ---------------------------------------------- windows boot initramfs
Write-Host "[setup] building the Windows initramfs (no 9p needed)…"
Invoke-Py @("qemu\mini2\tools\build_boot_windows.py")

# ------------------------------------------------------------ launch
Write-Host "[setup] starting the stand…"
& powershell -ExecutionPolicy Bypass -File "qemu\mini2\run_stand_windows.ps1"
Start-Process "http://127.0.0.1:8765/"
Write-Host "[setup] done. Panel: http://127.0.0.1:8765/ · next time: qemu\mini2\run_stand_windows.ps1"
