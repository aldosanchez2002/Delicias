#!/usr/bin/env python3
"""Generate square gallery thumbnails.

The grid shows each photo in a square tile about 271 CSS px wide at most, but the
originals are ~3 MP portraits, so the grid used to pull ~51 MB to draw postage
stamps. These thumbnails are pre-cropped to the same square the CSS would crop to,
at sizes that stay sharp up to a 3x display. The lightbox still loads the
untouched original, so the full-size view keeps every pixel.

Run after adding photos to GalleryPhotos/:
    python3 tools/make-gallery-thumbs.py
"""
from PIL import Image, ImageOps
import os, sys

SRC = "GalleryPhotos"
WIDTHS = [400, 600, 900]
QUALITY = 86

def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, SRC)
    files = sorted((f for f in os.listdir(src) if f.lower().endswith(".jpg")),
                   key=lambda f: int(f.split(".")[0]))
    for w in WIDTHS:
        os.makedirs(os.path.join(src, "thumbs", str(w)), exist_ok=True)

    written = total = 0
    for f in files:
        im = ImageOps.exif_transpose(Image.open(os.path.join(src, f))).convert("RGB")
        for w in WIDTHS:
            out = os.path.join(src, "thumbs", str(w), f)
            # Centre-crop to a square first: object-cover would crop the same way,
            # so the pixels outside it are pure waste on the wire.
            sq = ImageOps.fit(im, (w, w), method=Image.LANCZOS, centering=(0.5, 0.5))
            sq.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            total += os.path.getsize(out)
            written += 1
    print(f"wrote {written} thumbnails for {len(files)} photos, {total/1e6:.2f} MB total")

if __name__ == "__main__":
    sys.exit(main())
