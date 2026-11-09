"""Service catalog stored in assets/services/services.json (edited from the Admin page).

Structure:
  currencies    ["USD", "ILS", "EUR", "GBP"]
  units         ["Monthly", "Hourly", ...]   fee units offered in drop-downs
  client_types  {id: {label, code, proposal_title, default_currency,
                      segments: [segment ids switched on for this type],
                      excluded: {segment id: [service ids that start unticked]}}}
  segments      [{id, name, section, footnotes, bullets, fee_header?, rows[]}]
     rows: {"type": "subheader", "text", "note"?}
           {"type": "service", "id", "description"[], "unit", "fees": {currency: amount|null}}

Older files (segments with "default_for", services with "selected") are upgraded when read.
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
CODE_RE = re.compile(r"^[A-Z]{2}$")
DEFAULT_CODES = {"accounting": "LF", "fund_admin": "TC", "payroll": "RB"}


def upgrade(cat: dict) -> dict:
    """Bring a catalog in the older format up to date (in memory)."""
    types = cat.setdefault("client_types", {})
    segs = cat.get("segments", [])
    used = {t.get("code") for t in types.values() if t.get("code")}
    for tid, t in types.items():
        if not t.get("code"):
            code = DEFAULT_CODES.get(tid) or re.sub(r"[^A-Z]", "", (t.get("label") or tid).upper())[:2].ljust(2, "X")
            while code in used:
                code = code[0] + chr(((ord(code[1]) - 64) % 26) + 65)
            t["code"] = code
            used.add(code)
        if "segments" not in t:
            t["segments"] = [s["id"] for s in segs if tid in (s.get("default_for") or [])]
        if "excluded" not in t:
            t["excluded"] = {}
            for s in segs:
                if s["id"] in t["segments"]:
                    off = [r["id"] for r in s["rows"] if r.get("type") == "service" and r.get("selected") is False]
                    if off:
                        t["excluded"][s["id"]] = off
    for s in segs:
        s.pop("default_for", None)
        for r in s.get("rows", []):
            r.pop("selected", None)
    return cat


def load() -> dict:
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return upgrade(json.load(f))


def segments_for(cat: dict, client_type: str) -> list[dict]:
    """The segments switched on for a client type, in catalog order."""
    ids = set(cat["client_types"][client_type].get("segments", []))
    return [s for s in cat["segments"] if s["id"] in ids]


def service_on(cat: dict, client_type: str, segment_id: str, service_id: str) -> bool:
    return service_id not in cat["client_types"][client_type].get("excluded", {}).get(segment_id, [])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]


def _is_new(raw) -> bool:
    """The Admin page gives unsaved segments/services/types a temporary 'new_...' id."""
    return str(raw or "").startswith("new_")


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
    segs, seg_ids = [], set()
    seg_map, svc_map = {}, {}          # submitted id -> saved id (ids are tidied / de-duplicated)
    for si, s in enumerate(data.get("segments") or [], 1):
        name = (s.get("name") or "").strip()
        if not name:
            raise ValueError(f"Segment {si} needs a name")
        raw_sid = s.get("id") or ""
        sid = (_slug(name) if _is_new(raw_sid) else _slug(raw_sid)) or _slug(name) or uuid.uuid4().hex[:8]
        base, n = sid, 2
        while sid in seg_ids:
            sid, n = f"{base}_{n}", n + 1
        seg_ids.add(sid)
        seg_map[str(s.get("id") or "")] = sid
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
            rid = ("" if _is_new(r.get("id")) else _slug(r.get("id") or "")) or uuid.uuid4().hex[:8]
            while rid in row_ids:
                rid = f"{rid}_{uuid.uuid4().hex[:3]}"
            row_ids.add(rid)
            svc_map[(sid, str(r.get("id") or ""))] = rid
            rows.append({"type": "service", "id": rid, "description": desc, "unit": unit, "fees": fees})
        seg = {"id": sid, "name": name, "section": (s.get("section") or "").strip(),
               "footnotes": s.get("footnotes") if s.get("footnotes") in ("default", "fund") else "default",
               "bullets": bool(s.get("bullets", True)), "rows": rows}
        if (s.get("fee_header") or "").strip() and s["fee_header"].strip() != "Cost":
            seg["fee_header"] = s["fee_header"].strip()
        segs.append(seg)
    if not segs:
        raise ValueError("Keep at least one segment")
    types = _validate_client_types(data.get("client_types"), current, segs, seg_map, svc_map)
    out = dict(current)
    out["units"], out["segments"], out["client_types"] = units, segs, types
    return out


def _validate_client_types(submitted, current, segs, seg_map, svc_map) -> dict:
    if submitted is None:                       # older Admin page: keep the types as they are
        submitted = current["client_types"]
    if isinstance(submitted, dict):
        submitted = [dict(v, id=k) for k, v in submitted.items()]
    valid_segs = {s["id"]: {r["id"] for r in s["rows"] if r["type"] == "service"} for s in segs}
    out, codes, labels = {}, set(), set()
    for i, t in enumerate(submitted, 1):
        label = (t.get("label") or "").strip()
        if not label:
            raise ValueError(f"Type of client {i} needs a name")
        code = (t.get("code") or "").strip().upper()
        if not CODE_RE.match(code):
            raise ValueError(f"“{label}”: the letters must be exactly two capital letters A–Z (e.g. LF)")
        if code in codes:
            raise ValueError(f"The letters {code} are used by more than one type of client")
        if label.lower() in labels:
            raise ValueError(f"There are two types of client called “{label}”")
        codes.add(code); labels.add(label.lower())
        raw_tid = t.get("id") or ""
        tid = (_slug(label) if _is_new(raw_tid) else _slug(raw_tid)) or _slug(label) or uuid.uuid4().hex[:8]
        base, n = tid, 2
        while tid in out:
            tid, n = f"{base}_{n}", n + 1
        cur = (t.get("default_currency") or current["currencies"][0]).upper()
        if cur not in current["currencies"]:
            raise ValueError(f"“{label}”: unknown currency {cur}")
        seg_ids = []
        for sid in t.get("segments") or []:
            sid = seg_map.get(str(sid), sid)
            if sid in valid_segs and sid not in seg_ids:
                seg_ids.append(sid)
        excluded = {}
        for sid, svcs in (t.get("excluded") or {}).items():
            new_sid = seg_map.get(str(sid), sid)
            if new_sid not in seg_ids:
                continue
            ids = [svc_map.get((new_sid, str(x)), x) for x in svcs or []]
            ids = [x for x in dict.fromkeys(ids) if x in valid_segs[new_sid]]
            if ids:
                excluded[new_sid] = ids
        out[tid] = {"label": label, "code": code,
                    "proposal_title": (t.get("proposal_title") or label).strip(),
                    "default_currency": cur, "segments": seg_ids, "excluded": excluded}
    if not out:
        raise ValueError("Keep at least one type of client")
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
