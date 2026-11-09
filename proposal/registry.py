"""Proposal numbers and the list of generated proposals (the output folder).

Numbers look like LF26-0001: the two letters of the client type (set in Admin), the
year (two digits) and a running number per letters and year. A revision made with "Edit"
keeps the original's number with a suffix: LF26-0001-R1, LF26-0001-R2, ...
Numbers issued in the earlier format (2026-0001) are kept as they are.
The counters live in output/numbers.json; proposals created before numbering existed
get a number the first time the list is read (in order of creation).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path

from . import model

NUMBER_RE = re.compile(r"^([A-Z]{2}\d{2}-\d{4}|\d{4}-\d{4})(?:-R(\d+))?$")
_lock = threading.RLock()


def _out() -> Path:
    return model.OUTPUT_DIR          # read at call time (tests point it elsewhere)


def _load_counters() -> dict:
    f = _out() / "numbers.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_counters(c: dict):
    _out().mkdir(parents=True, exist_ok=True)
    f = _out() / "numbers.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1), encoding="utf-8")
    tmp.replace(f)


def base_number(number: str) -> str:
    m = NUMBER_RE.match(number or "")
    return m.group(1) if m else number


def _all_proposals() -> list[tuple[Path, dict]]:
    out = []
    for f in _out().glob("*/proposal.json"):
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def _next_new(counters: dict, code: str, year: int, existing: set[str]) -> str:
    key = f"{code}{year % 100:02d}"
    n = int(counters.get(key, 0))
    while True:
        n += 1
        number = f"{key}-{n:04d}"
        if number not in existing:
            counters[key] = n
            return number


def _next_revision(counters: dict, base: str, existing: set[str]) -> str:
    key = f"rev:{base}"
    r = int(counters.get(key, 0))
    while True:
        r += 1
        number = f"{base}-R{r}"
        if number not in existing:
            counters[key] = r
            return number


def ensure_numbers() -> None:
    """Give every saved proposal a number (older proposals had none)."""
    with _lock:
        props = _all_proposals()
        missing = sorted([(p.get("created") or "", f, p) for f, p in props if not p.get("number")], key=lambda t: t[0])
        if not missing:
            return
        counters = _load_counters()
        existing = {p.get("number") for _, p in props if p.get("number")}
        types = _client_types()
        for created, f, p in missing:
            try:
                year = dt.datetime.fromisoformat(created).year
            except ValueError:
                year = dt.date.today().year
            code = p.get("client", {}).get("client_type_code") or types.get(p.get("client", {}).get("client_type"), {}).get("code") or "XX"
            p["number"] = _next_new(counters, code, year, existing)
            existing.add(p["number"])
            f.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        _save_counters(counters)


def _client_types() -> dict:
    from .catalog import load
    try:
        return load()["client_types"]
    except Exception:
        return {}


def _number(code: str, revision_of: dict | None, reserve: bool) -> str:
    with _lock:
        ensure_numbers()
        counters = _load_counters()
        existing = {p.get("number") for _, p in _all_proposals() if p.get("number")}
        if revision_of:
            number = _next_revision(counters, base_number(revision_of["number"]), existing)
        else:
            number = _next_new(counters, code, dt.date.today().year, existing)
        if reserve:
            _save_counters(counters)
        return number


def assign_number(code: str, revision_of: dict | None = None) -> str:
    """Reserve the number for a new proposal of the client type with letters *code*,
    or for a revision of *revision_of*."""
    return _number(code, revision_of, reserve=True)


def peek_number(code: str, revision_of: dict | None = None) -> str:
    """The number the next proposal would get (shown in the wizard; not reserved)."""
    return _number(code, revision_of, reserve=False)


def list_proposals() -> list[dict]:
    ensure_numbers()
    rows = []
    for f, p in _all_proposals():
        c = p.get("client", {})
        rows.append({
            "id": p["id"],
            "number": p.get("number", ""),
            "revision_of": (p.get("revision_of") or {}).get("number", ""),
            "created": p.get("created", ""),
            "date": c.get("date", ""),
            "company": c.get("company", ""),
            "contact": " ".join(x for x in (c.get("salutation", ""), c.get("contact_name", "")) if x),
            "opportunity": c.get("opportunity", ""),
            "client_type": c.get("client_type_label", ""),
            "title": c.get("title", ""),
            "currency": c.get("currency", ""),
            "files": sorted(x.name for x in f.parent.iterdir() if x.suffix in (".pptx", ".pdf", ".html")),
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    return rows
