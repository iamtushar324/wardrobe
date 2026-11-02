"""Items, photos and the links between them, plus search and facet counts.

A photo can show many items (a flat-lay on the bed), an item can appear in many photos (product shot,
worn photo, tag photo, AI picture). The `links` table joins them with a role and an optional box.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from fastapi import HTTPException

from . import db, media
from .taxonomy import INACTIVE, LINK_ROLES, PALETTE, PHOTO_KINDS, STATUSES, norm_category, norm_color, norm_season

ITEM_TEXT = ["name", "category", "subcategory", "pattern", "material", "fit", "size", "size_system", "brand",
             "status", "location", "notes", "store", "store_url", "purchase_date", "currency", "gifted_by"]
ITEM_LISTS = ["seasons", "occasions", "styles", "tags"]
ITEM_NUM = ["price", "original_price", "formality"]
PURCHASE = ["store", "store_url", "purchase_date", "price", "original_price", "currency", "gifted_by"]


# ---------------- serialisation ----------------
def media_url(sha: str | None, size: str = "md") -> str | None:
    return f"/media/{sha}/{size}" if sha else None


def _image(sha: str | None) -> dict | None:
    if not sha:
        return None
    return {"sha": sha, "sm": media_url(sha, "sm"), "md": media_url(sha, "md"), "lg": media_url(sha, "lg"),
            "full": media_url(sha, "full")}


def _link_image(link: dict, photo: dict | None) -> str | None:
    return link.get("cutout_sha") or link.get("crop_sha") or (photo or {}).get("sha256")


def cover_for(item: dict, links: list[dict] | None = None, photos: dict[str, dict] | None = None) -> dict | None:
    links = links if links is not None else db.q("SELECT * FROM links WHERE item_id=?", (item["id"],))
    if not links:
        return None
    if photos is None:
        ids = list({l["photo_id"] for l in links})
        photos = {p["id"]: p for p in db.q(f"SELECT * FROM photos WHERE id IN ({','.join('?' * len(ids))}) "
                                           "AND deleted_at IS NULL", ids)}
    links = [l for l in links if l["photo_id"] in photos]
    chosen = next((l for l in links if l["id"] == item.get("cover_link_id")), None)
    if chosen is None:
        def rank(l: dict) -> tuple:
            p = photos[l["photo_id"]]
            role_rank = {"shows": 0, "generated": 2, "detail": 3, "worn": 4, "tag": 6, "receipt": 7}.get(l["role"], 5)
            if l["role"] == "generated" and p.get("template") in ("white-bg-cloth-only", "ghost-mannequin", "flat-lay"):
                role_rank = 1
            return (role_rank, 0 if l.get("cutout_sha") else 1, -(l.get("created_at") or 0))
        chosen = min(links, key=rank)
    photo = photos[chosen["photo_id"]]
    img = _image(_link_image(chosen, photo))
    if img:
        img["cutout"] = bool(chosen.get("cutout_sha"))
        img["ai"] = bool(photo.get("ai"))
        img["link_id"] = chosen["id"]
    return img


def item_out(row: dict, links: list[dict] | None = None, photos: dict[str, dict] | None = None,
             full: bool = False) -> dict:
    out: dict[str, Any] = {k: row.get(k) for k in ["id", "owner_id", *ITEM_TEXT, *ITEM_NUM, "favorite", "wear_count",
                                                     "last_worn_at", "created_at", "updated_at", "created_by",
                                                     "cover_link_id"]}
    out["favorite"] = bool(row.get("favorite"))
    out["colors"] = db.loads(row.get("colors"), [])
    for k in ITEM_LISTS:
        out[k] = db.loads(row.get(k), [])
    out["provenance"] = db.loads(row.get("provenance"), {})
    out["cover"] = cover_for(row, links, photos)
    if links is not None:
        out["photo_count"] = len({l["photo_id"] for l in links})
        out["worn_count_photos"] = len({l["photo_id"] for l in links if l["role"] == "worn"})
        out["ai_count"] = len({l["photo_id"] for l in links if l["role"] == "generated"})
    if full:
        out["photos"] = item_photos(row["id"])
    return out


def item_photos(item_id: str) -> list[dict]:
    rows = db.q("""SELECT l.id AS link_id, l.role, l.bbox, l.crop_sha, l.cutout_sha, l.confidence, l.confirmed,
                          p.id AS photo_id, p.sha256, p.kind, p.ai, p.template, p.width, p.height, p.taken_at,
                          p.created_at, p.source
                   FROM links l JOIN photos p ON p.id=l.photo_id
                   WHERE l.item_id=? AND p.deleted_at IS NULL ORDER BY p.created_at DESC""", (item_id,))
    out = []
    for r in rows:
        out.append({"link_id": r["link_id"], "role": r["role"], "bbox": db.loads(r["bbox"]),
                    "confidence": r["confidence"], "confirmed": bool(r["confirmed"]),
                    "photo": {"id": r["photo_id"], "kind": r["kind"], "ai": bool(r["ai"]), "template": r["template"],
                              "width": r["width"], "height": r["height"], "taken_at": r["taken_at"],
                              "created_at": r["created_at"], "source": r["source"], "image": _image(r["sha256"])},
                    "crop": _image(r["crop_sha"]), "cutout": _image(r["cutout_sha"])})
    return out


def photo_out(p: dict, links: list[dict] | None = None, items: dict[str, dict] | None = None,
              people: list[str] | None = None) -> dict:
    out = {k: p.get(k) for k in ["id", "owner_id", "kind", "source", "template", "gen_job_id", "width", "height",
                                  "taken_at", "filename", "note", "batch_id", "status", "error", "created_at",
                                  "created_by"]}
    out["ai"] = bool(p.get("ai"))
    out["image"] = _image(p["sha256"])
    if people is not None:
        out["people"] = people
    if links is not None:
        out["links"] = [{"id": l["id"], "item_id": l["item_id"], "role": l["role"], "bbox": db.loads(l["bbox"]),
                         "confidence": l["confidence"], "confirmed": bool(l["confirmed"]),
                         "crop": _image(l.get("crop_sha")), "cutout": _image(l.get("cutout_sha")),
                         "item": ({"id": items[l["item_id"]]["id"], "name": items[l["item_id"]]["name"],
                                   "category": items[l["item_id"]]["category"]} if items and l["item_id"] in items
                                  else None)} for l in links]
    return out


# ---------------- items ----------------
def get_item(owner_id: str, item_id: str) -> dict:
    row = db.one("SELECT * FROM items WHERE id=? AND owner_id=? AND deleted_at IS NULL", (item_id, owner_id))
    if not row:
        raise HTTPException(404, "item not found")
    return row


def clean_item_fields(data: dict, partial: bool = True) -> dict:
    """Validate and normalise item fields coming from the UI, an agent or the vision model."""
    out: dict[str, Any] = {}
    for k in ITEM_TEXT:
        if k in data:
            v = data[k]
            out[k] = (str(v).strip()[:500] or None) if v not in (None, "") else None
    for k in ITEM_NUM:
        if k in data:
            v = data[k]
            if v in (None, ""):
                out[k] = None
            else:
                try:
                    out[k] = float(str(v).replace(",", "").replace("₹", "").strip()) if k != "formality" else max(1, min(5, int(v)))
                except (TypeError, ValueError):
                    raise HTTPException(422, f"{k} must be a number")
    for k in ITEM_LISTS:
        if k in data:
            v = data[k] or []
            if isinstance(v, str):
                v = [s for s in re.split(r"[,;]", v)]
            vals = [str(s).strip().lower() for s in v if str(s).strip()]
            if k == "seasons":
                vals = [s for s in (norm_season(x) for x in vals) if s]
            out[k] = sorted(set(vals), key=vals.index)
    if "category" in out or "subcategory" in out:
        cat, sub = norm_category(out.get("category", data.get("category")), out.get("subcategory", data.get("subcategory")))
        out["category"], out["subcategory"] = cat, sub
    if "status" in out and out["status"] not in STATUSES:
        out["status"] = "active"
    if "currency" in out and out["currency"]:
        out["currency"] = out["currency"].upper()[:3]
    if "colors" in data:
        cols = []
        for c in data["colors"] or []:
            if isinstance(c, dict):
                n = norm_color(c.get("name"))
                if n:
                    cols.append({"name": n, "hex": c.get("hex") or PALETTE.get(n, "#999999"), "share": c.get("share")})
            else:
                n = norm_color(str(c))
                if n:
                    cols.append({"name": n, "hex": PALETTE.get(n, "#999999"), "share": None})
        seen, uniq = set(), []
        for c in cols:
            if c["name"] not in seen:
                seen.add(c["name"])
                uniq.append(c)
        out["colors"] = uniq
        out["color_names"] = " " + " ".join(c["name"] for c in uniq) + " "
    if "favorite" in data:
        out["favorite"] = bool(data["favorite"])
    if not partial and not out.get("name"):
        out["name"] = (out.get("subcategory") or out.get("category") or "Item").capitalize()
    return out


def index_item(item_id: str) -> None:
    row = db.one("SELECT * FROM items WHERE id=?", (item_id,))
    db.run("DELETE FROM items_fts WHERE item_id=?", (item_id,))
    if not row or row.get("deleted_at"):
        return
    parts = [row.get(k) or "" for k in ITEM_TEXT]
    parts += [" ".join(db.loads(row.get(k), [])) for k in ITEM_LISTS]
    parts.append(row.get("color_names") or "")
    db.run("INSERT INTO items_fts(item_id, body) VALUES (?,?)", (item_id, " ".join(p for p in parts if p)))


def create_item(owner_id: str, data: dict, actor: str, provenance_source: str = "user") -> dict:
    fields = clean_item_fields(data, partial=False)
    now = db.now()
    prov = {k: provenance_source for k in fields if k in PURCHASE and fields.get(k) not in (None, "")}
    prov.update(data.get("provenance") or {})
    row = {"id": db.new_id("itm"), "owner_id": owner_id, "created_at": now, "updated_at": now, "created_by": actor,
           "provenance": prov, **fields}
    with db.tx():
        db.insert("items", row)
        index_item(row["id"])
        db.audit(actor, "item_created", owner_id, row["id"], {"name": row.get("name")})
    return get_item(owner_id, row["id"])


def update_item(owner_id: str, item_id: str, data: dict, actor: str, provenance_source: str = "user") -> dict:
    item = get_item(owner_id, item_id)
    fields = clean_item_fields(data)
    if "cover_link_id" in data:
        lid = data["cover_link_id"]
        if lid and not db.one("SELECT 1 FROM links WHERE id=? AND item_id=?", (lid, item_id)):
            raise HTTPException(422, "that photo is not linked to this item")
        fields["cover_link_id"] = lid or None
    if not fields:
        return item
    prov = db.loads(item.get("provenance"), {})
    for k in PURCHASE:
        if k in fields:
            if fields[k] in (None, ""):
                prov.pop(k, None)
            else:
                prov[k] = (data.get("provenance") or {}).get(k, provenance_source)
    fields["provenance"] = prov
    fields["updated_at"] = db.now()
    with db.tx():
        db.update("items", item_id, fields)
        index_item(item_id)
        db.audit(actor, "item_updated", owner_id, item_id, {k: v for k, v in fields.items() if k != "provenance"})
    return get_item(owner_id, item_id)


def delete_item(owner_id: str, item_id: str, actor: str) -> None:
    get_item(owner_id, item_id)
    with db.tx():
        db.run("UPDATE items SET deleted_at=?, updated_at=? WHERE id=?", (db.now(), db.now(), item_id))
        db.run("DELETE FROM links WHERE item_id=?", (item_id,))
        index_item(item_id)
        db.audit(actor, "item_deleted", owner_id, item_id)


def mark_worn(owner_id: str, item_id: str, actor: str) -> dict:
    get_item(owner_id, item_id)
    with db.tx():
        db.run("UPDATE items SET wear_count=wear_count+1, last_worn_at=?, updated_at=? WHERE id=?",
               (db.now(), db.now(), item_id))
        db.audit(actor, "item_worn", owner_id, item_id)
    return get_item(owner_id, item_id)


# ---------------- search ----------------
def _csv(v: str | list | None) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return [x.strip().lower() for x in str(v).split(",") if x.strip()]


FILTERS = ["category", "subcategory", "color", "season", "occasion", "brand", "status", "size", "style", "material",
           "pattern"]


def _match(row: dict, dim: str, wanted: list[str]) -> bool:
    if not wanted:
        return True
    if dim == "color":
        return any(f" {w} " in (row.get("color_names") or "") for w in wanted)
    if dim == "season":
        seasons = db.loads(row.get("seasons"), [])
        return any(w in seasons or "all-season" in seasons for w in wanted)
    if dim in ("occasion", "style"):
        vals = db.loads(row.get(dim + "s"), [])
        return any(w in vals for w in wanted)
    if dim == "status":
        if "all" in wanted:
            return True
        return (row.get("status") or "active") in wanted
    return (row.get(dim) or "").lower() in wanted


def _facet_values(row: dict, dim: str) -> list[str]:
    if dim == "color":
        return (row.get("color_names") or "").split()
    if dim in ("season", "occasion", "style"):
        return db.loads(row.get(dim + "s"), [])
    v = row.get(dim)
    return [v.lower()] if v else []


def search(owner_id: str, params: dict, me: str | None = None) -> dict:
    rows = db.q("SELECT * FROM items WHERE owner_id=? AND deleted_at IS NULL", (owner_id,))
    q = (params.get("q") or "").strip()
    if q:
        terms = [re.sub(r"[^\w\-]", "", t) for t in q.split()]
        terms = [t for t in terms if t]
        if terms:
            match = " ".join(f'"{t}"*' for t in terms)
            ids = {r["item_id"] for r in db.q("SELECT item_id FROM items_fts WHERE items_fts MATCH ?", (match,))}
            rows = [r for r in rows if r["id"] in ids]
    wanted = {d: _csv(params.get(d)) for d in FILTERS}
    wanted["color"] = [norm_color(c) or c for c in wanted["color"]]
    if not wanted["status"]:
        wanted["status"] = [s for s in STATUSES if s not in INACTIVE]
    flags = {"favorite": str(params.get("favorite", "")).lower() in ("1", "true", "yes"),
             "has_worn": str(params.get("has_worn", "")).lower() in ("1", "true", "yes"),
             "has_ai": str(params.get("has_ai", "")).lower() in ("1", "true", "yes"),
             "no_photo": str(params.get("no_photo", "")).lower() in ("1", "true", "yes")}
    ids = [r["id"] for r in rows]
    links_by_item: dict[str, list[dict]] = {i: [] for i in ids}
    photos: dict[str, dict] = {}
    if ids:
        for l in db.q("SELECT l.* FROM links l JOIN photos p ON p.id=l.photo_id WHERE p.deleted_at IS NULL "
                      "AND p.owner_id=?", (owner_id,)):
            if l["item_id"] in links_by_item:
                links_by_item[l["item_id"]].append(l)
        photos = {p["id"]: p for p in db.q("SELECT * FROM photos WHERE owner_id=? AND deleted_at IS NULL", (owner_id,))}

    def flag_ok(r: dict) -> bool:
        ls = links_by_item.get(r["id"], [])
        if flags["favorite"] and not r.get("favorite"):
            return False
        if flags["has_worn"] and not any(l["role"] == "worn" for l in ls):
            return False
        if flags["has_ai"] and not any(l["role"] == "generated" for l in ls):
            return False
        if flags["no_photo"] and ls:
            return False
        return True

    rows = [r for r in rows if flag_ok(r)]
    facets: dict[str, list[dict]] = {}
    for dim in ["category", "color", "season", "occasion", "brand", "status", "style", "size", "material", "pattern"]:
        others = [r for r in rows if all(_match(r, d, w) for d, w in wanted.items() if d != dim)]
        c = Counter(v for r in others for v in _facet_values(r, dim))
        facets[dim] = [{"value": k, "count": n} for k, n in c.most_common()]
    rows = [r for r in rows if all(_match(r, d, w) for d, w in wanted.items())]
    sort = params.get("sort") or "recent"
    keyf = {
        "recent": lambda r: -(r.get("created_at") or 0),
        "oldest": lambda r: r.get("created_at") or 0,
        "name": lambda r: (r.get("name") or "").lower(),
        "worn_most": lambda r: -(r.get("wear_count") or 0),
        "worn_least": lambda r: (r.get("wear_count") or 0, r.get("last_worn_at") or 0),
        "price_high": lambda r: -(r.get("price") or r.get("original_price") or 0),
        "price_low": lambda r: (r.get("price") or r.get("original_price") or 1e12),
        "category": lambda r: (r.get("category") or "zz", r.get("subcategory") or "", (r.get("name") or "").lower()),
    }.get(sort, lambda r: -(r.get("created_at") or 0))
    rows.sort(key=keyf)
    total = len(rows)
    limit = max(1, min(int(params.get("limit") or 60), 500))
    offset = max(0, int(params.get("offset") or 0))
    page = rows[offset:offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "facets": facets,
            "items": [item_out(r, links_by_item.get(r["id"], []), photos) for r in page]}


# ---------------- photos ----------------
def get_photo(owner_id: str, photo_id: str) -> dict:
    p = db.one("SELECT * FROM photos WHERE id=? AND owner_id=? AND deleted_at IS NULL", (photo_id, owner_id))
    if not p:
        raise HTTPException(404, "photo not found")
    return p


def photo_full(owner_id: str, photo_id: str) -> dict:
    p = get_photo(owner_id, photo_id)
    links = db.q("SELECT * FROM links WHERE photo_id=? ORDER BY created_at", (photo_id,))
    ids = list({l["item_id"] for l in links})
    items = {i["id"]: i for i in db.q(f"SELECT id,name,category FROM items WHERE id IN ({','.join('?' * len(ids))}) "
                                      "AND deleted_at IS NULL", ids)} if ids else {}
    links = [l for l in links if l["item_id"] in items]
    people = [r["user_id"] for r in db.q("SELECT user_id FROM photo_people WHERE photo_id=?", (photo_id,))]
    out = photo_out(p, links, items, people)
    out["analysis"] = db.loads(p.get("analysis"))
    return out


def list_photos(owner_id: str, params: dict, me: str) -> dict:
    where, args = ["p.owner_id=?", "p.deleted_at IS NULL"], [owner_id]
    kinds = _csv(params.get("kind"))
    if kinds:
        where.append(f"p.kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    person = params.get("person")
    if person:
        pid = me if person == "me" else person
        where.append("p.id IN (SELECT photo_id FROM photo_people WHERE user_id=?)")
        args.append(pid)
    source = params.get("source") or "all"
    if source == "real":
        where.append("p.ai=0")
    elif source == "ai":
        where.append("p.ai=1")
    if params.get("item_id"):
        where.append("p.id IN (SELECT photo_id FROM links WHERE item_id=?)")
        args.append(params["item_id"])
    if params.get("batch_id"):
        where.append("p.batch_id=?")
        args.append(params["batch_id"])
    if params.get("template"):
        where.append("p.template=?")
        args.append(params["template"])
    if str(params.get("unlinked", "")).lower() in ("1", "true"):
        where.append("p.id NOT IN (SELECT photo_id FROM links)")
    # Item filters narrow photos to those showing a matching item.
    item_params = {k: params.get(k) for k in FILTERS + ["q"] if params.get(k)}
    item_ids: set[str] | None = None
    if item_params:
        item_params["limit"] = 100000
        item_ids = {i["id"] for i in search(owner_id, item_params)["items"]}
    sql = f"SELECT p.* FROM photos p WHERE {' AND '.join(where)} ORDER BY COALESCE(p.taken_at, p.created_at) DESC"
    rows = db.q(sql, args)
    pids = [r["id"] for r in rows]
    links_by_photo: dict[str, list[dict]] = {}
    if pids:
        for l in db.q("SELECT l.* FROM links l JOIN photos p ON p.id=l.photo_id WHERE p.owner_id=?", (owner_id,)):
            links_by_photo.setdefault(l["photo_id"], []).append(l)
    if item_ids is not None:
        rows = [r for r in rows if any(l["item_id"] in item_ids for l in links_by_photo.get(r["id"], []))]
    total = len(rows)
    limit = max(1, min(int(params.get("limit") or 60), 500))
    offset = max(0, int(params.get("offset") or 0))
    page = rows[offset:offset + limit]
    ids = list({l["item_id"] for r in page for l in links_by_photo.get(r["id"], [])})
    items = {i["id"]: i for i in db.q(f"SELECT id,name,category FROM items WHERE id IN ({','.join('?' * len(ids))}) "
                                      "AND deleted_at IS NULL", ids)} if ids else {}
    kinds_count = Counter(r["kind"] for r in db.q("SELECT kind FROM photos WHERE owner_id=? AND deleted_at IS NULL",
                                                  (owner_id,)))
    return {"total": total, "offset": offset, "limit": limit, "kinds": dict(kinds_count),
            "photos": [photo_out(r, [l for l in links_by_photo.get(r["id"], []) if l["item_id"] in items], items)
                       for r in page]}


def add_photo(owner_id: str, raw: bytes, actor: str, *, filename: str | None = None, kind: str = "unknown",
              batch_id: str | None = None, note: str | None = None, source: str = "upload", ai: bool = False,
              template: str | None = None, gen_job_id: str | None = None, status: str = "ready",
              people: list[str] | None = None) -> tuple[dict, bool]:
    """Store an uploaded image. Returns (photo row, created). Re-uploading the same image returns the old row."""
    info = media.ingest(raw)
    existing = db.one("SELECT * FROM photos WHERE owner_id=? AND sha256=? AND deleted_at IS NULL", (owner_id, info["sha"]))
    if existing:
        return existing, False
    row = {"id": db.new_id("pho"), "owner_id": owner_id, "sha256": info["sha"], "kind": kind if kind in PHOTO_KINDS else "unknown",
           "source": source, "ai": ai, "template": template, "gen_job_id": gen_job_id, "width": info["width"],
           "height": info["height"], "taken_at": info.get("taken_at"), "filename": (filename or "")[:200] or None,
           "note": note, "batch_id": batch_id, "status": status, "created_by": actor, "created_at": db.now()}
    with db.tx():
        db.insert("photos", row)
        for uid in people or []:
            db.run("INSERT OR IGNORE INTO photo_people(photo_id,user_id) VALUES(?,?)", (row["id"], uid))
        db.audit(actor, "photo_added", owner_id, row["id"], {"kind": row["kind"], "batch": batch_id, "ai": ai})
    return row, True


def update_photo(owner_id: str, photo_id: str, data: dict, actor: str) -> dict:
    get_photo(owner_id, photo_id)
    fields = {}
    if "kind" in data:
        if data["kind"] not in PHOTO_KINDS:
            raise HTTPException(422, "unknown photo kind")
        fields["kind"] = data["kind"]
    if "note" in data:
        fields["note"] = (data["note"] or "")[:1000] or None
    with db.tx():
        if fields:
            db.update("photos", photo_id, fields)
        if "people" in data:
            db.run("DELETE FROM photo_people WHERE photo_id=?", (photo_id,))
            for uid in data["people"] or []:
                if db.one("SELECT 1 FROM users WHERE id=?", (uid,)):
                    db.run("INSERT OR IGNORE INTO photo_people(photo_id,user_id) VALUES(?,?)", (photo_id, uid))
        db.audit(actor, "photo_updated", owner_id, photo_id, data)
    return photo_full(owner_id, photo_id)


def delete_photo(owner_id: str, photo_id: str, actor: str) -> None:
    get_photo(owner_id, photo_id)
    with db.tx():
        db.run("UPDATE photos SET deleted_at=? WHERE id=?", (db.now(), photo_id))
        db.run("DELETE FROM links WHERE photo_id=?", (photo_id,))
        db.run("DELETE FROM photo_people WHERE photo_id=?", (photo_id,))
        db.run("UPDATE items SET cover_link_id=NULL WHERE cover_link_id NOT IN (SELECT id FROM links)")
        db.audit(actor, "photo_deleted", owner_id, photo_id)


def add_link(owner_id: str, photo_id: str, item_id: str, role: str, bbox: list | None, actor: str,
             crop_sha: str | None = None, cutout_sha: str | None = None, confidence: float | None = None,
             confirmed: bool = True, enqueue_cutout: bool = True) -> dict:
    get_photo(owner_id, photo_id)
    get_item(owner_id, item_id)
    if role not in LINK_ROLES:
        raise HTTPException(422, f"role must be one of {LINK_ROLES}")
    if bbox is not None:
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox)):
            raise HTTPException(422, "bbox must be [x0, y0, x1, y1] between 0 and 1")
        x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in bbox]
        if x1 <= x0 or y1 <= y0:
            raise HTTPException(422, "bbox must have x1 > x0 and y1 > y0")
        bbox = [x0, y0, x1, y1]
    dup = db.one("SELECT * FROM links WHERE photo_id=? AND item_id=? AND role=?", (photo_id, item_id, role))
    if dup and bbox is None:
        return dup
    row = {"id": db.new_id("lnk"), "photo_id": photo_id, "item_id": item_id, "role": role, "bbox": bbox,
           "crop_sha": crop_sha, "cutout_sha": cutout_sha, "confidence": confidence, "confirmed": confirmed,
           "created_at": db.now()}
    with db.tx():
        db.insert("links", row)
        db.run("UPDATE items SET updated_at=? WHERE id=?", (db.now(), item_id))
        db.audit(actor, "photo_linked", owner_id, row["id"], {"photo": photo_id, "item": item_id, "role": role})
        if enqueue_cutout and role in ("shows", "worn", "detail") and not cutout_sha:
            from .jobs import enqueue
            enqueue("link_media", {"link_id": row["id"]})
    return db.one("SELECT * FROM links WHERE id=?", (row["id"],))


def update_link(owner_id: str, link_id: str, data: dict, actor: str) -> dict:
    l = db.one("SELECT l.* FROM links l JOIN photos p ON p.id=l.photo_id WHERE l.id=? AND p.owner_id=?",
               (link_id, owner_id))
    if not l:
        raise HTTPException(404, "link not found")
    fields: dict = {}
    if "role" in data:
        if data["role"] not in LINK_ROLES:
            raise HTTPException(422, "unknown role")
        fields["role"] = data["role"]
    if "item_id" in data:
        get_item(owner_id, data["item_id"])
        fields["item_id"] = data["item_id"]
    if "bbox" in data:
        fields["bbox"] = data["bbox"]
        fields["crop_sha"] = None
        fields["cutout_sha"] = None
    fields["confirmed"] = True
    with db.tx():
        db.update("links", link_id, fields)
        db.audit(actor, "link_updated", owner_id, link_id, data)
        if "bbox" in data and data["bbox"]:
            from .jobs import enqueue
            enqueue("link_media", {"link_id": link_id})
    return db.one("SELECT * FROM links WHERE id=?", (link_id,))


def delete_link(owner_id: str, link_id: str, actor: str) -> None:
    l = db.one("SELECT l.* FROM links l JOIN photos p ON p.id=l.photo_id WHERE l.id=? AND p.owner_id=?",
               (link_id, owner_id))
    if not l:
        raise HTTPException(404, "link not found")
    with db.tx():
        db.run("DELETE FROM links WHERE id=?", (link_id,))
        db.run("UPDATE items SET cover_link_id=NULL WHERE cover_link_id=?", (link_id,))
        db.audit(actor, "link_deleted", owner_id, link_id)


def stats(owner_id: str) -> dict:
    n_items = db.scalar("SELECT COUNT(*) FROM items WHERE owner_id=? AND deleted_at IS NULL", (owner_id,))
    n_photos = db.scalar("SELECT COUNT(*) FROM photos WHERE owner_id=? AND deleted_at IS NULL", (owner_id,))
    n_ai = db.scalar("SELECT COUNT(*) FROM photos WHERE owner_id=? AND deleted_at IS NULL AND ai=1", (owner_id,))
    pending = db.scalar("SELECT COUNT(*) FROM proposals WHERE owner_id=? AND status='pending'", (owner_id,))
    value = db.one("SELECT COALESCE(SUM(price),0) AS paid, COALESCE(SUM(original_price),0) AS mrp FROM items "
                   "WHERE owner_id=? AND deleted_at IS NULL", (owner_id,))
    return {"items": n_items, "photos": n_photos, "ai_photos": n_ai, "pending_proposals": pending,
            "paid_total": value["paid"], "mrp_total": value["mrp"]}
