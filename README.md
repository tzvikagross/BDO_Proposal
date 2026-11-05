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

## Running on IIS (Windows server)
IIS runs the Python app for you, using Microsoft's HttpPlatformHandler module. Opening the site, or an application such as `https://server/proposals/`, shows the wizard. A setup script installs everything:

```bash
powershell -ExecutionPolicy Bypass -File .\deploy\iis\setup-iis.ps1 -PublicBaseUrl "https://intranet.bdo.co.il/proposals"
```

See **[deploy/iis/README.md](deploy/iis/README.md)** for the prerequisites, HTTPS, access control, updating and troubleshooting. To run the production server on any other system:

```bash
python serve.py
```

It reads `PORT`, `URL_PREFIX` (e.g. `/proposals`), `PUBLIC_BASE_URL` and `BEHIND_PROXY`.

## The wizard
1. **Client details:** company, contact person (salutation and name), opportunity number, date, **currency** (ILS, USD, EUR or GBP), client type (*Accounting*, *Payroll only*, *Fund Admin*), cover title and optional scope of operations. Each client type has a default currency (USD; ILS for Fund Admin), and you can change it.
2. **Engagement Team:** shows every bio in `assets/team` with photo, title and the full bio text. Tick the people to include; a proposal can have any number of bios, and they appear in the order shown. Bios marked `"default": true` (Tzvika Gross) start ticked but can be unticked. **+ Add a bio** uploads a new bio slide.
3. **Services & fees:** the segments for the chosen client type are switched on. Each service shows its default fee in the chosen currency, and its defaults in every currency are listed underneath. You can tick or untick services, change a fee (edited fees are highlighted and have a *reset* link), choose the fee unit from the drop-down, edit the wording, or add services and sub-headings. You can also switch the currency here; doing so resets all fees to that currency's defaults. Segments that aren't on by default for the client type are under *Other service segments*.
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

## Admin: the list of services
Open **Admin** (top right of the wizard, or `/admin`) to edit the services the wizard offers. Changes are saved to **`assets/services/services.json`**, and every save keeps the previous version in `assets/services/history/` (the last 30). The Admin page has a *Restore a previous version* picker and buttons to *Export CSV* or *Download JSON*.

- **Segments** are the fee tables. You can add, delete or reorder them, and set for each one:
  - its name (the table heading);
  - its section (the slide sub-title and HTML sub-section; segments with the same section share a slide);
  - which client types it is switched on for by default;
  - its footnotes, and whether descriptions are shown as bullets.
- **Services** are the rows of a segment. You can add, remove or reorder them. For each one you set:
  - the description (one bullet per line);
  - the **fee unit**, which is required;
  - the **default fee in each currency**;
  - whether it is pre-selected in the wizard.
- **Sub-headings** are grey rows that group services within a table.
- **Fee units** is the list offered in every unit drop-down: Monthly, Hourly, Annually, Quarterly, Per case, Per employee, PePP, Per report, Per investor, One-off and Included. You can add your own units. A unit can only be removed once no service uses it. *Included* means there is no charge, so it takes no amount.

> The non-USD default prices were first calculated from the template's prices (ILS ≈ 3.7 × USD, EUR ≈ 0.92 × USD, GBP ≈ 0.79 × USD, rounded). Fund services started from the template's ILS prices. Please review them in Admin.

Anyone who can open the app can use Admin. If the app is reachable from outside BDO, put it behind your login or VPN.

## Customising
| File | Purpose |
|---|---|
| `assets/services/services.json` | Service catalog. Edit it through **Admin** (see above) |
| `config/settings.json` | Firm details, letter text, terms & conditions (used by the HTML and the signed PDF), footnotes, scope fields, signing certificate |
| `template/New_Proposal_Format.pptx` | The PowerPoint template. If you change its slide order, update the slide numbers at the top of `proposal/pptx_gen.py`. Run `python scripts/build_assets.py` afterwards to refresh the images used by the HTML |

Terms & conditions in the **PPTX** come straight from template slide 4. If you edit them in `settings.json`, edit the template too.

## Project layout
```
app.py                  Flask app (wizard, generation API, online proposal, signing endpoint)
serve.py                production server (waitress) – started by IIS
deploy/iis/             IIS: setup-iis.ps1, web.config.template, README.md
proposal/model.py       config loading + normalising wizard input
proposal/pptx_gen.py    template-based PPTX generation
proposal/catalog.py     service catalog: load, validate, save with history
proposal/bios.py        engagement-team bios (assets/team) and bio-slide import
proposal/pdf_convert.py LibreOffice PPTX→PDF
proposal/html_gen.py    self-contained HTML proposal
proposal/sign.py        T&C + fees acceptance PDF and PAdES signing
templates/              wizard.html, admin.html, proposal.html (Jinja)
static/                 wizard and admin JS/CSS
assets/services/        services.json – the service catalog (edited in Admin)
assets/                 images extracted from the template for the HTML
vendor/jspdf.umd.min.js offline PDF fallback (inlined into the HTML)
tests/                  pytest suite
```

```bash
python -m pytest -q
```
