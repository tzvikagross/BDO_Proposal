"""Production entry point (waitress WSGI server).

Under IIS, HttpPlatformHandler starts this script (see web.config) and forwards every
request to it on the port it passes in HTTP_PLATFORM_PORT.

Environment variables:
  HTTP_PLATFORM_PORT / PORT  port to listen on (IIS sets HTTP_PLATFORM_PORT)        default 5000
  URL_PREFIX                 sub-path when the app is an IIS application, e.g. /proposals
  PUBLIC_BASE_URL            public address used in links sent to clients, e.g. https://server/proposals
  BEHIND_PROXY               1 = trust X-Forwarded-* headers from IIS
  SOFFICE_PATH               full path to LibreOffice soffice.exe (for PDF output)
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)                       # IIS may start the process in another folder
sys.path.insert(0, str(ROOT))

from waitress import serve  # noqa: E402

from app import app  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    port = int(os.environ.get("HTTP_PLATFORM_PORT") or os.environ.get("PORT") or 5000)
    prefix = os.environ.get("URL_PREFIX", "").strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    logging.info("BDO Proposal Generator listening on 127.0.0.1:%s%s", port, prefix or "")
    serve(app, host="127.0.0.1", port=port, url_prefix=prefix, threads=8,
          channel_timeout=600, max_request_body_size=30 * 1024 * 1024)
