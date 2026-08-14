#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot Windows setup for Bill_Automation_Kit
  (venv x3, Playwright, runtime dirs, desktop shortcuts, secret checks).

.EXAMPLE
  .\setup_windows.ps1
  .\setup_windows.ps1 -InstallPrerequisites
  .\setup_windows.ps1 -SkipPlaywright
  .\setup_windows.ps1 -InstallPrerequisites -CreateDesktopShortcuts
#>
[CmdletBinding()]
param(
    [switch]$SkipPlaywright,
    [switch]$InstallPrerequisites,
    [switch]$CreateDesktopShortcuts,
    [switch]$SkipDesktopShortcuts
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# Default: create desktop icons unless explicitly skipped
if (-not $PSBoundParameters.ContainsKey("CreateDesktopShortcuts") -and -not $SkipDesktopShortcuts) {
    $CreateDesktopShortcuts = $true
}

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

function Refresh-PathEnv {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Resolve-PythonExe {
    Refresh-PathEnv
    foreach ($cmd in @("py -3", "python", "python3")) {
        try {
            $exe = & cmd /c "$cmd -c `"import sys; print(sys.executable)`"" 2>$null
            if ($exe -and (Test-Path $exe.Trim())) {
                return $exe.Trim()
            }
        } catch { }
    }
    # Common install locations if PATH not refreshed yet
    $candidates = @(
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python313\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "${env:ProgramFiles}\Python312\python.exe",
        "${env:ProgramFiles}\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
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
        "install", "--id", $PackageId, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity"
    ) -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) {
        Write-Ok "$Label installed (or already present)"
        Refresh-PathEnv
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
    $venvPy = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        throw "python not found in $VenvDir"
    }
    # Use python -m pip (avoids "To modify pip" error on some Windows installs)
    & $venvPy -m pip install -q --upgrade pip
    if (Test-Path $RequirementsFile) {
        Write-Host "  pip install -r $RequirementsFile"
        & $venvPy -m pip install -q -r $RequirementsFile
    }
    foreach ($pkg in $ExtraPip) {
        Write-Host "  pip install $pkg"
        & $venvPy -m pip install -q $pkg
    }
    return $venvPy
}

function Install-PlaywrightChromium([string]$VenvPython) {
    Write-Host "  playwright install chromium ($VenvPython)"
    & $VenvPython -m playwright install chromium
}

function New-DesktopShortcut(
    [string]$Name,
    [string]$TargetPath,
    [string]$WorkingDirectory,
    [string]$Description,
    [string]$IconPath
) {
    if (-not (Test-Path $TargetPath)) {
        Write-Warn "Skip shortcut '$Name' - target missing: $TargetPath"
        return
    }
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "$Name.lnk"
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $TargetPath
    $sc.WorkingDirectory = $WorkingDirectory
    $sc.Description = $Description
    if ($IconPath -and (Test-Path $IconPath)) {
        $sc.IconLocation = $IconPath
    }
    $sc.Save()
    Write-Ok "Desktop: $Name.lnk"
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
        Write-Err "Or double-click INSTALL.bat again after installing Python."
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
    Write-Warn "ngrok not found (PATH or .\ngrok.exe) - optional until Webhook/Token setup"
    Write-Warn "  Download: https://ngrok.com/download  or  winget search ngrok"
    if ($InstallPrerequisites) {
        # Package id varies by winget source; try common ids then ignore failure
        $ok = Try-WingetInstall "Ngrok.Ngrok" "ngrok"
        if (-not $ok) { Try-WingetInstall "ngrok.ngrok" "ngrok" | Out-Null }
    }
}

Refresh-PathEnv
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Warn "git not on PATH"
    if ($InstallPrerequisites) {
        Try-WingetInstall "Git.Git" "Git"
        Refresh-PathEnv
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

# --- E. Desktop shortcuts ---
if ($CreateDesktopShortcuts -and -not $SkipDesktopShortcuts) {
    Write-Step "Creating desktop shortcuts"
    $icon = Join-Path $ProjectRoot "no_api_send_bill_manual\send_bill.ico"
    New-DesktopShortcut `
        -Name "Send Bill Launcher" `
        -TargetPath (Join-Path $ProjectRoot "no_api_send_bill_manual\run_launcher_ui.vbs") `
        -WorkingDirectory (Join-Path $ProjectRoot "no_api_send_bill_manual") `
        -Description "Bill Automation Kit - Send Bill Launcher" `
        -IconPath $icon
    New-DesktopShortcut `
        -Name "Capture Bill Launcher" `
        -TargetPath (Join-Path $ProjectRoot "run_capture_launcher.vbs") `
        -WorkingDirectory $ProjectRoot `
        -Description "Bill Automation Kit - Capture Bill Launcher" `
        -IconPath $icon
}

# --- F. Secrets check (warnings only) ---
Write-Step "Secrets and config (fill via Settings UI - do not copy from another PC blindly)"

$secretChecks = @(
    @{ Path = ".env"; Note = "WEBHOOK_VERIFY_TOKEN, ..." },
    @{ Path = "auth.json"; Note = "Anousith Playwright session (optional)" },
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

# --- G. Smoke test ---
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

# --- H. Summary ---
Write-Step "Done"
Write-Host @"

Next steps (no AI required):
  1. Double-click Desktop icon:  Send Bill Launcher
  2. Settings opens on first run if config is incomplete
  3. Fill: Google Sheet / Facebook pages / Webhook+ngrok
  4. Save - then use Token / Playwright send as usual

Re-run install anytime:
  Double-click INSTALL.bat
  or:  .\setup_windows.ps1 -InstallPrerequisites

"@ -ForegroundColor White

if ($missingSecrets -gt 0) {
    Write-Warn "$missingSecrets secret file(s) still missing - fill them in Settings UI."
    exit 0
}

Write-Ok "Setup complete."
exit 0
