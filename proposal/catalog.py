"""Service catalog stored in assets/services/services.json (edited from the Admin page).

Structure:
  currencies    ["USD", "ILS", "EUR", "GBP"]
  units         ["Monthly", "Hourly", ...]   fee units offered in drop-downs
  client_types  {id: {label, proposal_title, default_currency}}
  segments      [{id, name, section, default_for[], footnotes, bullets, fee_header?, rows[]}]
     rows: {"type": "subheader", "text", "note"?}
           {"type": "service", "id", "description"[], "unit", "fees": {currency: amount|null}, "selected"}
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid

from .model import ASSETS_DIR

SERVICES_DIR = ASSETS_DIR / "services"
CATALOG_FILE = SERVICES_DIR / "services.json"
HISTORY_DIR = SERVICES_DIR / "history"
KEEP_HISTORY = 30
NO_AMOUNT_UNITS = {"Included"}


def load() -> dict:
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]


def _amount(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        try:
            n = float(str(v).replace(",", "").strip())
        except ValueError:
            raise ValueError(f"'{v}' is not a number")
    if n < 0:
        raise ValueError("Fees cannot be negative")
    return int(n) if n.is_integer() else round(n, 2)


def validate(data: dict) -> dict:
    """Clean and validate a catalog submitted by the Admin page. Raises ValueError."""
    current = load()
    currencies = current["currencies"]
    units = [u.strip() for u in data.get("units") or [] if str(u).strip()]
    if not units:
        raise ValueError("Keep at least one fee unit")
    if len(set(u.lower() for u in units)) != len(units):
        raise ValueError("Fee units must be unique")
    client_types = current["client_types"]
    segs, seg_ids = [], set()
    for si, s in enumerate(data.get("segments") or [], 1):
        name = (s.get("name") or "").strip()
        if not name:
            raise ValueError(f"Segment {si} needs a name")
        sid = _slug(s.get("id") or "") or _slug(name) or uuid.uuid4().hex[:8]
        base, n = sid, 2
        while sid in seg_ids:
            sid, n = f"{base}_{n}", n + 1
        seg_ids.add(sid)
        rows, row_ids = [], set()
        for ri, r in enumerate(s.get("rows") or [], 1):
            if r.get("type") == "subheader":
                text = (r.get("text") or "").strip()
                if text:
                    row = {"type": "subheader", "text": text}
                    if (r.get("note") or "").strip():
                        row["note"] = r["note"].strip()
                    rows.append(row)
                continue
            desc = r.get("description") or []
            if isinstance(desc, str):
                desc = desc.splitlines()
            desc = [d.strip() for d in desc if d and d.strip()]
            if not desc:
                raise ValueError(f"“{name}”: service {ri} needs a description")
            unit = (r.get("unit") or "").strip()
            if unit not in units:
                raise ValueError(f"“{name}” – “{desc[0]}”: choose a fee unit")
            try:
                fees = {c: (None if unit in NO_AMOUNT_UNITS else _amount((r.get("fees") or {}).get(c))) for c in currencies}
            except ValueError as e:
                raise ValueError(f"“{name}” – “{desc[0]}”: {e}")
            rid = _slug(r.get("id") or "") or uuid.uuid4().hex[:8]
            while rid in row_ids:
                rid = f"{rid}_{uuid.uuid4().hex[:3]}"
            row_ids.add(rid)
            rows.append({"type": "service", "id": rid, "description": desc, "unit": unit,
                         "fees": fees, "selected": bool(r.get("selected", True))})
        seg = {"id": sid, "name": name, "section": (s.get("section") or "").strip(),
               "default_for": [c for c in s.get("default_for") or [] if c in client_types],
               "footnotes": s.get("footnotes") if s.get("footnotes") in ("default", "fund") else "default",
               "bullets": bool(s.get("bullets", True)), "rows": rows}
        if (s.get("fee_header") or "").strip() and s["fee_header"].strip() != "Cost":
            seg["fee_header"] = s["fee_header"].strip()
        segs.append(seg)
    if not segs:
        raise ValueError("Keep at least one segment")
    out = dict(current)
    out["units"], out["segments"] = units, segs
    return out


def save(data: dict) -> dict:
    clean = validate(data)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if CATALOG_FILE.exists():
        (HISTORY_DIR / f"services-{stamp}.json").write_bytes(CATALOG_FILE.read_bytes())
    for old in sorted(HISTORY_DIR.glob("services-*.json"))[:-KEEP_HISTORY]:
        old.unlink()
    tmp = CATALOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CATALOG_FILE)
    return clean


def history() -> list[str]:
    return sorted((p.name for p in HISTORY_DIR.glob("services-*.json")), reverse=True) if HISTORY_DIR.exists() else []


def restore(name: str) -> dict:
    if not re.fullmatch(r"services-\d{8}-\d{6}\.json", name or ""):
        raise ValueError("Unknown version")
    data = json.loads((HISTORY_DIR / name).read_text(encoding="utf-8"))
    return save(data)
