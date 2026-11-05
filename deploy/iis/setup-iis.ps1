<#
.SYNOPSIS
  Installs the BDO Proposal Generator on IIS (Windows Server / Windows 10+).

.DESCRIPTION
  Run in Windows PowerShell (not PowerShell 7) opened with "Run as Administrator", from the app folder:

    .\deploy\iis\setup-iis.ps1 -PublicBaseUrl "https://intranet.bdo.co.il/proposals"

  What it does:
    1. checks IIS and HttpPlatformHandler are installed
    2. creates a Python virtual environment in .venv and installs requirements.txt
    3. writes web.config (from deploy\iis\web.config.template)
    4. creates an application pool (No Managed Code) and grants it access to the app folders
    5. creates the IIS application (default: /proposals under "Default Web Site"),
       or a separate site with -NewSiteName/-Port
  Re-run it after updating the code (git pull) – it is safe to run more than once.

.PARAMETER PublicBaseUrl
  The address clients will use, including the application path, e.g. https://server/proposals
.PARAMETER SiteName
  Existing IIS site to add the application to (default "Default Web Site").
.PARAMETER AppName
  Application path under that site (default "proposals" -> https://server/proposals).
.PARAMETER NewSiteName
  Create a separate IIS site instead of an application (the app is then at the site root).
.PARAMETER Port
  HTTP port for -NewSiteName (default 8080). Add an HTTPS binding afterwards in IIS Manager.
.PARAMETER PythonExe
  Python 3.10+ installed for all users. Default: found with the "py" launcher.
.PARAMETER SofficePath
  LibreOffice soffice.exe (for PDF). Default: C:\Program Files\LibreOffice\program\soffice.exe if present.
.PARAMETER P12Password
  Password of data\signing.p12 if you install BDO's signing certificate.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$PublicBaseUrl,
  [string]$SiteName = "Default Web Site",
  [string]$AppName = "proposals",
  [string]$NewSiteName = "",
  [int]$Port = 8080,
  [string]$AppPoolName = "BDOProposals",
  [string]$PythonExe = "",
  [string]$SofficePath = "",
  [string]$P12Password = ""
)

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "App folder: $AppDir"

# ---------------------------------------------------------------- prerequisites
Step "Checking prerequisites"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Fail "Run this script in PowerShell opened with 'Run as Administrator'."
}
$inetsrv = Join-Path $env:windir "System32\inetsrv"
if (-not (Test-Path (Join-Path $inetsrv "appcmd.exe"))) {
  Fail "IIS is not installed. Install the 'Web Server (IIS)' role / Windows feature first."
}
Import-Module WebAdministration
if (-not (Get-WebGlobalModule | Where-Object { $_.Name -eq "httpPlatformHandler" })) {
  Fail "HttpPlatformHandler is not installed. Download it from https://www.iis.net/downloads/microsoft/httpplatformhandler (x64), install, then re-run."
}

if (-not $PythonExe) {
  try { $PythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim() } catch { }
  if (-not $PythonExe) { try { $PythonExe = (Get-Command python -ErrorAction Stop).Source } catch { } }
}
if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
  Fail "Python 3.10+ not found. Install it from python.org with 'Install for all users', or pass -PythonExe."
}
$ver = & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.10") { Fail "Python $ver found at $PythonExe – version 3.10 or newer is required." }
if ($PythonExe -like "*\Users\*") {
  Write-Warning "Python is installed under a user profile ($PythonExe). The IIS app pool may not be able to run it. Reinstall Python with 'Install for all users' if the site returns 502 errors."
}
Write-Host "Python $ver : $PythonExe"

if (-not $SofficePath) {
  foreach ($p in @("$env:ProgramFiles\LibreOffice\program\soffice.exe", "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe")) {
    if ($p -and (Test-Path $p)) { $SofficePath = $p; break }
  }
}
if ($SofficePath) { Write-Host "LibreOffice: $SofficePath" }
else { Write-Warning "LibreOffice not found – PDF output will be unavailable (PPTX, HTML and signing still work)." }

# ---------------------------------------------------------------- python environment
Step "Creating the Python environment (.venv) and installing packages"
$venvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & $PythonExe -m venv (Join-Path $AppDir ".venv") }
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $AppDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
Push-Location $AppDir; & $venvPy -c "import app; print('App imports OK')"; Pop-Location

foreach ($d in @("output", "data", "logs", "assets\services\history")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $AppDir $d) | Out-Null
}

# ---------------------------------------------------------------- web.config
Step "Writing web.config"
if ($NewSiteName) { $prefix = "" } else { $prefix = "/" + $AppName.Trim("/") }
function XmlEsc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
$tpl = Get-Content (Join-Path $PSScriptRoot "web.config.template") -Raw
$cfg = $tpl.Replace("{{PYTHON}}", (XmlEsc $venvPy))
$cfg = $cfg.Replace("{{APP_DIR}}", (XmlEsc $AppDir))
$cfg = $cfg.Replace("{{URL_PREFIX}}", (XmlEsc $prefix))
$cfg = $cfg.Replace("{{PUBLIC_BASE_URL}}", (XmlEsc $PublicBaseUrl.TrimEnd("/")))
$cfg = $cfg.Replace("{{SOFFICE_PATH}}", (XmlEsc $SofficePath))
$cfg = $cfg.Replace("{{P12_PASSWORD}}", (XmlEsc $P12Password))
Set-Content -Path (Join-Path $AppDir "web.config") -Value $cfg -Encoding UTF8

# allow web.config to configure the handler (locked by default on many servers)
& (Join-Path $inetsrv "appcmd.exe") unlock config -section:system.webServer/handlers | Out-Null
& (Join-Path $inetsrv "appcmd.exe") unlock config -section:system.webServer/httpPlatform 2>$null | Out-Null

# ---------------------------------------------------------------- app pool + permissions
Step "Application pool '$AppPoolName'"
if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) { New-WebAppPool -Name $AppPoolName | Out-Null }
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.loadUserProfile -Value $true
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name startMode -Value "AlwaysRunning"

Step "Granting the app pool access to the app folder"
$identity = "IIS AppPool\$AppPoolName"
icacls $AppDir /grant "${identity}:(OI)(CI)RX" /T /Q | Out-Null
foreach ($d in @("output", "data", "logs", "assets\team", "assets\services")) {
  icacls (Join-Path $AppDir $d) /grant "${identity}:(OI)(CI)M" /T /Q | Out-Null
}

# ---------------------------------------------------------------- site / application
if ($NewSiteName) {
  Step "IIS site '$NewSiteName' on port $Port"
  if (-not (Get-Website -Name $NewSiteName)) {
    New-Website -Name $NewSiteName -Port $Port -PhysicalPath $AppDir -ApplicationPool $AppPoolName | Out-Null
  } else {
    Set-ItemProperty "IIS:\Sites\$NewSiteName" -Name physicalPath -Value $AppDir
    Set-ItemProperty "IIS:\Sites\$NewSiteName" -Name applicationPool -Value $AppPoolName
  }
  $localUrl = "http://localhost:$Port/"
} else {
  Step "IIS application '$prefix' under '$SiteName'"
  if (-not (Get-Website -Name $SiteName)) { Fail "IIS site '$SiteName' not found. Use -SiteName, or -NewSiteName to create one." }
  $existing = Get-WebApplication -Site $SiteName -Name $AppName.Trim("/")
  if (-not $existing) {
    New-WebApplication -Site $SiteName -Name $AppName.Trim("/") -PhysicalPath $AppDir -ApplicationPool $AppPoolName | Out-Null
  } else {
    Set-ItemProperty "IIS:\Sites\$SiteName\$($AppName.Trim('/'))" -Name physicalPath -Value $AppDir
    Set-ItemProperty "IIS:\Sites\$SiteName\$($AppName.Trim('/'))" -Name applicationPool -Value $AppPoolName
  }
  $binding = (Get-WebBinding -Name $SiteName | Where-Object { $_.protocol -eq "http" } | Select-Object -First 1)
  $p = if ($binding) { $binding.bindingInformation.Split(":")[1] } else { "80" }
  $localUrl = "http://localhost:$p$prefix/"
}

Restart-WebAppPool -Name $AppPoolName

# ---------------------------------------------------------------- smoke test
Step "Testing $localUrl"
Start-Sleep -Seconds 3
try {
  $r = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 120
  if ($r.Content -match "Proposal Generator") { Write-Host "OK – the wizard is running at $localUrl" -ForegroundColor Green }
  else { Write-Warning "Got HTTP $($r.StatusCode) but not the wizard page." }
} catch {
  Write-Warning "The site did not respond correctly: $($_.Exception.Message)"
  Write-Warning "Check the log files in $AppDir\logs and the troubleshooting section of deploy\iis\README.md."
}
Write-Host "`nPublic address: $PublicBaseUrl   (Admin: $($PublicBaseUrl.TrimEnd('/'))/admin)"
