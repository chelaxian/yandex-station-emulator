# Windows setup for the Yandex Station Mini 2 emulator (port of setup_macos.sh).
# Usage:  powershell -ExecutionPolicy Bypass -File setup_windows.ps1
# Requires: Windows 10/11 x64, ~4 GB free disk space, internet access.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

if (-not ([Environment]::Is64BitOperatingSystem)) { throw "Requires a 64-bit Windows." }

# ------------------------------------------------------------- python
function Get-PyExe {
    if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
    if (Get-Command py -ErrorAction SilentlyContinue)     { return @("py", "-3") }
    return $null
}
$py = Get-PyExe
if (-not $py) {
    Write-Host "[setup] installing Python 3.12 via winget…"
    winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
    $py = Get-PyExe
    if (-not $py) { throw "Python install failed. Install manually from python.org and re-run." }
}

# --------------------------------------------------------------- qemu
$qemu = Get-Command qemu-system-aarch64.exe -ErrorAction SilentlyContinue
if (-not $qemu) {
    foreach ($c in @("C:\Program Files\qemu\qemu-system-aarch64.exe", "C:\Program Files\qemu64\qemu-system-aarch64.exe")) {
        if (Test-Path $c) { $qemu = $c; break }
    }
}
if (-not $qemu) {
    Write-Host "[setup] installing QEMU via winget (SoftwareFreedomConservancy.QEMU)…"
    winget install --id SoftwareFreedomConservancy.QEMU --exact --accept-package-agreements --accept-source-agreements
    $env:Path += ";C:\Program Files\qemu"
    $qemu = Get-Command qemu-system-aarch64.exe -ErrorAction SilentlyContinue
    if (-not $qemu -and (Test-Path "C:\Program Files\qemu\qemu-system-aarch64.exe")) { $qemu = "C:\Program Files\qemu\qemu-system-aarch64.exe" }
    if (-not $qemu) { throw "QEMU install failed. Install from https://qemu.weilnetz.de/w64/ and re-run." }
}
Write-Host "[setup] QEMU: $qemu"

# --------------------------------------------- python deps (mic capture)
& $py[0] @($py[1..($py.Count-1)]) -m pip install --quiet sounddevice 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "sounddevice not installed — microphone will be unavailable (pip install sounddevice)."
}

# ------------------------------------------------------------- runtime
if (-not (Test-Path "assets\runtime-manifest.json")) {
    throw "assets/ not found — clone the full repository first (git clone --recursive is not needed; assets are regular git files)."
}
Write-Host "[setup] verifying and unpacking the runtime (~3 GB)…"
& $py[0] @($py[1..($py.Count-1)]) "scripts\install_runtime_windows.py"
if ($LASTEXITCODE -ne 0) { throw "Runtime installation failed." }

# ---------------------------------------------- windows boot initramfs
Write-Host "[setup] building the Windows initramfs (no 9p needed)…"
& $py[0] @($py[1..($py.Count-1)]) "qemu\mini2\tools\build_boot_windows.py"
if ($LASTEXITCODE -ne 0) { throw "Initramfs build failed." }

# ------------------------------------------------------------ launch
Write-Host "[setup] starting the stand…"
& powershell -ExecutionPolicy Bypass -File "qemu\mini2\run_stand_windows.ps1"
Start-Process "http://127.0.0.1:8765/"
Write-Host "[setup] done. Panel: http://127.0.0.1:8765/ · next time: qemu\mini2\run_stand_windows.ps1"
