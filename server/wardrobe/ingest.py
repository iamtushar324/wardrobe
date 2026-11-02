"""Bulk ingest: a folder of photos becomes reviewed wardrobe items.

1. create a batch (optional note and purchase hints that apply to every item in it)
2. add photos -> each is stored and an `analyze_photo` job runs (kind, garments + boxes, tag/receipt text,
   crops, background-removed cutouts, pixel colours)
3. when every photo is analysed, `build_proposals` groups the same garment across photos (flat-lay + worn),
   matches existing items, pairs tag photos and receipt lines, and writes one proposal per item
4. proposals wait in the Inbox (or are committed automatically when auto_commit allows)

Purchase details are only ever filled from what the owner said (hints), a tag photo (MRP) or a receipt,
and each field records which of those it came from.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import defaultdict
from typing import Any

from fastapi import HTTPException

from . import catalog, colors, cutout, db, media, vision
from .jobs import Retry, enqueue, handler
from .taxonomy import MATERIALS, PALETTE, norm_category, norm_color, norm_season

log = logging.getLogger("wardrobe.ingest")
HINT_FIELDS = ["store", "store_url", "purchase_date", "price", "original_price", "currency", "gifted_by", "occasions",
               "seasons", "status", "location", "notes", "brand", "size", "tags"]
AUTO_CONFIDENCE = 0.7


# ---------------- batches ----------------
def create_batch(owner_id: str, actor: str, note: str | None = None, hints: dict | None = None,
                 auto_commit: str = "none", analyze: bool = True) -> dict:
    if auto_commit not in ("none", "confident", "all"):
        raise HTTPException(422, "auto_commit must be none, confident or all")
    hints = {k: v for k, v in (hints or {}).items() if k in HINT_FIELDS and v not in (None, "", [])}
    row = {"id": db.new_id("bat"), "owner_id": owner_id, "note": (note or "")[:2000] or None, "hints": hints,
           "auto_commit": auto_commit, "analyze": analyze and vision.available(), "status": "open",
           "created_by": actor, "created_at": db.now(), "updated_at": db.now()}
    with db.tx():
        db.insert("batches", row)
        db.audit(actor, "batch_created", owner_id, row["id"], {"note": note, "hints": hints})
    return get_batch(owner_id, row["id"])


def get_batch(owner_id: str, batch_id: str) -> dict:
    b = db.one("SELECT * FROM batches WHERE id=? AND owner_id=?", (batch_id, owner_id))
    if not b:
        raise HTTPException(404, "batch not found")
    return b


def upload_token(owner_id: str, batch_id: str, actor: str, ttl: float = 3 * 3600) -> str:
    raw = "up_" + secrets.token_urlsafe(24)
    with db.tx():
        db.insert("upload_tokens", {"token_hash": hashlib.sha256(raw.encode()).hexdigest(), "batch_id": batch_id,
                                    "owner_id": owner_id, "actor": actor, "expires_at": db.now() + ttl})
    return raw


def check_upload_token(raw: str) -> dict:
    row = db.one("SELECT * FROM upload_tokens WHERE token_hash=? AND expires_at>?",
                 (hashlib.sha256(raw.encode()).hexdigest(), db.now()))
    if not row:
        raise HTTPException(403, "upload link expired or invalid")
    return row


def add_photos(owner_id: str, batch_id: str, files: list[tuple[str, bytes]], actor: str) -> list[dict]:
    b = get_batch(owner_id, batch_id)
    if b["status"] in ("done", "cancelled"):
        raise HTTPException(409, "this batch is closed; start a new one")
    out = []
    for name, raw in files:
        try:
            photo, created = catalog.add_photo(owner_id, raw, actor, filename=name, batch_id=batch_id,
                                               status="queued" if b["analyze"] else "ready")
        except media.BadImage as exc:
            out.append({"filename": name, "error": str(exc)})
            continue
        if not created:
            out.append({"filename": name, "photo_id": photo["id"], "duplicate": True})
            continue
        with db.tx():
            if b["analyze"]:
                enqueue("analyze_photo", {"photo_id": photo["id"]})
        out.append({"filename": name, "photo_id": photo["id"], "duplicate": False})
    with db.tx():
        db.update("batches", batch_id, {"status": "analyzing" if b["analyze"] else "review", "updated_at": db.now()})
    return out


def analyze_batch(owner_id: str, batch_id: str) -> dict:
    """(Re)start analysis for photos that have not been analysed (e.g. added while vision was off)."""
    b = get_batch(owner_id, batch_id)
    with db.tx():
        n = 0
        for p in db.q("SELECT id FROM photos WHERE batch_id=? AND deleted_at IS NULL AND (analysis IS NULL OR status='error')",
                      (batch_id,)):
            db.run("UPDATE photos SET status='queued', error=NULL WHERE id=?", (p["id"],))
            enqueue("analyze_photo", {"photo_id": p["id"]})
            n += 1
        if n == 0:
            enqueue("build_proposals", {"batch_id": batch_id})
        db.update("batches", b["id"], {"status": "analyzing", "analyze": 1, "updated_at": db.now()})
    return {"queued": n}


def batch_view(owner_id: str, batch_id: str) -> dict:
    b = get_batch(owner_id, batch_id)
    photos = db.q("SELECT * FROM photos WHERE batch_id=? AND deleted_at IS NULL ORDER BY COALESCE(taken_at, created_at), filename",
                  (batch_id,))
    props = db.q("SELECT * FROM proposals WHERE batch_id=? ORDER BY created_at", (batch_id,))
    photo_map = {p["id"]: p for p in photos}
    linked = {l["photo_id"] for pr in props if pr["status"] in ("pending", "accepted") for l in db.loads(pr["links"], [])}
    linked |= {r["photo_id"] for r in db.q("SELECT DISTINCT l.photo_id FROM links l JOIN photos p ON p.id=l.photo_id "
                                           "WHERE p.batch_id=?", (batch_id,))}
    match_ids = [pr["match_item_id"] for pr in props if pr["match_item_id"]]
    matches = {i["id"]: i for i in db.q(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(match_ids))})",
                                        match_ids)} if match_ids else {}
    return {
        "batch": batch_out(b),
        "photos": [{**catalog.photo_out(p), "analysis": _analysis_summary(db.loads(p.get("analysis"))),
                    "assigned": p["id"] in linked} for p in photos],
        "proposals": [proposal_out(pr, photo_map, matches) for pr in props],
    }


def _analysis_summary(a: dict | None) -> dict | None:
    if not a:
        return None
    return {"kind": a.get("kind"), "summary": a.get("summary"), "items": len(a.get("items") or []),
            "tag": a.get("tag"), "receipt": a.get("receipt")}


def batch_out(b: dict) -> dict:
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM photos WHERE batch_id=? AND deleted_at IS NULL "
                                                "GROUP BY status", (b["id"],))}
    pcounts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM proposals WHERE batch_id=? GROUP BY status",
                                                 (b["id"],))}
    cover = db.one("SELECT sha256 FROM photos WHERE batch_id=? AND deleted_at IS NULL ORDER BY created_at LIMIT 1", (b["id"],))
    return {"id": b["id"], "note": b["note"], "hints": db.loads(b["hints"], {}), "auto_commit": b["auto_commit"],
            "analyze": bool(b["analyze"]), "status": b["status"], "message": b["message"], "created_by": b["created_by"],
            "created_at": b["created_at"], "updated_at": b["updated_at"], "photo_counts": counts,
            "photos": sum(counts.values()), "proposal_counts": pcounts,
            "cover": catalog.media_url(cover["sha256"], "sm") if cover else None}


def list_batches(owner_id: str, limit: int = 50) -> list[dict]:
    return [batch_out(b) for b in db.q("SELECT * FROM batches WHERE owner_id=? ORDER BY created_at DESC LIMIT ?",
                                       (owner_id, limit))]


def proposal_out(pr: dict, photos: dict[str, dict] | None = None, matches: dict[str, dict] | None = None) -> dict:
    links = db.loads(pr["links"], [])
    photos = photos or {}
    out_links = []
    for l in links:
        p = photos.get(l["photo_id"]) or db.one("SELECT * FROM photos WHERE id=?", (l["photo_id"],)) or {}
        out_links.append({**l, "photo": catalog._image(p.get("sha256")), "kind": p.get("kind"),
                          "crop": catalog._image(l.get("crop_sha")), "cutout": catalog._image(l.get("cutout_sha"))})
    preview = next((l for l in out_links if l.get("cutout")), None) or next((l for l in out_links if l.get("crop")), None)
    match = None
    if pr.get("match_item_id"):
        m = (matches or {}).get(pr["match_item_id"]) or db.one("SELECT * FROM items WHERE id=?", (pr["match_item_id"],))
        if m and not m.get("deleted_at"):
            match = {"id": m["id"], "name": m["name"], "cover": catalog.cover_for(m)}
    return {"id": pr["id"], "batch_id": pr["batch_id"], "status": pr["status"], "data": db.loads(pr["data"], {}),
            "links": out_links, "match": match, "confidence": pr["confidence"], "reason": pr["reason"],
            "item_id": pr["item_id"],
            "preview": (preview.get("cutout") or preview.get("crop")) if preview else None}


# ---------------- analysis ----------------
def _hint_text(b: dict | None) -> str:
    if not b:
        return ""
    bits = [b.get("note") or ""]
    hints = db.loads(b.get("hints"), {})
    if hints:
        bits.append("; ".join(f"{k}: {v}" for k, v in hints.items()))
    return " | ".join(x for x in bits if x)


@handler("analyze_photo")
def analyze_photo(payload: dict) -> None:
    p = db.one("SELECT * FROM photos WHERE id=?", (payload["photo_id"],))
    if not p or p.get("deleted_at"):
        return
    b = db.one("SELECT * FROM batches WHERE id=?", (p["batch_id"],)) if p.get("batch_id") else None
    with db.tx():
        db.run("UPDATE photos SET status='analyzing' WHERE id=?", (p["id"],))
    try:
        result = vision.analyze(p["owner_id"], p["sha256"], _hint_text(b))
    except vision.VisionError as exc:
        if "cap" in str(exc):
            raise Retry(1800, str(exc))
        raise
    kind = result.get("kind") if result.get("kind") in ("flat_lay", "product", "worn", "tag", "receipt", "detail", "other") else "other"
    dets = result.get("items") or [] if kind not in ("tag", "receipt") else []
    for d in dets:
        try:
            crop = media.crop(p["sha256"], d["bbox"])
            d["crop_sha"] = crop["sha"]
            if kind in ("flat_lay", "product", "detail"):
                try:
                    cut = cutout.cutout(crop["sha"])
                    d["cutout_sha"] = cut["sha"] if cut else None
                except Exception as exc:  # model download/runtime problems should not lose the analysis
                    log.warning("cutout failed for %s: %s", p["id"], exc)
            src = d.get("cutout_sha") or d["crop_sha"]
            d["px_colors"] = colors.dominant(src)
            d["dhash"] = media.dhash(src)
        except media.BadImage:
            d["skip"] = True
    result["items"] = [d for d in dets if not d.get("skip")]
    result["kind"] = kind
    with db.tx():
        db.update("photos", p["id"], {"analysis": result, "kind": kind, "status": "ready", "error": None})
        if kind == "worn" and result.get("people", 1) >= 1:
            db.run("INSERT OR IGNORE INTO photo_people(photo_id,user_id) VALUES(?,?)", (p["id"], p["owner_id"]))
    _maybe_finish_analysis(p.get("batch_id"))


@handler("analyze_photo:failed")
def analyze_failed(payload: dict) -> None:
    p = db.one("SELECT * FROM photos WHERE id=?", (payload["photo_id"],))
    if not p:
        return
    with db.tx():
        db.update("photos", p["id"], {"status": "error", "error": payload.get("_error", "analysis failed")[:500]})
    _maybe_finish_analysis(p.get("batch_id"))


def _maybe_finish_analysis(batch_id: str | None) -> None:
    if not batch_id:
        return
    left = db.scalar("SELECT COUNT(*) FROM photos WHERE batch_id=? AND deleted_at IS NULL AND status IN ('queued','analyzing')",
                     (batch_id,))
    if left == 0:
        with db.tx():
            db.update("batches", batch_id, {"status": "grouping", "updated_at": db.now()})
            enqueue("build_proposals", {"batch_id": batch_id})


# ---------------- proposals ----------------
def _det_label(photo: dict, d: dict, idx: int) -> str:
    return f"{vision.describe(d)} (photo {idx}, {photo['kind']})"


def _existing_candidates(owner_id: str, cats: set[str], batch_id: str, limit: int = 18) -> list[dict]:
    rows = db.q("SELECT * FROM items WHERE owner_id=? AND deleted_at IS NULL ORDER BY updated_at DESC", (owner_id,))
    rows = [r for r in rows if r.get("category") in cats]
    out = []
    for r in rows:
        cov = catalog.cover_for(r)
        if cov:
            out.append({**r, "_sha": cov["sha"]})
        if len(out) >= limit:
            break
    return out


def _merge_data(dets: list[tuple[dict, dict]]) -> dict:
    """Merge attributes from all detections of one item; prefer flat-lay/product detections."""
    ordered = sorted(dets, key=lambda pd: (0 if pd[0]["kind"] in ("product", "flat_lay") else 1, -(pd[1].get("confidence") or 0)))
    best = ordered[0][1]
    cat, sub = norm_category(best.get("category"), best.get("subcategory"))
    px = next((d.get("px_colors") for _, d in ordered if d.get("px_colors") and d.get("cutout_sha")), None) \
        or next((d.get("px_colors") for _, d in ordered if d.get("px_colors")), None)
    if px:
        cols = px
    else:
        cols = [{"name": n, "hex": PALETTE.get(n, "#999999"), "share": None}
                for n in (norm_color(c) for c in best.get("colors") or []) if n]
    seasons, occasions, styles = [], [], []
    for _, d in ordered:
        for s in d.get("seasons") or []:
            n = norm_season(s)
            if n and n not in seasons:
                seasons.append(n)
        for o in d.get("occasions") or []:
            o = str(o).lower()
            if o and o not in occasions:
                occasions.append(o)
        for s in d.get("styles") or []:
            s = str(s).lower()
            if s and s not in styles:
                styles.append(s)
    material = best.get("material")
    return {"name": best.get("name") or (sub or cat or "Item").capitalize(), "category": cat, "subcategory": sub,
            "colors": cols, "pattern": best.get("pattern"), "material": material if material in MATERIALS else material,
            "seasons": seasons[:3], "occasions": occasions[:4], "styles": styles[:3], "formality": best.get("formality"),
            "brand": next((d.get("brand") for _, d in ordered if d.get("brand")), None)}


def _material_from_tag(text: str | None) -> str | None:
    t = (text or "").lower()
    found = [(t.find(m), m) for m in MATERIALS if m in t]
    return min(found)[1] if found else None


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip())
    except ValueError:
        return None


@handler("build_proposals")
def build_proposals(payload: dict) -> None:
    b = db.one("SELECT * FROM batches WHERE id=?", (payload["batch_id"],))
    if not b or b["status"] in ("done", "cancelled"):
        return
    owner = b["owner_id"]
    photos = db.q("SELECT * FROM photos WHERE batch_id=? AND deleted_at IS NULL ORDER BY COALESCE(taken_at, created_at), filename",
                  (b["id"],))
    # Photos already turned into items (an earlier round in a batch that grew) are not grouped again.
    done_ids = {l["photo_id"] for pr in db.q("SELECT links FROM proposals WHERE batch_id=? AND status='accepted'", (b["id"],))
                for l in db.loads(pr["links"], [])}
    photos = [p for p in photos if p["id"] not in done_ids]
    # Detections across the batch: C1, C2, ...
    dets: dict[str, tuple[dict, dict]] = {}
    for idx, p in enumerate(photos, start=1):
        a = db.loads(p.get("analysis"), {}) or {}
        for d in a.get("items") or []:
            if d.get("crop_sha"):
                dets[f"C{len(dets) + 1}"] = (p, d)
    tags = [p for p in photos if p["kind"] == "tag"]
    receipts = [p for p in photos if p["kind"] == "receipt"]
    groups: list[dict] = []
    existing_by_ref: dict[str, dict] = {}
    if dets and vision.available():
        by_cat: dict[str, list[str]] = defaultdict(list)
        for cid, (_, d) in dets.items():
            by_cat[norm_category(d.get("category"), d.get("subcategory"))[0] or "other"].append(cid)
        # one grouping call per category family keeps prompts small (<= 30 crops each)
        for cat, cids in by_cat.items():
            cands = _existing_candidates(owner, {cat}, b["id"], 12)
            ex_refs = []
            for j, c in enumerate(cands, start=1):
                ref = f"E{len(existing_by_ref) + 1}"
                existing_by_ref[ref] = c
                ex_refs.append((ref, c["_sha"], f"{c.get('name')} ({c.get('brand') or 'no brand'})"))
            for start in range(0, len(cids), 30):
                chunk = cids[start:start + 30]
                if len(chunk) == 1 and not ex_refs:
                    groups.append({"crops": chunk, "existing": None, "confidence": 0.8, "reason": "single"})
                    continue
                crops = [(cid, dets[cid][1].get("cutout_sha") or dets[cid][1]["crop_sha"],
                          _det_label(dets[cid][0], dets[cid][1], photos.index(dets[cid][0]) + 1)) for cid in chunk]
                try:
                    groups += vision.group(owner, crops, ex_refs)
                except vision.VisionError as exc:
                    log.warning("grouping failed: %s", exc)
                    groups += [{"crops": [c], "existing": None, "confidence": 0.5, "reason": "grouping failed"} for c in chunk]
    else:
        groups = [{"crops": [cid], "existing": None, "confidence": 0.6, "reason": "no grouping"} for cid in dets]

    # Tags and receipt lines -> groups
    tag_for: dict[int, list[dict]] = defaultdict(list)
    line_for: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
    receipt_meta = [db.loads(r.get("analysis"), {}).get("receipt") or {} for r in receipts]
    if groups and (tags or receipts) and vision.available():
        reps = []
        for gi, g in enumerate(groups):
            p, d = dets[g["crops"][0]]
            reps.append((f"G{gi + 1}", d.get("cutout_sha") or d["crop_sha"], vision.describe(d)))
        tag_refs = [(f"T{i + 1}", t["sha256"], str((db.loads(t.get("analysis"), {}).get("tag") or {}).get("text") or "")[:300])
                    for i, t in enumerate(tags)]
        try:
            res = vision.assign(owner, reps, tag_refs, [(f"R{i + 1}", r) for i, r in enumerate(receipt_meta)])
            for t in res.get("tags") or []:
                ti, gi = _ref(t.get("tag"), "T"), _ref(t.get("item"), "G")
                if ti is not None and gi is not None and ti < len(tags) and gi < len(groups):
                    tag_for[gi].append(tags[ti])
            for ln in res.get("lines") or []:
                ri, gi = _ref(ln.get("receipt"), "R"), _ref(ln.get("item"), "G")
                li = ln.get("line")
                if ri is not None and gi is not None and ri < len(receipts) and gi < len(groups) and isinstance(li, int):
                    lines = receipt_meta[ri].get("lines") or []
                    if 0 <= li < len(lines):
                        line_for[gi].append((receipts[ri], {**lines[li], "_receipt": receipt_meta[ri]}))
        except vision.VisionError as exc:
            log.warning("tag assignment failed: %s", exc)
    elif len(groups) == 1:  # a single item: every tag and receipt belongs to it
        tag_for[0] = list(tags)
        for r, meta in zip(receipts, receipt_meta):
            lines = meta.get("lines") or []
            line_for[0].append((r, {**(lines[0] if lines else {}), "_receipt": meta}))

    hints = db.loads(b["hints"], {})
    with db.tx():
        db.run("DELETE FROM proposals WHERE batch_id=? AND status='pending'", (b["id"],))
        for gi, g in enumerate(groups):
            members = [dets[c] for c in g["crops"] if c in dets]
            if not members:
                continue
            data = _merge_data(members)
            prov: dict[str, str] = {}
            links = [{"photo_id": p["id"], "role": "worn" if p["kind"] == "worn" else ("detail" if p["kind"] == "detail" else "shows"),
                      "bbox": d["bbox"], "crop_sha": d.get("crop_sha"), "cutout_sha": d.get("cutout_sha"),
                      "confidence": d.get("confidence")} for p, d in members]
            for t in tag_for.get(gi, []):
                info = db.loads(t.get("analysis"), {}).get("tag") or {}
                links.append({"photo_id": t["id"], "role": "tag", "bbox": None})
                for field, val in (("brand", info.get("brand")), ("size", info.get("size")),
                                   ("size_system", info.get("size_system")),
                                   ("material", _material_from_tag(info.get("materials")))):
                    if val and not data.get(field):
                        data[field] = val
                        prov[field] = "tag"
                mrp = _num(info.get("mrp"))
                if mrp:
                    data["original_price"] = mrp
                    data["currency"] = (info.get("currency") or "INR").upper()[:3]
                    prov["original_price"] = prov["currency"] = "tag"
                if info.get("care") or info.get("style_code"):
                    extra = "; ".join(x for x in [f"Care: {info['care']}" if info.get("care") else "",
                                                  f"Style code: {info['style_code']}" if info.get("style_code") else ""] if x)
                    data["notes"] = ((data.get("notes") or "") + "\n" + extra).strip()
            for r, line in line_for.get(gi, []):
                links.append({"photo_id": r["id"], "role": "receipt", "bbox": None})
                meta = line.get("_receipt") or {}
                if _num(line.get("price")):
                    data["price"] = _num(line.get("price"))
                    prov["price"] = "receipt"
                if _num(line.get("mrp")) and not data.get("original_price"):
                    data["original_price"] = _num(line.get("mrp"))
                    prov["original_price"] = "receipt"
                for field, val in (("store", meta.get("store")), ("purchase_date", meta.get("date")),
                                   ("currency", meta.get("currency"))):
                    if val and not data.get(field):
                        data[field] = val
                        prov[field] = "receipt"
            for k, v in hints.items():  # the owner's words win
                if k in ("occasions", "seasons", "tags"):
                    vals = v if isinstance(v, list) else [s.strip() for s in str(v).split(",") if s.strip()]
                    data[k] = list(dict.fromkeys([*(data.get(k) or []), *vals]))
                else:
                    data[k] = v
                prov[k] = "user"
            data["provenance"] = prov
            mean_conf = sum((d.get("confidence") or 0.6) for _, d in members) / len(members)
            match = existing_by_ref.get(g.get("existing") or "")
            db.insert("proposals", {
                "id": db.new_id("prp"), "batch_id": b["id"], "owner_id": owner, "status": "pending", "data": data,
                "links": links, "match_item_id": match["id"] if match else None,
                "confidence": round(min(1.0, g["confidence"]) * mean_conf, 3), "reason": g.get("reason"),
                "created_at": db.now(), "updated_at": db.now()})
        n = db.scalar("SELECT COUNT(*) FROM proposals WHERE batch_id=? AND status='pending'", (b["id"],))
        db.update("batches", b["id"], {"status": "review", "updated_at": db.now(),
                                       "message": f"{n} item{'s' if n != 1 else ''} found in {len(photos)} photos"})
    if b["auto_commit"] in ("confident", "all"):
        commit_batch(owner, b["id"], b["auto_commit"], b["created_by"] or "system")


def _ref(v: Any, prefix: str) -> int | None:
    if isinstance(v, str) and v.upper().startswith(prefix) and v[1:].isdigit():
        return int(v[1:]) - 1
    return None


# ---------------- review ----------------
def get_proposal(owner_id: str, pid: str) -> dict:
    pr = db.one("SELECT * FROM proposals WHERE id=? AND owner_id=?", (pid, owner_id))
    if not pr:
        raise HTTPException(404, "proposal not found")
    return pr


def update_proposal(owner_id: str, pid: str, body: dict, actor: str) -> dict:
    pr = get_proposal(owner_id, pid)
    if pr["status"] != "pending":
        raise HTTPException(409, "already decided")
    fields: dict = {"updated_at": db.now()}
    if "data" in body:
        data = {**db.loads(pr["data"], {}), **(body["data"] or {})}
        prov = data.get("provenance") or {}
        for k in (body["data"] or {}):
            if k in catalog.PURCHASE:
                prov[k] = "user"
        data["provenance"] = prov
        fields["data"] = data
    if "match_item_id" in body:
        if body["match_item_id"]:
            catalog.get_item(owner_id, body["match_item_id"])
        fields["match_item_id"] = body["match_item_id"] or None
    if "links" in body:
        fields["links"] = body["links"]
    with db.tx():
        db.update("proposals", pid, fields)
    return proposal_out(get_proposal(owner_id, pid))


def commit_proposal(owner_id: str, pid: str, actor: str) -> dict:
    pr = get_proposal(owner_id, pid)
    if pr["status"] != "pending":
        return proposal_out(pr)
    data = db.loads(pr["data"], {})
    prov = data.pop("provenance", {}) or {}
    links = db.loads(pr["links"], [])
    new = False
    if pr["match_item_id"] and db.one("SELECT 1 FROM items WHERE id=? AND deleted_at IS NULL", (pr["match_item_id"],)):
        item = catalog.get_item(owner_id, pr["match_item_id"])
        fill = {}
        for k, v in data.items():  # only fill what the existing item lacks
            cur = item.get(k)
            if v not in (None, "", []) and cur in (None, "", "[]") and k in catalog.clean_item_fields({k: v}):
                fill[k] = v
        if fill:
            fill["provenance"] = {k: prov[k] for k in fill if k in prov}
            item = catalog.update_item(owner_id, item["id"], fill, actor, "user")
    else:
        item = catalog.create_item(owner_id, {**data, "provenance": {k: v for k, v in prov.items()}}, actor, "user")
        new = True
    cover = None
    for l in links:
        try:
            row = catalog.add_link(owner_id, l["photo_id"], item["id"], l.get("role") or "shows", l.get("bbox"), actor,
                                   l.get("crop_sha"), l.get("cutout_sha"), l.get("confidence"), True,
                                   enqueue_cutout=not l.get("crop_sha") and l.get("role") == "shows")
            if cover is None and l.get("cutout_sha") and l.get("role") == "shows":
                cover = row["id"]
        except HTTPException as exc:
            log.warning("link skipped: %s", exc.detail)
    with db.tx():
        if cover and (new or not item.get("cover_link_id")):
            db.run("UPDATE items SET cover_link_id=? WHERE id=?", (cover, item["id"]))
        db.update("proposals", pid, {"status": "accepted", "item_id": item["id"], "updated_at": db.now()})
        db.audit(actor, "proposal_accepted", owner_id, pid, {"item": item["id"], "new": new})
        _close_batch_if_done(pr["batch_id"])
    if new:
        from . import studio
        studio.on_item_created(owner_id, item["id"])
    return proposal_out(get_proposal(owner_id, pid))


def reject_proposal(owner_id: str, pid: str, actor: str) -> dict:
    pr = get_proposal(owner_id, pid)
    with db.tx():
        db.update("proposals", pid, {"status": "rejected", "updated_at": db.now()})
        db.audit(actor, "proposal_rejected", owner_id, pid)
        _close_batch_if_done(pr["batch_id"])
    return proposal_out(get_proposal(owner_id, pid))


def merge_proposals(owner_id: str, ids: list[str], actor: str) -> dict:
    if len(ids) < 2:
        raise HTTPException(422, "pick at least two proposals to merge")
    prs = [get_proposal(owner_id, i) for i in ids]
    if any(p["status"] != "pending" for p in prs):
        raise HTTPException(409, "only pending proposals can be merged")
    first = prs[0]
    data = db.loads(first["data"], {})
    links = db.loads(first["links"], [])
    for other in prs[1:]:
        od = db.loads(other["data"], {})
        for k, v in od.items():
            if data.get(k) in (None, "", []) and v not in (None, "", []):
                data[k] = v
        links += db.loads(other["links"], [])
    with db.tx():
        db.update("proposals", first["id"], {"data": data, "links": links, "updated_at": db.now(),
                                             "match_item_id": first["match_item_id"] or next((p["match_item_id"] for p in prs if p["match_item_id"]), None)})
        for other in prs[1:]:
            db.update("proposals", other["id"], {"status": "merged", "updated_at": db.now()})
        db.audit(actor, "proposals_merged", owner_id, first["id"], {"merged": ids[1:]})
    return proposal_out(get_proposal(owner_id, first["id"]))


def commit_batch(owner_id: str, batch_id: str, which: str | list[str], actor: str) -> dict:
    get_batch(owner_id, batch_id)
    prs = db.q("SELECT * FROM proposals WHERE batch_id=? AND status='pending'", (batch_id,))
    if isinstance(which, list):
        chosen = [p for p in prs if p["id"] in which]
    elif which == "all":
        chosen = prs
    else:
        chosen = [p for p in prs if (p["confidence"] or 0) >= (0.8 if p["match_item_id"] else AUTO_CONFIDENCE)]
    done = [commit_proposal(owner_id, p["id"], actor) for p in chosen]
    return {"committed": len(done), "left": len(prs) - len(done), "items": [d["item_id"] for d in done]}


def _close_batch_if_done(batch_id: str) -> None:
    left = db.scalar("SELECT COUNT(*) FROM proposals WHERE batch_id=? AND status='pending'", (batch_id,))
    if left == 0:
        db.run("UPDATE batches SET status='done', updated_at=? WHERE id=? AND status='review'", (db.now(), batch_id))


def cancel_batch(owner_id: str, batch_id: str, actor: str) -> None:
    get_batch(owner_id, batch_id)
    with db.tx():
        db.run("UPDATE batches SET status='cancelled', updated_at=? WHERE id=?", (db.now(), batch_id))
        db.run("UPDATE proposals SET status='rejected' WHERE batch_id=? AND status='pending'", (batch_id,))
        db.audit(actor, "batch_cancelled", owner_id, batch_id)


# ---------------- link media (manual links) ----------------
@handler("link_media")
def link_media(payload: dict) -> None:
    l = db.one("SELECT * FROM links WHERE id=?", (payload["link_id"],))
    if not l:
        return
    p = db.one("SELECT * FROM photos WHERE id=?", (l["photo_id"],))
    if not p:
        return
    bbox = db.loads(l.get("bbox"))
    src = p["sha256"]
    crop_sha = None
    if bbox:
        crop_sha = media.crop(src, bbox)["sha"]
        src = crop_sha
    cut = None
    if l["role"] in ("shows", "detail") and not p.get("ai"):
        try:
            cut = cutout.cutout(src)
        except Exception as exc:
            log.warning("cutout failed: %s", exc)
    with db.tx():
        db.update("links", l["id"], {"crop_sha": crop_sha, "cutout_sha": cut["sha"] if cut else None})
        item = db.one("SELECT * FROM items WHERE id=?", (l["item_id"],))
        if item and db.loads(item.get("colors"), []) == []:
            cols = colors.dominant(cut["sha"] if cut else src)
            if cols:
                db.update("items", item["id"], {"colors": cols, "color_names": " " + " ".join(c["name"] for c in cols) + " "})
                catalog.index_item(item["id"])
