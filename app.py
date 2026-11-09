"""BDO Proposal Generator – web app.

    pip install -r requirements.txt
    python app.py            # development server, http://localhost:5000
    python serve.py          # production server (waitress) – used by IIS, see deploy/iis

Clients sign the emailed HTML proposal in their own browser; the server is only used by staff.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, url_for

from proposal.bios import BIO_DIR, add_bio_from_upload, list_bios
from proposal import catalog as svc_catalog
from proposal import registry
from proposal.html_gen import generate_html, render_html
from proposal.model import OUTPUT_DIR, ROOT, catalog, normalise, safe_filename, settings
from proposal.pdf_convert import pptx_to_pdf
from proposal.pptx_gen import generate_pptx

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024   # bio slides can be a few MB
app.json.sort_keys = False      # keep the order of client types / segments as set in Admin

@app.errorhandler(Exception)
def api_error(e):
    """API calls always answer in JSON, so the wizard can show the real problem
    instead of failing to read an HTML error page."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        if not request.path.startswith("/api/"):
            return e
        return jsonify({"error": f"{e.code} {e.name}: {e.description}"}), e.code
    app.logger.exception("Error while handling %s %s", request.method, request.path)
    if not request.path.startswith("/api/"):
        return "Internal server error – see the logs folder on the server.", 500
    return jsonify({"error": f"Server error: {type(e).__name__}: {e}. Details are in the logs folder on the server."}), 500


@app.context_processor
def inject_base():
    # the app may live under a sub-path (IIS application, e.g. /proposals); scripts prefix API calls with BASE
    return {"BASE": request.script_root}


def proposal_dir(pid: str) -> Path:
    if not pid or any(ch in pid for ch in "/\\.") or len(pid) > 80:
        abort(404)
    d = OUTPUT_DIR / pid
    if not (d / "proposal.json").exists():
        abort(404)
    return d


def load_proposal(pid: str) -> dict:
    return json.loads((proposal_dir(pid) / "proposal.json").read_text(encoding="utf-8"))


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(ROOT / "static" / "brand", "favicon.ico", mimetype="image/vnd.microsoft.icon")


@app.get("/")
def wizard():
    return render_template("wizard.html")


@app.get("/api/catalog")
def api_catalog():
    return jsonify(catalog() | {"scope_fields": settings()["scope_fields"]})


# ---------------------------------------------------------------- admin: service catalog
@app.get("/admin")
def admin():
    return render_template("admin.html")


@app.post("/api/admin/catalog")
def api_admin_save():
    try:
        saved = svc_catalog.save(request.get_json(force=True, silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(saved)


@app.get("/api/admin/history")
def api_admin_history():
    return jsonify(svc_catalog.history())


@app.post("/api/admin/restore")
def api_admin_restore():
    try:
        return jsonify(svc_catalog.restore((request.get_json(silent=True) or {}).get("name", "")))
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/admin/export.csv")
def api_admin_csv():
    import csv
    import io
    cat = catalog()
    buf = io.StringIO()
    w = csv.writer(buf)
    types = list(cat["client_types"].items())
    w.writerow(["Segment", "Section", "Type", "Description", "Unit"] + [f"Fee {c}" for c in cat["currencies"]]
               + [f"Ticked for {t['code']} ({t['label']})" for _, t in types])
    for seg in cat["segments"]:
        for r in seg["rows"]:
            if r["type"] == "subheader":
                w.writerow([seg["name"], seg["section"], "Sub-heading", r["text"], ""] + [""] * len(cat["currencies"]) + [""] * len(types))
            else:
                w.writerow([seg["name"], seg["section"], "Service", " / ".join(r["description"]), r["unit"]]
                           + [("" if r["fees"].get(c) is None else r["fees"][c]) for c in cat["currencies"]]
                           + [("yes" if seg["id"] in t["segments"] and svc_catalog.service_on(cat, tid, seg["id"], r["id"]) else "no")
                              for tid, t in types])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="services.csv"'})


@app.get("/api/team")
def api_team():
    return jsonify(list_bios())


@app.post("/api/team")
def api_team_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pptx"):
        return jsonify({"error": "Upload a .pptx file containing the bio slide"}), 400
    try:
        bio = add_bio_from_upload(f.read(), f.filename)
    except Exception as e:
        return jsonify({"error": f"Could not read the presentation: {e}"}), 400
    return jsonify(bio)


@app.get("/team/<bio_id>/<kind>")
def team_file(bio_id, kind):
    if not bio_id.replace("_", "").isalnum() or kind not in ("photo", "slide"):
        abort(404)
    name = f"{bio_id}.jpg" if kind == "photo" else f"{bio_id}.pptx"
    if not (BIO_DIR / name).exists():
        abort(404)
    return send_from_directory(BIO_DIR, name, as_attachment=(kind == "slide"))


@app.post("/api/proposals")
def api_create():
    body = request.get_json(force=True, silent=True) or {}
    formats = [f for f in body.get("formats", ["pptx", "pdf", "html"]) if f in ("pptx", "pdf", "html")]
    raw = body.get("proposal") or {}
    try:
        p = normalise(raw)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # "Edit" on a previous proposal: the result is a new proposal numbered as its revision
    if body.get("revision_of"):
        registry.ensure_numbers()                     # older proposals get their number first
        original = load_proposal(str(body["revision_of"]))
        p["revision_of"] = {"id": original["id"], "number": original.get("number", "")}
    code = catalog()["client_types"][p["client"]["client_type"]].get("code", "XX")
    p["number"] = registry.assign_number(code, p.get("revision_of"))
    p["client"]["opportunity"] = p["number"]          # shown on the letter slide
    d = OUTPUT_DIR / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    # the wizard's full input (incl. unticked services) – used by "Edit", never sent to clients
    (d / "request.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    stem = safe_filename(f"BDO_Proposal_{p['number']}_{p['client']['company']}")
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
        files["html"] = generate_html(p, d / f"{stem}.html").name
    links = {k: url_for("download", pid=p["id"], name=v) for k, v in files.items()}
    if "html" in formats:
        links["online"] = url_for("online", pid=p["id"])   # preview for staff on the LAN
    return jsonify({"id": p["id"], "number": p["number"], "files": links, "errors": errors})


@app.get("/api/next-number")
def api_next_number():
    """The number the proposal being prepared in the wizard will get (not reserved)."""
    cat = catalog()
    ctype = request.args.get("client_type", "")
    if ctype not in cat["client_types"]:
        return jsonify({"error": "Unknown client type"}), 400
    rev = None
    if request.args.get("revision_of"):
        registry.ensure_numbers()
        orig = load_proposal(request.args["revision_of"])
        rev = {"id": orig["id"], "number": orig.get("number", "")}
    return jsonify({"number": registry.peek_number(cat["client_types"][ctype].get("code", "XX"), rev)})


@app.get("/api/proposals/<pid>")
def api_get_proposal(pid):
    """A saved proposal and the wizard input it was made from, for "Edit"."""
    d = proposal_dir(pid)
    req = d / "request.json"
    return jsonify({"proposal": load_proposal(pid),
                    "request": json.loads(req.read_text(encoding="utf-8")) if req.exists() else None})


@app.get("/proposals/<pid>/files/<path:name>")
def download(pid, name):
    return send_from_directory(proposal_dir(pid), name, as_attachment=True)


@app.get("/p/<pid>")
def online(pid):
    p = load_proposal(pid)
    return Response(render_html(p), mimetype="text/html")


@app.get("/proposals")
def list_proposals():
    rows = registry.list_proposals()
    for r in rows:
        r["online"] = url_for("online", pid=r["id"])
        r["files"] = {Path(n).suffix[1:]: url_for("download", pid=r["id"], name=n) for n in r["files"]}
    return jsonify(rows)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("DEBUG")))
