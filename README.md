# BDO Proposal Generator

A small web app that turns a few answers (client details, client type and fees) into a fee proposal built on the BDO template in [`template/New_Proposal_Format.pptx`](template/New_Proposal_Format.pptx). It can produce:

| Format | What you get |
|---|---|
| **PPTX** | The full template deck: cover, letter, contents, T&C, scope, about-BDO and the selected team, with the fee slides rebuilt from the services you chose. The tables are cloned from the template, so they keep its formatting. |
| **PDF** | The same deck exported through LibreOffice. |
| **HTML** | A single self-contained file (also served online at `/p/<id>`). Each part of the proposal has its own tab. Inside *Proposed Services & Fees*, each service group appears as its own sub-section. The *Accept & Sign* tab lets the client sign. |

### Digital signing (HTML)
The client fills in name, title and date, then draws or types a signature and clicks **Sign & download PDF**:

1. **Online (the normal case).** The proposal posts to the app's `/api/proposals/<id>/sign` endpoint. The server builds a PDF that contains only **Terms & Conditions and Proposed Services & Fees**, together with the signature block and an audit trail (UTC time, IP and a SHA-256 hash of the proposal). It then seals the PDF with a **PAdES digital signature** using BDO's certificate (pyHanko). The client downloads the sealed PDF, and a copy is kept in `output/<id>/signed/`.
2. **Offline fallback.** If the signing server can't be reached (for example, the HTML was opened from an email while the app is down), the browser builds the same two-section PDF with the signature image. This copy is electronically signed but **not** cryptographically sealed, and the client is told so.

> **Certificate:** put BDO's real signing certificate at `data/signing.p12` and set its password in the `BDO_SIGNING_P12_PASSWORD` environment variable. Until then, a **self-signed development certificate** is created automatically. PDFs signed with it are valid and tamper-evident, but Adobe will mark the signer as "unknown".

## Running

```bash
pip install -r requirements.txt
python app.py                # open http://localhost:5000
```

PDF export needs [LibreOffice](https://www.libreoffice.org/). If `soffice` isn't on your PATH, set `SOFFICE_PATH`. To let clients sign from the HTML file, the app has to be reachable by them. Deploy it and set `PUBLIC_BASE_URL` (for example `https://proposals.bdo.co.il`) so the generated files point to the right signing URL.

## The wizard
1. **Client details:** company, contact person (salutation and name), opportunity number, date, client type (*Accounting*, *Payroll only*, *Fund Admin*), cover title and optional scope of operations.
2. **Engagement Team:** shows every bio in `assets/team` with photo, title and the full bio text. Tick the people to include; a proposal can have any number of bios, and they appear in the order shown. Bios marked `"default": true` (Tzvika Gross) start ticked but can be unticked. **+ Add a bio** uploads a new bio slide.
3. **Services & fees:** the service groups for the chosen client type are switched on. You can untick services, edit fees, units and wording, change currency, or add lines and sub-headings. Groups from other client types are under *Other service groups*.
4. **Generate:** pick the formats and download, or copy the online link to send to the client.

*Previous proposals* lists everything generated so far, with links to any signed copies.

## Engagement-team bios (`assets/team`)
Each person is a **single-slide PowerPoint file**, `assets/team/<id>.pptx`, holding their bio slide exactly as it should appear in the deck. Next to it:

| File | Contents |
|---|---|
| `<id>.json` | Name, credentials, title, phone, e-mail, current role and experience paragraphs (used by the wizard and the HTML proposal), plus `"default"` (pre-selected) and `"order"` (sort position). Created automatically from the slide text when the slide is first seen. Edit it to tidy the text, or delete it to re-read the slide. |
| `<id>.jpg` | Photo, extracted automatically from the slide. |

**To add a person**, use any of these:
- In the wizard, choose **Engagement Team → + Add a bio** and upload a PPTX. If the file has several slides, only its first slide is used.
- Copy a one-slide bio PPTX into `assets/team/`.
- Split bio slides out of a deck: `python scripts/extract_bios.py deck.pptx 3 4 5` (add `--default` to pre-select them).

The easiest way to make a new bio slide is to download an existing one from the wizard (*Read bio → Download slide*), then change the photo and text in PowerPoint. Bios uploaded on a server are saved in that server's `assets/team` folder. Commit them to git to keep them.

## Customising
| File | Purpose |
|---|---|
| `config/services.json` | Service catalog: groups (one table each), default fees, units, descriptions, and which groups each client type gets |
| `config/settings.json` | Firm details, letter text, terms & conditions (used by the HTML and the signed PDF), footnotes, scope fields, signing certificate |
| `template/New_Proposal_Format.pptx` | The PowerPoint template. If you change its slide order, update the slide numbers at the top of `proposal/pptx_gen.py`. Run `python scripts/build_assets.py` afterwards to refresh the images used by the HTML |

Terms & conditions in the **PPTX** come straight from template slide 4. If you edit them in `settings.json`, edit the template too.

## Project layout
```
app.py                  Flask app (wizard, generation API, online proposal, signing endpoint)
proposal/model.py       config loading + normalising wizard input
proposal/pptx_gen.py    template-based PPTX generation
proposal/bios.py        engagement-team bios (assets/team) and bio-slide import
proposal/pdf_convert.py LibreOffice PPTX→PDF
proposal/html_gen.py    self-contained HTML proposal
proposal/sign.py        T&C + fees acceptance PDF and PAdES signing
templates/              wizard.html, proposal.html (Jinja)
static/                 wizard JS/CSS
assets/                 images extracted from the template for the HTML
vendor/jspdf.umd.min.js offline PDF fallback (inlined into the HTML)
tests/                  pytest suite
```

```bash
python -m pytest -q
```
