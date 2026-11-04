"""Self-contained interactive HTML proposal (one file; images and scripts inlined)."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .model import ASSETS_DIR, ROOT, settings

_env = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=select_autoescape(["html"]))


def data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def assets_for(proposal: dict) -> dict:
    return {
        "logo": data_uri(ASSETS_DIR / "logo.png"),
        "cover": data_uri(ASSETS_DIR / "cover.jpg"),
        "team": {m["id"]: data_uri(ASSETS_DIR / "team" / f"{m['id']}.jpg") for m in proposal["team"]},
        "about": [data_uri(ASSETS_DIR / "about" / f"slide-{n:02d}.jpg") for n in settings()["about_slides"]],
    }


def render_html(proposal: dict, sign_url: str | None) -> str:
    jspdf = (ROOT / "vendor" / "jspdf.umd.min.js").read_text(encoding="utf-8")
    p_json = json.dumps(proposal, ensure_ascii=False).replace("</", "<\\/")
    return _env.get_template("proposal.html").render(
        p=proposal, a=assets_for(proposal), p_json=p_json, sign_url=sign_url or "",
        jspdf=jspdf.replace("</script", "<\\/script"))


def generate_html(proposal: dict, out_path: Path, sign_url: str | None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(proposal, sign_url), encoding="utf-8")
    return out_path
