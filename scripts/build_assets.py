"""Extract the images used by the HTML proposal from the PPTX template.

Run once after changing the template (requires LibreOffice):
    python scripts/build_assets.py
Writes assets/cover.jpg, assets/logo.png and assets/about/slide-NN.jpg
(Team photos are extracted from the bio slides in assets/team – see proposal/bios.py.)
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from proposal.model import ASSETS_DIR, TEMPLATE_PPTX, settings  # noqa: E402
from proposal.pdf_convert import pptx_to_pdf  # noqa: E402

SLIDE_W_EMU = 12192000
RENDER_W = 2400

LOGO = (11090518, 301521, 850523, 326867)


def crop(img: Image.Image, rect, pad=0):
    s = img.width / SLIDE_W_EMU
    x, y, w, h = rect
    return img.crop((int(x * s) - pad, int(y * s) - pad, int((x + w) * s) + pad, int((y + h) * s) + pad))


def main():
    (ASSETS_DIR / "about").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TEMPLATE_PPTX) as z:
        (ASSETS_DIR / "cover.jpg").write_bytes(z.read("ppt/media/image2.jpeg"))
    with tempfile.TemporaryDirectory() as td:
        pdf = pptx_to_pdf(TEMPLATE_PPTX, Path(td))
        doc = pdfium.PdfDocument(str(pdf))

        def render(n):  # 1-based
            page = doc[n - 1]
            return page.render(scale=RENDER_W / page.get_width()).to_pil().convert("RGB")

        cover = render(1)
        crop(cover, LOGO, pad=6).save(ASSETS_DIR / "logo.png")
        for n in settings()["about_slides"]:
            img = render(n)
            img.thumbnail((1600, 1600))
            img.save(ASSETS_DIR / "about" / f"slide-{n:02d}.jpg", quality=78, optimize=True)
    print(json.dumps(sorted(str(p.relative_to(ROOT)) for p in ASSETS_DIR.rglob("*.*")), indent=1))


if __name__ == "__main__":
    main()
