"""MCP server (streamable HTTP, JSON responses): POST /mcp with `Authorization: Bearer <api token>`.

Every tool wraps the same functions the web app uses, so an agent sees and writes exactly what the
owner sees. Tokens are created in Settings -> Agents and every write records the token label.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import auth, catalog, db, ingest, studio
from .config import settings
from .taxonomy import CATEGORIES, OCCASIONS, PHOTO_KINDS, SEASONS, STATUSES, taxonomy

router = APIRouter()
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

INSTRUCTIONS = f"""A personal wardrobe: clothes, footwear, bags and accessories, with photos.
Photos and items are separate: one photo can show many items (a flat-lay on a bed), one item can have many
photos (product shot, worn photo, tag photo, AI pictures). Links join them with a role
(shows | worn | tag | receipt | detail | generated) and an optional box [x0,y0,x1,y1] (0..1).

Find: wardrobe_search (text + filters: category, color, season, occasion, brand, status), wardrobe_get_item.
Photos of the owner wearing things: wardrobe_list_photos with kind="worn", person="me".

Import a folder of photos (the main workflow):
1. wardrobe_create_import with a note and only the purchase details the owner actually gave
   (store, price, original_price, currency, purchase_date...) as hints. Never invent prices or stores.
2. Upload the files: run the returned curl command (multipart, many -F files=@... per call) or use
   wardrobe_add_photo_urls / wardrobe_add_photo_base64. Duplicates are skipped automatically.
3. Poll wardrobe_import_status until status is "review" (the server classifies each photo, finds every item
   with boxes, cuts out backgrounds, reads tags/receipts and groups the same garment across photos).
4. Review the proposals with the owner if unsure; fix with wardrobe_update_proposal or wardrobe_merge_proposals,
   then wardrobe_commit_import (which="confident" or "all", or a list of proposal ids).
If the server has no vision configured, create items yourself with wardrobe_add_item and photo_links.

AI pictures (Studio): wardrobe_templates, wardrobe_generate (template + item_ids). They are queued and made with
the owner's ChatGPT subscription; wardrobe_generation_queue lists, cancels, retries, pauses or resumes.
Try-on: wardrobe_try_on edits one of the owner's own photos (photo_id, e.g. from wardrobe_list_photos with
person=me, kind=worn) so they wear the chosen items; everything else in the photo stays the same unless options say otherwise.
Ask the owner before deleting anything. Link the owner to items as {settings.public_url}/item/<item_id>."""

S = {"type": "string"}
I = {"type": "integer"}
SA = {"type": "array", "items": {"type": "string"}}
FILTERS = {
    "q": {"type": "string", "description": "free text (name, brand, colour, notes...)"},
    "category": {"type": "string", "description": f"comma list of {list(CATEGORIES)}"},
    "subcategory": S,
    "color": {"type": "string", "description": "comma list of colour names, e.g. navy,white"},
    "season": {"type": "string", "description": f"comma list of {SEASONS}"},
    "occasion": {"type": "string", "description": f"comma list, e.g. {OCCASIONS}"},
    "brand": S, "size": S,
    "status": {"type": "string", "description": f"comma list of {STATUSES} or 'all' (default: everything still owned)"},
    "favorite": {"type": "boolean"},
    "has_worn": {"type": "boolean", "description": "only items with a photo of the owner wearing them"},
    "sort": {"type": "string", "enum": ["recent", "oldest", "name", "worn_most", "worn_least", "price_high", "price_low",
                                         "category"]},
    "limit": I, "offset": I,
}
ITEM_FIELDS = {
    "name": S, "category": {"type": "string", "enum": list(CATEGORIES)}, "subcategory": S,
    "colors": {"type": "array", "items": {"type": "string"}, "description": "colour names, most dominant first"},
    "pattern": S, "material": S, "seasons": SA, "occasions": SA, "styles": SA, "tags": SA,
    "formality": {"type": "integer", "minimum": 1, "maximum": 5}, "fit": S, "size": S, "size_system": S, "brand": S,
    "status": {"type": "string", "enum": STATUSES}, "location": S, "favorite": {"type": "boolean"}, "notes": S,
    "store": {"type": "string", "description": "only if the owner said so or a receipt shows it"},
    "store_url": S, "purchase_date": {"type": "string", "description": "YYYY-MM-DD"},
    "price": {"type": "number", "description": "price paid, only if given"},
    "original_price": {"type": "number", "description": "MRP/original price, only if given or on the tag"},
    "currency": {"type": "string", "description": "ISO code, default INR"}, "gifted_by": S,
}
HINTS = {"type": "object", "description": "applies to every item in the import; only what the owner said",
         "properties": {k: ITEM_FIELDS[k] for k in ["store", "store_url", "purchase_date", "price", "original_price",
                                                    "currency", "gifted_by", "occasions", "seasons", "brand", "size",
                                                    "location", "notes", "tags"]}}
LINKS = {"type": "array", "items": {"type": "object", "properties": {
    "photo_id": S, "role": {"type": "string", "enum": ["shows", "worn", "tag", "receipt", "detail"]},
    "bbox": {"type": "array", "items": {"type": "number"}, "description": "[x0,y0,x1,y1] 0..1, optional"}},
    "required": ["photo_id"]}}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOLS = [
    {"name": "wardrobe_search", "description": "Search items with filters. Returns compact items and facet counts.",
     "inputSchema": _schema(FILTERS), "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_get_item", "description": "Everything about one item, including all its photos and links.",
     "inputSchema": _schema({"item_id": S}, ["item_id"]), "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_list_photos", "description": "List photos. kind: " + ", ".join(PHOTO_KINDS) +
     ". person='me' for photos the owner appears in. source: real | ai | all.",
     "inputSchema": _schema({"kind": S, "person": S, "source": {"type": "string", "enum": ["real", "ai", "all"]},
                             "item_id": S, "batch_id": S, "unlinked": {"type": "boolean"}, "limit": I, "offset": I}),
     "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_get_photo", "description": "One photo with its item links, boxes and the vision analysis.",
     "inputSchema": _schema({"photo_id": S}, ["photo_id"]), "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_create_import", "description": "Start an import batch. Returns batch_id, a one-time upload_url "
     "and a ready curl command for uploading local files.",
     "inputSchema": _schema({"note": S, "hints": HINTS,
                             "auto_commit": {"type": "string", "enum": ["none", "confident", "all"]},
                             "analyze": {"type": "boolean", "description": "default true; false = you will describe items yourself"}})},
    {"name": "wardrobe_add_photo_urls", "description": "Add photos to an import from public https URLs.",
     "inputSchema": _schema({"batch_id": S, "urls": SA}, ["batch_id", "urls"])},
    {"name": "wardrobe_add_photo_base64", "description": "Add one photo to an import as base64 (small images only; "
     "prefer the curl upload for folders).",
     "inputSchema": _schema({"batch_id": S, "filename": S, "data": S}, ["batch_id", "data"])},
    {"name": "wardrobe_import_status", "description": "Status of an import: photo analysis progress, proposals "
     "(new items or matches to existing items) and photos nothing was found in.",
     "inputSchema": _schema({"batch_id": S}, ["batch_id"]), "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_update_proposal", "description": "Edit a proposal before committing: data fields, or "
     "match_item_id to add its photos to an existing item instead (null = new item).",
     "inputSchema": _schema({"proposal_id": S, "data": {"type": "object", "properties": ITEM_FIELDS},
                             "match_item_id": {"type": ["string", "null"]}}, ["proposal_id"])},
    {"name": "wardrobe_merge_proposals", "description": "Merge proposals that are the same item.",
     "inputSchema": _schema({"ids": SA}, ["ids"])},
    {"name": "wardrobe_reject_proposal", "description": "Drop a proposal (nothing is created).",
     "inputSchema": _schema({"proposal_id": S}, ["proposal_id"])},
    {"name": "wardrobe_commit_import", "description": "Create/update items from proposals: which='confident' "
     "(default) | 'all', or proposals=[ids].",
     "inputSchema": _schema({"batch_id": S, "which": {"type": "string", "enum": ["confident", "all"]},
                             "proposals": SA}, ["batch_id"])},
    {"name": "wardrobe_add_item", "description": "Create an item directly, optionally linking photos (with boxes; the "
     "server crops and removes the background).",
     "inputSchema": _schema({**ITEM_FIELDS, "photo_links": LINKS}, ["name"])},
    {"name": "wardrobe_update_item", "description": "Change any item fields (only the ones you pass).",
     "inputSchema": _schema({"item_id": S, **ITEM_FIELDS}, ["item_id"])},
    {"name": "wardrobe_link_photo", "description": "Link a photo to an item with a role and optional box.",
     "inputSchema": _schema({"photo_id": S, "item_id": S,
                             "role": {"type": "string", "enum": ["shows", "worn", "tag", "receipt", "detail"]},
                             "bbox": {"type": "array", "items": {"type": "number"}}}, ["photo_id", "item_id"])},
    {"name": "wardrobe_mark_worn", "description": "Record that the owner wore an item today.",
     "inputSchema": _schema({"item_id": S}, ["item_id"])},
    {"name": "wardrobe_delete_item", "description": "Delete an item. Ask the owner first; pass confirm=true.",
     "inputSchema": _schema({"item_id": S, "confirm": {"type": "boolean"}}, ["item_id", "confirm"]),
     "annotations": {"destructiveHint": True}},
    {"name": "wardrobe_templates", "description": "AI picture templates (e.g. me-lifestyle, white-bg-cloth-only, "
     "me-white-bg). 'needs_person' templates use the owner's model photo.",
     "inputSchema": _schema({}), "annotations": {"readOnlyHint": True}},
    {"name": "wardrobe_generate", "description": "Queue AI pictures: one job per item (or one outfit job for "
     "multi-item templates). Generated with the owner's ChatGPT subscription through a queue.",
     "inputSchema": _schema({"template": S, "item_ids": SA, "person_photo_id": S, "extra": S,
                             "engine": {"type": "string", "enum": ["chatgpt", "openrouter"]}}, ["template", "item_ids"])},
    {"name": "wardrobe_try_on", "description": "Edit one of the owner's photos so they wear other items from the "
     "wardrobe; by default only the clothes change. Options: background keep|tidy|studio|blur|scene (+scene text), "
     "keep_rest, light, smooth, crop original|card|square|tight, transparent, cover (make it the item's main "
     "picture), variants 1-3, extra (free text, e.g. 'remove the bag on the bed').",
     "inputSchema": _schema({"photo_id": S, "item_ids": SA, "options": {"type": "object"},
                             "engine": {"type": "string", "enum": ["chatgpt", "openrouter"]}}, ["photo_id", "item_ids"])},
    {"name": "wardrobe_generation_queue", "description": "Studio queue: action list (default) | cancel | retry | pause "
     "| resume. Shows usage, limits and whether ChatGPT is connected.",
     "inputSchema": _schema({"action": {"type": "string", "enum": ["list", "cancel", "retry", "pause", "resume"]},
                             "job_ids": SA})},
    {"name": "wardrobe_taxonomy", "description": "Allowed categories, colours, seasons, occasions, kinds.",
     "inputSchema": _schema({}), "annotations": {"readOnlyHint": True}},
]


def _abs(url: str | None) -> str | None:
    return f"{settings.public_url}{url}" if url and url.startswith("/") else url


def _compact(it: dict) -> dict:
    return {"id": it["id"], "name": it["name"], "category": it.get("category"), "subcategory": it.get("subcategory"),
            "colors": [c["name"] for c in it.get("colors") or []], "seasons": it.get("seasons"),
            "occasions": it.get("occasions"), "brand": it.get("brand"), "size": it.get("size"),
            "status": it.get("status"), "favorite": it.get("favorite"), "price": it.get("price"),
            "original_price": it.get("original_price"), "store": it.get("store"),
            "photos": it.get("photo_count"), "worn_photos": it.get("worn_count_photos"),
            "image": _abs((it.get("cover") or {}).get("md")), "url": f"{settings.public_url}/item/{it['id']}"}


def _public_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("only https URLs are allowed")
    for info in socket.getaddrinfo(u.hostname, 443):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("that URL points to a private address")


def _fetch(url: str) -> bytes:
    _public_url(url)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        res = client.get(url, headers={"User-Agent": "wardrobe-import/1.0"})
    if res.status_code != 200:
        raise ValueError(f"download failed ({res.status_code})")
    if len(res.content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("file too large")
    return res.content


def call(name: str, a: dict, ctx: auth.Ctx) -> Any:
    o = ctx.owner_id
    if name == "wardrobe_search":
        res = catalog.search(o, {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in a.items()}, ctx.uid)
        return {"total": res["total"], "items": [_compact(i) for i in res["items"]],
                "facets": {k: v[:12] for k, v in res["facets"].items() if v}}
    if name == "wardrobe_get_item":
        it = catalog.item_out(catalog.get_item(o, a["item_id"]), full=True)
        it["url"] = f"{settings.public_url}/item/{it['id']}"
        return json.loads(json.dumps(it, default=str).replace('"/media/', f'"{settings.public_url}/media/'))
    if name == "wardrobe_list_photos":
        params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in a.items()}
        res = catalog.list_photos(o, params, ctx.uid)
        return {"total": res["total"], "kinds": res["kinds"],
                "photos": [{"id": p["id"], "kind": p["kind"], "ai": p["ai"], "template": p.get("template"),
                            "image": _abs(p["image"]["md"]), "taken_at": p.get("taken_at"),
                            "items": [{"item_id": l["item_id"], "name": (l.get("item") or {}).get("name"), "role": l["role"]}
                                      for l in p.get("links") or []]} for p in res["photos"]]}
    if name == "wardrobe_get_photo":
        p = catalog.photo_full(o, a["photo_id"])
        return json.loads(json.dumps(p, default=str).replace('"/media/', f'"{settings.public_url}/media/'))
    if name == "wardrobe_taxonomy":
        return taxonomy()
    if name == "wardrobe_templates":
        return {"templates": [{k: t[k] for k in ("id", "name", "group", "description", "needs_person", "multi_item")}
                              for t in studio.templates(o) if not t.get("tryon")],
                "model_photos": studio.prefs(o)["model_photo_ids"]}
    if name == "wardrobe_import_status":
        v = ingest.batch_view(o, a["batch_id"])
        return {"batch": v["batch"],
                "proposals": [{"id": p["id"], "status": p["status"], "confidence": p["confidence"],
                               "data": {k: v2 for k, v2 in p["data"].items() if v2 not in (None, "", [])},
                               "match": p["match"], "photos": [{"photo_id": l["photo_id"], "role": l["role"]} for l in p["links"]],
                               "preview": _abs((p.get("preview") or {}).get("md"))} for p in v["proposals"]],
                "unassigned_photos": [{"id": p["id"], "kind": p["kind"], "status": p["status"], "error": p.get("error"),
                                       "image": _abs(p["image"]["md"])} for p in v["photos"] if not p["assigned"]]}
    # ---- writes ----
    ctx.need_write()
    if name == "wardrobe_create_import":
        b = ingest.create_batch(o, ctx.actor, a.get("note"), a.get("hints"), a.get("auto_commit") or "none",
                                a.get("analyze", True))
        tok = ingest.upload_token(o, b["id"], ctx.actor)
        url = f"{settings.public_url}/api/v1/upload/{tok}"
        return {"batch_id": b["id"], "analyze": bool(b["analyze"]), "upload_url": url, "expires_in_minutes": 180,
                "curl": f"curl -sS -F 'files=@/path/IMG_1.jpg' -F 'files=@/path/IMG_2.heic' {url}",
                "tip": "Upload up to ~20 files per curl call; repeat for the rest. Then poll wardrobe_import_status."}
    if name == "wardrobe_add_photo_urls":
        files, errors = [], []
        for u in (a.get("urls") or [])[:50]:
            try:
                files.append((u.rsplit("/", 1)[-1][:80] or "photo", _fetch(u)))
            except Exception as exc:
                errors.append({"url": u, "error": str(exc)})
        return {"results": ingest.add_photos(o, a["batch_id"], files, ctx.actor), "errors": errors}
    if name == "wardrobe_add_photo_base64":
        data = a["data"].split(",", 1)[-1]
        return {"results": ingest.add_photos(o, a["batch_id"], [(a.get("filename") or "photo.jpg", base64.b64decode(data))],
                                             ctx.actor)}
    if name == "wardrobe_update_proposal":
        body = {k: a[k] for k in ("data", "match_item_id") if k in a}
        return ingest.update_proposal(o, a["proposal_id"], body, ctx.actor)
    if name == "wardrobe_merge_proposals":
        return ingest.merge_proposals(o, a["ids"], ctx.actor)
    if name == "wardrobe_reject_proposal":
        return ingest.reject_proposal(o, a["proposal_id"], ctx.actor)
    if name == "wardrobe_commit_import":
        res = ingest.commit_batch(o, a["batch_id"], a.get("proposals") or a.get("which") or "confident", ctx.actor)
        res["item_urls"] = [f"{settings.public_url}/item/{i}" for i in res["items"] if i]
        return res
    if name == "wardrobe_add_item":
        links = a.pop("photo_links", None) or []
        item = catalog.create_item(o, a, ctx.actor, "agent")
        for l in links:
            catalog.add_link(o, l["photo_id"], item["id"], l.get("role") or "shows", l.get("bbox"), ctx.actor)
        studio.on_item_created(o, item["id"])
        return _compact(catalog.item_out(catalog.get_item(o, item["id"])))
    if name == "wardrobe_update_item":
        iid = a.pop("item_id")
        return _compact(catalog.item_out(catalog.update_item(o, iid, a, ctx.actor, "agent")))
    if name == "wardrobe_link_photo":
        catalog.add_link(o, a["photo_id"], a["item_id"], a.get("role") or "shows", a.get("bbox"), ctx.actor)
        return {"ok": True, "url": f"{settings.public_url}/item/{a['item_id']}"}
    if name == "wardrobe_mark_worn":
        it = catalog.mark_worn(o, a["item_id"], ctx.actor)
        return {"ok": True, "wear_count": it["wear_count"]}
    if name == "wardrobe_delete_item":
        if a.get("confirm") is not True:
            raise ValueError("ask the owner, then call again with confirm=true")
        catalog.delete_item(o, a["item_id"], ctx.actor)
        return {"ok": True}
    if name == "wardrobe_generate":
        jobs = studio.enqueue(o, a["template"], a["item_ids"], ctx.actor, "agent", a.get("person_photo_id"),
                              a.get("engine"), a.get("extra") or "")
        ok, reason = studio.availability(o)
        return {"queued": [{"id": j["id"], "status": j["status"], "items": db.loads(j["item_ids"], [])} for j in jobs],
                "will_run_now": ok, "waiting_because": reason or None,
                "studio_url": f"{settings.public_url}/studio"}
    if name == "wardrobe_try_on":
        jobs = studio.enqueue_tryon(o, a["photo_id"], a["item_ids"], a.get("options") or {}, ctx.actor, "agent",
                                    a.get("engine"))
        ok, reason = studio.availability(o)
        return {"queued": [{"id": j["id"], "status": j["status"]} for j in jobs], "will_run_now": ok,
                "waiting_because": reason or None, "try_on_url": f"{settings.public_url}/tryon"}
    if name == "wardrobe_generation_queue":
        action = a.get("action") or "list"
        if action == "cancel":
            studio.cancel(o, a.get("job_ids"), ctx.actor)
        elif action == "retry":
            for j in a.get("job_ids") or []:
                studio.retry(o, j, ctx.actor)
        elif action in ("pause", "resume"):
            studio.save_prefs(o, {"paused": action == "pause"}, ctx.actor)
        ov = studio.overview(o)
        return {"available": ov["available"], "reason": ov["reason"], "paused": ov["prefs"]["paused"],
                "account": {k: ov["account"].get(k) for k in ("status", "email", "plan", "limits")},
                "usage": ov["usage"], "counts": ov["counts"],
                "jobs": [{"id": j["id"], "status": j["status"], "template": j["template"],
                          "items": [i["name"] for i in j.get("items") or []], "error": j.get("error"),
                          "result": _abs((j.get("result") or {}).get("md"))} for j in ov["jobs"][:40]]}
    raise ValueError(f"unknown tool {name}")


def handle(message: Any, ctx: auth.Ctx) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    ident, method, params = message.get("id"), message.get("method"), message.get("params") or {}
    if ident is None:
        return None
    if method == "initialize":
        v = params.get("protocolVersion")
        result = {"protocolVersion": v if v in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "wardrobe", "version": "1.0"}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            value, error = call(params.get("name"), dict(params.get("arguments") or {}), ctx), False
        except HTTPException as exc:
            value, error = {"error": exc.detail, "status": exc.status_code}, True
        except (ValueError, KeyError, TypeError) as exc:
            value, error = {"error": str(exc)}, True
        text = json.dumps(value, ensure_ascii=False, default=str)
        result = {"content": [{"type": "text", "text": text}], "isError": error}
        if isinstance(value, dict):
            result["structuredContent"] = json.loads(text)
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


@router.post("/mcp")
def mcp(request: Request, body: Any = Body(None)):
    ctx = auth.optional(request)
    if ctx is None or ctx.via == "session":
        return JSONResponse({"error": "unauthorized: use Authorization: Bearer <token from Settings -> Agents>"},
                            status_code=401, headers={"WWW-Authenticate": "Bearer"})
    auth.resolve_owner(ctx, request.headers.get("x-wardrobe"))
    message = body
    if isinstance(message, list):
        replies = [r for r in (handle(m, ctx) for m in message) if r]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = handle(message, ctx)
    return Response(status_code=202) if reply is None else JSONResponse(reply)


@router.get("/mcp")
def mcp_get():
    return JSONResponse({"error": "use POST /mcp (JSON responses, no SSE stream)"}, status_code=405)
