"""Make the browser-tab icon and the footer mark from TGlogo.jpg (repository root).

    python scripts/build_brand.py

Writes static/brand/tg-mark.png (transparent background), favicon.ico (16/32/48 px),
favicon-32.png and apple-touch-icon.png. Run it again if TGlogo.jpg changes.
"""
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "TGlogo.jpg"
OUT = ROOT / "static" / "brand"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGB")
    # the logo sits on a near-white background: find the mark by its distance from the corner colour
    bg = Image.new("RGB", im.size, im.getpixel((5, 5)))
    diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 40 else 0)
    box = diff.getbbox()
    mark = im.crop(box)
    # transparent background: alpha follows how far each pixel is from white
    gray = mark.convert("L")
    alpha = gray.point(lambda v: 0 if v > 235 else (255 if v < 150 else int((235 - v) * 255 / 85)))
    mark = mark.convert("RGBA")
    mark.putalpha(alpha)
    # square canvas with a little breathing room
    side = int(max(mark.size) * 1.12)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
    sq.resize((256, 256), Image.LANCZOS).save(OUT / "tg-mark.png")
    sq.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    sq.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    touch = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    small = sq.resize((150, 150), Image.LANCZOS)
    touch.paste(small, (15, 15), small)
    touch.convert("RGB").save(OUT / "apple-touch-icon.png")
    # report the mark's main colour (used for the footer text)
    data = mark.get_flattened_data() if hasattr(mark, "get_flattened_data") else mark.getdata()
    px = [p for p in data if p[3] > 250]
    avg = tuple(sum(c[i] for c in px) // len(px) for i in range(3))
    print("mark box", box, "colour #%02x%02x%02x" % avg)


if __name__ == "__main__":
    main()
