"""PPTX -> PDF conversion through LibreOffice (headless).

Set SOFFICE_PATH if `soffice` is not on PATH (e.g. on Windows:
C:\\Program Files\\LibreOffice\\program\\soffice.exe).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def find_soffice() -> str | None:
    cand = os.environ.get("SOFFICE_PATH")
    if cand and Path(cand).exists():
        return cand
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).exists():
            return p
    return None


def pptx_to_pdf(pptx: Path, out_dir: Path | None = None, timeout: int = 240) -> Path:
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) was not found – install it or set SOFFICE_PATH to export PDF.")
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir or pptx.parent).resolve()
    env = os.environ.copy()
    if os.name != "nt":                       # headless display backend; Linux/macOS only
        env.setdefault("SAL_USE_VCLPLUGIN", "svp")
    # ignore_cleanup_errors: on Windows LibreOffice can keep the profile folder locked briefly
    with tempfile.TemporaryDirectory(prefix="lo_profile_", ignore_cleanup_errors=True) as profile:
        cmd = [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
               "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx)]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    pdf = out_dir / (pptx.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"PDF conversion failed: {res.stderr or res.stdout}")
    return pdf
