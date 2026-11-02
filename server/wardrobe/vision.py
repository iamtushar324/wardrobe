"""Vision and image models through OpenRouter (OpenAI-compatible chat API).

* analyze(): what kind of photo is this, which garments are in it (with boxes), tag/receipt text.
* group(): which crops across a batch show the same physical item, and which existing item they are.
* assign(): which item each tag photo / receipt line belongs to.
* generate_image(): image model with reference images (paid fallback engine for the Studio).

Prompt ideas for multi-garment detection were adapted from tandpfun/wardrobe (MIT).
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from . import db, media
from .config import settings
from .taxonomy import CATEGORIES, MATERIALS, OCCASIONS, PALETTE, PATTERNS, SEASONS


class VisionError(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.analysis and settings.openrouter_key)


def _headers() -> dict:
    key = settings.openrouter_key
    if not key:
        raise VisionError("vision is not configured (no OpenRouter key)")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": settings.public_url, "X-Title": settings.site_name}


def _img_part(sha: str, edge: int = 1280) -> dict:
    b64 = base64.b64encode(media.jpeg_bytes(sha, edge)).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise VisionError("model did not return JSON")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise VisionError("model returned malformed JSON") from exc


def _chat(owner_id: str, content: list[dict], max_tokens: int = 4000) -> dict:
    if db.usage_today(None, "vision")["count"] >= settings.daily_vision_cap:
        raise VisionError(f"daily vision cap of {settings.daily_vision_cap} calls reached")
    body = {"model": settings.vision_model, "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"}, "temperature": 0.1, "max_tokens": max_tokens,
            "usage": {"include": True}}
    with httpx.Client(timeout=180) as client:
        res = client.post(f"{settings.openrouter_url}/chat/completions", headers=_headers(), json=body)
    if res.status_code != 200:
        raise VisionError(f"vision model error {res.status_code}: {res.text[:300]}")
    data = res.json()
    cost = (data.get("usage") or {}).get("cost")
    with db.tx():
        db.bump_usage(owner_id, "vision", cost)
    msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if isinstance(msg, list):
        msg = "".join(p.get("text", "") for p in msg if isinstance(p, dict))
    return _parse_json(msg)


ANALYZE = """You are cataloguing a personal wardrobe from ONE photo. Reply with JSON only.

1. Decide the photo "kind":
   - "flat_lay": several items laid out together (on a bed, floor, table)
   - "product": a single item on its own (on a hanger, laid flat, on a surface, a shop photo)
   - "worn": a person wearing clothes (selfie, mirror photo, full-body or half-body shot)
   - "tag": close-up of a clothing label, brand/price tag, size or care label
   - "receipt": a bill, invoice, order confirmation or shopping-app screenshot
   - "detail": a close-up of fabric, print or part of an item
   - "other": none of the above
2. List every distinct wearable item that is clearly visible: clothing, footwear, bags, accessories.
   In "worn" photos list only what the main person wears. Never list bedding, furniture or hangers.
   For each item give:
   - "box_2d": [ymin, xmin, ymax, xmax] normalised 0-1000, tight around the item
   - "name": short and specific, e.g. "Navy linen shirt", "White leather sneakers"
   - "category": one of %(categories)s
   - "subcategory": e.g. %(subcats)s
   - "colors": 1-3 names from %(colors)s, most dominant first
   - "pattern": one of %(patterns)s
   - "material": best guess from %(materials)s, or null
   - "seasons": subset of %(seasons)s
   - "occasions": subset of %(occasions)s
   - "styles": 1-3 short style words (e.g. "minimal", "streetwear", "smart casual")
   - "formality": 1 (very casual) to 5 (black tie)
   - "brand": only if a logo or label is legible, else null
   - "confidence": 0-1
3. If the photo is a tag/label, fill "tag": {"brand", "size", "size_system" (IN/UK/US/EU/intl), "materials",
   "care", "mrp" (number: printed MRP / original price), "price" (number: sale price if a separate one is
   printed), "currency" (ISO code; INR for ₹ or Rs), "style_code", "made_in", "text" (all legible text)}.
   Use null for anything not printed. Never guess a price.
4. If it is a receipt/order, fill "receipt": {"store", "date" (YYYY-MM-DD), "currency", "total",
   "lines": [{"description", "price", "mrp"}]}. Only what is printed.

Shape: {"kind": "...", "people": <people visible>, "items": [...], "tag": null|{...}, "receipt": null|{...},
"summary": "one short line"}
%(hint)s"""


def analyze(owner_id: str, sha: str, hint: str = "") -> dict:
    subcats = ", ".join(s for subs in CATEGORIES.values() for s in subs[:3])
    prompt = ANALYZE % {
        "categories": json.dumps(list(CATEGORIES)), "subcats": subcats, "colors": json.dumps(list(PALETTE)),
        "patterns": json.dumps(PATTERNS), "materials": json.dumps(MATERIALS), "seasons": json.dumps(SEASONS),
        "occasions": json.dumps(OCCASIONS),
        "hint": f"\nContext from the owner (may help, may not apply to this photo): {hint}" if hint else "",
    }
    out = _chat(owner_id, [{"type": "text", "text": prompt}, _img_part(sha, 1536)])
    items = []
    for it in out.get("items") or []:
        box = it.get("box_2d") or it.get("box")
        if not (isinstance(box, list) and len(box) == 4):
            continue
        try:
            y0, x0, y1, x1 = [max(0.0, min(1.0, float(v) / 1000.0)) for v in box]
        except (TypeError, ValueError):
            continue
        if x1 - x0 < 0.02 or y1 - y0 < 0.02:
            continue
        it["bbox"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
        it.pop("box_2d", None)
        items.append(it)
    out["items"] = items
    return out


GROUP = """These are crops of wardrobe items from one upload batch, plus some items already in the wardrobe.
Decide which crops show the SAME physical item (the same garment, not merely a similar one). A garment laid
flat and the same garment worn by a person are the same item when colour, pattern, cut and details match.
Then say whether each group is one of the existing items (only when you are confident it is the very same item).

Reply with JSON only: {"groups": [{"crops": ["C1", "C4"], "existing": "E2" or null, "confidence": 0-1,
"reason": "short"}]}. Every crop id must appear in exactly one group. Do not invent ids."""


def group(owner_id: str, crops: list[tuple[str, str, str]], existing: list[tuple[str, str, str]]) -> list[dict]:
    """crops/existing: [(id, sha, label)]. Returns groups [{crops, existing, confidence, reason}]."""
    content: list[dict] = [{"type": "text", "text": GROUP}]
    for cid, sha, label in crops:
        content += [{"type": "text", "text": f"Crop {cid}: {label}"}, _img_part(sha, 384)]
    for eid, sha, label in existing:
        content += [{"type": "text", "text": f"Existing item {eid}: {label}"}, _img_part(sha, 384)]
    out = _chat(owner_id, content, 3000)
    known_c = {c[0] for c in crops}
    known_e = {e[0] for e in existing}
    seen: set[str] = set()
    groups = []
    for g in out.get("groups") or []:
        ids = [c for c in (g.get("crops") or []) if c in known_c and c not in seen]
        if not ids:
            continue
        seen.update(ids)
        ex = g.get("existing") if g.get("existing") in known_e else None
        groups.append({"crops": ids, "existing": ex, "confidence": float(g.get("confidence") or 0.5),
                       "reason": (g.get("reason") or "")[:200]})
    for cid in known_c - seen:  # anything the model forgot becomes its own group
        groups.append({"crops": [cid], "existing": None, "confidence": 0.5, "reason": "ungrouped"})
    return groups


ASSIGN = """Match clothing tags/labels and receipt lines to the items they belong to.
Items are shown as G1, G2, ... Tags are T1, T2, ... (photos of labels). Receipt lines are listed as text.
Use brand, colour, material, size and description. Only match when it is reasonably clear.

Reply with JSON only: {"tags": [{"tag": "T1", "item": "G2" or null, "confidence": 0-1}],
"lines": [{"receipt": "R1", "line": 0, "item": "G3" or null, "confidence": 0-1}]}"""


def assign(owner_id: str, items: list[tuple[str, str, str]], tags: list[tuple[str, str, str]],
           receipts: list[tuple[str, dict]]) -> dict:
    content: list[dict] = [{"type": "text", "text": ASSIGN}]
    for gid, sha, label in items:
        content += [{"type": "text", "text": f"Item {gid}: {label}"}, _img_part(sha, 320)]
    for tid, sha, label in tags:
        content += [{"type": "text", "text": f"Tag {tid}: {label}"}, _img_part(sha, 768)]
    for rid, rec in receipts:
        lines = "\n".join(f"  line {i}: {ln.get('description')} — {ln.get('price')}" for i, ln in
                          enumerate(rec.get("lines") or []))
        content.append({"type": "text", "text": f"Receipt {rid} from {rec.get('store')}:\n{lines}"})
    return _chat(owner_id, content, 2000)


def generate_image(owner_id: str, prompt: str, refs: list[str], aspect: str = "3:4") -> tuple[bytes, dict]:
    """Paid fallback engine: OpenRouter image model with reference images. Returns (png/jpeg bytes, meta)."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for sha in refs:
        content.append(_img_part(sha, 1280))
    body = {"model": settings.image_model, "modalities": ["image", "text"],
            "messages": [{"role": "user", "content": content}],
            "image_config": {"aspect_ratio": aspect}, "usage": {"include": True}}
    with httpx.Client(timeout=300) as client:
        res = client.post(f"{settings.openrouter_url}/chat/completions", headers=_headers(), json=body)
    if res.status_code != 200:
        raise VisionError(f"image model error {res.status_code}: {res.text[:300]}")
    data = res.json()
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    images = msg.get("images") or []
    if not images:
        raise VisionError("the image model returned no image" + (f": {str(msg.get('content'))[:200]}" if msg.get("content") else ""))
    url = images[0]["image_url"]["url"]
    raw = base64.b64decode(url.split(",", 1)[1])
    cost = (data.get("usage") or {}).get("cost")
    return raw, {"model": settings.image_model, "cost_usd": cost}


def describe(it: dict[str, Any]) -> str:
    bits = [", ".join(c["name"] if isinstance(c, dict) else str(c) for c in (it.get("colors") or [])[:2]),
            it.get("pattern") if it.get("pattern") not in (None, "solid") else None,
            it.get("material"), it.get("name") or it.get("subcategory") or it.get("category")]
    return " ".join(b for b in bits if b)
