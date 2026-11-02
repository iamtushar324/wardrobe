"""REST API (/api/v1). The web app, the MCP server and the CLI all use these same functions."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from . import auth, catalog, db, ingest, media, studio, vision
from .auth import Ctx, require, require_owner_role, require_worker
from .config import settings
from .taxonomy import taxonomy

router = APIRouter(prefix="/api/v1")
worker_router = APIRouter(prefix="/api/worker", dependencies=[Depends(require_worker)])
LOGIN_COOKIE = "wd_login"
CONNECT_COOKIE = "wd_connect"


def _extra_occasions(owner_id: str) -> list[str]:
    u = db.one("SELECT prefs FROM users WHERE id=?", (owner_id,))
    return (db.loads(u["prefs"], {}) if u else {}).get("occasions") or []


# ---------------- session & config ----------------
@router.get("/config")
def config(request: Request):
    ctx = auth.optional(request)
    out: dict[str, Any] = {"site_name": settings.site_name, "auth_modes": settings.auth_modes,
                           "signed_in": ctx is not None, "public_url": settings.public_url}
    if "clerk" in settings.auth_modes and settings.clerk_publishable:
        out["clerk"] = {"publishable_key": settings.clerk_publishable,
                        "frontend_api": auth.frontend_api(settings.clerk_publishable)}
    out["chatgpt_available"] = "chatgpt" in settings.auth_modes and studio.worker_state()["online"]
    return out


@router.get("/me")
def me(ctx: Ctx = Depends(require)):
    shared = db.q("SELECT s.owner_id, s.can_edit, u.name, u.email FROM shares s JOIN users u ON u.id=s.owner_id "
                  "WHERE s.member_id=?", (ctx.uid,))
    return {"user": auth.public_user(ctx.user), "via": ctx.via, "label": ctx.label, "scopes": sorted(ctx.scopes),
            "wardrobe": ctx.owner_id, "can_edit": ctx.can_edit,
            "wardrobes": [{"owner_id": ctx.uid, "name": "My wardrobe", "can_edit": True}] +
                         [{"owner_id": s["owner_id"], "name": f"{s['name'] or s['email']}'s wardrobe",
                           "can_edit": bool(s["can_edit"])} for s in shared],
            "stats": catalog.stats(ctx.owner_id), "studio": studio.overview_counts_for_nav(ctx.owner_id),
            "vision": vision.available(), "taxonomy": taxonomy(_extra_occasions(ctx.owner_id))}


@router.post("/auth/clerk")
def auth_clerk(request: Request, response: Response, body: dict = Body(...)):
    info = auth.verify_clerk(body.get("token") or "")
    user = auth.sign_in(info["email"], "google", info.get("name", ""), info.get("avatar"))
    auth.start_session(response, user, "google", request.headers.get("user-agent", ""))
    return {"user": auth.public_user(user)}


@router.post("/auth/password")
def auth_password(request: Request, response: Response, body: dict = Body(...)):
    if not auth.check_password(body.get("email") or "", body.get("password") or ""):
        raise HTTPException(401, "wrong email or password")
    user = auth.sign_in(body["email"], "password")
    auth.start_session(response, user, "password", request.headers.get("user-agent", ""))
    return {"user": auth.public_user(user)}


@router.post("/auth/chatgpt/start")
def auth_chatgpt_start(request: Request, response: Response):
    nonce = secrets.token_urlsafe(24)
    st = studio.start_login("login", None, nonce)
    response.set_cookie(LOGIN_COOKIE, nonce, max_age=studio.LOGIN_TTL, httponly=True, secure=settings.secure_cookies,
                        samesite="lax", path="/api/v1/auth")
    return st


@router.get("/auth/chatgpt/{rid}")
def auth_chatgpt_status(rid: str, request: Request, response: Response):
    nonce = request.cookies.get(LOGIN_COOKIE, "")
    st = studio.login_status(rid, nonce)
    if st["status"] == "approved" and st["kind"] == "login":
        user = studio.consume_login(rid)
        if user:
            auth.start_session(response, user, "chatgpt", request.headers.get("user-agent", ""))
            response.delete_cookie(LOGIN_COOKIE, path="/api/v1/auth")
            st["status"] = "signed_in"
    return st


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.end_session(request, response)
    return {"ok": True}


@router.get("/taxonomy")
def get_taxonomy(ctx: Ctx = Depends(require)):
    return taxonomy(_extra_occasions(ctx.owner_id))


# ---------------- items ----------------
@router.get("/items")
def list_items(request: Request, ctx: Ctx = Depends(require)):
    return catalog.search(ctx.owner_id, dict(request.query_params), ctx.uid)


@router.post("/items")
def create_item(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    item = catalog.create_item(ctx.owner_id, body, ctx.actor)
    studio.on_item_created(ctx.owner_id, item["id"])
    return catalog.item_out(item, full=True)


@router.get("/items/{item_id}")
def get_item(item_id: str, ctx: Ctx = Depends(require)):
    return catalog.item_out(catalog.get_item(ctx.owner_id, item_id), full=True)


@router.patch("/items/{item_id}")
def patch_item(item_id: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return catalog.item_out(catalog.update_item(ctx.owner_id, item_id, body, ctx.actor), full=True)


@router.delete("/items/{item_id}")
def delete_item(item_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    catalog.delete_item(ctx.owner_id, item_id, ctx.actor)
    return {"ok": True}


@router.post("/items/{item_id}/wear")
def wear_item(item_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    return catalog.item_out(catalog.mark_worn(ctx.owner_id, item_id, ctx.actor), full=True)


@router.post("/items/{item_id}/photos")
def add_item_photos(item_id: str, files: list[UploadFile] = File(...), role: str = Form("shows"),
                    ctx: Ctx = Depends(require)):
    """Upload photos straight onto an item (no review)."""
    ctx.need_write()
    catalog.get_item(ctx.owner_id, item_id)
    out = []
    for f in files:
        try:
            photo, _ = catalog.add_photo(ctx.owner_id, f.file.read(), ctx.actor, filename=f.filename,
                                         kind="worn" if role == "worn" else ("tag" if role == "tag" else "product"),
                                         people=[ctx.owner_id] if role == "worn" else None)
        except media.BadImage as exc:
            out.append({"filename": f.filename, "error": str(exc)})
            continue
        link = catalog.add_link(ctx.owner_id, photo["id"], item_id, role, None, ctx.actor)
        out.append({"filename": f.filename, "photo_id": photo["id"], "link_id": link["id"]})
    return {"results": out, "item": catalog.item_out(catalog.get_item(ctx.owner_id, item_id), full=True)}


@router.get("/facets")
def facets(request: Request, ctx: Ctx = Depends(require)):
    params = dict(request.query_params)
    params["limit"] = 1
    res = catalog.search(ctx.owner_id, params, ctx.uid)
    return {"total": res["total"], "facets": res["facets"]}


@router.get("/stats")
def stats(ctx: Ctx = Depends(require)):
    return catalog.stats(ctx.owner_id)


# ---------------- photos & links ----------------
@router.get("/photos")
def list_photos(request: Request, ctx: Ctx = Depends(require)):
    return catalog.list_photos(ctx.owner_id, dict(request.query_params), ctx.uid)


@router.post("/photos")
def upload_photos(files: list[UploadFile] = File(...), kind: str = Form("unknown"), ctx: Ctx = Depends(require)):
    """Add photos without analysis (use batches for the analysed import)."""
    ctx.need_write()
    out = []
    for f in files:
        try:
            photo, created = catalog.add_photo(ctx.owner_id, f.file.read(), ctx.actor, filename=f.filename, kind=kind,
                                               people=[ctx.owner_id] if kind == "worn" else None)
            out.append({"filename": f.filename, "photo_id": photo["id"], "duplicate": not created})
        except media.BadImage as exc:
            out.append({"filename": f.filename, "error": str(exc)})
    return {"results": out}


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, ctx: Ctx = Depends(require)):
    return catalog.photo_full(ctx.owner_id, photo_id)


@router.patch("/photos/{photo_id}")
def patch_photo(photo_id: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return catalog.update_photo(ctx.owner_id, photo_id, body, ctx.actor)


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    catalog.delete_photo(ctx.owner_id, photo_id, ctx.actor)
    return {"ok": True}


@router.post("/photos/{photo_id}/links")
def link_photo(photo_id: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    """Link a photo to an item: {item_id, role, bbox?}. With a bbox the crop and cutout are made in the background."""
    ctx.need_write()
    link = catalog.add_link(ctx.owner_id, photo_id, body.get("item_id") or "", body.get("role") or "shows",
                            body.get("bbox"), ctx.actor)
    return catalog.photo_full(ctx.owner_id, link["photo_id"])


@router.patch("/links/{link_id}")
def patch_link(link_id: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    link = catalog.update_link(ctx.owner_id, link_id, body, ctx.actor)
    return catalog.photo_full(ctx.owner_id, link["photo_id"])


@router.delete("/links/{link_id}")
def delete_link(link_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    catalog.delete_link(ctx.owner_id, link_id, ctx.actor)
    return {"ok": True}


# ---------------- import batches ----------------
@router.post("/batches")
def create_batch(request: Request, body: dict = Body(default={}), ctx: Ctx = Depends(require)):
    ctx.need_write()
    b = ingest.create_batch(ctx.owner_id, ctx.actor, body.get("note"), body.get("hints"),
                            body.get("auto_commit") or "none", body.get("analyze", True))
    tok = ingest.upload_token(ctx.owner_id, b["id"], ctx.actor)
    url = f"{settings.public_url}/api/v1/upload/{tok}"
    return {**ingest.batch_out(b), "upload_url": url,
            "curl": f"curl -sS -F 'files=@photo1.jpg' -F 'files=@photo2.heic' {url}"}


@router.get("/batches")
def list_batches(ctx: Ctx = Depends(require)):
    return {"batches": ingest.list_batches(ctx.owner_id)}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, ctx: Ctx = Depends(require)):
    return ingest.batch_view(ctx.owner_id, batch_id)


@router.post("/batches/{batch_id}/photos")
def batch_photos(batch_id: str, files: list[UploadFile] = File(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    res = ingest.add_photos(ctx.owner_id, batch_id, [(f.filename or "photo", f.file.read()) for f in files], ctx.actor)
    return {"results": res, "batch": ingest.batch_out(ingest.get_batch(ctx.owner_id, batch_id))}


@router.post("/upload/{token}")
def upload_with_token(token: str, files: list[UploadFile] = File(...)):
    """One-time upload link for agents that cannot attach files to an MCP call."""
    t = ingest.check_upload_token(token)
    res = ingest.add_photos(t["owner_id"], t["batch_id"], [(f.filename or "photo", f.file.read()) for f in files], t["actor"])
    return {"batch_id": t["batch_id"], "results": res}


@router.post("/batches/{batch_id}/analyze")
def batch_analyze(batch_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    if not vision.available():
        raise HTTPException(409, "photo analysis is not configured on this server")
    return ingest.analyze_batch(ctx.owner_id, batch_id)


@router.post("/batches/{batch_id}/commit")
def batch_commit(batch_id: str, body: dict = Body(default={}), ctx: Ctx = Depends(require)):
    """Commit proposals: {"proposals": [ids]} or {"which": "confident"|"all"}."""
    ctx.need_write()
    which = body.get("proposals") or body.get("which") or "confident"
    return ingest.commit_batch(ctx.owner_id, batch_id, which, ctx.actor)


@router.delete("/batches/{batch_id}")
def batch_cancel(batch_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    ingest.cancel_batch(ctx.owner_id, batch_id, ctx.actor)
    return {"ok": True}


@router.patch("/proposals/{pid}")
def patch_proposal(pid: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return ingest.update_proposal(ctx.owner_id, pid, body, ctx.actor)


@router.post("/proposals/{pid}/accept")
def accept_proposal(pid: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    return ingest.commit_proposal(ctx.owner_id, pid, ctx.actor)


@router.post("/proposals/{pid}/reject")
def reject_proposal(pid: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    return ingest.reject_proposal(ctx.owner_id, pid, ctx.actor)


@router.post("/proposals/merge")
def merge_proposals(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return ingest.merge_proposals(ctx.owner_id, body.get("ids") or [], ctx.actor)


# ---------------- studio ----------------
@router.get("/studio")
def studio_overview(ctx: Ctx = Depends(require)):
    return studio.overview(ctx.owner_id)


@router.patch("/studio/prefs")
def studio_prefs(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.save_prefs(ctx.owner_id, body, ctx.actor)


@router.post("/studio/jobs")
def studio_create(body: dict = Body(...), ctx: Ctx = Depends(require)):
    """Queue pictures: {template, item_ids:[...], person_photo_id?, engine?, extra?}."""
    ctx.need_write()
    jobs = studio.enqueue(ctx.owner_id, body.get("template") or "", body.get("item_ids") or [], ctx.actor,
                          "agent" if ctx.is_agent else "manual", body.get("person_photo_id"), body.get("engine"),
                          body.get("extra") or "", int(body.get("priority") or 0))
    return {"jobs": [studio.job_out(j) for j in jobs]}


@router.post("/studio/backfill")
def studio_backfill(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.backfill(ctx.owner_id, body.get("templates") or [], ctx.actor)


@router.post("/studio/cancel")
def studio_cancel(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return {"cancelled": studio.cancel(ctx.owner_id, body.get("ids"), ctx.actor, bool(body.get("all_queued")))}


@router.post("/studio/jobs/{job_id}/retry")
def studio_retry(job_id: str, body: dict = Body(default={}), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.job_out(studio.retry(ctx.owner_id, job_id, ctx.actor, body.get("engine")))


@router.post("/studio/jobs/{job_id}/top")
def studio_top(job_id: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.job_out(studio.move_top(ctx.owner_id, job_id, ctx.actor))


@router.post("/studio/clear")
def studio_clear(ctx: Ctx = Depends(require)):
    ctx.need_write()
    return {"removed": studio.clear_finished(ctx.owner_id)}


@router.post("/studio/templates")
def studio_template_new(body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.save_template(ctx.owner_id, body, ctx.actor)


@router.patch("/studio/templates/{tid}")
def studio_template_edit(tid: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    ctx.need_write()
    return studio.save_template(ctx.owner_id, body, ctx.actor, tid)


@router.delete("/studio/templates/{tid}")
def studio_template_delete(tid: str, ctx: Ctx = Depends(require)):
    ctx.need_write()
    studio.delete_template(ctx.owner_id, tid, ctx.actor)
    return {"ok": True}


@router.get("/chatgpt")
def chatgpt_status(ctx: Ctx = Depends(require)):
    return {"account": studio.account(ctx.uid), "worker": studio.worker_state()}


@router.post("/chatgpt/connect")
def chatgpt_connect(response: Response, ctx: Ctx = Depends(require)):
    if ctx.is_agent:
        raise HTTPException(403, "connect ChatGPT from the web app")
    nonce = secrets.token_urlsafe(24)
    st = studio.start_login("connect", ctx.uid, nonce)
    response.set_cookie(CONNECT_COOKIE, nonce, max_age=studio.LOGIN_TTL, httponly=True, secure=settings.secure_cookies,
                        samesite="lax", path="/api/v1/chatgpt")
    return st


@router.get("/chatgpt/connect/{rid}")
def chatgpt_connect_status(rid: str, request: Request, ctx: Ctx = Depends(require)):
    return studio.login_status(rid, request.cookies.get(CONNECT_COOKIE, ""))


@router.post("/chatgpt/disconnect")
def chatgpt_disconnect(ctx: Ctx = Depends(require)):
    if ctx.is_agent:
        raise HTTPException(403, "disconnect ChatGPT from the web app")
    studio.disconnect(ctx.uid, ctx.actor)
    return {"ok": True}


# ---------------- people, sharing, tokens ----------------
@router.get("/members")
def members(ctx: Ctx = Depends(require)):
    users = db.q("SELECT * FROM users ORDER BY role DESC, created_at")
    shares = db.q("SELECT * FROM shares WHERE owner_id=?", (ctx.uid,))
    return {"members": [auth.public_user(u) for u in users],
            "my_shares": [{"member_id": s["member_id"], "can_edit": bool(s["can_edit"])} for s in shares]}


@router.post("/members")
def invite(body: dict = Body(...), ctx: Ctx = Depends(require_owner_role)):
    email = (body.get("email") or "").strip().lower()
    if "@" not in email:
        raise HTTPException(422, "enter an email address")
    if db.one("SELECT 1 FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "already invited")
    row = {"id": db.new_id("usr"), "email": email, "name": (body.get("name") or "")[:80], "role": "member",
           "status": "invited", "prefs": "{}", "created_at": db.now()}
    with db.tx():
        db.insert("users", row)
        db.audit(ctx.actor, "member_invited", ctx.uid, row["id"], {"email": email})
    return auth.public_user(row)


@router.delete("/members/{uid}")
def remove_member(uid: str, ctx: Ctx = Depends(require_owner_role)):
    u = auth.get_user(uid)
    if not u or u["role"] == "owner":
        raise HTTPException(404, "member not found")
    with db.tx():
        db.update("users", uid, {"status": "disabled"})
        db.run("UPDATE sessions SET revoked=1 WHERE user_id=?", (uid,))
        db.run("UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (db.now(), uid))
        db.run("DELETE FROM shares WHERE member_id=? OR owner_id=?", (uid, uid))
        db.audit(ctx.actor, "member_removed", ctx.uid, uid)
    return {"ok": True}


@router.put("/shares/{member_id}")
def share(member_id: str, body: dict = Body(...), ctx: Ctx = Depends(require)):
    if ctx.is_agent:
        raise HTTPException(403, "manage sharing from the web app")
    if member_id == ctx.uid or not auth.get_user(member_id):
        raise HTTPException(404, "member not found")
    with db.tx():
        if body.get("level") in (None, "none"):
            db.run("DELETE FROM shares WHERE owner_id=? AND member_id=?", (ctx.uid, member_id))
        else:
            db.run("INSERT INTO shares(owner_id,member_id,can_edit,created_at) VALUES(?,?,?,?) ON CONFLICT(owner_id,member_id) "
                   "DO UPDATE SET can_edit=excluded.can_edit", (ctx.uid, member_id, int(body["level"] == "edit"), db.now()))
        db.audit(ctx.actor, "share_changed", ctx.uid, member_id, body)
    return {"ok": True}


@router.get("/tokens")
def tokens(ctx: Ctx = Depends(require)):
    rows = db.q("SELECT id,label,prefix,scopes,created_at,last_used_at,revoked_at FROM api_tokens WHERE user_id=? "
                "ORDER BY created_at DESC", (ctx.uid,))
    return {"tokens": rows}


@router.post("/tokens")
def new_token(body: dict = Body(...), ctx: Ctx = Depends(require)):
    if ctx.is_agent:
        raise HTTPException(403, "create tokens from the web app")
    scopes = "read" if body.get("read_only") else "read,write"
    row, raw = auth.create_token(ctx.uid, (body.get("label") or "agent").strip(), scopes)
    return {**row, "token": raw}


@router.delete("/tokens/{tid}")
def revoke_token(tid: str, ctx: Ctx = Depends(require)):
    with db.tx():
        n = db.run("UPDATE api_tokens SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL", (db.now(), tid, ctx.uid))
        db.audit(ctx.actor, "token_revoked", ctx.uid, tid)
    if not n:
        raise HTTPException(404, "token not found")
    return {"ok": True}


@router.patch("/prefs")
def patch_prefs(body: dict = Body(...), ctx: Ctx = Depends(require)):
    """Personal settings, e.g. extra occasion names: {"occasions": ["convocation"]}."""
    ctx.need_write()
    u = db.one("SELECT prefs FROM users WHERE id=?", (ctx.owner_id,))
    p = db.loads(u["prefs"], {}) if u else {}
    if "occasions" in body:
        p["occasions"] = [str(o).strip().lower()[:30] for o in body["occasions"] or [] if str(o).strip()][:30]
    with db.tx():
        db.run("UPDATE users SET prefs=? WHERE id=?", (db._enc(p), ctx.owner_id))
    return {"ok": True, "occasions": p.get("occasions", [])}


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), ctx: Ctx = Depends(require)):
    rows = db.q("SELECT * FROM audit WHERE owner_id=? ORDER BY id DESC LIMIT ?", (ctx.owner_id, limit))
    for r in rows:
        r["detail"] = db.loads(r["detail"])
    return {"events": rows}


# ---------------- host image worker ----------------
@worker_router.post("/heartbeat")
def w_heartbeat(body: dict = Body(...)):
    return studio.worker_heartbeat(body)


@worker_router.post("/claim")
def w_claim(body: dict = Body(default={})):
    return {"job": studio.worker_claim(body.get("ready_users") or [])}


@worker_router.get("/media/{sha}")
def w_media(sha: str):
    if not all(c in "0123456789abcdef" for c in sha) or len(sha) != 64:
        raise HTTPException(404)
    p = media.path(sha, "full")
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


@worker_router.post("/jobs/{job_id}/complete")
def w_complete(job_id: str, file: UploadFile = File(...), meta: str = Form("{}")):
    return studio.worker_complete(job_id, file.file.read(), db.loads(meta, {}) or {})


@worker_router.post("/jobs/{job_id}/fail")
def w_fail(job_id: str, body: dict = Body(...)):
    studio.worker_fail(job_id, body.get("error") or "failed", bool(body.get("limited")), bool(body.get("retry", True)))
    return {"ok": True}


@worker_router.post("/login/{rid}/code")
def w_login_code(rid: str, body: dict = Body(...)):
    studio.worker_login_code(rid, body.get("url") or "", body.get("code") or "")
    return {"ok": True}


@worker_router.post("/login/{rid}/done")
def w_login_done(rid: str, body: dict = Body(...)):
    return studio.worker_login_done(rid, body.get("email") or "", body.get("plan"))


@worker_router.post("/login/{rid}/fail")
def w_login_fail(rid: str, body: dict = Body(...)):
    studio.worker_login_failed(rid, body.get("message") or "sign-in failed")
    return {"ok": True}
