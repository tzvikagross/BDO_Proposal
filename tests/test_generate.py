import io
import json
import zipfile

import pytest
from pptx import Presentation

from app import app
from proposal.model import default_proposal, normalise
from proposal.pptx_gen import generate_pptx
from proposal.sign import build_acceptance_pdf, create_signed_acceptance

SIG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
       "60e6kgAAAABJRU5ErkJggg==")


@pytest.mark.parametrize("ctype", ["accounting", "payroll", "fund_admin"])
def test_pptx_contains_selected_services_only(tmp_path, ctype):
    p = normalise(default_proposal(ctype))
    out = generate_pptx(p, tmp_path / "p.pptx")
    prs = Presentation(str(out))
    text = "\n".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    tables = "\n".join(c.text for s in prs.slides for sh in s.shapes if sh.has_table
                       for r in sh.table.rows for c in r.cells)
    assert p["client"]["company"] in text and p["client"]["title"] in text
    for g in p["groups"]:
        assert g["title"] in tables
    if ctype == "payroll":
        assert "Audit financial statements" not in tables and "Payroll Setup" in tables
    if ctype == "fund_admin":
        assert "Payroll Setup" not in tables and "World-check" in tables
    ct = zipfile.ZipFile(out).read("[Content_Types].xml")
    assert b'"image/jpg"' not in ct


def test_unticked_items_and_empty_groups_are_dropped():
    req = default_proposal("payroll")
    for r in req["groups"][0]["rows"]:
        r["include"] = False
    p = normalise(req)
    assert [g["id"] for g in p["groups"]] == ["hourly_rates"]


def test_fee_formatting():
    req = default_proposal("accounting")
    req["groups"][0]["rows"][1]["fee"] = "12500"
    p = normalise(req)
    assert p["groups"][0]["rows"][1]["fee_text"] == "12,500 Annual"


def test_signed_pdf_is_valid():
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    p = normalise(default_proposal("fund_admin"))
    pdf = create_signed_acceptance(p, {"name": "Jane", "title": "CFO", "date": "2026-11-04", "signature": SIG})
    sig = PdfFileReader(io.BytesIO(pdf)).embedded_signatures[0]
    st = validate_pdf_signature(sig, ValidationContext(trust_roots=[sig.signer_cert], allow_fetching=False))
    assert st.intact and st.valid


def test_api_flow(tmp_path, monkeypatch):
    import app as appmod
    import proposal.model as model
    monkeypatch.setattr(appmod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(model, "OUTPUT_DIR", tmp_path)
    c = app.test_client()
    r = c.post("/api/proposals", json={"proposal": default_proposal("payroll"), "formats": ["pptx", "html"]})
    assert r.status_code == 200, r.data
    j = r.get_json()
    assert set(j["files"]) == {"pptx", "html", "online"}
    assert c.get(j["files"]["html"]).status_code == 200
    r = c.post(f"/api/proposals/{j['id']}/sign", json={"name": "Jane", "title": "CFO", "date": "2026-11-04", "signature": SIG})
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    assert c.post("/api/proposals", json={"proposal": {"client": {}}}).status_code == 400
