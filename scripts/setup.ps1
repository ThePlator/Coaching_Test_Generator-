# One-time setup for Windows 10/11 (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# PDF export on Windows uses Chromium (via Playwright), because WeasyPrint's
# GTK libraries are hard to install there. ctg/export/pdf.py falls back to it.
# Safe to run again.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Model = if ($env:CTG_MODEL) { $env:CTG_MODEL } else { "gemma3:4b" }

function Say($m)  { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    !   $m" -ForegroundColor Yellow }

# 1. Python
Say "Python"
$py = $null
foreach ($cand in @("py -3.13", "py -3.12", "py -3.11", "python")) {
    try {
        $v = & cmd /c "$cand -c `"import sys; print(sys.version_info >= (3, 11))`"" 2>$null
        if ($v -eq "True") { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Warn "Python 3.11+ not found. Installing with winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    Write-Host "    Close this window, open a new PowerShell and run the script again."
    exit 1
}
Ok (& cmd /c "$py --version")

# 2. Virtual environment + packages
Say "Python packages"
if (-not (Test-Path ".venv")) { & cmd /c "$py -m venv .venv" }
$vpy = ".venv\Scripts\python.exe"
& $vpy -m pip install -q --upgrade pip
& $vpy -m pip install -q -r requirements.txt
& $vpy -m pip install -q playwright
& $vpy -m playwright install chromium
Ok "installed into .venv (PDF engine: Chromium)"

# 3. Ollama + model
Say "Ollama and $Model"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Warn "Ollama not installed. Installing with winget..."
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
}
try { Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 3 | Out-Null }
catch { Warn "Starting Ollama..."; Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 4 }
$have = (ollama list) -match "^$([regex]::Escape($Model))\s"
if ($have) { Ok "$Model already downloaded" }
else { Write-Host "    Downloading $Model (one time, about 3 GB)..."; ollama pull $Model }

# 4. Institute profile
Say "Institute profile"
if (-not (Test-Path "config\institute.toml")) {
    Copy-Item "config\institute.example.toml" "config\institute.toml"
    Ok "created config\institute.toml - set your institute name in the app sidebar"
} else { Ok "config\institute.toml exists" }

# 5. Check
Say "Checking"
& $vpy scripts\preflight.py

Write-Host "`nDone. To start the app:"
Write-Host "    .venv\Scripts\streamlit run app.py"
Write-Host "Then open http://localhost:8501"
