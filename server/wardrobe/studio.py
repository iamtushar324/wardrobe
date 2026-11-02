"""Studio: AI pictures of your wardrobe, generated through a queue you control.

Engines
* chatgpt    - your ChatGPT subscription. A host worker (worker/wardrobe-codex-worker.py) runs the Codex CLI's
               built-in image tool with your own ChatGPT login, pulls jobs from this queue and uploads results.
* openrouter - optional paid fallback through OpenRouter (off by default, own daily cap).

Every job is one picture: a template (e.g. "Me · lifestyle") applied to one item, or to several items for
outfit templates. Person templates use one of your chosen model photos as the identity reference.
Owners can pause the queue, cancel or reprioritise jobs, cap daily usage and turn on auto mode, which queues
the selected templates for every new item.

The same module also runs "Sign in with ChatGPT": the worker performs the Codex device-code login, the
browser shows the code, and the verified ChatGPT email signs the person in (if invited) and connects
their account for image generation.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from fastapi import HTTPException

from . import catalog, db, finish, media, vision
from .config import settings
from .jobs import Retry, enqueue as enqueue_job, handler

log = logging.getLogger("wardrobe.studio")

OFFLINE_AFTER = 90           # seconds without a worker heartbeat = offline
CLAIM_TTL = 900              # a claimed job not finished within this goes back to the queue
MAX_ATTEMPTS = 3
LOGIN_TTL = 15 * 60

SETTINGS_BY_OCCASION = {
    "office": "a bright modern office or a city street on a workday morning",
    "formal": "an elegant hotel lobby with warm light",
    "party": "a stylish evening party with soft warm lights",
    "wedding": "an Indian wedding venue decorated with marigolds and fairy lights",
    "festive": "a festive Indian celebration with diyas and marigold decor",
    "ethnic": "the courtyard of a heritage haveli",
    "sport": "a modern gym or an early-morning running track",
    "travel": "a sunlit airport terminal or a scenic travel viewpoint",
    "lounge": "a cosy, tidy living room",
    "date": "a candle-lit rooftop restaurant at dusk",
    "outdoor": "a green hiking trail",
    "casual": "a sunny café terrace or a leafy city street",
}
SEASON_LIGHT = {"winter": "crisp winter light", "monsoon": "soft overcast monsoon light and lush greenery",
                "summer": "bright summer daylight"}

TEMPLATES: list[dict] = [
    {"id": "white-bg-cloth-only", "name": "Product · white", "icon": "shirt", "needs_person": False, "multi_item": False,
     "aspect": "square", "group": "Product",
     "description": "The piece alone on pure white, like a shop listing. Great as the gallery cover.",
     "prompt": "A clean e-commerce product photo of the {item} on its own: front view, upright the way it is worn (top of "
               "the garment at the top of the frame), centred, neatly shaped, on a pure "
               "white (#FFFFFF) seamless background with a very soft natural shadow. No person, no mannequin, no hanger, "
               "no props, no text."},
    {"id": "me-lifestyle", "name": "Me · lifestyle", "icon": "sun", "needs_person": True, "multi_item": False,
     "aspect": "portrait", "group": "Me",
     "description": "You wearing the piece in an everyday setting that suits it.",
     "prompt": "A candid, natural lifestyle photo of the person wearing the {item}, in {setting}, {light}. Style the rest of "
               "the outfit with simple, neutral pieces that complement it. Shot on a full-frame camera, 50mm lens, shallow "
               "depth of field, relaxed natural pose, looking effortless."},
    {"id": "me-white-bg", "name": "Me · studio white", "icon": "user-square", "needs_person": True, "multi_item": False,
     "aspect": "portrait", "group": "Me",
     "description": "Full-body lookbook shot of you in the piece on a white studio background.",
     "prompt": "A full-body fashion lookbook photo of the person wearing the {item}, standing relaxed and facing the camera "
               "on a seamless pure white studio background, soft even lighting, sharp focus, e-commerce model style. Keep "
               "the rest of the outfit simple and neutral."},
    {"id": "ghost-mannequin", "name": "Product · ghost mannequin", "icon": "box", "needs_person": False,
     "multi_item": False, "aspect": "square", "group": "Product",
     "description": "Invisible-mannequin 3D shape on white, showing how it fits.",
     "prompt": "A professional ghost-mannequin (invisible mannequin) product photo of the {item}, showing its natural 3D "
               "shape and fit, front view, on a pure white background, studio lighting, no visible mannequin or person."},
    {"id": "flat-lay", "name": "Product · flat lay", "icon": "layout-grid", "needs_person": False, "multi_item": False,
     "aspect": "square", "group": "Product",
     "description": "Top-down styled flat lay on linen with soft window light.",
     "prompt": "A top-down styled flat lay photo of the {item}, neatly arranged on a light natural linen surface with soft "
               "window light and gentle shadows, minimal tasteful props, editorial catalogue style."},
    {"id": "on-hanger", "name": "Product · on hanger", "icon": "shirt", "needs_person": False, "multi_item": False,
     "aspect": "portrait", "group": "Product",
     "description": "Hanging on a wooden hanger against a warm wall.",
     "prompt": "A photo of the {item} hanging on a wooden hanger against a warm off-white plaster wall, soft daylight, "
               "minimal and calm, shot straight on."},
    {"id": "me-occasion", "name": "Me · at the occasion", "icon": "party-popper", "needs_person": True,
     "multi_item": False, "aspect": "portrait", "group": "Me",
     "description": "You wearing it at the event it's made for (wedding, office, party...).",
     "prompt": "A photo of the person wearing the {item} at {occasion_scene}, {light}. They look natural and confident, "
               "candid moment, realistic event photography, the rest of the outfit suits the occasion."},
    {"id": "me-mirror-selfie", "name": "Me · mirror selfie", "icon": "smartphone", "needs_person": True,
     "multi_item": False, "aspect": "portrait", "group": "Me",
     "description": "Casual phone mirror selfie, like you'd send a friend.",
     "prompt": "A casual mirror selfie of the person wearing the {item}, taken with a phone held at chest height so the face "
               "stays visible, in a tidy, well-lit bedroom, natural phone-camera look."},
    {"id": "me-editorial", "name": "Me · editorial", "icon": "aperture", "needs_person": True, "multi_item": False,
     "aspect": "portrait", "group": "Me",
     "description": "A magazine-style portrait with dramatic light.",
     "prompt": "A high-fashion editorial portrait of the person wearing the {item}, dramatic directional light, minimal "
               "backdrop with a subtle colour that complements the piece, confident pose, magazine quality."},
    {"id": "me-outfit", "name": "Me · full outfit", "icon": "users", "needs_person": True, "multi_item": True,
     "aspect": "portrait", "group": "Outfits",
     "description": "You wearing several pieces together as one outfit.",
     "prompt": "A full-body photo of the person wearing all of these together as one outfit: {items}. Natural pose, "
               "{setting}, {light}, realistic fashion photography."},
    {"id": "outfit-board", "name": "Outfit board", "icon": "panels-top-left", "needs_person": False, "multi_item": True,
     "aspect": "portrait", "group": "Outfits",
     "description": "A styled mood board of several pieces as one look.",
     "prompt": "A styled outfit board laid out flat on a warm neutral background, showing these items together as one look: "
               "{items}. Clean magazine layout, even soft light, no text."},
    {"id": "detail-closeup", "name": "Detail close-up", "icon": "zoom-in", "needs_person": False, "multi_item": False,
     "aspect": "square", "group": "Product",
     "description": "Macro shot of fabric, print and stitching.",
     "prompt": "A macro close-up photo of the fabric texture, print and stitching of the {item}, raking soft light that "
               "shows the weave, shallow depth of field."},
]
# "Try on" edits one of your own photos: only the chosen clothes change. It has its own page and options,
# so it never shows up among the templates you queue for items or switch to auto.
TRYON = {"id": "tryon", "name": "Try on", "icon": "replace", "needs_person": True, "multi_item": True,
         "aspect": "portrait", "group": "Try on", "tryon": True,
         "description": "One of your own photos with the outfit swapped; everything else stays as it was.",
         "prompt": "Edit image 1 so the person wears {items}."}
TEMPLATE_IDS = {t["id"] for t in TEMPLATES} | {TRYON["id"]}

DEFAULT_PREFS = {
    "paused": False,
    "auto_mode": False,
    "auto_templates": ["white-bg-cloth-only", "me-lifestyle"],
    "model_photo_ids": [],
    "daily_cap": 30,
    "engine": "chatgpt",
    "fallback_openrouter": False,
    "openrouter_daily_cap": 10,
    "min_interval_s": 15,
}

ASPECTS = {"portrait": "3:4", "square": "1:1", "landscape": "4:3"}


# ---------------- prefs & templates ----------------
def prefs(owner_id: str) -> dict:
    u = db.one("SELECT prefs FROM users WHERE id=?", (owner_id,))
    p = (db.loads(u["prefs"], {}) if u else {}).get("studio") or {}
    return {**DEFAULT_PREFS, **p}


def save_prefs(owner_id: str, changes: dict, actor: str) -> dict:
    u = db.one("SELECT prefs FROM users WHERE id=?", (owner_id,))
    allp = db.loads(u["prefs"], {}) if u else {}
    cur = {**DEFAULT_PREFS, **(allp.get("studio") or {})}
    for k, v in changes.items():
        if k not in DEFAULT_PREFS:
            continue
        if k in ("paused", "auto_mode", "fallback_openrouter"):
            cur[k] = bool(v)
        elif k in ("daily_cap", "openrouter_daily_cap", "min_interval_s"):
            cur[k] = max(0, min(int(v), 1000))
        elif k == "engine":
            cur[k] = v if v in ("chatgpt", "openrouter") else "chatgpt"
        elif k == "auto_templates":
            known = {t["id"] for t in templates(owner_id) if not t.get("tryon")}
            cur[k] = [t for t in (v or []) if t in known]
        elif k == "model_photo_ids":
            ids = [i for i in (v or []) if db.one("SELECT 1 FROM photos WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                                                  (i, owner_id))]
            cur[k] = ids[:6]
    allp["studio"] = cur
    with db.tx():
        db.run("UPDATE users SET prefs=? WHERE id=?", (db._enc(allp), owner_id))
        db.audit(actor, "studio_prefs", owner_id, None, changes)
    return cur


def templates(owner_id: str) -> list[dict]:
    custom = [{"id": t["id"], "name": t["name"], "icon": t["icon"] or "sparkles", "needs_person": bool(t["needs_person"]),
               "multi_item": bool(t["multi_item"]), "aspect": t["aspect"], "group": "Custom",
               "description": t["description"] or "", "prompt": t["prompt"], "custom": True}
              for t in db.q("SELECT * FROM gen_templates WHERE owner_id=? ORDER BY created_at", (owner_id,))]
    return [*TEMPLATES, TRYON, *custom]


def template(owner_id: str, tid: str) -> dict:
    t = next((t for t in templates(owner_id) if t["id"] == tid), None)
    if not t:
        raise HTTPException(404, f"unknown template {tid}")
    return t


def save_template(owner_id: str, body: dict, actor: str, tid: str | None = None) -> dict:
    name = (body.get("name") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    if not name or not prompt:
        raise HTTPException(422, "a template needs a name and a prompt")
    row = {"name": name[:60], "description": (body.get("description") or "")[:300], "icon": body.get("icon") or "sparkles",
           "needs_person": bool(body.get("needs_person")), "multi_item": bool(body.get("multi_item")),
           "aspect": body.get("aspect") if body.get("aspect") in ASPECTS else "portrait", "prompt": prompt[:2000]}
    with db.tx():
        if tid:
            if tid in TEMPLATE_IDS or not db.one("SELECT 1 FROM gen_templates WHERE id=? AND owner_id=?", (tid, owner_id)):
                raise HTTPException(404, "only your own templates can be edited")
            db.update("gen_templates", tid, row)
        else:
            tid = db.new_id("tpl")
            db.insert("gen_templates", {"id": tid, "owner_id": owner_id, "created_at": db.now(), **row})
        db.audit(actor, "template_saved", owner_id, tid, {"name": name})
    return template(owner_id, tid)


def delete_template(owner_id: str, tid: str, actor: str) -> None:
    with db.tx():
        if not db.run("DELETE FROM gen_templates WHERE id=? AND owner_id=?", (tid, owner_id)):
            raise HTTPException(404, "template not found")
        db.audit(actor, "template_deleted", owner_id, tid)


# ---------------- prompt building ----------------
def _item_desc(item: dict) -> str:
    cols = [c["name"] for c in db.loads(item.get("colors"), [])][:2]
    bits = [" and ".join(cols) if cols else None,
            item.get("pattern") if item.get("pattern") not in (None, "solid") else None,
            item.get("material"), (item.get("name") or item.get("subcategory") or "garment").lower()]
    desc = " ".join(b for b in bits if b)
    if item.get("brand"):
        desc += f" by {item['brand']}"
    return desc


def _scene(items: list[dict]) -> tuple[str, str, str]:
    occ = next((o for it in items for o in db.loads(it.get("occasions"), []) if o in SETTINGS_BY_OCCASION), "casual")
    season = next((s for it in items for s in db.loads(it.get("seasons"), []) if s in SEASON_LIGHT), "")
    setting = SETTINGS_BY_OCCASION[occ]
    return setting, SEASON_LIGHT.get(season, "flattering natural daylight"), setting


def build_prompt(t: dict, items: list[dict], has_person: bool, extra: str = "") -> str:
    setting, light, occasion_scene = _scene(items)
    descs = [_item_desc(i) for i in items]
    values = {"item": descs[0] if descs else "outfit", "items": "; ".join(descs), "setting": setting, "light": light,
              "occasion_scene": occasion_scene}
    body = t["prompt"]
    for k, v in values.items():  # plain replace: custom prompts may contain other braces
        body = body.replace("{" + k + "}", v)
    n_items = len(items)
    if has_person:
        refs = (f"Reference images: image 1 is the person - keep their face, hair, skin tone, body shape, age and "
                f"likeness exactly. Image{'s' if n_items > 1 else ''} 2{'-' + str(n_items + 1) if n_items > 1 else ''} "
                f"show{'' if n_items > 1 else 's'} the clothing to dress them in - reproduce "
                f"{'each piece' if n_items > 1 else 'it'} faithfully: same colour, pattern, fabric, cut, fit, logos and details.")
    else:
        refs = (f"Reference image{'s' if n_items > 1 else ''}: the attached photo{'s show' if n_items > 1 else ' shows'} the real "
                f"item{'s' if n_items > 1 else ''} - reproduce {'them' if n_items > 1 else 'it'} faithfully: same colour, "
                "pattern, fabric, cut, logos and details. Do not invent new logos or text.")
    aspect = {"portrait": "Vertical 3:4 frame.", "square": "Square 1:1 frame.", "landscape": "Horizontal 4:3 frame."}[t["aspect"]]
    prompt = f"{refs}\n\n{body}\n\nPhotorealistic, high detail. {aspect}"
    if extra:
        prompt += f"\n\nAlso: {extra.strip()[:500]}"
    return prompt


def item_ref_sha(item_id: str) -> str | None:
    """Best real picture of an item for use as a generation reference."""
    links = db.q("""SELECT l.*, p.sha256, p.ai, p.template FROM links l JOIN photos p ON p.id=l.photo_id
                    WHERE l.item_id=? AND p.deleted_at IS NULL""", (item_id,))
    if not links:
        return None

    def rank(l: dict) -> tuple:
        real = 0 if not l["ai"] else 1
        role = {"shows": 0, "detail": 2, "worn": 3, "generated": 4}.get(l["role"], 9)
        return (real, role, 0 if l.get("cutout_sha") else 1)
    best = min((l for l in links if l["role"] not in ("tag", "receipt")), key=rank, default=None)
    if not best:
        return None
    return best.get("cutout_sha") or best.get("crop_sha") or best["sha256"]


# ---------------- try on ----------------
TRYON_DEFAULTS = {
    "background": "keep",   # keep | tidy | studio | blur | scene
    "scene": "",            # where to put them when background == scene
    "keep_rest": True,      # keep the clothes and accessories that are not being swapped
    "light": False,         # even out exposure and white balance
    "smooth": False,        # freshly pressed: no creases or lint on the new clothes
    "crop": "original",     # original | card (3:4) | square | tight  - done on the server after generation
    "transparent": False,   # cut the person out (transparent background) - done on the server
    "cover": False,         # make the result the item's main picture
    "variants": 1,          # how many versions to make (1-3)
    "extra": "",
}
BACKGROUNDS = ("keep", "tidy", "studio", "blur", "scene")
CROPS = ("original", "card", "square", "tight")

SLOT = {"top": "top", "bottom": "trousers or skirt", "outerwear": "outer layer (jacket, over the top)",
        "dress": "outfit (it replaces both the top and the bottom)", "activewear": "matching garment",
        "lounge": "matching garment", "innerwear": "matching garment", "footwear": "shoes", "bag": "bag",
        "ethnic": "matching garment"}


def tryon_options(raw: dict | None) -> dict:
    o = {**TRYON_DEFAULTS}
    raw = raw or {}
    for k in ("keep_rest", "light", "smooth", "transparent", "cover"):
        if k in raw:
            o[k] = bool(raw[k])
    if raw.get("background") in BACKGROUNDS:
        o["background"] = raw["background"]
    if raw.get("crop") in CROPS:
        o["crop"] = raw["crop"]
    o["scene"] = str(raw.get("scene") or "").strip()[:300]
    o["extra"] = str(raw.get("extra") or "").strip()[:600]
    if o["background"] == "scene" and not o["scene"]:
        o["background"] = "keep"
    try:
        o["variants"] = max(1, min(int(raw.get("variants") or 1), 3))
    except (TypeError, ValueError):
        o["variants"] = 1
    return o


def _slot(item: dict) -> str:
    if item.get("category") in ("ethnic", "accessory", "activewear", "lounge", "innerwear") and item.get("subcategory"):
        return item["subcategory"]
    return SLOT.get(item.get("category") or "", item.get("subcategory") or "garment")


def _shape(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "portrait"
    r = height / width
    return "portrait" if r > 1.12 else ("landscape" if r < 0.89 else "square")


def build_tryon_prompt(items: list[dict], o: dict, width: int | None = None, height: int | None = None,
                       with_ref: set[str] | None = None) -> str:
    """with_ref: the items that have a reference picture; they are images 2, 3... in the order given."""
    with_ref = {i["id"] for i in items} if with_ref is None else with_ref
    pieces, n = [], 1
    for it in items:
        if it["id"] in with_ref:
            n += 1
            pieces.append(f"image {n}: {_item_desc(it)} - their new {_slot(it)}")
        else:
            pieces.append(f"(no picture, follow the description) {_item_desc(it)} - their new {_slot(it)}")
    lines = [
        "Edit image 1. It is a real photo of a person. Change ONLY what is described below; everything else must stay "
        "exactly as it is in image 1, as if this were the same photo.",
        f"Dress the person in these clothes: {'; '.join(pieces)}. "
        "Each new piece replaces what they wear in that place now. Reproduce every piece faithfully from its reference "
        "image: same colour, pattern, fabric, cut, length, logos and details. Fit it naturally to their body and pose, "
        "with realistic folds and shadows that match the light in image 1.",
        "Keep every other garment, shoe and accessory they wear exactly as it is." if o["keep_rest"] else
        "Restyle the rest of the outfit with simple pieces that go well with the new clothes.",
        "Do not change their face, expression, hair, skin tone, body shape, pose, hands or anything that makes them "
        "recognisable.",
    ]
    bg = {
        "keep": "Keep the background, the scene and the lighting exactly as they are.",
        "tidy": "Tidy the background: remove clutter, mess and any other people, but keep the same place, perspective "
                "and light.",
        "studio": "Replace the background with a seamless pure white (#FFFFFF) studio backdrop with soft, even light "
                  "and a gentle shadow on the floor.",
        "blur": "Keep the same place, but softly blur the background like a portrait-mode photo so the person stands "
                "out.",
        "scene": f"Move the person into this setting: {o['scene']}. Match the light on them to the new setting.",
    }[o["background"]]
    lines.append(bg)
    if o["light"]:
        lines.append("Correct the exposure and white balance so the photo looks bright, natural and evenly lit, "
                     "without changing their skin tone.")
    if o["smooth"]:
        lines.append("Make the new clothes look freshly pressed: no creases, lint or stains.")
    shape = {"portrait": "vertical", "square": "square", "landscape": "horizontal"}[_shape(width, height)]
    lines.append(f"Keep the same camera angle, framing and {shape} aspect ratio as image 1. Photorealistic; the result "
                 "must look like the original photo, not a new photo shoot. No added text, watermarks or logos.")
    if o["extra"]:
        lines.append(f"Also: {o['extra']}")
    return "\n\n".join(lines)


def enqueue_tryon(owner_id: str, photo_id: str, item_ids: list[str], options: dict | None, requested_by: str,
                  source: str = "manual", engine: str | None = None, priority: int = 0) -> list[dict]:
    """Queue edits of one of your photos with other clothes (one job per version)."""
    photo = catalog.get_photo(owner_id, photo_id)
    if photo["kind"] in ("tag", "receipt"):
        raise HTTPException(422, "pick a photo of a person for try-on")
    ids = list(dict.fromkeys(i for i in item_ids if i))
    if not ids:
        raise HTTPException(422, "choose at least one item to wear")
    if len(ids) > 6:
        raise HTTPException(422, "try-on takes up to 6 items at once")
    items = [catalog.get_item(owner_id, i) for i in ids]
    o = tryon_options(options)
    o["aspect"] = _shape(photo.get("width"), photo.get("height"))
    p = prefs(owner_id)
    engine = engine if engine in ("chatgpt", "openrouter") else p["engine"]
    with_ref = [i["id"] for i in items if item_ref_sha(i["id"])]
    missing = [i["name"] for i in items if i["id"] not in with_ref]
    o["ref_items"] = with_ref
    prompt = build_tryon_prompt(items, o, photo.get("width"), photo.get("height"), set(with_ref))
    rows = []
    with db.tx():
        for v in range(o["variants"]):
            row = {"id": db.new_id("gen"), "owner_id": owner_id, "requested_by": requested_by, "template": TRYON["id"],
                   "item_ids": ids, "person_photo_id": photo_id, "engine": engine, "source": source,
                   "status": "queued", "priority": priority, "prompt": prompt, "options": {**o, "variant": v + 1},
                   "note": f"no photo of {', '.join(missing)} yet - drawn from the description" if missing else None,
                   "created_at": db.now()}
            db.insert("gen_jobs", row)
            if engine == "openrouter":
                enqueue_job("gen_openrouter", {"job_id": row["id"]})
            rows.append(row)
        db.audit(requested_by, "tryon_queued", owner_id, photo_id, {"items": ids, "versions": o["variants"],
                                                                     "options": {k: v for k, v in o.items() if k != "extra"}})
    return [db.one("SELECT * FROM gen_jobs WHERE id=?", (r["id"],)) for r in rows]


# ---------------- queue ----------------
def job_out(j: dict, items: dict[str, dict] | None = None, position: int | None = None) -> dict:
    ids = db.loads(j["item_ids"], [])
    out = {k: j.get(k) for k in ["id", "owner_id", "requested_by", "template", "person_photo_id", "engine", "source",
                                  "status", "priority", "attempts", "note", "error", "result_photo_id", "account_email",
                                  "duration_s", "cost_usd", "created_at", "claimed_at", "finished_at"]}
    out["item_ids"] = ids
    out["prompt"] = j["prompt"]
    o = job_options(j)
    out["options"] = {k: v for k, v in o.items() if k not in ("meta", "raw_sha", "ref_items")}
    out["finishing"] = bool(o.get("raw_sha")) and j["status"] == "running"
    if j["template"] == TRYON["id"] and j.get("person_photo_id"):
        ph = db.one("SELECT sha256 FROM photos WHERE id=? AND deleted_at IS NULL", (j["person_photo_id"],))
        out["base"] = catalog._image(ph["sha256"]) if ph else None
    if items is not None:
        out["items"] = [{"id": i, "name": items[i]["name"], "cover": catalog.cover_for(items[i])} for i in ids if i in items]
    if j.get("result_photo_id"):
        p = db.one("SELECT sha256 FROM photos WHERE id=? AND deleted_at IS NULL", (j["result_photo_id"],))
        out["result"] = catalog._image(p["sha256"]) if p else None
    if position is not None:
        out["position"] = position
    if j["status"] == "running" and j.get("claimed_at"):
        out["elapsed_s"] = int(db.now() - j["claimed_at"])
    return out


def enqueue(owner_id: str, template_id: str, item_ids: list[str], requested_by: str, source: str = "manual",
            person_photo_id: str | None = None, engine: str | None = None, extra: str = "", priority: int = 0) -> list[dict]:
    t = template(owner_id, template_id)
    if t.get("tryon"):
        raise HTTPException(422, "try-on edits one of your photos; use the Try on page (POST /studio/tryon)")
    p = prefs(owner_id)
    items = []
    for iid in item_ids:
        items.append(catalog.get_item(owner_id, iid))
    if not items:
        raise HTTPException(422, "choose at least one item")
    person = None
    if t["needs_person"]:
        person = person_photo_id or (p["model_photo_ids"][0] if p["model_photo_ids"] else None)
        if not person:
            raise HTTPException(422, "this template needs a model photo of you; add one in Studio first")
        catalog.get_photo(owner_id, person)
    groups = [items] if t["multi_item"] else [[i] for i in items]
    if t["multi_item"] and len(items) > 6:
        raise HTTPException(422, "outfit templates take up to 6 items")
    engine = engine if engine in ("chatgpt", "openrouter") else p["engine"]
    out = []
    with db.tx():
        for grp in groups:
            ids = [i["id"] for i in grp]
            missing = [i["name"] for i in grp if not item_ref_sha(i["id"])]
            dup = db.one("SELECT * FROM gen_jobs WHERE owner_id=? AND template=? AND item_ids=? AND status IN ('queued','running')",
                         (owner_id, template_id, db._enc(ids)))
            if dup:
                out.append(dup)
                continue
            row = {"id": db.new_id("gen"), "owner_id": owner_id, "requested_by": requested_by, "template": template_id,
                   "item_ids": ids, "person_photo_id": person, "engine": engine, "source": source,
                   "status": "queued", "priority": priority,
                   "prompt": build_prompt(t, grp, bool(person), extra),
                   "note": f"no photo of {', '.join(missing)} yet - the picture is generated from the description" if missing else None,
                   "created_at": db.now()}
            db.insert("gen_jobs", row)
            if engine == "openrouter":
                enqueue_job("gen_openrouter", {"job_id": row["id"]})
            out.append(row)
        db.audit(requested_by, "generation_queued", owner_id, None, {"template": template_id, "jobs": len(out)})
    return [db.one("SELECT * FROM gen_jobs WHERE id=?", (r["id"],)) for r in out]


def on_item_created(owner_id: str, item_id: str) -> None:
    """Auto mode: queue the chosen templates for a new item."""
    p = prefs(owner_id)
    if not p["auto_mode"]:
        return
    for tid in p["auto_templates"]:
        try:
            t = template(owner_id, tid)
            if t["needs_person"] and not p["model_photo_ids"]:
                continue
            if t["multi_item"]:
                continue
            enqueue(owner_id, tid, [item_id], "auto", source="auto", priority=-1)
        except HTTPException as exc:
            log.info("auto generation skipped for %s/%s: %s", item_id, tid, exc.detail)


def backfill(owner_id: str, template_ids: list[str], actor: str, limit: int = 500) -> dict:
    """Queue templates for every active item that has no picture (or job) from them yet."""
    p = prefs(owner_id)
    queued, skipped = 0, []
    items = db.q("SELECT id FROM items WHERE owner_id=? AND deleted_at IS NULL AND status NOT IN ('donated','sold','discarded') "
                 "ORDER BY created_at DESC", (owner_id,))
    for tid in template_ids:
        t = template(owner_id, tid)
        if t["multi_item"]:
            skipped.append(f"{t['name']}: outfit templates need you to pick items")
            continue
        if t["needs_person"] and not p["model_photo_ids"]:
            skipped.append(f"{t['name']}: add a model photo first")
            continue
        have = {r["item_ids"] for r in db.q("SELECT item_ids FROM gen_jobs WHERE owner_id=? AND template=? "
                                            "AND status IN ('queued','running','done')", (owner_id, tid))}
        for it in items:
            if queued >= limit:
                break
            if db._enc([it["id"]]) in have:
                continue
            enqueue(owner_id, tid, [it["id"]], actor, source="auto", priority=-2)
            queued += 1
    return {"queued": queued, "skipped": skipped}


def cancel(owner_id: str, ids: list[str] | None, actor: str, all_queued: bool = False) -> int:
    with db.tx():
        if all_queued:
            n = db.run("UPDATE gen_jobs SET status='cancelled', finished_at=? WHERE owner_id=? AND status='queued'",
                       (db.now(), owner_id))
        else:
            n = 0
            for i in ids or []:
                n += db.run("UPDATE gen_jobs SET status='cancelled', finished_at=? WHERE id=? AND owner_id=? "
                            "AND status IN ('queued','running')", (db.now(), i, owner_id))
        db.audit(actor, "generation_cancelled", owner_id, None, {"ids": ids, "all": all_queued, "n": n})
    return n


def retry(owner_id: str, job_id: str, actor: str, engine: str | None = None) -> dict:
    j = db.one("SELECT * FROM gen_jobs WHERE id=? AND owner_id=?", (job_id, owner_id))
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] in ("queued", "running") and not engine:
        return j
    fields = {"status": "queued", "error": None, "attempts": 0, "claimed_at": None, "finished_at": None}
    o = job_options(j)
    if o.pop("raw_sha", None):  # a half-finished picture from the last attempt is not reused
        o.pop("meta", None)
        fields["options"] = o
    if engine in ("chatgpt", "openrouter"):
        if j["status"] == "running":
            raise HTTPException(409, "this job is running; cancel it first")
        fields["engine"] = engine
    with db.tx():
        db.update("gen_jobs", job_id, fields)
        if fields.get("engine", j["engine"]) == "openrouter":
            enqueue_job("gen_openrouter", {"job_id": job_id})
        db.audit(actor, "generation_retried", owner_id, job_id, {"engine": engine})
    return db.one("SELECT * FROM gen_jobs WHERE id=?", (job_id,))


def move_top(owner_id: str, job_id: str, actor: str) -> dict:
    top = db.scalar("SELECT COALESCE(MAX(priority),0) FROM gen_jobs WHERE owner_id=? AND status='queued'", (owner_id,))
    with db.tx():
        if not db.run("UPDATE gen_jobs SET priority=? WHERE id=? AND owner_id=? AND status='queued'", (top + 1, job_id, owner_id)):
            raise HTTPException(409, "only queued jobs can be moved")
    return db.one("SELECT * FROM gen_jobs WHERE id=?", (job_id,))


def clear_finished(owner_id: str) -> int:
    with db.tx():
        return db.run("DELETE FROM gen_jobs WHERE owner_id=? AND status IN ('cancelled','failed')", (owner_id,))


def _done_today(owner_id: str, engine: str) -> int:
    start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    return db.scalar("SELECT COUNT(*) FROM gen_jobs WHERE owner_id=? AND engine=? AND status='done' AND finished_at>=?",
                     (owner_id, engine, start)) or 0


def _requeue_expired() -> None:
    now = db.now()
    for j in db.q("SELECT * FROM gen_jobs WHERE status='running' AND claimed_at<?", (now - CLAIM_TTL,)):
        with db.tx():
            if job_options(j).get("raw_sha"):  # the picture is made; only the finishing touches are pending
                enqueue_job("gen_finish", {"job_id": j["id"]})
                continue
            if j["attempts"] >= MAX_ATTEMPTS:
                db.update("gen_jobs", j["id"], {"status": "failed", "error": "the worker did not finish it in time",
                                                "finished_at": now})
            else:
                db.update("gen_jobs", j["id"], {"status": "queued", "claimed_at": None,
                                                "note": "retrying: the worker did not finish in time"})


# ---------------- overview (Studio page) ----------------
def worker_state() -> dict:
    w = db.kv_get("worker:codex", {}) or {}
    online = bool(w.get("last_seen")) and db.now() - w["last_seen"] < OFFLINE_AFTER
    return {**w, "online": online}


def account(owner_id: str) -> dict:
    a = db.one("SELECT * FROM chatgpt_accounts WHERE user_id=?", (owner_id,))
    if not a:
        return {"status": "not_connected"}
    return {"status": a["status"], "email": a["email"], "plan": a["plan"], "limits": db.loads(a["limits"], {}),
            "limits_at": a["limits_at"], "message": a["message"], "connected_at": a["connected_at"]}


def availability(owner_id: str) -> tuple[bool, str]:
    p = prefs(owner_id)
    if p["paused"]:
        return False, "the queue is paused"
    w = worker_state()
    if not w["online"]:
        return False, "the ChatGPT image worker is offline"
    a = account(owner_id)
    if a["status"] in ("not_connected", "pending", "disconnecting"):
        return False, "connect your ChatGPT account to generate"
    if a["status"] == "error":
        return False, a.get("message") or "the ChatGPT account has a problem"
    if a["status"] == "limited":
        return False, "your ChatGPT plan's image/Codex limit is used up" + _resets(a.get("limits") or {})
    if _done_today(owner_id, "chatgpt") >= p["daily_cap"]:
        return False, f"today's cap of {p['daily_cap']} pictures is reached"
    return True, ""


def _resets(lim: dict) -> str:
    at = max([(lim.get(k) or {}).get("resets_at") or 0 for k in ("primary", "secondary")], default=0)
    return f" (resets {time.strftime('%a %d %b, %H:%M', time.localtime(at))})" if at else ""


def overview(owner_id: str) -> dict:
    _requeue_expired()
    p = prefs(owner_id)
    jobs = db.q("SELECT * FROM gen_jobs WHERE owner_id=? ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 "
                "ELSE 2 END, CASE WHEN status='queued' THEN -priority ELSE 0 END, "
                "CASE WHEN status IN ('queued','running') THEN created_at ELSE -COALESCE(finished_at, created_at) END LIMIT 300",
                (owner_id,))
    ids = list({i for j in jobs for i in db.loads(j["item_ids"], [])})
    items = {i["id"]: i for i in db.q(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    pos, n = {}, 0
    for j in jobs:
        if j["status"] == "queued":
            n += 1
            pos[j["id"]] = n
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM gen_jobs WHERE owner_id=? GROUP BY status",
                                                (owner_id,))}
    durations = [j["duration_s"] for j in jobs if j["status"] == "done" and j.get("duration_s")]
    ok, reason = availability(owner_id)
    warnings = []
    person_auto = [t for t in p["auto_templates"] if template(owner_id, t)["needs_person"]] if p["auto_templates"] else []
    if p["auto_mode"] and person_auto and not p["model_photo_ids"]:
        warnings.append("Auto mode includes 'Me' templates but you have no model photo yet, so those are skipped.")
    if p["engine"] == "openrouter" and not settings.openrouter_key:
        warnings.append("OpenRouter is not configured on this server.")
    models = []
    for pid in p["model_photo_ids"]:
        ph = db.one("SELECT * FROM photos WHERE id=? AND deleted_at IS NULL", (pid,))
        if ph:
            models.append({"id": pid, "image": catalog._image(ph["sha256"])})
    week_start = db.now() - 7 * 86400
    return {
        "prefs": p,
        "templates": [{**{k: v for k, v in t.items() if k != "prompt"}, "prompt": t["prompt"],
                       "auto": t["id"] in p["auto_templates"],
                       "done": db.scalar("SELECT COUNT(*) FROM gen_jobs WHERE owner_id=? AND template=? AND status='done'",
                                         (owner_id, t["id"]))} for t in templates(owner_id)],
        "jobs": [job_out(j, items, pos.get(j["id"])) for j in jobs],
        "counts": counts,
        "available": ok, "reason": reason,
        "worker": worker_state(),
        "account": account(owner_id),
        "usage": {
            "chatgpt_today": _done_today(owner_id, "chatgpt"), "daily_cap": p["daily_cap"],
            "openrouter_today": _done_today(owner_id, "openrouter"), "openrouter_daily_cap": p["openrouter_daily_cap"],
            "openrouter_cost_today": db.usage_today(owner_id, "image:openrouter")["cost"],
            "week": db.scalar("SELECT COUNT(*) FROM gen_jobs WHERE owner_id=? AND status='done' AND finished_at>=?",
                              (owner_id, week_start)) or 0,
            "total": counts.get("done", 0),
            "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "openrouter_configured": bool(settings.openrouter_key),
        },
        "model_photos": models,
        "warnings": warnings,
    }


# ---------------- results ----------------
def job_options(job: dict) -> dict:
    return db.loads(job.get("options"), {}) or {}


def _refs(j: dict) -> list[str]:
    """Reference pictures in prompt order: the person (or the photo to edit) first, then the clothes."""
    refs = []
    if j.get("person_photo_id"):
        ph = db.one("SELECT sha256 FROM photos WHERE id=?", (j["person_photo_id"],))
        if ph:
            refs.append(ph["sha256"])
    o = job_options(j)
    for iid in o["ref_items"] if "ref_items" in o else db.loads(j["item_ids"], []):
        sha = item_ref_sha(iid)
        if sha:
            refs.append(sha)
    return refs


def _aspect(j: dict) -> str:
    return job_options(j).get("aspect") or template(j["owner_id"], j["template"])["aspect"]


def _needs_finish(job: dict) -> bool:
    o = job_options(job)
    return o.get("crop", "original") != "original" or bool(o.get("transparent"))


def _deliver(job: dict, raw: bytes, meta: dict, defer: bool) -> dict | None:
    """Save a finished picture. Framing and cut-outs need the cut-out model, which lives in the background
    worker, so a web request (defer=True) stores the raw picture and hands the finishing over."""
    if not _needs_finish(job):
        return _save_result(job, raw, meta)
    if defer:
        info = media.ingest(raw)
        with db.tx():
            db.update("gen_jobs", job["id"], {"options": {**job_options(job), "raw_sha": info["sha"], "meta": meta},
                                              "note": "finishing touches (framing / cut-out)"})
            enqueue_job("gen_finish", {"job_id": job["id"]})
        return None
    return _save_result(job, _finished_bytes(job, media.ingest(raw)["sha"]), meta)


def _finished_bytes(job: dict, sha: str) -> bytes:
    o = job_options(job)
    img = finish.finish(media.open_full(sha), o.get("crop", "original"), bool(o.get("transparent")),
                        white_bg=o.get("background") == "studio")
    return finish.encode(img)


@handler("gen_finish")
def gen_finish(payload: dict) -> None:
    j = db.one("SELECT * FROM gen_jobs WHERE id=?", (payload["job_id"],))
    if not j or j["status"] != "running":
        return
    o = job_options(j)
    if not o.get("raw_sha"):
        return
    try:
        data = _finished_bytes(j, o["raw_sha"])
    except Exception as exc:  # never lose the picture: keep it unfinished and say why
        log.warning("finishing %s failed: %s", j["id"], exc)
        data = media.path(o["raw_sha"], "full").read_bytes()
        o["meta"] = {**(o.get("meta") or {}), "finish_error": str(exc)[:200]}
    _save_result(j, data, o.get("meta") or {})


def _save_result(job: dict, raw: bytes, meta: dict) -> dict:
    t = template(job["owner_id"], job["template"])
    o = job_options(job)
    tryon = job["template"] == TRYON["id"]
    note = t["name"]
    if tryon and job.get("person_photo_id"):
        note = f"Try on · from photo {job['person_photo_id']}"
    photo, _ = catalog.add_photo(job["owner_id"], raw, f"studio:{job['engine']}", kind="worn" if t["needs_person"] else "product",
                                 source="generated", ai=True, template=job["template"], gen_job_id=job["id"],
                                 note=note, people=[job["owner_id"]] if t["needs_person"] else None)
    for iid in db.loads(job["item_ids"], []):
        if db.one("SELECT 1 FROM items WHERE id=? AND deleted_at IS NULL", (iid,)):
            link = catalog.add_link(job["owner_id"], photo["id"], iid, "generated", None, f"studio:{job['engine']}",
                                    confirmed=True, enqueue_cutout=False)
            if tryon and o.get("cover"):
                with db.tx():
                    db.update("items", iid, {"cover_link_id": link["id"], "updated_at": db.now()})
    if meta.get("finish_error"):
        meta["note"] = f"saved without finishing touches: {meta['finish_error']}"
    fields = {"status": "done", "result_photo_id": photo["id"], "finished_at": db.now(),
              "duration_s": meta.get("duration_s"), "cost_usd": meta.get("cost_usd"),
              "account_email": meta.get("account_email"), "error": None}
    if _needs_finish(job):
        fields["note"] = meta.get("note")
    with db.tx():
        db.update("gen_jobs", job["id"], fields)
        db.bump_usage(job["owner_id"], f"image:{job['engine']}", meta.get("cost_usd"))
    return photo


@handler("gen_openrouter")
def gen_openrouter(payload: dict) -> None:
    j = db.one("SELECT * FROM gen_jobs WHERE id=?", (payload["job_id"],))
    if not j or j["status"] != "queued" or j["engine"] != "openrouter":
        return
    p = prefs(j["owner_id"])
    if p["paused"]:
        raise Retry(60, "queue paused")
    if _done_today(j["owner_id"], "openrouter") >= p["openrouter_daily_cap"]:
        with db.tx():
            db.update("gen_jobs", j["id"], {"note": "waiting: today's OpenRouter cap is reached"})
        raise Retry(1800, "openrouter cap")
    with db.tx():
        if not db.run("UPDATE gen_jobs SET status='running', claimed_at=?, attempts=attempts+1 WHERE id=? AND status='queued'",
                      (db.now(), j["id"])):
            return
    refs = _refs(j)
    started = time.time()
    try:
        raw, meta = vision.generate_image(j["owner_id"], j["prompt"], refs, ASPECTS.get(_aspect(j), "3:4"))
    except Exception as exc:
        with db.tx():
            if (j["attempts"] + 1) >= MAX_ATTEMPTS:
                db.update("gen_jobs", j["id"], {"status": "failed", "error": str(exc)[:400], "finished_at": db.now()})
            else:
                db.update("gen_jobs", j["id"], {"status": "queued", "error": str(exc)[:400]})
                enqueue_job("gen_openrouter", {"job_id": j["id"]}, delay=60, dedupe=False)
        return
    cur = db.one("SELECT status FROM gen_jobs WHERE id=?", (j["id"],))
    if cur and cur["status"] == "cancelled":
        return
    meta["duration_s"] = round(time.time() - started, 1)
    _deliver(j, raw, meta, defer=False)


def tick() -> None:
    """Periodic housekeeping from the worker process: expire claims, OpenRouter fallback, expire logins."""
    _requeue_expired()
    with db.tx():
        db.run("UPDATE login_requests SET status='expired' WHERE status IN ('pending','code') AND expires_at<?", (db.now(),))
    w = worker_state()
    for owner in [r["owner_id"] for r in db.q("SELECT DISTINCT owner_id FROM gen_jobs WHERE status='queued' AND engine='chatgpt'")]:
        p = prefs(owner)
        if not p["fallback_openrouter"] or p["paused"] or not settings.openrouter_key:
            continue
        ok, _ = availability(owner)
        if ok and w["online"]:
            continue
        oldest = db.scalar("SELECT MIN(created_at) FROM gen_jobs WHERE owner_id=? AND status='queued' AND engine='chatgpt'", (owner,))
        if oldest and db.now() - oldest > 15 * 60:
            room = p["openrouter_daily_cap"] - _done_today(owner, "openrouter")
            for j in db.q("SELECT id FROM gen_jobs WHERE owner_id=? AND status='queued' AND engine='chatgpt' "
                          "ORDER BY priority DESC, created_at LIMIT ?", (owner, max(0, room))):
                with db.tx():
                    db.update("gen_jobs", j["id"], {"engine": "openrouter", "note": "moved to OpenRouter: ChatGPT unavailable"})
                    enqueue_job("gen_openrouter", {"job_id": j["id"]})


# ---------------- host worker API ----------------
def worker_heartbeat(body: dict) -> dict:
    w = {"last_seen": db.now(), "state": body.get("state") or "idle", "message": body.get("message"),
         "version": body.get("version"), "codex_version": body.get("codex_version"), "current_job": body.get("current_job"),
         "host": body.get("host")}
    with db.tx():
        db.kv_set("worker:codex", w)
        for uid, a in (body.get("accounts") or {}).items():
            if not db.one("SELECT 1 FROM users WHERE id=?", (uid,)):
                continue
            row = db.one("SELECT * FROM chatgpt_accounts WHERE user_id=?", (uid,))
            if row and row["status"] == "disconnecting":
                continue
            status = a.get("status") or "error"
            email = (a.get("email") or "").lower()
            if status == "connected" and _blocked(email):
                status, a["message"] = "error", f"{email} is a blocked domain for image generation; sign in with a personal account"
            fields = {"status": status, "email": email or None, "plan": a.get("plan"), "limits": a.get("limits") or {},
                      "limits_at": a.get("limits_at"), "message": a.get("message"), "updated_at": db.now()}
            if row:
                db.update("chatgpt_accounts", uid, fields, where="user_id")
            else:
                db.insert("chatgpt_accounts", {"user_id": uid, "connected_at": db.now(), **fields})
    pending = [{"id": r["id"], "kind": r["kind"], "user_id": r["user_id"]}
               for r in db.q("SELECT * FROM login_requests WHERE status='pending' AND expires_at>?", (db.now(),))]
    logout = [r["user_id"] for r in db.q("SELECT user_id FROM chatgpt_accounts WHERE status='disconnecting'")]
    reported = set((body.get("accounts") or {}).keys())
    with db.tx():
        for uid in logout:
            if uid not in reported:
                db.update("chatgpt_accounts", uid, {"status": "not_connected", "email": None, "plan": None,
                                                    "limits": {}, "message": None, "updated_at": db.now()}, where="user_id")
    running = [j["id"] for j in db.q("SELECT id FROM gen_jobs WHERE status='cancelled' AND claimed_at IS NOT NULL "
                                     "AND finished_at>?", (db.now() - 600,))]
    ready = [uid for uid in reported if availability(uid)[0] and _has_queued(uid)]
    return {"pending_logins": pending, "logout": logout, "cancelled": running, "work": bool(ready),
            "blocked_domains": settings.blocked_chatgpt_domains}


def _has_queued(uid: str) -> bool:
    return bool(db.one("SELECT 1 FROM gen_jobs WHERE owner_id=? AND status='queued' AND engine='chatgpt'", (uid,)))


def _blocked(email: str) -> bool:
    return any(email.endswith("@" + d) or email.endswith("." + d) for d in settings.blocked_chatgpt_domains)


def worker_claim(ready_users: list[str]) -> dict | None:
    _requeue_expired()
    candidates = []
    for uid in ready_users:
        ok, _ = availability(uid)
        if not ok:
            continue
        p = prefs(uid)
        last = db.scalar("SELECT MAX(finished_at) FROM gen_jobs WHERE owner_id=? AND engine='chatgpt' AND status='done'", (uid,)) or 0
        if db.now() - last < p["min_interval_s"]:
            continue
        candidates.append(uid)
    if not candidates:
        return None
    marks = ",".join("?" * len(candidates))
    with db.tx():
        j = db.one(f"SELECT * FROM gen_jobs WHERE status='queued' AND engine='chatgpt' AND owner_id IN ({marks}) "
                   "ORDER BY priority DESC, created_at LIMIT 1", candidates)
        if not j:
            return None
        db.run("UPDATE gen_jobs SET status='running', claimed_at=?, attempts=attempts+1 WHERE id=?", (db.now(), j["id"]))
    refs = _refs(j)
    t = template(j["owner_id"], j["template"])
    return {"id": j["id"], "user_id": j["owner_id"], "prompt": j["prompt"], "template": j["template"],
            "template_name": t["name"], "aspect": _aspect(j),
            "inputs": [f"/api/worker/media/{sha}" for sha in refs], "attempt": j["attempts"] + 1}


def worker_complete(job_id: str, raw: bytes, meta: dict) -> dict:
    j = db.one("SELECT * FROM gen_jobs WHERE id=?", (job_id,))
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] != "running":
        raise HTTPException(409, f"job is {j['status']}")
    a = account(j["owner_id"])
    meta["account_email"] = a.get("email")
    photo = _deliver(j, raw, meta, defer=True)
    return {"photo_id": photo["id"] if photo else None, "finishing": photo is None}


def worker_fail(job_id: str, error: str, limited: bool, retry_it: bool) -> None:
    j = db.one("SELECT * FROM gen_jobs WHERE id=?", (job_id,))
    if not j or j["status"] != "running":
        return
    with db.tx():
        if limited:
            db.update("gen_jobs", job_id, {"status": "queued", "claimed_at": None, "attempts": max(0, j["attempts"] - 1),
                                           "note": "waiting: ChatGPT limit reached", "error": error[:300]})
            db.run("UPDATE chatgpt_accounts SET status='limited', message=?, updated_at=? WHERE user_id=?",
                   (error[:200], db.now(), j["owner_id"]))
        elif retry_it and j["attempts"] < MAX_ATTEMPTS:
            db.update("gen_jobs", job_id, {"status": "queued", "claimed_at": None, "error": error[:300],
                                           "note": f"retrying after: {error[:120]}"})
        else:
            db.update("gen_jobs", job_id, {"status": "failed", "error": error[:400], "finished_at": db.now()})


# ---------------- ChatGPT sign-in / connect ----------------
def _nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def start_login(kind: str, user_id: str | None, nonce: str) -> dict:
    if "chatgpt" not in settings.auth_modes and kind == "login":
        raise HTTPException(400, "ChatGPT sign-in is not enabled")
    if not worker_state()["online"]:
        raise HTTPException(503, "the ChatGPT worker is offline, so ChatGPT sign-in is unavailable right now")
    rid = db.new_id("lgn")
    with db.tx():
        db.run("UPDATE login_requests SET status='expired' WHERE status IN ('pending','code') AND nonce_hash=?",
               (_nonce_hash(nonce),))
        db.insert("login_requests", {"id": rid, "kind": kind, "user_id": user_id, "nonce_hash": _nonce_hash(nonce),
                                     "status": "pending", "created_at": db.now(), "expires_at": db.now() + LOGIN_TTL})
        if kind == "connect" and user_id:
            row = db.one("SELECT * FROM chatgpt_accounts WHERE user_id=?", (user_id,))
            if not row:
                db.insert("chatgpt_accounts", {"user_id": user_id, "status": "pending", "updated_at": db.now()})
            elif row["status"] in ("not_connected", "error"):
                db.update("chatgpt_accounts", user_id, {"status": "pending", "message": None, "updated_at": db.now()},
                          where="user_id")
    return login_status(rid, nonce)


def login_status(rid: str, nonce: str) -> dict:
    r = db.one("SELECT * FROM login_requests WHERE id=?", (rid,))
    if not r or r["nonce_hash"] != _nonce_hash(nonce):
        raise HTTPException(404, "sign-in request not found")
    if r["status"] in ("pending", "code") and r["expires_at"] < db.now():
        with db.tx():
            db.run("UPDATE login_requests SET status='expired' WHERE id=?", (rid,))
        r["status"] = "expired"
    return {"id": r["id"], "kind": r["kind"], "status": r["status"], "verification_url": r["verification_url"],
            "user_code": r["user_code"], "email": r["email"], "message": r["message"], "expires_at": r["expires_at"]}


def consume_login(rid: str) -> dict | None:
    """After approval of a sign-in request: return the user to start a session for (once)."""
    with db.tx():
        r = db.one("SELECT * FROM login_requests WHERE id=? AND status='approved' AND kind='login'", (rid,))
        if not r:
            return None
        db.run("UPDATE login_requests SET status='consumed' WHERE id=?", (rid,))
    return db.one("SELECT * FROM users WHERE id=?", (r["user_id"],))


def worker_login_code(rid: str, url: str, code: str) -> None:
    with db.tx():
        db.run("UPDATE login_requests SET status='code', verification_url=?, user_code=? WHERE id=? AND status='pending'",
               (url[:200], code[:20], rid))


def worker_login_done(rid: str, email: str, plan: str | None) -> dict:
    """The device login finished on the worker. Decide whether to keep it, and for whom."""
    r = db.one("SELECT * FROM login_requests WHERE id=?", (rid,))
    email = (email or "").strip().lower()
    if not r or r["status"] not in ("pending", "code"):
        return {"accept": False, "message": "request expired"}
    if _blocked(email):
        msg = f"{email} can't be used here; sign in with your personal ChatGPT account"
        with db.tx():
            db.update("login_requests", rid, {"status": "rejected", "email": email, "message": msg})
            if r["user_id"]:
                db.run("UPDATE chatgpt_accounts SET status='error', message=? WHERE user_id=?", (msg, r["user_id"]))
        return {"accept": False, "message": msg}
    uid = r["user_id"]
    if r["kind"] == "login":
        u = db.one("SELECT * FROM users WHERE email=?", (email,))
        if not u or u["status"] == "disabled":
            msg = f"{email} is not invited to this wardrobe"
            with db.tx():
                db.update("login_requests", rid, {"status": "rejected", "email": email, "message": msg})
            return {"accept": False, "message": msg}
        uid = u["id"]
        with db.tx():
            db.update("users", uid, {"status": "active", "last_login_at": db.now()})
    with db.tx():
        db.update("login_requests", rid, {"status": "approved", "email": email, "user_id": uid, "message": None})
        row = db.one("SELECT * FROM chatgpt_accounts WHERE user_id=?", (uid,))
        fields = {"status": "connected", "email": email, "plan": plan, "message": None, "updated_at": db.now(),
                  "connected_at": db.now()}
        if row:
            db.update("chatgpt_accounts", uid, fields, where="user_id")
        else:
            db.insert("chatgpt_accounts", {"user_id": uid, **fields})
        db.audit(f"chatgpt:{email}", "chatgpt_connected", uid, rid, {"kind": r["kind"]})
    return {"accept": True, "user_id": uid}


def worker_login_failed(rid: str, message: str) -> None:
    with db.tx():
        r = db.one("SELECT * FROM login_requests WHERE id=?", (rid,))
        if not r:
            return
        db.update("login_requests", rid, {"status": "failed", "message": message[:300]})
        if r["user_id"]:
            db.run("UPDATE chatgpt_accounts SET status='not_connected', message=? WHERE user_id=? AND status='pending'",
                   (message[:200], r["user_id"]))


def disconnect(user_id: str, actor: str) -> None:
    with db.tx():
        db.run("UPDATE chatgpt_accounts SET status='disconnecting', updated_at=? WHERE user_id=?", (db.now(), user_id))
        db.audit(actor, "chatgpt_disconnect", user_id)


def overview_counts_for_nav(owner_id: str) -> dict[str, Any]:
    return {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM gen_jobs WHERE owner_id=? AND "
                                              "status IN ('queued','running') GROUP BY status", (owner_id,))}
