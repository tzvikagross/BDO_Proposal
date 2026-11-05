"""Engagement-team bios.

Each person is one single-slide PowerPoint file in ``assets/team/<id>.pptx`` (the bio
slide exactly as it should appear in the proposal deck). Next to it:

  * ``<id>.json`` – name, title, contact details and bio text used by the HTML proposal
    and the wizard, plus ``default`` (pre-selected) and ``order`` (sort position).
    Created automatically from the slide text the first time the slide is seen;
    edit it to fine-tune, or delete it to re-read the slide.
  * ``<id>.jpg``  – photo, extracted automatically from the slide.

To add a person: drop a one-slide bio PPTX into assets/team (or upload it from the
"Engagement Team" step of the wizard).
"""
from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part

from .model import ASSETS_DIR

BIO_DIR = ASSETS_DIR / "team"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
LEFT_PANEL = 2_500_000          # EMU – photo / name / contacts column of the bio layout
FIELDS = ("name", "credentials", "title", "focus", "phone", "email", "role", "experience", "default", "order")


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:40] or "bio"


# ---------------------------------------------------------------- reading a bio slide
def _paras(shape):
    return [p.text.replace("\x0b", "\n").strip() for p in shape.text_frame.paragraphs]


def parse_bio_slide(slide) -> dict:
    """Best-effort extraction of the bio fields from a bio slide."""
    info = {"name": "", "credentials": "", "title": "", "focus": "", "phone": "", "email": "",
            "role": "", "experience": []}
    name_block = None
    for sh in slide.shapes:
        if not sh.has_text_frame or not sh.text_frame.text.strip():
            continue
        text = sh.text_frame.text.strip()
        head = text.split("\n")[0].strip().upper()
        if head.startswith("CURRENT ROLE"):
            body = [p for p in _paras(sh)[1:] if p]
            info["role"] = " ".join(body)
        elif head.startswith("RELEVANT EXPERIENCE"):
            info["experience"] = [p for p in _paras(sh)[1:] if p]
        elif "@" in text and len(text) < 80:
            info["email"] = text
        elif re.match(r"^[MT]\s*:", text):
            if text.startswith("M") or not info["phone"]:
                info["phone"] = re.sub(r"^[MT]\s*:\s*", "", text).replace("[", "").replace("]", "")
        elif sh.left is not None and sh.left < LEFT_PANEL and sh.width and sh.width < LEFT_PANEL and not text.isdigit():
            if name_block is None or (sh.height or 0) > (name_block.height or 0):
                name_block = sh
    if name_block is not None:
        lines = [l.strip(" ,") for p in _paras(name_block) for l in p.split("\n") if l.strip(" ,")]
        if lines:
            info["name"] = lines[0]
            rest = lines[1:]
            if rest and re.search(r"C\.?P\.?A|Tax Consultant|Adv\.|CFA|ACCA|MBA|LL\.?B", rest[0], re.I):
                info["credentials"] = rest.pop(0)
            info["title"] = ", ".join(rest[:2])
            info["focus"] = " | ".join(rest[2:])
    if not info["role"]:
        info["role"] = info["title"]
    return info


def extract_photo(slide) -> bytes | None:
    """JPEG bytes of the portrait (top-most large picture in the left column)."""
    from PIL import Image

    pics = [sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE
            and (sh.left or 0) < LEFT_PANEL and (sh.width or 0) > 800_000]
    if not pics:
        return None
    pic = pics[-1]
    try:
        img = Image.open(io.BytesIO(pic.image.blob)).convert("RGB")
    except Exception:
        return None
    # apply the picture's crop, if any
    l, t, r, b = pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom
    if any((l, t, r, b)):
        w, h = img.size
        img = img.crop((int(w * l), int(h * t), int(w * (1 - r)), int(h * (1 - b))))
    img.thumbnail((600, 800))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def refresh_bio(bio_id: str, force: bool = False) -> dict:
    """(Re)build <id>.json / <id>.jpg from <id>.pptx where missing."""
    pptx = BIO_DIR / f"{bio_id}.pptx"
    meta_path, photo_path = BIO_DIR / f"{bio_id}.json", BIO_DIR / f"{bio_id}.jpg"
    slide = None
    if force or not meta_path.exists() or not photo_path.exists():
        slide = Presentation(str(pptx)).slides[0]
    if force or not meta_path.exists():
        meta = parse_bio_slide(slide) | {"default": False, "order": 100}
        if not meta["name"]:
            meta["name"] = bio_id.replace("_", " ").title()
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if force or not photo_path.exists():
        photo = extract_photo(slide)
        if photo:
            photo_path.write_bytes(photo)
    return load_bio(bio_id)


def load_bio(bio_id: str) -> dict:
    meta = json.loads((BIO_DIR / f"{bio_id}.json").read_text(encoding="utf-8"))
    bio = {k: meta.get(k, "" if k not in ("experience", "default", "order") else None) for k in FIELDS}
    bio["experience"] = meta.get("experience") or []
    bio["default"] = bool(meta.get("default"))
    bio["order"] = meta.get("order", 100)
    bio["id"] = bio_id
    bio["has_photo"] = (BIO_DIR / f"{bio_id}.jpg").exists()
    return bio


def list_bios() -> list[dict]:
    bios = []
    for pptx in BIO_DIR.glob("*.pptx"):
        try:
            bios.append(refresh_bio(pptx.stem))
        except Exception as e:  # a broken file must not break the app
            print(f"Skipping bio {pptx.name}: {e}")
    return sorted(bios, key=lambda b: (b["order"], b["name"].lower()))


def get_bios(ids) -> list[dict]:
    by_id = {b["id"]: b for b in list_bios()}
    return [by_id[i] for i in ids if i in by_id]


def default_bio_ids() -> list[str]:
    return [b["id"] for b in list_bios() if b["default"]]


def add_bio_from_upload(data: bytes, filename: str) -> dict:
    """Save an uploaded bio deck. A multi-slide deck is accepted: its first slide is used."""
    prs = Presentation(io.BytesIO(data))
    if not len(prs.slides):
        raise ValueError("The presentation has no slides")
    info = parse_bio_slide(prs.slides[0])
    base = slugify(info["name"] or Path(filename).stem)
    bio_id, n = base, 2
    while (BIO_DIR / f"{bio_id}.pptx").exists():
        bio_id, n = f"{base}_{n}", n + 1
    if len(prs.slides) > 1:
        keep_first_slide(prs)
        buf = io.BytesIO()
        prs.save(buf)
        data = buf.getvalue()
    BIO_DIR.mkdir(parents=True, exist_ok=True)
    (BIO_DIR / f"{bio_id}.pptx").write_bytes(data)
    from .pptx_gen import _fix_content_types
    _fix_content_types(BIO_DIR / f"{bio_id}.pptx")
    return refresh_bio(bio_id, force=True)


def keep_first_slide(prs, index: int = 0):
    """Reduce *prs* to the single slide at *index*, dropping unused layouts/masters
    so the bio file stays small."""
    ids = prs.slides._sldIdLst
    for i, sid in enumerate(list(ids)):
        if i != index:
            prs.part.drop_rel(sid.rId)
            ids.remove(sid)
    used = prs.slides[0].slide_layout.part
    master_ids = prs.part._element.find(f"{{{P_NS}}}sldMasterIdLst")
    for mid in list(master_ids):
        master = prs.part.related_part(mid.get(f"{{{R_NS}}}id"))
        lst = master._element.find(f"{{{P_NS}}}sldLayoutIdLst")
        keep_master = False
        for lid in list(lst):
            rid = lid.get(f"{{{R_NS}}}id")
            if master.related_part(rid) is used:
                keep_master = True
            else:
                master.drop_rel(rid)
                lst.remove(lid)
        if not keep_master:
            prs.part.drop_rel(mid.get(f"{{{R_NS}}}id"))
            master_ids.remove(mid)


# ---------------------------------------------------------------- copying into a deck
def import_bio_slide(prs, bio_id: str):
    """Append the bio slide from assets/team/<id>.pptx to *prs* (with its images)."""
    src = Presentation(str(BIO_DIR / f"{bio_id}.pptx")).slides[0]
    layouts = [l for m in prs.slide_masters for l in m.slide_layouts]
    layout = next((l for l in layouts if l.name == src.slide_layout.name), layouts[0])
    new = prs.slides.add_slide(layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)

    pkg = prs.part.package
    rid_map = {}
    for rel in src.part.rels.values():
        if rel.reltype in (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE):
            continue
        if rel.is_external:
            rid_map[rel.rId] = new.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
            continue
        tp = rel.target_part
        ext = tp.partname.ext
        partname = pkg.next_partname(f"/ppt/media/bio_{bio_id}_%d.{ext}")
        part = Part(partname, tp.content_type, pkg, tp.blob)
        rid_map[rel.rId] = new.part.relate_to(part, rel.reltype)

    src_csld = src._element.find(f"{{{P_NS}}}cSld")
    new_csld = new._element.find(f"{{{P_NS}}}cSld")
    bg = src_csld.find(f"{{{P_NS}}}bg")
    if bg is not None:
        new_csld.insert(0, copy.deepcopy(bg))
    tree = new.shapes._spTree
    for child in src.shapes._spTree:
        if child.tag in (f"{{{P_NS}}}nvGrpSpPr", f"{{{P_NS}}}grpSpPr"):
            continue
        el = copy.deepcopy(child)
        for node in el.iter():
            for attr, val in list(node.attrib.items()):
                if attr.startswith(f"{{{R_NS}}}") and val in rid_map:
                    node.set(attr, rid_map[val])
        tree.append(el)
    # the bio slide title is "ENGAGEMENT TEAM" (older bio slides say "OUR TEAM LEADERS")
    for sh in new.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip().upper() == "OUR TEAM LEADERS":
            runs = sh.text_frame.paragraphs[0].runs
            runs[0].text = "ENGAGEMENT TEAM"
            for r in runs[1:]:
                r.text = ""
    return new
