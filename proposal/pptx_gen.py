"""Generate a proposal PPTX from the BDO template.

The template is kept intact (branding, about-BDO slides); only these parts change:
  * slide 1  – company name, proposal title, date
  * slide 2  – proposal number (top right), contact name, company
  * slide 5  – scope of operations table (removed when no scope was entered)
  * slides 6-12 – replaced with fee slides generated from the selected services,
    built by cloning the template's fee slide / table so the look is identical
  * slides 13-16 – replaced by the selected bio slides from assets/team/<id>.pptx
"""
from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree
from pptx import Presentation

from .bios import import_bio_slide
from .model import TEMPLATE_PPTX

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}


def q(tag: str) -> str:
    pfx, name = tag.split(":")
    return f"{{{NS[pfx]}}}{name}"


# template slide numbers (1-based)
SLIDE_COVER, SLIDE_LETTER, SLIDE_SCOPE = 1, 2, 5
FEE_SLIDES = range(6, 13)          # replaced by generated fee slides
FEE_PROTO_SLIDE = 9                # "Payroll services": title + subtitle + one table + footnote
TEAM_SLIDES = range(13, 17)

# geometry of the fee slide (EMU)
TABLE_X = 621862
TABLE_W = 9026290
TOP_WITH_SUBTITLE = 1791696
TOP_NO_SUBTITLE = 1250000
BOTTOM = 5950000
TABLE_GAP = 300000
LINE_H = 127000          # 10pt line spacing
ROW_PAD = 100000
HEADER_H = 241733
DESC_CHARS = 105         # approx. characters per line in the description column
FEE_CHARS = 38


# ---------------------------------------------------------------- text helpers
def _strip_highlight(el):
    for h in el.iter(q("a:highlight")):
        h.getparent().remove(h)


def _set_run(run, text):
    run.text = text
    _strip_highlight(run._r)


def set_paragraph_lines(p_proto, parent, lines, bullets: bool | None = None):
    """Replace all <a:p> in *parent* (a txBody) with one paragraph per line,
    styled like *p_proto* (its pPr and first run's rPr)."""
    p_proto = copy.deepcopy(p_proto)
    for p in parent.findall(q("a:p")):
        parent.remove(p)
    r_proto = p_proto.find(q("a:r"))
    rpr = None
    if r_proto is not None and r_proto.find(q("a:rPr")) is not None:
        rpr = copy.deepcopy(r_proto.find(q("a:rPr")))
    elif p_proto.find(q("a:endParaRPr")) is not None:
        rpr = copy.deepcopy(p_proto.find(q("a:endParaRPr")))
        rpr.tag = q("a:rPr")
    end = p_proto.find(q("a:endParaRPr"))
    for child in list(p_proto):
        if child.tag != q("a:pPr"):
            p_proto.remove(child)
    if bullets is not None:
        ppr = p_proto.find(q("a:pPr"))
        if ppr is not None:
            if bullets is False:
                for b in ppr.findall(q("a:buChar")) + ppr.findall(q("a:buAutoNum")):
                    if ppr.find(q("a:buNone")) is None:
                        b.addprevious(etree.Element(q("a:buNone")))
                    ppr.remove(b)
                ppr.set("marL", "0")
                ppr.set("indent", "0")
    for line in lines or [""]:
        p = copy.deepcopy(p_proto)
        if line:
            r = etree.SubElement(p, q("a:r"))
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
                _strip_highlight(r)
            t = etree.SubElement(r, q("a:t"))
            t.text = line
        if end is not None:
            p.append(copy.deepcopy(end))
        parent.append(p)


def shape_by_id(slide, shape_id):
    for sh in slide.shapes:
        if sh.shape_id == shape_id:
            return sh
    raise KeyError(shape_id)


def shape_by_text(slide, text):
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip().startswith(text):
            return sh
    return None


# ---------------------------------------------------------------- slide helpers
def duplicate_slide(prs, src):
    """Append a copy of *src* (a slide whose only relationship is its layout)."""
    new = prs.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    tree = new.shapes._spTree
    for child in src.shapes._spTree:
        if child.tag in (q("p:nvGrpSpPr"), q("p:grpSpPr")):
            continue
        tree.append(copy.deepcopy(child))
    return new


def delete_slides(prs, slides):
    sld_ids = prs.slides._sldIdLst
    for s in slides:
        for sid in list(sld_ids):
            if prs.slides.part.related_part(sid.rId) is s.part:
                prs.part.drop_rel(sid.rId)
                sld_ids.remove(sid)


def move_slide(prs, slide, new_index):
    sld_ids = prs.slides._sldIdLst
    for sid in list(sld_ids):
        if prs.part.related_part(sid.rId) is slide.part:
            sld_ids.remove(sid)
            sld_ids.insert(new_index, sid)
            return


def _next_shape_id(slide):
    ids = [int(e.get("id")) for e in slide.shapes._spTree.iter(q("p:cNvPr"))]
    return max(ids + [1]) + 1


# ---------------------------------------------------------------- fee tables
class TableProto:
    """Row prototypes taken from the template's fee table."""

    def __init__(self, graphic_frame):
        self.frame = copy.deepcopy(graphic_frame._element)
        tbl = self.frame.find(".//" + q("a:tbl"))
        rows = tbl.findall(q("a:tr"))
        self.header, self.subheader, self.item = (copy.deepcopy(r) for r in rows[:3])
        for r in rows:
            tbl.remove(r)

    @staticmethod
    def _cells(tr):
        return tr.findall(q("a:tc"))

    def _fill(self, tr, cell_lines, bullets=None):
        for tc, (lines, bul) in zip(self._cells(tr), cell_lines):
            body = tc.find(q("a:txBody"))
            proto = body.find(q("a:p"))
            set_paragraph_lines(proto, body, lines, bul if bullets is None else (bullets if bul else None))
        return tr

    def build(self, group, rows, continued=False):
        frame = copy.deepcopy(self.frame)
        tbl = frame.find(".//" + q("a:tbl"))
        title = group["title"] + (" (cont.)" if continued else "")
        heights = []
        tr = self._fill(copy.deepcopy(self.header), [([group["fee_header"]], None), ([title], None)])
        tr.set("h", str(HEADER_H)); heights.append(HEADER_H); tbl.append(tr)
        for r in rows:
            h = estimate_row_height(r)
            if r["type"] == "subheader":
                tr = self._fill(copy.deepcopy(self.subheader), [([r["note"]] if r.get("note") else [""], None), ([r["text"]], None)])
            else:
                fee_lines = r["fee_text"].split("\n") if r["fee_text"] else [""]
                tr = self._fill(copy.deepcopy(self.item), [(fee_lines, None), (r["description"], True)],
                                bullets=group.get("bullets", True))
            tr.set("h", str(h)); heights.append(h); tbl.append(tr)
        _strip_ext_ids(tbl)
        return frame, sum(heights)


def _strip_ext_ids(tbl):
    # row/column ids must be unique; dropping them is valid and PowerPoint regenerates them
    for tr in tbl.findall(q("a:tr")):
        ext = tr.find(q("a:extLst"))
        if ext is not None:
            tr.remove(ext)


def _lines_needed(text, width):
    return max(1, -(-len(text) // width))


def estimate_row_height(r):
    if r["type"] == "subheader":
        return 202086
    desc = sum(_lines_needed(d, DESC_CHARS) for d in r["description"]) or 1
    fee = sum(_lines_needed(f, FEE_CHARS) for f in (r["fee_text"] or " ").split("\n"))
    return max(desc, fee) * LINE_H + ROW_PAD


def paginate(section, top):
    """Split a section's groups into pages of (group, rows, continued) chunks."""
    avail = BOTTOM - top
    pages, page, used = [], [], 0
    for g in section["groups"]:
        rows, continued = list(g["rows"]), False
        while rows:
            need_gap = TABLE_GAP if page else 0
            take, h = [], HEADER_H
            for r in rows:
                rh = estimate_row_height(r)
                if used + need_gap + h + rh > avail and take:
                    break
                take.append(r); h += rh
            # nothing fits on this page except a lone header (or a lone sub-header): new page
            fits = used + need_gap + h <= avail
            only_sub = all(r["type"] == "subheader" for r in take)
            if page and (not fits or only_sub):
                pages.append(page); page, used = [], 0
                continue
            # don't leave a sub-header orphaned at the bottom of a page
            if len(take) < len(rows) and take and take[-1]["type"] == "subheader" and len(take) > 1:
                take.pop(); h -= estimate_row_height({"type": "subheader"})
            page.append((g, take, continued))
            used += need_gap + h
            rows = rows[len(take):]
            if rows:
                pages.append(page); page, used, continued = [], 0, True
    if page:
        pages.append(page)
    return pages


def build_fee_slides(prs, proto_slide, proposal):
    shapes = {sh.shape_id: sh for sh in proto_slide.shapes}
    table_frame = next(sh for sh in proto_slide.shapes if sh.has_table)
    tproto = TableProto(table_frame)
    new_slides = []
    for section in proposal["sections"]:
        top = TOP_WITH_SUBTITLE if section["title"] else TOP_NO_SUBTITLE
        pages = paginate(section, top)
        for pi, page in enumerate(pages):
            s = duplicate_slide(prs, proto_slide)
            title = shape_by_text(s, "PROPOSED SERVICES")
            subtitle = shape_by_text(s, "Payroll services")
            foot = shape_by_text(s, "***")
            if subtitle is not None:
                if section["title"]:
                    sub = section["title"] + (" (cont.)" if pi else "")
                    _set_run(subtitle.text_frame.paragraphs[0].runs[0], sub)
                else:
                    subtitle._element.getparent().remove(subtitle._element)
            if foot is not None:
                body = foot.text_frame._txBody
                set_paragraph_lines(body.find(q("a:p")), body, section["footnote_lines"])
            for sh in list(s.shapes):
                if sh.has_table:
                    sh._element.getparent().remove(sh._element)
            y = top
            for gi, (g, rows, cont) in enumerate(page):
                frame, h = tproto.build(g, rows, cont)
                nid = _next_shape_id(s)
                cnv = frame.find(".//" + q("p:cNvPr"))
                cnv.set("id", str(nid)); cnv.set("name", f"Fee table {nid}")
                for e in cnv.findall(q("a:extLst")):
                    cnv.remove(e)
                off = frame.find(q("p:xfrm")).find(q("a:off"))
                ext = frame.find(q("p:xfrm")).find(q("a:ext"))
                off.set("x", str(TABLE_X)); off.set("y", str(y))
                ext.set("cx", str(TABLE_W)); ext.set("cy", str(h))
                # keep z-order sane: insert before the footnote
                s.shapes._spTree.append(frame)
                y += h + TABLE_GAP
            new_slides.append(s)
    return new_slides


# ---------------------------------------------------------------- main
def fill_cover(slide, p):
    c = p["client"]
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text.strip()
        runs = sh.text_frame.paragraphs[0].runs
        if t == "COMPANY NAME":
            _set_run(runs[0], c["company"])
        elif t.startswith("Fund Administration Services"):
            _set_run(runs[0], c["title"])
            for r in runs[1:]:
                r.text = ""
        elif t == "October 2026":
            _set_run(runs[0], c["date_display"])


NUMBER_BOX_W = 1150000        # EMU – wide enough for e.g. "LF26-0001-R12" at 9pt
NUMBER_LABEL_W = 1300000


def fill_letter(slide, p):
    c = p["client"]
    number = p.get("number") or c.get("opportunity", "")
    label = box = None
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        paras = sh.text_frame.paragraphs
        t = sh.text_frame.text.strip()
        if t == "000000":
            box = sh
            _set_run(paras[0].runs[0], number)
        elif t.startswith("Opportunity number"):
            label = sh
            _set_run(paras[0].runs[0], "Proposal number:")
            for r in paras[0].runs[1:]:
                r.text = ""
        elif t.startswith("Dear"):
            r = paras[1].runs
            _set_run(r[0], (c["salutation"] + " ") if c["salutation"] else "")
            _set_run(r[2], c["contact_name"])
            r = paras[2].runs
            _set_run(r[2], c["company"])
    if box is not None:
        # widen the red box to the left (keeping its right edge) so the whole number fits
        right = box.left + box.width
        box.width = NUMBER_BOX_W
        box.left = right - NUMBER_BOX_W
        if label is not None:
            # one line, right-aligned, vertically centred on the box
            label.width = NUMBER_LABEL_W
            label.left = box.left - NUMBER_LABEL_W - 40000
            label.top = box.top + (box.height - label.height) // 2
            body = label.text_frame._txBody.find(q("a:bodyPr"))
            body.set("wrap", "none")
            body.set("anchor", "ctr")
            ppr = label.text_frame.paragraphs[0]._p.get_or_add_pPr()
            ppr.set("algn", "r")


def fill_scope(slide, p):
    table = next(sh for sh in slide.shapes if sh.has_table)
    tbl = table._element.find(".//" + q("a:tbl"))
    rows = tbl.findall(q("a:tr"))
    header, proto = rows[0], rows[1]
    hdr_cells = header.findall(q("a:tc"))
    body = hdr_cells[1].find(q("a:txBody"))
    set_paragraph_lines(body.find(q("a:p")), body, ["Scope of operations"])
    for r in rows[1:]:
        tbl.remove(r)
    for item in p["scope"]:
        tr = copy.deepcopy(proto)
        for tc, text in zip(tr.findall(q("a:tc")), [item["value"], item["label"]]):
            b = tc.find(q("a:txBody"))
            set_paragraph_lines(b.find(q("a:p")), b, [text])
        tbl.append(tr)
    _strip_ext_ids(tbl)


def _slide_index(prs, slide):
    for i, s in enumerate(prs.slides):
        if s.part is slide.part:
            return i
    return len(prs.slides)


def _renumber_bio_slides(prs, bio_slides):
    """Bio slides carry a hard-coded page number text box; update it to the real position."""
    for s in bio_slides:
        n = _slide_index(prs, s) + 1
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip().isdigit() and sh.top and sh.top > 6_000_000:
                runs = sh.text_frame.paragraphs[0].runs
                if runs:
                    runs[0].text = str(n)
                    for r in runs[1:]:
                        r.text = ""


def make_left_to_right(prs) -> int:
    """Switch every slide, layout and master to left-to-right text.

    The template was authored with right-to-left paragraph and table settings. With
    English text that makes LibreOffice (and PowerPoint) reorder words and numbers,
    e.g. '4,500 Annual' comes out as 'Annual 4,500' in the PDF. Removing the rtl flags
    gives normal left-to-right paragraphs and tables.

    A right-to-left table shows its first column on the right (the fees, in the fee
    tables). So that tables keep the layout they had in the template, the columns of
    every table that loses its rtl flag are reversed.
    Returns the number of attributes changed."""
    changed = 0
    to_mirror = []
    parts = list(prs.slides) + list(prs.slide_layouts) + list(prs.slide_masters)
    parts += [l for m in prs.slide_masters for l in m.slide_layouts]
    seen = set()
    for part in parts:
        el = part._element
        if id(el) in seen:
            continue
        seen.add(id(el))
        for node in el.iter():
            tag = node.tag
            if not isinstance(tag, str):
                continue
            local = tag.rsplit("}", 1)[-1]
            if node.get("rtl") == "1" and (local == "pPr" or local == "tblPr" or local.endswith("pPr")):
                del node.attrib["rtl"]
                changed += 1
                if local == "tblPr":
                    to_mirror.append(node.getparent())
            if local == "bodyPr" and node.get("rtlCol") == "1":
                del node.attrib["rtlCol"]
                changed += 1
    for tbl in to_mirror:
        mirror_table_columns(tbl)
    return changed


def mirror_table_columns(tbl):
    """Reverse the column order of an <a:tbl> (grid and every row), keeping merged cells
    (gridSpan + hMerge) together so the table stays valid."""
    grid = tbl.find(q("a:tblGrid"))
    if grid is not None:
        cols = grid.findall(q("a:gridCol"))
        for c in cols:
            grid.remove(c)
        for c in reversed(cols):
            grid.append(c)
    for tr in tbl.findall(q("a:tr")):
        cells = tr.findall(q("a:tc"))
        groups, i = [], 0
        while i < len(cells):
            span = int(cells[i].get("gridSpan", "1") or 1)
            groups.append(cells[i:i + span])
            i += span
        anchor = cells[-1].getnext() if cells else None   # e.g. the row's extLst stays last
        for c in cells:
            tr.remove(c)
        for g in reversed(groups):
            for c in g:
                if anchor is not None:
                    anchor.addprevious(c)
                else:
                    tr.append(c)


def generate_pptx(proposal: dict, out_path: Path, template: Path = TEMPLATE_PPTX) -> Path:
    prs = Presentation(str(template))
    slides = list(prs.slides)
    tpl = {i + 1: s for i, s in enumerate(slides)}

    fill_cover(tpl[SLIDE_COVER], proposal)
    fill_letter(tpl[SLIDE_LETTER], proposal)
    if proposal["scope"]:
        fill_scope(tpl[SLIDE_SCOPE], proposal)

    fee_slides = build_fee_slides(prs, tpl[FEE_PROTO_SLIDE], proposal)

    to_delete = [tpl[n] for n in FEE_SLIDES]
    if not proposal["scope"]:
        to_delete.append(tpl[SLIDE_SCOPE])
    to_delete += [tpl[n] for n in TEAM_SLIDES]
    bio_slides = [import_bio_slide(prs, m["id"]) for m in proposal["team"]]

    # place generated fee slides right after the scope slide (or after T&C slide 4)
    insert_at = SLIDE_SCOPE if proposal["scope"] else SLIDE_SCOPE - 1
    for i, s in enumerate(fee_slides):
        move_slide(prs, s, insert_at + i)
    delete_slides(prs, to_delete)

    # bios go where the template's team slides were: just before "Services provided..."
    anchor = _slide_index(prs, tpl[TEAM_SLIDES.stop])
    for i, s in enumerate(bio_slides):
        move_slide(prs, s, anchor + i)
    _renumber_bio_slides(prs, bio_slides)
    make_left_to_right(prs)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    _fix_content_types(out_path)
    return out_path


def _fix_content_types(path: Path):
    """python-pptx re-declares the template's .jpg parts as 'image/jpg' (non-standard);
    rewrite them as 'image/jpeg' so strict validators and PowerPoint agree."""
    import os
    import tempfile
    import zipfile

    # Close the temp file's handle before writing and replacing it: Windows cannot
    # rename or delete a file that is still open.
    fd, tmp_name = tempfile.mkstemp(suffix=".pptx", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "[Content_Types].xml":
                    data = data.replace(b'ContentType="image/jpg"', b'ContentType="image/jpeg"')
                    if b'Default Extension="jpg"' not in data:
                        data = data.replace(b"<Default ", b'<Default Extension="jpg" ContentType="image/jpeg"/><Default ', 1)
                zout.writestr(info, data)
        os.replace(tmp, path)          # overwrites the original; works on Windows too
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
