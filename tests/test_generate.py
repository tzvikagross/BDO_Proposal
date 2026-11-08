import io
import json
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation

from app import app
from proposal.model import default_proposal, normalise
from proposal.pptx_gen import generate_pptx

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
    assert p["groups"][0]["rows"][1]["fee_text"] == "12,500 Annually"


def test_html_is_self_contained_and_offline(tmp_path):
    """The emailed HTML must work on the client's computer without contacting any server."""
    import re
    from proposal.html_gen import generate_html
    p = normalise(default_proposal("fund_admin"))
    html = generate_html(p, tmp_path / "p.html").read_text(encoding="utf-8")
    own_script = html[html.index("const PROPOSAL = "):]         # our code (the bundled jsPDF library comes before it)
    assert "fetch(" not in own_script and "XMLHttpRequest" not in own_script and "sendBeacon" not in own_script
    assert not re.search(r'<(script|link|img)[^>]+(src|href)="https?://', html)
    assert "window.jspdf" in html and "Sign &amp; download PDF" in html
    assert p["firm"]["email"] in html                     # "email the signed PDF to BDO" button


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
    assert c.get(j["files"]["online"]).status_code == 200
    assert c.post(f"/api/proposals/{j['id']}/sign", json={}).status_code in (404, 405)   # no signing server
    assert c.post("/api/proposals", json={"proposal": {"client": {}}}).status_code == 400


# ---------------------------------------------------------------- engagement-team bios
def _team_names(pptx_path):
    prs = Presentation(str(pptx_path))
    return [s for s in prs.slides
            if any(sh.has_text_frame and sh.text_frame.text.strip() == "ENGAGEMENT TEAM" for sh in s.shapes)]


def test_default_bio_is_tzvika_only():
    p = normalise(default_proposal("accounting"))
    assert [m["id"] for m in p["team"]] == ["tzvika"]


def test_selected_bios_in_order_and_none(tmp_path):
    req = default_proposal("payroll")
    req["team"] = ["racheli", "tzvika", "lea"]
    out = generate_pptx(normalise(req), tmp_path / "a.pptx")
    slides = _team_names(out)
    texts = [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in slides]
    assert len(slides) == 3
    assert "Racheli" in texts[0] and "Tzvika" in texts[1] and "Lea" in texts[2]

    req["team"] = []
    out = generate_pptx(normalise(req), tmp_path / "b.pptx")
    assert _team_names(out) == []


def test_upload_new_bio(tmp_path, monkeypatch):
    import shutil
    import proposal.bios as bios
    monkeypatch.setattr(bios, "BIO_DIR", tmp_path)
    src = Path(__file__).resolve().parent.parent / "assets" / "team" / "lea.pptx"
    bio = bios.add_bio_from_upload(src.read_bytes(), "someone.pptx")
    assert bio["name"] == "Lea Feinstein" and bio["has_photo"]
    assert (tmp_path / f"{bio['id']}.pptx").exists() and (tmp_path / f"{bio['id']}.json").exists()
    assert [b["id"] for b in bios.list_bios()] == [bio["id"]]


# ---------------------------------------------------------------- currencies & service catalog
@pytest.mark.parametrize("cur", ["USD", "ILS", "EUR", "GBP"])
def test_defaults_follow_currency(cur):
    from proposal.catalog import load
    p = normalise(default_proposal("accounting", cur))
    seg = next(s for s in load()["segments"] if s["id"] == "audit_tax")
    expected = seg["rows"][1]["fees"][cur]
    row = p["groups"][0]["rows"][1]
    assert p["client"]["currency"] == cur and p["groups"][0]["fee_header"] == f"Cost ({cur})"
    assert row["fee"] == expected and row["fee_text"].startswith(f"{expected:,}")


def test_included_unit_has_no_amount():
    p = normalise(default_proposal("payroll"))
    inc = next(r for r in p["groups"][0]["rows"] if r.get("unit") == "Included")
    assert inc["fee_text"] == "Included"


def test_bad_currency_rejected():
    req = default_proposal("payroll")
    req["client"]["currency"] = "JPY"
    with pytest.raises(ValueError):
        normalise(req)


@pytest.fixture
def temp_catalog(tmp_path, monkeypatch):
    import shutil
    import proposal.catalog as catalog
    src = catalog.CATALOG_FILE
    monkeypatch.setattr(catalog, "CATALOG_FILE", tmp_path / "services.json")
    monkeypatch.setattr(catalog, "HISTORY_DIR", tmp_path / "history")
    shutil.copy(src, tmp_path / "services.json")
    return catalog


def test_admin_add_segment_service_and_save(temp_catalog):
    cat = temp_catalog.load()
    cat["segments"].append({"name": "Crypto Services", "section": "Additional services", "default_for": ["accounting"],
                            "rows": [{"type": "service", "description": "Wallet reconciliation", "unit": "Monthly",
                                      "fees": {"USD": "1,200", "ILS": 4400, "EUR": "", "GBP": None}}]})
    cat["segments"] = [s for s in cat["segments"] if s.get("id") != "vat_rep"]
    saved = temp_catalog.save(cat)
    seg = saved["segments"][-1]
    assert seg["id"] == "crypto_services"
    assert seg["rows"][0]["fees"] == {"USD": 1200, "ILS": 4400, "EUR": None, "GBP": None}
    assert not any(s["id"] == "vat_rep" for s in temp_catalog.load()["segments"])
    assert len(temp_catalog.history()) == 1


@pytest.mark.parametrize("bad, msg", [
    ({"unit": "Fortnightly"}, "unit"),
    ({"description": []}, "description"),
    ({"fees": {"USD": "abc"}}, "number"),
])
def test_admin_validation(temp_catalog, bad, msg):
    cat = temp_catalog.load()
    cat["segments"][0]["rows"][1].update(bad)
    with pytest.raises(ValueError, match=msg):
        temp_catalog.save(cat)


def test_admin_api(temp_catalog):
    c = app.test_client()
    assert c.get("/admin").status_code == 200
    cat = c.get("/api/catalog").get_json()
    cat["units"].append("Per entity")
    r = c.post("/api/admin/catalog", json=cat)
    assert r.status_code == 200 and "Per entity" in r.get_json()["units"]
    assert c.post("/api/admin/catalog", json={"units": [], "segments": []}).status_code == 400
    csv = c.get("/api/admin/export.csv").data.decode("utf-8-sig")
    assert csv.startswith("Segment,Section,Type,Description,Unit,Fee USD")


# ---------------------------------------------------------------- hosting under a sub-path (IIS application)
def test_links_under_sub_path(tmp_path, monkeypatch):
    import app as appmod
    import proposal.model as model
    monkeypatch.setattr(appmod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(model, "OUTPUT_DIR", tmp_path)
    c = app.test_client()
    env = "http://localhost/proposals/"
    page = c.get("/", base_url=env).get_data(as_text=True)
    assert 'window.APP_BASE = "/proposals"' in page and 'href="/proposals/admin"' in page
    r = c.post("/api/proposals", json={"proposal": default_proposal("payroll"), "formats": ["html"]}, base_url=env)
    j = r.get_json()
    assert j["files"]["html"].startswith("/proposals/proposals/")
    assert j["files"]["online"] == f"/proposals/p/{j['id']}"


def test_iis_setup_script_is_plain_ascii():
    """Windows PowerShell 5.1 misreads non-ASCII characters in a script (e.g. an en dash)
    and then reports parser errors, so the setup script must stay plain ASCII."""
    root = Path(__file__).resolve().parent.parent / "deploy" / "iis"
    for name in ("setup-iis.ps1", "web.config.template"):
        data = (root / name).read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        bad = [i for i, ch in enumerate(data) if ch > 127]
        assert not bad, f"{name} has non-ASCII characters at byte {bad[0]}"


# ---------------------------------------------------------------- Windows-safe file handling & API errors
def test_fix_content_types_closes_temp_file(tmp_path):
    """On Windows an open handle stops the temp file from being renamed/deleted:
    the post-processing step must not leave any file handle or temp file behind."""
    import os
    from proposal.pptx_gen import _fix_content_types
    out = generate_pptx(normalise(default_proposal("payroll")), tmp_path / "a.pptx")
    fds = set(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
    _fix_content_types(out)
    if fds is not None:
        assert set(os.listdir("/proc/self/fd")) <= fds
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pptx"]


def test_api_errors_are_json(tmp_path, monkeypatch):
    import app as appmod
    import proposal.model as model
    monkeypatch.setattr(appmod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(model, "OUTPUT_DIR", tmp_path)

    def boom(*a, **k):
        raise PermissionError("file in use")
    monkeypatch.setattr(appmod, "generate_pptx", boom)
    c = app.test_client()
    r = c.post("/api/proposals", json={"proposal": default_proposal("payroll"), "formats": ["pptx"]})
    assert r.status_code == 500 and r.is_json
    assert "PermissionError" in r.get_json()["error"]
    assert c.get("/api/nope").is_json


def test_generated_deck_is_left_to_right(tmp_path):
    """No right-to-left flags may remain, or the PDF shows '4,500 Annual' as 'Annual 4,500'."""
    import re
    req = default_proposal("accounting")
    req["team"] = ["tzvika", "lea", "racheli", "tzippora"]
    out = generate_pptx(normalise(req), tmp_path / "ltr.pptx")
    z = zipfile.ZipFile(out)
    flags = sum(len(re.findall(rb'\brtl="1"|rtlCol="1"', z.read(n))) for n in z.namelist() if n.endswith(".xml"))
    assert flags == 0


def test_fee_column_on_the_right(tmp_path):
    """After switching to left-to-right, tables keep the template's layout: fees in the right column."""
    req = default_proposal("accounting")
    req["scope"] = {"employees": "5"}
    prs = Presentation(str(generate_pptx(normalise(req), tmp_path / "f.pptx")))
    tables = [sh.table for s in prs.slides for sh in s.shapes if sh.has_table]
    fee_tables = [t for t in tables if t.rows[0].cells[-1].text.startswith(("Cost", "Hourly Cost"))]
    assert fee_tables and len(fee_tables) == len(tables) - 1          # all but the scope table
    for t in fee_tables:
        assert t.columns[-1].width < t.columns[0].width                 # narrow fee column last
    scope = next(t for t in tables if t not in fee_tables)
    assert scope.rows[1].cells[0].text == "Number of employees" and scope.rows[1].cells[-1].text == "5"
