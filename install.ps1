# Tutorial Studio - one-time setup for Windows.
# Easiest: double-click install.bat (it runs this script with the right settings).
# Note: keep this file ASCII-only; Windows PowerShell 5.1 misreads other characters.

# Do NOT use "Stop" here: Windows PowerShell 5.1 treats harmless warnings that pip/playwright
# print on stderr as fatal errors. Every step checks $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "INSTALL FAILED: $msg" -ForegroundColor Red
    Write-Host "Copy the messages above and send them to get help."
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "=== Tutorial Studio setup ===" -ForegroundColor Cyan
Write-Host "Folder: $PSScriptRoot"

# 1. Find a real Python 3.11+.
#    Try the 'py' launcher first; 'python' can be the Microsoft Store placeholder, which fails to run.
$pyExe = $null
$pyArgs = @()
$candidates = @(
    @{ exe = "py"; args = @("-3") },
    @{ exe = "python"; args = @() },
    @{ exe = "python3"; args = @() }
)
foreach ($c in $candidates) {
    if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
    $cargs = $c.args
    & $c.exe @cargs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $pyExe = $c.exe; $pyArgs = $c.args; break }
}
if (-not $pyExe) {
    Fail "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run install.bat again."
}
$pyVersion = & $pyExe @pyArgs -c "import sys; print(sys.version.split()[0])"
Write-Host "[1/5] Python $pyVersion found ($pyExe)" -ForegroundColor Green

# 2. FFmpeg (installed with winget if missing).
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "FFmpeg not found - installing it with winget (this can take a few minutes)..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    # winget puts a link here; this window may not see the new PATH yet
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    if (Test-Path (Join-Path $links "ffmpeg.exe")) { $env:Path = "$env:Path;$links" }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Fail "FFmpeg is not installed. Open PowerShell, run: winget install Gyan.FFmpeg   then close all windows and run install.bat again."
}
Write-Host "[2/5] FFmpeg found" -ForegroundColor Green

# 3. Virtual environment.
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail "Could not create the .venv folder." }
}
Write-Host "[3/5] Virtual environment ready" -ForegroundColor Green

# 4. Python packages.
& $venvPy -m pip install --upgrade pip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Upgrading pip failed (check your internet connection)." }
& $venvPy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Installing the Python packages failed." }
Write-Host "[4/5] Python packages installed" -ForegroundColor Green

# 5. Browser used for recording demonstrations.
& $venvPy -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Fail "Downloading the Chromium browser for Playwright failed." }
Write-Host "[5/5] Chromium installed" -ForegroundColor Green

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

Write-Host ""
Write-Host "Installation complete. Start the studio by double-clicking start.bat" -ForegroundColor Green
Read-Host "Press Enter to close"
exit 0
