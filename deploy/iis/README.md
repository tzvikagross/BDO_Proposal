# Running the Proposal Generator on IIS

IIS can't run this app as a static `index.html`. Building the PPTX and PDF, saving Admin changes and storing bio uploads all happen in the Python part of the app, on the server. IIS hosts it using Microsoft's **HttpPlatformHandler** module:

```
staff browser (LAN) ──► IIS ──► HttpPlatformHandler ──► serve.py (Python, waitress)
```

IIS starts the Python app automatically and restarts it if it stops. Every request is passed to the app, so opening the site or application address shows the wizard. You don't need a separate service or a scheduled task.

The server only needs to be reachable by **staff on the LAN**. Clients never connect to it: they receive the proposal's HTML file by email, and sign it in their own browser.

## 1. Install the prerequisites (once per server)

| What | Where | Notes |
|---|---|---|
| IIS | Server Manager → *Add Roles and Features* → **Web Server (IIS)** | The default features are enough |
| **HttpPlatformHandler v1.2** (x64) | https://www.iis.net/downloads/microsoft/httpplatformhandler | |
| **Python 3.10+** (64-bit) | https://www.python.org/downloads/windows/ | Choose *Customize installation* and tick **Install Python for all users**, so it goes to `C:\Program Files\Python3xx`. IIS can't run a Python that is installed only for your user. |
| **LibreOffice** | https://www.libreoffice.org/download/ | Only needed for **PDF** output |
| Git (optional) | https://git-scm.com/download/win | For cloning and updating. You can also copy the folder over instead. |

## 2. Put the app on the server and create the site
1. Copy the app into a folder, e.g. `C:\inetpub\wwwroot\Proposal`. If the server has no internet access, also add the `wheels` folder (see *Server without internet*).
2. In IIS Manager, create a site called **Proposal** pointing to that folder, with an application pool also called **Proposal**. Add your bindings, e.g. HTTPS with your certificate.

If you skip step 2, the setup script creates the site for you, on HTTP port 8080.

## 3. Run the setup script
Open **Windows PowerShell as Administrator**, go to the app folder and run the script:

```bash
cd C:\inetpub\wwwroot\Proposal
```

```bash
powershell -ExecutionPolicy Bypass -File .\deploy\iis\setup-iis.ps1
```

By default the app runs as the site **Proposal**, with the app pool **Proposal**, at the root of the site (e.g. `https://proposal.yourdomain/`). If the site already exists, the script uses it as it is and doesn't change its bindings or certificate. The script:
- creates `.venv` and installs the Python packages (offline from `wheels`, if present);
- writes `web.config`;
- sets the app pool to *No Managed Code* and *always running*;
- gives the app pool access to the app folder;
- points the site at the app folder;
- opens the site once to check it works.

Other options:
- **Different site or app pool names:** `-SiteName "BDO Fees" -AppPoolName "BDOFees"`
- **As a sub-folder of another site instead of its own site:** `-SiteName "Default Web Site" -AppName "proposals"` gives `http://<server>/proposals/`
- **Python or LibreOffice in unusual folders:** `-PythonExe "C:\Python312\python.exe" -SofficePath "D:\LibreOffice\program\soffice.exe"`

It is safe to run the script again: after an update, or to change these settings.

## 4. Access
Admin (`/admin`) has no separate login: every employee who can open the app can edit the list of services. HTTPS is optional on the LAN. If you want it, add an HTTPS binding to the site in IIS Manager.

## Server without internet
The setup script normally downloads the Python packages from the internet. If the server can't do that, download them on another computer (a Mac is fine) and copy them over.

**Don't copy installed packages from a Mac.** lxml, Pillow and pypdfium2 contain compiled code built for macOS, which Windows can't load. Instead, ask pip for the **Windows** versions that match the server's Python.

**1. On the Mac**, in the project folder, download the Windows packages for Python 3.14 into a `wheels` folder (about 18 MB). Change `3.14` if the server has a different Python version.

```bash
python3 -m pip install --upgrade pip
```

```bash
python3 -m pip download -r requirements.txt --platform win_amd64 --python-version 3.14 --implementation cp --only-binary=:all: -d wheels
```

**2. Copy** the whole project folder, including `wheels`, to the server, e.g. `C:\inetpub\wwwroot\BDO_Proposal`.

**3. On the server**, run the setup script as usual. When the app folder contains a `wheels` folder, the script installs from it offline and never contacts the internet. You can also point it at another folder with `-WheelsDir "D:\wheels"`.

**After an update** that changes `requirements.txt`, download the `wheels` folder again on the Mac and copy it over before re-running the script.

### Installers to bring with you
Download these on the Mac and copy them to the server. All of them install offline:
- HttpPlatformHandler (x64): https://www.iis.net/downloads/microsoft/httpplatformhandler
- Python for Windows, *Windows installer (64-bit)*: https://www.python.org/downloads/windows/. Use the same version you used for the wheels.
- LibreOffice for Windows (x86_64): https://www.libreoffice.org/download/download-libreoffice/

### Python works in PowerShell but not in Command Prompt
This usually means Python was installed **for one user only**, or the `python` command in Command Prompt is the Microsoft Store shortcut. To check where Python is installed, run this in PowerShell:

```bash
(Get-Command python).Source
```

If the path is under `C:\Users\...\AppData\...`, Python is installed only for your user, and **IIS won't be able to run it**. Reinstall it: run the installer, choose *Customize installation*, then tick **Install Python for all users**. It then goes to `C:\Program Files\Python314\`. Use PowerShell for all the steps in this guide; Command Prompt isn't needed.

## Updating
To update to the latest code, run these commands in the app folder:

```bash
git pull
```

```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
Restart-WebAppPool Proposal
```

Your data is not touched by `git pull`: the `output` and `logs` folders and `web.config` aren't in git. **Admin edits** (`assets/services/services.json`) and **uploaded bios** (`assets/team/`) are tracked by git, though. If they were changed on the server, commit them before pulling, or git may refuse to update.

## Where things are
| Path | Contents |
|---|---|
| `web.config` | IIS settings, generated by the setup script. Edit the `environmentVariable` values here, e.g. `SOFFICE_PATH`. |
| `logs\python_*.log` | The app's output and errors |
| `output\` | Generated proposals (PPTX, PDF, HTML), one folder per proposal |
| `assets\services\services.json` | Service catalog (Admin) |
| `assets\team\` | Bio slides |

## Troubleshooting
| Symptom | Fix |
|---|---|
| **500.19** "configuration section cannot be used at this path" | Run `%windir%\system32\inetsrv\appcmd.exe unlock config -section:system.webServer/handlers` (the setup script does this) |
| **500.19** "unrecognized element httpPlatform" | HttpPlatformHandler isn't installed. Install it and run `iisreset`. |
| Setup script: "Missing argument in parameter list" or another parser error | The script was saved with special characters by an editor. Use the copy from GitHub; it is plain ASCII. Run it with `powershell -ExecutionPolicy Bypass -File ...` |
| Setup script: "Offline install failed" | The `wheels` folder holds packages for a different Python version or for Mac. Download them again with `--platform win_amd64 --python-version <server version>` (see *Server without internet*) |
| **502.3 / 502.5** or the page hangs | Look in `logs\python_*.log`. The usual causes: Python installed *for one user only*; packages missing (re-run the setup script); a Python error shown in the log |
| PDF fails, but PPTX and HTML work | Check that `SOFFICE_PATH` in `web.config` points to `soffice.exe`, and that the app pool has `loadUserProfile = True` (the setup script sets this) |
| Admin "Save" or bio upload fails | The app pool needs **Modify** rights on `assets\services` and `assets\team` (the setup script grants this) |
