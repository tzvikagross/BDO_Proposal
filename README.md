# BDO Proposal Generator

A small web app that turns a few answers (client details, client type and fees) into a fee proposal built on the BDO template in [`template/New_Proposal_Format.pptx`](template/New_Proposal_Format.pptx). It can produce:

| Format | What you get |
|---|---|
| **PPTX** | The full template deck: cover, letter, contents, T&C, scope, about-BDO and the selected team, with the fee slides rebuilt from the services you chose. The tables are cloned from the template, so they keep its formatting. |
| **PDF** | The same deck exported through LibreOffice. |
| **HTML** | A single self-contained file to email to the client. It works offline. Each part of the proposal has its own tab. Inside *Proposed Services & Fees*, each service segment appears as its own sub-section. The *Accept & Sign* tab lets the client sign. Staff can preview it on the LAN at `/p/<id>`. |

### How the client signs (no server needed)
The app is used by BDO staff on the LAN; clients never connect to it. You **email the HTML file** to the client, and the client opens it on their own computer:

1. In the **Accept & Sign** tab they enter their name, initials, job title and date, and sign with a **simple electronic signature**: their typed **full name**, their typed **initials**, or a **drawn** signature.
2. They tick the confirmation box and click **Sign & download PDF**. Their browser creates a PDF with only the **Terms & Conditions and Proposed Services & Fees**, plus:
   - the signature block;
   - their initials on every page;
   - the signing date and time;
   - a SHA-256 fingerprint of the accepted terms and fees.
3. An **Open an email** button starts an email to BDO (`firm.email` in `config/settings.json`), and they attach the downloaded PDF.

Nothing is sent anywhere automatically, and the file never contacts your server.

## Running

```bash
pip install -r requirements.txt
python app.py                # open http://localhost:5000
```

PDF export needs [LibreOffice](https://www.libreoffice.org/). If `soffice` isn't on your PATH, set `SOFFICE_PATH`.

## Running on IIS (Windows server)
IIS runs the Python app for you, using Microsoft's HttpPlatformHandler module. By default it runs as its own IIS site called **Proposal**; opening the site's address shows the wizard to staff on the LAN. A setup script installs everything:

```bash
powershell -ExecutionPolicy Bypass -File .\deploy\iis\setup-iis.ps1
```

See **[deploy/iis/README.md](deploy/iis/README.md)** for the prerequisites, updating and troubleshooting. To run the production server on any other system:

```bash
python serve.py
```

It reads `PORT`, `URL_PREFIX` (e.g. `/proposals`) and `SOFFICE_PATH`.

## The wizard
1. **Client details:** company, contact person (salutation and name), opportunity number, date, **currency** (ILS, USD, EUR or GBP), client type (*Accounting*, *Payroll only*, *Fund Admin*), cover title and optional scope of operations. Each client type has a default currency (USD; ILS for Fund Admin), and you can change it.
2. **Engagement Team:** shows every bio in `assets/team` with photo, title and the full bio text. Tick the people to include; a proposal can have any number of bios, and they appear in the order shown. Bios marked `"default": true` (Tzvika Gross) start ticked but can be unticked. **+ Add a bio** uploads a new bio slide.
3. **Services & fees:** the segments for the chosen client type are switched on. Each service shows its default fee in the chosen currency, and its defaults in every currency are listed underneath. You can tick or untick services, change a fee (edited fees are highlighted and have a *reset* link), choose the fee unit from the drop-down, edit the wording, or add services and sub-headings. You can also switch the currency here; doing so resets all fees to that currency's defaults. Segments that aren't on by default for the client type are under *Other service segments*.
4. **Generate:** pick the formats and download, or copy the online link to send to the client.

**Previous proposals** lists every proposal with its **number**, date, client, contact, opportunity, services and files. The **search** box filters the table as you type; it matches any of these fields, and several words must all match. Each row has:
- **Preview:** opens the HTML proposal.
- **Edit:** opens a copy in the wizard, with the client details, team, scope, currency, and every service and fee as they were. Unticked services and your own added lines are included. Generating it creates a **new** proposal; the original is never changed.

**Proposal numbers** look like `2026-0001` (year and running number). A revision made with Edit keeps the original number with a suffix: `2026-0001-R1`, `2026-0001-R2`, and so on. The number appears in the HTML proposal, in the client's signed PDF and in the file names.

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

Admin has no separate login: every employee who can open the app can use it.

## Customising
| File | Purpose |
|---|---|
| `assets/services/services.json` | Service catalog. Edit it through **Admin** (see above) |
| `config/settings.json` | Firm details (including the e-mail clients send the signed PDF to), letter text, terms & conditions (used by the HTML and the signed PDF), footnotes, scope fields |
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
templates/              wizard.html, admin.html, proposal.html (Jinja)
static/                 wizard and admin JS/CSS
assets/services/        services.json – the service catalog (edited in Admin)
assets/                 images extracted from the template for the HTML
vendor/jspdf.umd.min.js builds the signed PDF in the client's browser (inlined into the HTML)
tests/                  pytest suite
```

```bash
python -m pytest -q
```
