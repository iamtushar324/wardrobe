"""Background removal on the CPU with an ONNX segmentation model (the rembg model zoo).

Only onnxruntime + numpy + Pillow are needed (no rembg package). The model is downloaded once
into <data>/models on first use. One session per process; the worker runs one image at a time.
"""

from __future__ import annotations

import logging
import threading
import urllib.request

import numpy as np
from PIL import Image

from . import media
from .config import settings

log = logging.getLogger("wardrobe.cutout")

MODELS = {
    # name: (input size, mean, std)
    "isnet-general-use": (1024, (0.5, 0.5, 0.5), (1.0, 1.0, 1.0)),
    "u2net": (320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    "silueta": (320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    "u2netp": (320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
}
URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/{name}.onnx"

_session = None
_lock = threading.Lock()


def _load():
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is not None:
            return _session
        import onnxruntime as ort

        name = settings.cutout_model if settings.cutout_model in MODELS else "isnet-general-use"
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        path = settings.models_dir / f"{name}.onnx"
        if not path.exists():
            log.info("downloading background-removal model %s", name)
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(URL.format(name=name), tmp)  # noqa: S310 - fixed https URL
            tmp.replace(path)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        _session = (ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"]),
                    MODELS[name])
        return _session


def mask(img: Image.Image) -> Image.Image:
    sess, (size, mean, std) = _load()
    rgb = img.convert("RGB")
    arr = np.asarray(rgb.resize((size, size), Image.LANCZOS), dtype=np.float32)
    arr = arr / max(float(arr.max()), 1e-6)
    arr = (arr - np.array(mean, dtype=np.float32)) / np.array(std, dtype=np.float32)
    inp = arr.transpose(2, 0, 1)[None].astype(np.float32)
    pred = sess.run(None, {sess.get_inputs()[0].name: inp})[0][:, 0, :, :]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    m = Image.fromarray((np.squeeze(pred) * 255).astype("uint8"), mode="L")
    return m.resize(rgb.size, Image.LANCZOS)


def clean_mask(img: Image.Image) -> Image.Image:
    """Foreground mask with a soft edge but without the faint halo pixels."""
    return mask(img).point(lambda v: 0 if v < 24 else (255 if v > 232 else v))


def subject_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Pixel box around the main subject (a person or a garment), or None if nothing stands out."""
    small = img.convert("RGB")
    scale = 1.0
    if max(small.size) > 1024:
        scale = max(small.size) / 1024
        small = small.resize((round(small.width / scale), round(small.height / scale)), Image.LANCZOS)
    box = clean_mask(small).point(lambda v: 255 if v > 80 else 0).getbbox()
    if not box:
        return None
    x0, y0, x1, y1 = (round(v * scale) for v in box)
    if (x1 - x0) * (y1 - y0) < 0.02 * img.width * img.height:
        return None
    return min(x0, img.width), min(y0, img.height), min(x1, img.width), min(y1, img.height)


def cut(img: Image.Image) -> Image.Image:
    """The image with its background made transparent (same size)."""
    rgba = img.convert("RGB").copy()
    rgba.putalpha(clean_mask(img))
    return rgba


def cutout(sha: str) -> dict | None:
    """Remove the background of a stored image; returns the stored RGBA cutout {sha,...} or None."""
    if not settings.cutouts:
        return None
    img = media.open_full(sha).convert("RGB")
    if max(img.size) > 1600:
        img.thumbnail((1600, 1600), Image.LANCZOS)
    m = clean_mask(img)
    bbox = m.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not bbox:
        return None
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / (img.width * img.height)
    if area < 0.02:
        return None
    rgba = img.copy()
    rgba.putalpha(m)
    pad = int(max(img.size) * 0.02)
    box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
    return media.save(rgba.crop(box), keep_alpha=True)
