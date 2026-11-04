"""Signed acceptance PDF: Terms & Conditions + Proposed Services & Fees only.

1. The client's drawn/typed signature, name, title and date are rendered into an
   acceptance page together with an audit trail (UTC time, IP, document hash).
2. The PDF is then digitally signed (PAdES, via pyHanko) with BDO's certificate, which
   seals the document: any later change invalidates the signature in Adobe Reader.

Configure the certificate in config/settings.json -> signing. Without one, a self-signed
development certificate is created on first use (data/dev_signing.p12).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from xml.sax.saxutils import escape

from .model import ASSETS_DIR, DATA_DIR, ROOT, settings

BDO_RED = colors.HexColor("#E81A3B")
SLATE = colors.HexColor("#657C91")
BAND = colors.HexColor("#E8EBEE")
SUB = colors.HexColor("#D3D9DF")
INK = colors.HexColor("#333333")

ST = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, textColor=BDO_RED, spaceAfter=8, leading=22),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, textColor=INK, spaceBefore=8, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=9.5, textColor=INK, spaceBefore=6, spaceAfter=2),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8.6, leading=11.4, textColor=INK, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.2, leading=10.4, textColor=INK),
    "cellc": ParagraphStyle("cellc", fontName="Helvetica", fontSize=8.2, leading=10.4, textColor=INK, alignment=TA_CENTER),
    "hdr": ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=8.4, leading=10.4, textColor=colors.white),
    "hdrc": ParagraphStyle("hdrc", fontName="Helvetica-Bold", fontSize=8.4, leading=10.4, textColor=colors.white, alignment=TA_CENTER),
    "sub": ParagraphStyle("sub", fontName="Helvetica-Bold", fontSize=8.2, leading=10.4, textColor=INK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.4, leading=9.4, textColor=colors.HexColor("#555555")),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
}


def proposal_hash(proposal: dict) -> str:
    """SHA-256 over the commercial content the client is accepting."""
    content = {"client": proposal["client"], "groups": proposal["groups"], "terms": proposal["terms"]}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fee_table(group, width):
    data = [[Paragraph(escape(group["fee_header"]), ST["hdrc"]), Paragraph(escape(group["title"]), ST["hdr"])]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), SLATE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, r in enumerate(group["rows"], start=1):
        if r["type"] == "subheader":
            data.append([Paragraph(escape(r.get("note") or ""), ST["cellc"]), Paragraph(escape(r["text"]), ST["sub"])])
            style.append(("BACKGROUND", (0, i), (-1, i), SUB))
        else:
            fee = Paragraph("<br/>".join(escape(x) for x in r["fee_text"].split("\n")), ST["cellc"])
            if group.get("bullets", True) and r["description"]:
                desc = ListFlowable([ListItem(Paragraph(escape(d), ST["cell"]), leftIndent=9) for d in r["description"]],
                                    bulletType="bullet", start="•", bulletFontSize=7, leftIndent=9)
            else:
                desc = Paragraph("<br/>".join(escape(d) for d in r["description"]), ST["cell"])
            data.append([fee, desc])
            style.append(("BACKGROUND", (0, i), (-1, i), BAND))
    t = Table(data, colWidths=[width * 0.3, width * 0.7], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def build_acceptance_pdf(proposal: dict, signer: dict | None = None, audit: dict | None = None) -> bytes:
    """Render the T&C + Services & Fees document. *signer*: name, title, date, signature (data URL)."""
    buf = io.BytesIO()
    c = proposal["client"]
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=24 * mm,
                            bottomMargin=18 * mm, title=f"Fee Proposal – {c['company']}",
                            author=proposal["firm"]["name"], subject="Acceptance of fee proposal")
    width = A4[0] - 36 * mm
    logo = ASSETS_DIR / "logo.png"

    def on_page(canvas, d):
        canvas.saveState()
        if logo.exists():
            canvas.drawImage(str(logo), A4[0] - 18 * mm - 22 * mm, A4[1] - 16 * mm, width=22 * mm, height=8.5 * mm,
                             preserveAspectRatio=True, mask="auto")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(18 * mm, A4[1] - 13 * mm,
                          f"{c['company']}  ·  {c['title']}  ·  Opportunity {c['opportunity']}")
        canvas.drawString(18 * mm, 10 * mm, f"Proposal {proposal['id']}  ·  SHA-256 {proposal_hash(proposal)[:16]}…")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    story = [Paragraph("Fee Proposal – Acceptance", ST["h1"]),
             Paragraph(f"<b>Client:</b> {escape(c['company'])}<br/>"
                       f"<b>Contact:</b> {escape((c['salutation'] + ' ' + c['contact_name']).strip())}<br/>"
                       f"<b>Services:</b> {escape(c['title'])}<br/>"
                       f"<b>Proposal date:</b> {escape(c['date_long'])}", ST["meta"]),
             Spacer(1, 6),
             Paragraph("1. Acceptance, Terms and Conditions", ST["h2"])]
    for sec in proposal["terms"]:
        story.append(Paragraph(escape(sec["heading"]).upper(), ST["h3"]))
        story += [Paragraph(escape(p), ST["body"]) for p in sec["paragraphs"]]

    story += [PageBreak(), Paragraph("2. Proposed Services and Fees", ST["h2"])]
    for s in proposal["sections"]:
        if s["title"]:
            story.append(Paragraph(escape(s["title"]), ST["h3"]))
        for g in s["groups"]:
            story += [_fee_table(g, width), Spacer(1, 6)]
        story += [Paragraph(escape(f), ST["small"]) for f in s["footnote_lines"]]
        story.append(Spacer(1, 8))

    story.append(KeepTogether(_approval_block(signer, audit, width)))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _approval_block(signer, audit, width):
    out = [Spacer(1, 10), Paragraph("Approved by", ST["h2"])]
    signer = signer or {}
    sig_img = ""
    if signer.get("signature", "").startswith("data:image"):
        raw = base64.b64decode(signer["signature"].split(",", 1)[1])
        sig_img = Image(io.BytesIO(raw), width=55 * mm, height=20 * mm, kind="proportional")
    rows = [["Name:", signer.get("name", ""), "Job Title:", signer.get("title", "")],
            ["Signature:", sig_img, "Date:", signer.get("date", "")]]
    t = Table([[Paragraph(f"<b>{a}</b>", ST["cell"]) if isinstance(a, str) and a.endswith(":") else
                (Paragraph(escape(a), ST["cell"]) if isinstance(a, str) else a) for a in r] for r in rows],
              colWidths=[width * 0.13, width * 0.42, width * 0.13, width * 0.32], rowHeights=[9 * mm, 24 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, BDO_RED), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LINEBELOW", (1, 0), (1, -1), 0.5, colors.grey), ("LINEBELOW", (3, 0), (3, -1), 0.5, colors.grey),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    out.append(t)
    if audit:
        out += [Spacer(1, 6), Paragraph(
            "Electronically signed. " + "  ·  ".join(f"{escape(k)}: {escape(str(v))}" for k, v in audit.items()),
            ST["small"])]
    return out


# ---------------------------------------------------------------- certificate
def _load_or_create_p12():
    cfg = settings()["signing"]
    p12 = ROOT / cfg["p12_path"]
    pwd = os.environ.get(cfg.get("p12_password_env", ""), "")
    if p12.exists():
        return p12, pwd.encode() if pwd else None
    dev = DATA_DIR / "dev_signing.p12"
    if not dev.exists():
        _create_dev_p12(dev)
    return dev, b"dev-password"


def _create_dev_p12(path: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "BDO Israel Proposals (DEVELOPMENT)"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BDO Israel"),
                      x509.NameAttribute(NameOID.COUNTRY_NAME, "IL")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .sign(key, hashes.SHA256()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pkcs12.serialize_key_and_certificates(
        b"bdo-dev", key, cert, None, serialization.BestAvailableEncryption(b"dev-password")))


def digitally_sign(pdf_bytes: bytes, signer_name: str, company: str) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers

    p12, pwd = _load_or_create_p12()
    signer = signers.SimpleSigner.load_pkcs12(str(p12), passphrase=pwd)
    meta = signers.PdfSignatureMetadata(
        field_name="BDOAcceptanceSeal",
        reason=f"Proposal accepted by {signer_name} on behalf of {company}",
        location="Israel",
        certify=True,
    )
    out = io.BytesIO()
    signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf_bytes)), meta, signer=signer, output=out)
    return out.getvalue()


def create_signed_acceptance(proposal: dict, signer: dict, ip: str = "", user_agent: str = "") -> bytes:
    audit = {
        "Signed at (UTC)": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Signer": signer.get("name", ""),
        "IP": ip or "n/a",
        "Document SHA-256": proposal_hash(proposal),
    }
    if user_agent:
        audit["Client"] = user_agent[:80]
    pdf = build_acceptance_pdf(proposal, signer, audit)
    return digitally_sign(pdf, signer.get("name", ""), proposal["client"]["company"])
