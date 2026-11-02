"""Dominant colours from the actual pixels (k-means in Lab space, snapped to the named palette)."""

from __future__ import annotations

import numpy as np

from . import media
from .taxonomy import PALETTE


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


_NAMES = list(PALETTE)
_PAL_LAB = _srgb_to_lab(np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in PALETTE.values()], dtype=float))


def nearest(rgb: tuple[int, int, int]) -> str:
    lab = _srgb_to_lab(np.array([rgb], dtype=float))[0]
    d = np.linalg.norm(_PAL_LAB - lab, axis=1)
    return _NAMES[int(np.argmin(d))]


def _pixels(sha: str) -> np.ndarray:
    img = media.open_full(sha)
    img.thumbnail((160, 160))
    if img.mode == "RGBA":
        arr = np.asarray(img, dtype=float).reshape(-1, 4)
        arr = arr[arr[:, 3] > 200][:, :3]
    else:
        arr = np.asarray(img.convert("RGB"), dtype=float)
        h, w = arr.shape[:2]  # no mask: use the middle, where the garment usually is
        arr = arr[int(h * 0.2):int(h * 0.8), int(w * 0.2):int(w * 0.8)].reshape(-1, 3)
    return arr


def dominant(sha: str, k: int = 4, min_share: float = 0.08) -> list[dict]:
    px = _pixels(sha)
    if len(px) < 30:
        return []
    lab = _srgb_to_lab(px)
    rng = np.random.default_rng(7)
    centers = lab[rng.choice(len(lab), size=min(k, len(lab)), replace=False)]
    for _ in range(10):
        labels = np.argmin(((lab[:, None, :] - centers[None, :, :]) ** 2).sum(-1), axis=1)
        new = np.array([lab[labels == i].mean(0) if np.any(labels == i) else centers[i] for i in range(len(centers))])
        if np.allclose(new, centers, atol=0.5):
            break
        centers = new
    out: dict[str, dict] = {}
    for i in range(len(centers)):
        mask = labels == i
        share = float(mask.mean())
        if share == 0:
            continue
        rgb = px[mask].mean(0)
        name = _NAMES[int(np.argmin(np.linalg.norm(_PAL_LAB - centers[i], axis=1)))]
        hexv = "#%02x%02x%02x" % tuple(int(round(v)) for v in rgb)
        if name in out:
            out[name]["share"] += share
        else:
            out[name] = {"name": name, "hex": hexv, "share": share}
    res = sorted((c for c in out.values() if c["share"] >= min_share), key=lambda c: -c["share"])
    for c in res:
        c["share"] = round(c["share"], 3)
    return res[:3]
