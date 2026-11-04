"""BDO Proposal Generator – web app.

    pip install -r requirements.txt
    python app.py            # http://localhost:5000
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from proposal.html_gen import generate_html, render_html
from proposal.model import OUTPUT_DIR, ROOT, catalog, normalise, safe_filename, settings
from proposal.pdf_convert import pptx_to_pdf
from proposal.pptx_gen import generate_pptx
from proposal.sign import create_signed_acceptance

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or request.host_url).rstrip("/")


def proposal_dir(pid: str) -> Path:
    if not pid or any(ch in pid for ch in "/\\.") or len(pid) > 80:
        abort(404)
    d = OUTPUT_DIR / pid
    if not (d / "proposal.json").exists():
        abort(404)
    return d


def load_proposal(pid: str) -> dict:
    return json.loads((proposal_dir(pid) / "proposal.json").read_text(encoding="utf-8"))


@app.after_request
def cors(resp):
    # the HTML proposal may be opened from e-mail / file:// and posts its signature here
    if request.path.startswith("/api/proposals/") and request.path.endswith("/sign"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.get("/")
def wizard():
    return render_template("wizard.html")


@app.get("/api/catalog")
def api_catalog():
    st = settings()
    return jsonify({
        "client_types": catalog()["client_types"],
        "groups": catalog()["groups"],
        "team": [{k: m[k] for k in ("id", "name", "title")} for m in st["team"]],
        "scope_fields": st["scope_fields"],
    })


@app.post("/api/proposals")
def api_create():
    body = request.get_json(force=True, silent=True) or {}
    formats = [f for f in body.get("formats", ["pptx", "pdf", "html"]) if f in ("pptx", "pdf", "html")]
    try:
        p = normalise(body.get("proposal") or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    d = OUTPUT_DIR / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")

    stem = safe_filename(f"BDO_Proposal_{p['client']['company']}_{p['client']['date']}")
    files, errors = {}, {}
    if "pptx" in formats or "pdf" in formats:
        pptx = generate_pptx(p, d / f"{stem}.pptx")
        if "pptx" in formats:
            files["pptx"] = pptx.name
        if "pdf" in formats:
            try:
                files["pdf"] = pptx_to_pdf(pptx, d).name
            except Exception as e:  # LibreOffice missing / failed
                errors["pdf"] = str(e)
    if "html" in formats:
        sign_url = f"{base_url()}/api/proposals/{p['id']}/sign"
        files["html"] = generate_html(p, d / f"{stem}.html", sign_url).name
    links = {k: f"/proposals/{p['id']}/files/{v}" for k, v in files.items()}
    if "html" in formats:
        links["online"] = f"{base_url()}/p/{p['id']}"
    return jsonify({"id": p["id"], "files": links, "errors": errors})


@app.get("/proposals/<pid>/files/<path:name>")
def download(pid, name):
    return send_from_directory(proposal_dir(pid), name, as_attachment=True)


@app.get("/p/<pid>")
def online(pid):
    p = load_proposal(pid)
    return Response(render_html(p, f"{base_url()}/api/proposals/{pid}/sign"), mimetype="text/html")


@app.route("/api/proposals/<pid>/sign", methods=["POST", "OPTIONS"])
def api_sign(pid):
    if request.method == "OPTIONS":
        return ("", 204)
    p = load_proposal(pid)
    s = request.get_json(force=True, silent=True) or {}
    signer = {k: str(s.get(k, ""))[:200] for k in ("name", "title", "date")}
    signer["signature"] = str(s.get("signature", ""))
    if not signer["name"] or not signer["signature"].startswith("data:image/png;base64,"):
        return "Name and signature are required", 400
    if len(signer["signature"]) > 2_000_000:
        return "Signature image too large", 400
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    pdf = create_signed_acceptance(p, signer, ip=ip, user_agent=request.headers.get("User-Agent", ""))
    out = proposal_dir(pid) / "signed"
    out.mkdir(exist_ok=True)
    name = safe_filename(f"{p['client']['company']}_Signed_Proposal_{signer['date'] or 'undated'}") + ".pdf"
    (out / name).write_bytes(pdf)
    (out / (name[:-4] + ".json")).write_text(json.dumps({k: v for k, v in signer.items() if k != "signature"} | {"ip": ip}))
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/proposals")
def list_proposals():
    rows = []
    for d in sorted(OUTPUT_DIR.glob("*/proposal.json"), reverse=True):
        p = json.loads(d.read_text(encoding="utf-8"))
        signed = sorted((d.parent / "signed").glob("*.pdf")) if (d.parent / "signed").exists() else []
        rows.append({"id": p["id"], "company": p["client"]["company"], "title": p["client"]["title"],
                     "date": p["client"]["date"], "signed": [f"/proposals/{p['id']}/files/signed/{f.name}" for f in signed]})
    return jsonify(rows)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("DEBUG")))
