<#
.SYNOPSIS
  Installs the BDO Proposal Generator on IIS (Windows Server / Windows 10+).

.DESCRIPTION
  Run in Windows PowerShell opened with "Run as Administrator", from the app folder:

    powershell -ExecutionPolicy Bypass -File .\deploy\iis\setup-iis.ps1

  By default the app runs as its own IIS site called "Proposal", with an application pool
  called "Proposal", at the root of that site (e.g. https://proposal.yourdomain/).
  If the site already exists (created by you in IIS Manager, with your bindings and SSL
  certificate), the script uses it as it is and does not touch its bindings.

  What it does:
    1. checks IIS and HttpPlatformHandler are installed
    2. creates a Python virtual environment in .venv and installs requirements.txt
       (offline from the "wheels" folder when it exists)
    3. writes web.config (from deploy\iis\web.config.template)
    4. configures the application pool (No Managed Code) and grants it access to the app folders
    5. points the site at this folder (or creates the site if it does not exist)
  It is safe to run more than once, e.g. after updating the code.

.PARAMETER SiteName
  The IIS site the app runs as (default "Proposal"). Created on -Port if it does not exist.
.PARAMETER AppPoolName
  Application pool for the site (default: the same as -SiteName).
.PARAMETER Port
  HTTP port, used only when the script has to create the site (default 8080).
.PARAMETER AppName
  Optional. Install the app as an application at /<AppName> under -SiteName instead of at the
  site root, e.g. -SiteName "Default Web Site" -AppName "proposals".
.PARAMETER PythonExe
  Python 3.10+ installed for all users. Default: found with the "py" launcher or "python".
.PARAMETER WheelsDir
  Folder with the downloaded Python packages (.whl files), for a server without internet access.
  Default: the "wheels" folder in the app folder, if it exists.
.PARAMETER SofficePath
  LibreOffice soffice.exe (for PDF output). Default: the standard LibreOffice folder, if present.
#>
[CmdletBinding()]
param(
  [string]$SiteName = "Proposal",
  [string]$AppPoolName = "",
  [int]$Port = 8080,
  [string]$AppName = "",
  [string]$PythonExe = "",
  [string]$SofficePath = "",
  [string]$WheelsDir = ""
)

# NOTE: keep this file plain ASCII. Windows PowerShell 5.1 misreads other characters
# (e.g. typographic dashes or quotes) and then fails with parser errors.

$ErrorActionPreference = "Stop"
function Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
# run an external program without letting its warnings on stderr stop the script
function Invoke-Native([scriptblock]$Block) {
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $Block } finally { $ErrorActionPreference = $old }
}

if (-not $AppPoolName) { $AppPoolName = $SiteName }
$AppName = $AppName.Trim("/")
$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "App folder : $AppDir"
if ($AppName) { Write-Host "Install as : application /$AppName under site '$SiteName' (app pool '$AppPoolName')" }
else          { Write-Host "Install as : site '$SiteName' (app pool '$AppPoolName'), app at the site root" }

# ---------------------------------------------------------------- prerequisites
Step "Checking prerequisites"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Fail "Run this script in PowerShell opened with 'Run as Administrator'."
}
$inetsrv = Join-Path $env:windir "System32\inetsrv"
$appcmd = Join-Path $inetsrv "appcmd.exe"
if (-not (Test-Path $appcmd)) {
  Fail "IIS is not installed. Install the 'Web Server (IIS)' role / Windows feature first."
}
Import-Module WebAdministration
if (-not (Get-WebGlobalModule | Where-Object { $_.Name -eq "httpPlatformHandler" })) {
  Fail "HttpPlatformHandler is not installed. Install it (x64), run 'iisreset', then run this script again."
}

if (-not $PythonExe) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try { $PythonExe = ("" + (Invoke-Native { & py -3 -c "import sys; print(sys.executable)" } | Select-Object -Last 1)).Trim() } catch { }
  }
  if (-not $PythonExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $PythonExe = $cmd.Source }
  }
}
if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
  Fail "Python 3.10+ not found. Install it from python.org with 'Install for all users', or pass -PythonExe <path to python.exe>."
}
$ver = (Invoke-Native { & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])" } | Select-Object -Last 1).Trim()
if ([version]$ver -lt [version]"3.10") { Fail "Python $ver found at $PythonExe - version 3.10 or newer is required." }
Write-Host "Python $ver : $PythonExe"
if ($PythonExe -like "*\Users\*") {
  Write-Warning "Python is installed under a user profile ($PythonExe). IIS usually cannot run it from there. Reinstall Python with 'Install for all users' if the site returns 502 errors."
}

if (-not $SofficePath) {
  foreach ($cand in @("$env:ProgramFiles\LibreOffice\program\soffice.exe", "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe")) {
    if ($cand -and (Test-Path $cand)) { $SofficePath = $cand; break }
  }
}
if ($SofficePath) { Write-Host "LibreOffice: $SofficePath" }
else { Write-Warning "LibreOffice not found - PDF output will be unavailable (PPTX and HTML still work)." }

# ---------------------------------------------------------------- python environment
Step "Creating the Python environment (.venv) and installing packages"
$venvDir = Join-Path $AppDir ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Invoke-Native { & $PythonExe -m venv $venvDir }
  if (-not (Test-Path $venvPy)) { Fail "Could not create the Python environment in $venvDir." }
}
if (-not $WheelsDir -and (Test-Path (Join-Path $AppDir "wheels"))) { $WheelsDir = Join-Path $AppDir "wheels" }
$req = Join-Path $AppDir "requirements.txt"
if ($WheelsDir) {
  # offline: install only from the downloaded .whl files, never from the internet
  Write-Host "Installing packages offline from $WheelsDir"
  Invoke-Native { & $venvPy -m pip install --no-index --find-links $WheelsDir -r $req --quiet --disable-pip-version-check }
  if ($LASTEXITCODE -ne 0) {
    Fail "Offline install failed. The wheels folder must hold Windows (win_amd64) packages for Python $ver - see 'Server without internet' in deploy\iis\README.md."
  }
} else {
  Invoke-Native { & $venvPy -m pip install -r $req --quiet --disable-pip-version-check }
  if ($LASTEXITCODE -ne 0) { Fail "pip install failed. If this server has no internet access, put the 'wheels' folder in the app folder (see deploy\iis\README.md)." }
}
Push-Location $AppDir
try { Invoke-Native { & $venvPy -c "import app; print('App loads OK')" } } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Fail "The app could not be loaded with $venvPy - see the error above." }

foreach ($d in @("output", "logs", "assets\services\history")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $AppDir $d) | Out-Null
}

# ---------------------------------------------------------------- web.config
Step "Writing web.config"
if ($AppName) { $prefix = "/$AppName" } else { $prefix = "" }
function XmlEsc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
$tpl = Get-Content (Join-Path $PSScriptRoot "web.config.template") -Raw
$cfg = $tpl.Replace("{{PYTHON}}", (XmlEsc $venvPy))
$cfg = $cfg.Replace("{{APP_DIR}}", (XmlEsc $AppDir))
$cfg = $cfg.Replace("{{URL_PREFIX}}", (XmlEsc $prefix))
$cfg = $cfg.Replace("{{SOFFICE_PATH}}", (XmlEsc $SofficePath))
Set-Content -Path (Join-Path $AppDir "web.config") -Value $cfg -Encoding UTF8

# allow web.config to configure the handler (locked by default on many servers)
Invoke-Native { & $appcmd unlock config -section:system.webServer/handlers | Out-Null }
Invoke-Native { & $appcmd unlock config -section:system.webServer/httpPlatform 2>&1 | Out-Null }

# ---------------------------------------------------------------- app pool + permissions
Step "Application pool '$AppPoolName'"
if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) { New-WebAppPool -Name $AppPoolName | Out-Null; Write-Host "Created." }
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.loadUserProfile -Value $true
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name startMode -Value "AlwaysRunning"
Write-Host "No Managed Code, load user profile, always running."

Step "Granting the app pool access to the app folder"
$identity = "IIS AppPool\$AppPoolName"
Invoke-Native { icacls $AppDir /grant "${identity}:(OI)(CI)RX" /T /Q | Out-Null }
foreach ($d in @("output", "logs", "assets\team", "assets\services")) {
  Invoke-Native { icacls (Join-Path $AppDir $d) /grant "${identity}:(OI)(CI)M" /T /Q | Out-Null }
}
Write-Host "Read access to the app folder; write access to output, logs, assets\team, assets\services."

# ---------------------------------------------------------------- site / application
$site = Get-Website | Where-Object { $_.Name -eq $SiteName }
if ($AppName) {
  Step "IIS application /$AppName under site '$SiteName'"
  if (-not $site) { Fail "IIS site '$SiteName' was not found. Check the name in IIS Manager and pass it with -SiteName." }
  if (-not (Get-WebApplication -Site $SiteName -Name $AppName)) {
    New-WebApplication -Site $SiteName -Name $AppName -PhysicalPath $AppDir -ApplicationPool $AppPoolName | Out-Null
    Write-Host "Created."
  } else {
    Set-ItemProperty "IIS:\Sites\$SiteName\$AppName" -Name physicalPath -Value $AppDir
    Set-ItemProperty "IIS:\Sites\$SiteName\$AppName" -Name applicationPool -Value $AppPoolName
    Write-Host "Updated."
  }
} else {
  Step "IIS site '$SiteName'"
  if (-not $site) {
    New-Website -Name $SiteName -Port $Port -PhysicalPath $AppDir -ApplicationPool $AppPoolName | Out-Null
    Write-Host "Created on HTTP port $Port. Add your HTTPS binding and certificate in IIS Manager."
  } else {
    if ($site.physicalPath -ne $AppDir) {
      Write-Host "Physical path changed from '$($site.physicalPath)' to '$AppDir'."
      Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $AppDir
    }
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $AppPoolName
    Write-Host "Using the existing site; its bindings and certificate are not changed."
  }
}

Restart-WebAppPool -Name $AppPoolName
if ((Get-WebsiteState -Name $SiteName).Value -ne "Started") {
  try { Start-Website -Name $SiteName } catch { Write-Warning "Could not start site '$SiteName': $($_.Exception.Message)" }
}

# ---------------------------------------------------------------- smoke test
$bindings = @(Get-WebBinding -Name $SiteName)
$http = $bindings | Where-Object { $_.protocol -eq "http" } | Select-Object -First 1
$https = $bindings | Where-Object { $_.protocol -eq "https" } | Select-Object -First 1
$b = if ($http) { $http } else { $https }
$urls = @()
if ($b) {
  $parts = $b.bindingInformation.Split(":")       # ip:port:hostname
  $hostName = if ($parts[2]) { $parts[2] } else { "localhost" }
  $base = "$($b.protocol)://${hostName}:$($parts[1])"
  $urls += "$base$prefix/"
}
foreach ($url in $urls) {
  Step "Testing $url"
  Start-Sleep -Seconds 3
  try {
    # the certificate is usually issued for the public host name, not "localhost": skip the check for this test only
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 180
    if ($r.Content -match "Proposal Generator") { Write-Host "OK - the wizard is running at $url" -ForegroundColor Green }
    else { Write-Warning "Got HTTP $($r.StatusCode) but not the wizard page." }
  } catch {
    Write-Warning "The site did not respond correctly: $($_.Exception.Message)"
    Write-Warning "Open the site in a browser on the server, and check the log files in $AppDir\logs and the troubleshooting section of deploy\iis\README.md."
  } finally {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null
  }
}
Write-Host ""
Write-Host "Done. Staff open the site's address in a browser; the Admin page is at <address>$prefix/admin" -ForegroundColor Green
