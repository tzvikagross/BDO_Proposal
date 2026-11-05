"""Split bio slides out of a deck into assets/team/<id>.pptx (one slide per file).

    python scripts/extract_bios.py template/New_Proposal_Format.pptx 13 14 15 16
    python scripts/extract_bios.py new_bios.pptx 1 2 --default        # mark as pre-selected

The id is taken from the person's name on the slide. The matching <id>.json and <id>.jpg
are generated from the slide; edit the JSON afterwards if the text needs tidying.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pptx import Presentation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proposal.pptx_gen import _fix_content_types as fix_content_types  # noqa: E402
from proposal.bios import BIO_DIR, keep_first_slide, parse_bio_slide, refresh_bio, slugify  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("slides", nargs="+", type=int, help="1-based slide numbers")
    ap.add_argument("--default", action="store_true", help="pre-select these bios in the wizard")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    a = ap.parse_args()
    BIO_DIR.mkdir(parents=True, exist_ok=True)
    for n in a.slides:
        prs = Presentation(a.deck)
        info = parse_bio_slide(prs.slides[n - 1])
        bio_id = slugify(info["name"].split()[0] if info["name"] else f"bio_{n}")
        out = BIO_DIR / f"{bio_id}.pptx"
        if out.exists() and not a.force:
            print(f"skip {out.name} (exists; use --force)")
            continue
        keep_first_slide(prs, n - 1)
        prs.save(str(out))
        fix_content_types(out)
        for ext in (".json", ".jpg"):
            (BIO_DIR / f"{bio_id}{ext}").unlink(missing_ok=True)
        bio = refresh_bio(bio_id)
        if a.default:
            import json
            meta = json.loads((BIO_DIR / f"{bio_id}.json").read_text(encoding="utf-8"))
            meta["default"] = True
            (BIO_DIR / f"{bio_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"slide {n} -> {out.relative_to(BIO_DIR.parent.parent)}  ({bio['name']}, {out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
