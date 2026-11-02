"""Finishing touches for Studio pictures, done on the server without another AI image call.

* framing: crop around the subject (found with the cut-out model) to a closet card (3:4), a square or a
  tight frame, with a little more room above the head than below the feet;
* cut-out: make the background transparent.

Runs in the background worker (the cut-out model needs a few hundred MB), never in a web request.
"""

from __future__ import annotations

import io
import logging

from PIL import Image

from . import cutout
from .config import settings

log = logging.getLogger("wardrobe.finish")

FRAMES: dict[str, float | None] = {"original": None, "card": 3 / 4, "square": 1.0, "tight": 0.0}


def frame_box(size: tuple[int, int], subject: tuple[int, int, int, int] | None, aspect: float | None,
              allow_pad: bool = False) -> tuple[int, int, int, int]:
    """Crop box (may reach outside the picture only when allow_pad) for a subject and a target shape.

    aspect: width/height, 0 for "whatever shape the subject has", None for no crop.
    """
    W, H = size
    if aspect is None:
        return 0, 0, W, H
    if subject is None:  # nothing found: a plain centred crop to the shape
        subject, allow_pad = (0, 0, W, H), False
    x0, y0, x1, y1 = subject
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    if subject != (0, 0, W, H):
        x0, x1 = x0 - bw * 0.07, x1 + bw * 0.07
        y0, y1 = y0 - bh * 0.06, y1 + bh * 0.035
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if aspect:
        if w / h < aspect:
            w = h * aspect
        else:
            h = w / aspect
    if not allow_pad:
        k = min(1.0, W / w, H / h) if aspect else 1.0
        w, h = (w * k, h * k) if aspect else (min(w, W), min(h, H))
        x0 = min(max(cx - w / 2, 0), W - w)
        y0 = min(max(cy - h / 2, 0), H - h)
    else:
        x0, y0 = cx - w / 2, cy - h / 2
    return round(x0), round(y0), round(x0 + w), round(y0 + h)


def _crop(img: Image.Image, box: tuple[int, int, int, int], fill: tuple[int, ...]) -> Image.Image:
    x0, y0, x1, y1 = box
    if x0 >= 0 and y0 >= 0 and x1 <= img.width and y1 <= img.height:
        return img.crop(box)
    canvas = Image.new(img.mode, (x1 - x0, y1 - y0), fill)
    canvas.paste(img, (-x0, -y0))
    return canvas


def finish(img: Image.Image, crop: str = "original", transparent: bool = False, white_bg: bool = False) -> Image.Image:
    """Apply framing and/or a cut-out. white_bg: the picture has a plain white background (pad with white)."""
    aspect = FRAMES.get(crop)
    img = img.convert("RGB")
    if aspect is None and not transparent:
        return img
    m = None
    if settings.cutouts:
        try:
            m = cutout.clean_mask(img)
        except Exception as exc:  # model missing or broken: fall back to a centred crop
            log.warning("finishing without a subject mask: %s", exc)
    subject = m.point(lambda v: 255 if v > 80 else 0).getbbox() if m is not None else None
    if subject and (subject[2] - subject[0]) * (subject[3] - subject[1]) < 0.02 * img.width * img.height:
        subject = None
    out = img
    if transparent and m is not None:
        out = img.copy()
        out.putalpha(m)
    if aspect is None:
        return out
    pad = out.mode == "RGBA" or white_bg
    box = frame_box(img.size, subject, aspect, allow_pad=pad)
    return _crop(out, box, (0, 0, 0, 0) if out.mode == "RGBA" else (255, 255, 255))


def encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
