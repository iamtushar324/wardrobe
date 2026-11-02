"""Finishing touches for Studio pictures, done on the server without another AI image call.

* framing: crop around the subject (found with the cut-out model) to a closet card (3:4), a square or a
  tight frame, with a little more room above the head than below the feet. The subject is never cut: when
  the picture is too narrow for the shape the edge is padded (white, transparent, or a soft blur of the
  photo itself);
* cut-out: make the background transparent.

Runs in the background worker (the cut-out model needs a few hundred MB), never in a web request.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageFilter

from . import cutout
from .config import settings

log = logging.getLogger("wardrobe.finish")

FRAMES: dict[str, float | None] = {"original": None, "card": 3 / 4, "square": 1.0, "tight": 0.0}


def _place(center: float, length: float, limit: int) -> float:
    """Start of a span of `length` around `center`: inside [0, limit] when it fits, else centred (padded)."""
    if length <= limit:
        return min(max(center - length / 2, 0), limit - length)
    return center - length / 2


def frame_box(size: tuple[int, int], subject: tuple[int, int, int, int] | None, aspect: float | None,
              allow_pad: bool = True) -> tuple[int, int, int, int]:
    """Crop box for a subject and a target shape. It never cuts into the subject: where the picture is too
    small for the shape, the box reaches outside it (to be padded) unless allow_pad is False.

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
        # a little room around the subject, more above the head than below the feet - except where the
        # photo itself already cuts the subject off (legs out of shot): no margin past that edge
        ex, ey = W * 0.01, H * 0.01
        x0 = x0 - bw * 0.07 if x0 > ex else 0
        x1 = x1 + bw * 0.07 if x1 < W - ex else W
        y0 = y0 - bh * 0.06 if y0 > ey else 0
        y1 = y1 + bh * 0.035 if y1 < H - ey else H
    if not aspect:  # tight: no shape to keep, so the margins simply stop at the picture's edge
        if not allow_pad:
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        return round(x0), round(y0), round(x1), round(y1)
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    if not allow_pad:
        k = min(1.0, W / w, H / h)
        w, h = w * k, h * k
    x0, y0 = _place(cx, w, W), _place(cy, h, H)
    return round(x0), round(y0), round(x0 + w), round(y0 + h)


def _crop(img: Image.Image, box: tuple[int, int, int, int], fill: str) -> Image.Image:
    """Crop; parts of the box outside the picture are filled: "clear", "white" or "blur" (a soft, blurred
    stretch of the picture itself, so a photo keeps its colours instead of getting bars)."""
    x0, y0, x1, y1 = box
    if x0 >= 0 and y0 >= 0 and x1 <= img.width and y1 <= img.height:
        return img.crop(box)
    cw, ch = x1 - x0, y1 - y0
    if fill == "clear":
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    elif fill == "white":
        canvas = Image.new(img.mode, (cw, ch), (255, 255, 255, 255) if img.mode == "RGBA" else (255, 255, 255))
    else:
        scale = max(cw / img.width, ch / img.height)
        small = img.convert("RGB").resize((max(1, round(img.width / 8)), max(1, round(img.height / 8))), Image.BILINEAR)
        bg = small.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
        bg = bg.filter(ImageFilter.GaussianBlur(max(cw, ch) / 40))
        canvas = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2, (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
        canvas = Image.blend(canvas, Image.new("RGB", canvas.size, (245, 243, 239)), 0.25)
        if img.mode == "RGBA":
            canvas = canvas.convert("RGBA")
    canvas.paste(img, (-x0, -y0), img if img.mode == "RGBA" and fill != "clear" else None)
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
    box = frame_box(img.size, subject, aspect, allow_pad=out.mode == "RGBA" or white_bg or aspect > 0)
    return _crop(out, box, "clear" if out.mode == "RGBA" else "white" if white_bg else "blur")


def encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
