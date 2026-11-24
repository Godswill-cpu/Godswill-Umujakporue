# One-time setup for Windows (PowerShell): creates .venv, installs dependencies and Chromium.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Install Python 3.11+ from python.org (tick 'Add to PATH')." }
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg is required: winget install Gyan.FFmpeg" }
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Installed. Start the studio by double-clicking start.bat"
