#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot Windows setup for Automation_Work (venv x3, Playwright, runtime dirs, secret checks).

.EXAMPLE
  .\setup_windows.ps1
  .\setup_windows.ps1 -InstallPrerequisites
  .\setup_windows.ps1 -SkipPlaywright
#>
[CmdletBinding()]
param(
    [switch]$SkipPlaywright,
    [switch]$InstallPrerequisites
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "  OK  $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "  !!  $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "  ERR $Message" -ForegroundColor Red
}

function Resolve-PythonExe {
    foreach ($cmd in @("py -3", "python", "python3")) {
        try {
            $exe = & cmd /c "$cmd -c `"import sys; print(sys.executable)`"" 2>$null
            if ($exe -and (Test-Path $exe.Trim())) {
                return $exe.Trim()
            }
        } catch { }
    }
    return $null
}

function Test-WingetAvailable {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Try-WingetInstall([string]$PackageId, [string]$Label) {
    if (-not (Test-WingetAvailable)) {
        Write-Warn "winget not found - install $Label manually: $PackageId"
        return $false
    }
    Write-Host "  Installing $Label via winget ($PackageId)..."
    $proc = Start-Process -FilePath "winget" -ArgumentList @(
        "install", "--id", $PackageId, "-e", "--accept-package-agreements", "--accept-source-agreements"
    ) -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) {
        Write-Ok "$Label installed (or already present)"
        return $true
    }
    Write-Warn "winget install $Label exited with code $($proc.ExitCode)"
    return $false
}

function Ensure-Venv(
    [string]$VenvDir,
    [string]$RequirementsFile,
    [string[]]$ExtraPip = @()
) {
    $py = $script:PythonExe
    if (-not (Test-Path $VenvDir)) {
        Write-Host "  Creating venv: $VenvDir"
        & $py -m venv $VenvDir
    }
    $pip = Join-Path $VenvDir "Scripts\pip.exe"
    $venvPy = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $pip)) {
        throw "pip not found in $VenvDir"
    }
    & $pip install -q --upgrade pip
    if (Test-Path $RequirementsFile) {
        Write-Host "  pip install -r $RequirementsFile"
        & $pip install -q -r $RequirementsFile
    }
    foreach ($pkg in $ExtraPip) {
        Write-Host "  pip install $pkg"
        & $pip install -q $pkg
    }
    return $venvPy
}

function Install-PlaywrightChromium([string]$VenvPython) {
    Write-Host "  playwright install chromium ($VenvPython)"
    & $VenvPython -m playwright install chromium
}

# --- A. Prerequisites ---
Write-Step "Checking prerequisites"

$script:PythonExe = Resolve-PythonExe
if (-not $script:PythonExe) {
    Write-Err "Python 3.10+ not found."
    if ($InstallPrerequisites) {
        Try-WingetInstall "Python.Python.3.12" "Python 3.12"
        $script:PythonExe = Resolve-PythonExe
    }
    if (-not $script:PythonExe) {
        Write-Err "Install Python, then re-run: winget install Python.Python.3.12"
        exit 1
    }
}
$pyVer = & $script:PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $pyVer ($script:PythonExe)"

$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
$ngrokLocal = Test-Path (Join-Path $ProjectRoot "ngrok.exe")
if ($ngrokCmd -or $ngrokLocal) {
    $ngrokPath = if ($ngrokCmd) { $ngrokCmd.Source } else { (Join-Path $ProjectRoot "ngrok.exe") }
    Write-Ok "ngrok: $ngrokPath"
} else {
    Write-Warn "ngrok not found (PATH or .\ngrok.exe)"
    Write-Warn "  winget install ngrok.ngrok"
    Write-Warn '  ngrok config add-authtoken YOUR_TOKEN'
    if ($InstallPrerequisites) {
        Try-WingetInstall "ngrok.ngrok" "ngrok"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Warn "git not on PATH"
    if ($InstallPrerequisites) {
        Try-WingetInstall "Git.Git" "Git"
    }
} else {
    Write-Ok "git: $(git --version)"
}

$ahkPaths = @(
    "${env:ProgramFiles}\AutoHotkey\v2\AutoHotkey64.exe",
    "${env:ProgramFiles(x86)}\AutoHotkey\v2\AutoHotkey64.exe"
)
$ahkFound = $ahkPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($ahkFound) {
    Write-Ok "AutoHotkey v2: $ahkFound"
} else {
    Write-Warn "AutoHotkey v2 not found (optional - for send_bill_signal.ahk)"
    Write-Warn "  https://www.autohotkey.com/ or winget install AutoHotkey.AutoHotkey"
}

# --- B. Virtual environments ---
Write-Step "Creating virtual environments and installing packages"

$rootVenvPy = Ensure-Venv `
    -VenvDir (Join-Path $ProjectRoot ".venv") `
    -RequirementsFile (Join-Path $ProjectRoot "requirements.txt")

$noApiVenvPy = Ensure-Venv `
    -VenvDir (Join-Path $ProjectRoot "no_api_send_bill\.venv") `
    -RequirementsFile (Join-Path $ProjectRoot "no_api_send_bill\requirements.txt")

$manualVenvPy = Ensure-Venv `
    -VenvDir (Join-Path $ProjectRoot "no_api_send_bill_manual\.venv") `
    -RequirementsFile (Join-Path $ProjectRoot "no_api_send_bill_manual\requirements.txt") `
    -ExtraPip @("pywin32", "playwright")

Write-Ok "All venvs ready"

# --- C. Playwright browsers ---
if (-not $SkipPlaywright) {
    Write-Step "Installing Playwright Chromium"
    Install-PlaywrightChromium $rootVenvPy
    Install-PlaywrightChromium $noApiVenvPy
    Write-Ok "Playwright Chromium installed (root + no_api_send_bill)"
} else {
    Write-Warn "Skipped Playwright install (-SkipPlaywright)"
}

# --- D. Runtime directories ---
Write-Step "Runtime directories"
foreach ($dir in @("bill_images", "browser_profile", "hal_browser_profile")) {
    $path = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-Host "  Created $dir/"
    } else {
        Write-Host "  Exists $dir/"
    }
}

# --- E. Secrets check (warnings only) ---
Write-Step "Secrets and config (copy from old PC if missing)"

$secretChecks = @(
    @{ Path = ".env"; Note = "ANOUSITH_*, HAL_*, WEBHOOK_VERIFY_TOKEN, ..." },
    @{ Path = "auth.json"; Note = "Anousith Playwright session (Capture private)" },
    @{ Path = "no_api_send_bill\config\google_credentials.json"; Note = "Google Sheets API" },
    @{ Path = "page_token.json"; Note = "Facebook Page tokens" }
)

$missingSecrets = 0
foreach ($item in $secretChecks) {
    $full = Join-Path $ProjectRoot $item.Path
    if (Test-Path $full) {
        Write-Ok $item.Path
    } else {
        Write-Warn "Missing: $($item.Path) - $($item.Note)"
        $missingSecrets++
    }
}

$envExample = Join-Path $ProjectRoot ".env.example"
$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Write-Warn "No .env - run: Copy-Item .env.example .env  then edit values"
}

# --- F. Smoke test ---
Write-Step "Smoke test (imports)"
$smoke = @"
import playwright
import gspread
import capture_playwright_nav
print('imports_ok')
"@
& $rootVenvPy -c $smoke
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Root venv imports OK"
} else {
    Write-Warn "Smoke test failed - check errors above"
}

# --- G. Summary ---
Write-Step "Done"
Write-Host @"

Next steps (Bill Automation Kit):
  1. Copy templates — see README.md and SECRETS_CHECKLIST.md
  2. Fill .env, page_token.json, google_credentials.json, sheet_config
  3. Set ngrok: user_settings.json or env NGROK_DOMAIN
  4. ngrok once: ngrok config add-authtoken YOUR_TOKEN
  5. Open Launcher:
       cd $ProjectRoot\no_api_send_bill_manual
       ..\.venv\Scripts\pythonw.exe launcher_ui.py

Settings UI (phase 1) will live under settings\ — not required for file-based setup.

"@ -ForegroundColor White

if ($missingSecrets -gt 0) {
    Write-Warn "$missingSecrets secret file(s) still missing - Capture/Webhook may fail until copied."
    exit 0
}

Write-Ok "Setup complete."
exit 0
