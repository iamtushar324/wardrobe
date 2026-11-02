"""Content-addressed image store.

    media/<sha[:2]>/<sha>/full.jpg|full.png   normalised original (EXIF orientation applied, metadata stripped)
                         lg.webp md.webp sm.webp  resized copies for the UI

The sha is of the normalised full image, so the same picture uploaded twice is stored once.
Photos keep only the capture time from EXIF; GPS and camera details are dropped.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from .config import settings

try:  # HEIC/HEIF from iPhones
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional
    pass

Image.MAX_IMAGE_PIXELS = 60_000_000
SIZES = {"lg": 1600, "md": 800, "sm": 360}
FULL_MAX = 3200


class BadImage(ValueError):
    pass


def folder(sha: str) -> Path:
    return settings.media_dir / sha[:2] / sha


def path(sha: str, size: str = "md") -> Path | None:
    d = folder(sha)
    if size == "full":
        for name in ("full.jpg", "full.png"):
            if (d / name).exists():
                return d / name
        return None
    p = d / f"{size}.webp"
    return p if p.exists() else None


def _taken_at(img: Image.Image) -> float | None:
    try:
        exif = img.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, DateTime
        if raw:
            return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    return None


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alpha = img.convert("RGBA").getchannel("A")
        return alpha.getextrema()[0] < 250
    return False


def save(img: Image.Image, keep_alpha: bool | None = None) -> dict:
    """Store a PIL image; returns {sha, width, height}."""
    alpha = _has_alpha(img) if keep_alpha is None else keep_alpha
    img = img.convert("RGBA" if alpha else "RGB")
    if max(img.size) > FULL_MAX:
        img.thumbnail((FULL_MAX, FULL_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    if alpha:
        img.save(buf, "PNG", optimize=True)
        name = "full.png"
    else:
        img.save(buf, "JPEG", quality=90, optimize=True, progressive=True)
        name = "full.jpg"
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    d = folder(sha)
    if not (d / name).exists():
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(d / name)
        for size, edge in SIZES.items():
            v = img.copy()
            v.thumbnail((edge, edge), Image.LANCZOS)
            vb = io.BytesIO()
            v.save(vb, "WEBP", quality=82, method=4)
            (d / f"{size}.webp").write_bytes(vb.getvalue())
    return {"sha": sha, "width": img.width, "height": img.height}


def ingest(raw: bytes) -> dict:
    """Decode an uploaded file (JPEG/PNG/WEBP/HEIC...), normalise and store it."""
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise BadImage(f"file is larger than {settings.max_upload_mb} MB")
    try:
        img = Image.open(io.BytesIO(raw))
        taken = _taken_at(img)
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception as exc:
        raise BadImage("not an image this server can read") from exc
    info = save(img)
    info["taken_at"] = taken
    return info


def open_full(sha: str) -> Image.Image:
    p = path(sha, "full")
    if p is None:
        raise FileNotFoundError(sha)
    img = Image.open(p)
    img.load()
    return img


def jpeg_bytes(sha: str, edge: int = 1280, quality: int = 85) -> bytes:
    """A JPEG copy for sending to a model (alpha flattened on white)."""
    img = open_full(sha)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def png_bytes(sha: str, edge: int = 1536) -> bytes:
    img = open_full(sha)
    img.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def crop(sha: str, bbox: list[float], pad: float = 0.04) -> dict:
    """Crop a normalised [x0,y0,x1,y1] box (with a little padding) and store it."""
    img = open_full(sha)
    w, h = img.size
    x0, y0, x1, y1 = bbox
    pw, ph = (x1 - x0) * pad, (y1 - y0) * pad
    box = (max(0, int((x0 - pw) * w)), max(0, int((y0 - ph) * h)),
           min(w, int((x1 + pw) * w)), min(h, int((y1 + ph) * h)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        raise BadImage("box too small")
    return save(img.crop(box))


def dhash(sha: str, size: int = 8) -> str:
    """Perceptual difference hash (hex) of an image; similar pictures have a small Hamming distance."""
    img = open_full(sha)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{size * size // 4}x}"


def hamming(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")
