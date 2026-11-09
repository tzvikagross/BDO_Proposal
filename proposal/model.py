"""Loading configuration and normalising a proposal request into one data structure
shared by the PPTX, PDF, HTML and signed-PDF generators."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
TEMPLATE_PPTX = ROOT / "template" / "New_Proposal_Format.pptx"
ASSETS_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"


def load_json(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def catalog() -> dict:
    """The service catalog (assets/services/services.json, edited from the Admin page)."""
    from .catalog import load
    return load()


def settings() -> dict:
    return load_json("settings.json")


def format_fee(fee) -> str:
    """4500 -> '4,500'; '1500.5' -> '1,500.5'; free text is returned unchanged."""
    if fee is None:
        return ""
    if isinstance(fee, (int, float)):
        return f"{fee:,.0f}" if float(fee).is_integer() else f"{fee:,.2f}"
    s = str(fee).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s.replace(",", "")):
        return format_fee(float(s.replace(",", "")))
    return s


NO_AMOUNT_UNITS = {"Included"}


def fee_text(row: dict) -> str:
    """Text shown in the fee column, e.g. '4,500 Monthly' or 'Included'."""
    unit = (row.get("unit") or "").strip()
    if unit in NO_AMOUNT_UNITS:
        return unit
    parts = [format_fee(row.get("fee")), unit]
    return " ".join(p for p in parts if p)


def _clean_lines(desc) -> list[str]:
    if isinstance(desc, str):
        desc = desc.splitlines()
    return [d.strip() for d in (desc or []) if d and d.strip()]


def segment_to_group(seg: dict, currency: str, excluded=()) -> dict:
    """A catalog segment as a proposal group with the default fees in *currency*;
    services in *excluded* start unticked."""
    rows = []
    for r in seg["rows"]:
        if r["type"] == "subheader":
            rows.append(copy.deepcopy(r))
        else:
            rows.append({"type": "item", "id": r["id"], "include": r["id"] not in excluded,
                         "fee": (r.get("fees") or {}).get(currency), "unit": r["unit"],
                         "description": list(r["description"])})
    return {"id": seg["id"], "section": seg.get("section", ""), "title": seg["name"],
            "fee_header": seg.get("fee_header", "Cost"), "footnotes": seg.get("footnotes", "default"),
            "bullets": seg.get("bullets", True), "rows": rows}


def default_proposal(client_type: str = "accounting", currency: str | None = None) -> dict:
    """A complete proposal pre-filled from the catalog defaults (used by tests/CLI)."""
    cat = catalog()
    ct = cat["client_types"][client_type]
    currency = currency or ct.get("default_currency", cat["currencies"][0])
    from .catalog import segments_for
    groups = [segment_to_group(s, currency, ct.get("excluded", {}).get(s["id"], [])) for s in segments_for(cat, client_type)]
    return {
        "client": {
            "company": "Example Company Ltd.",
            "contact_name": "Jane Doe",
            "salutation": "Ms.",
            "client_type": client_type,
            "currency": currency,
            "title": ct["proposal_title"],
            "date": dt.date.today().isoformat(),
        },
        "team": None,  # None = the default bios
        "scope": {},
        "groups": groups,
    }


def normalise(req: dict) -> dict:
    """Validate and normalise a proposal request coming from the wizard."""
    cat = catalog()
    st = settings()
    client = dict(req.get("client") or {})
    ctype = client.get("client_type") or "accounting"
    if ctype not in cat["client_types"]:
        raise ValueError(f"Unknown client type: {ctype}")
    if not (client.get("company") or "").strip():
        raise ValueError("Company name is required")
    client.setdefault("title", cat["client_types"][ctype]["proposal_title"])
    client["title"] = (client.get("title") or cat["client_types"][ctype]["proposal_title"]).strip()
    client["company"] = client["company"].strip()
    client["contact_name"] = (client.get("contact_name") or "").strip()
    client["salutation"] = (client.get("salutation") or "").strip()
    client["opportunity"] = (client.get("opportunity") or "").strip() or "000000"
    try:
        d = dt.date.fromisoformat(client.get("date") or "")
    except ValueError:
        d = dt.date.today()
    client["date"] = d.isoformat()
    client["date_display"] = f"{d.strftime('%B')} {d.year}"
    client["date_long"] = f"{d.day} {d.strftime('%B')} {d.year}"
    client["client_type_label"] = cat["client_types"][ctype]["label"]
    client["client_type_code"] = cat["client_types"][ctype].get("code", "")
    cur = (client.get("currency") or cat["client_types"][ctype].get("default_currency") or "USD").strip().upper()
    if cur not in cat["currencies"]:
        raise ValueError(f"Unsupported currency: {cur}")
    client["currency"] = cur

    groups = []
    for g in req.get("groups") or []:
        rows = []
        for r in g.get("rows") or []:
            if r.get("type") == "subheader":
                if (r.get("text") or "").strip():
                    rows.append({"type": "subheader", "text": r["text"].strip(), "note": (r.get("note") or "").strip()})
            else:
                if r.get("include") is False:
                    continue
                desc = _clean_lines(r.get("description"))
                if not desc and not str(r.get("fee") or "").strip():
                    continue
                item = {"type": "item", "id": r.get("id") or uuid.uuid4().hex[:8],
                        "fee": r.get("fee"), "unit": (r.get("unit") or "").strip(), "description": desc}
                if item["unit"] in NO_AMOUNT_UNITS:
                    item["fee"] = None
                item["fee_display"] = format_fee(item["fee"]) if item["unit"] not in NO_AMOUNT_UNITS else item["unit"]
                item["fee_text"] = fee_text(item)
                rows.append(item)
        # drop sub-headers that ended up with no items below them
        cleaned = []
        for i, r in enumerate(rows):
            if r["type"] == "subheader":
                nxt = rows[i + 1] if i + 1 < len(rows) else None
                if nxt is None or nxt["type"] == "subheader":
                    continue
            cleaned.append(r)
        if not any(r["type"] == "item" for r in cleaned):
            continue
        groups.append({
            "id": g.get("id") or uuid.uuid4().hex[:8],
            "section": (g.get("section") or "").strip(),
            "title": (g.get("title") or "Services").strip(),
            "currency": cur,
            "fee_header": f"{(g.get('fee_header') or 'Cost').strip()} ({cur})",
            "footnotes": g.get("footnotes") or "default",
            "bullets": g.get("bullets", True) is not False,
            "rows": cleaned,
        })
    if not groups:
        raise ValueError("Select at least one service")

    # group the tables into sections, keeping first-seen order
    sections: list[dict] = []
    for g in groups:
        sec = next((s for s in sections if s["title"] == g["section"]), None)
        if sec is None:
            sec = {"title": g["section"], "groups": [], "footnotes": g["footnotes"]}
            sections.append(sec)
        sec["groups"].append(g)
        if g["footnotes"] != "default":
            sec["footnotes"] = g["footnotes"]
    for s in sections:
        s["footnote_lines"] = st["footnotes"].get(s["footnotes"], st["footnotes"]["default"])

    from .bios import default_bio_ids, get_bios
    team_ids = req.get("team")
    if team_ids is None:          # not specified -> pre-selected bios; [] -> no bios
        team_ids = default_bio_ids()
    team = get_bios(team_ids)

    scope = {k: str(v).strip() for k, v in (req.get("scope") or {}).items() if str(v or "").strip()}
    scope_rows = [{"label": f["label"], "value": scope[f["id"]]} for f in st["scope_fields"] if f["id"] in scope]

    return {
        "id": req.get("id") or dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        "client": client,
        "groups": groups,
        "sections": sections,
        "team": team,
        "scope": scope_rows,
        "firm": st["firm"],
        "terms": st["terms"],
        "letter": st["letter"],
        "outsourcing_services": st["outsourcing_services"],
        "created": dt.datetime.now().isoformat(timespec="seconds"),
    }


def safe_filename(s: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "", s, flags=re.UNICODE).strip().replace(" ", "_")
    return s or "proposal"
