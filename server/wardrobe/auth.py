"""Who is calling, and whose wardrobe they are looking at.

People sign in with one of the configured methods (Clerk/Google, ChatGPT device code, owner password,
or `none` for local development). Only invited emails may sign in; the owner is invited at startup.
After sign-in the app issues its own signed, HttpOnly session cookie.

Agents use personal API tokens (`Authorization: Bearer wd_...`) created in Settings -> Agents; every
write records the token label. The host image worker has its own token that only reaches /api/worker/*.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import HTTPException, Request, Response

from . import db
from .config import settings

COOKIE = "wd_session"
SESSION_TTL = 30 * 24 * 3600
CLIENT_HEADER = "x-wardrobe-client"


@dataclass
class Ctx:
    user: dict
    via: str                      # session | token | dev
    label: str = ""               # token label for agents
    scopes: set[str] = field(default_factory=lambda: {"read", "write"})
    owner_id: str = ""            # whose wardrobe this request acts on
    can_edit: bool = True

    @property
    def uid(self) -> str:
        return self.user["id"]

    @property
    def actor(self) -> str:
        if self.via == "token":
            return f"agent:{self.label}:{self.user['email']}"
        return f"web:{self.user['email']}"

    @property
    def is_agent(self) -> bool:
        return self.via == "token"

    def need_write(self) -> None:
        if "write" not in self.scopes:
            raise HTTPException(403, "this token is read-only")
        if not self.can_edit:
            raise HTTPException(403, "you can view this wardrobe but not edit it")


# ---------------- users ----------------
def ensure_owner() -> dict:
    with db.tx():
        u = db.one("SELECT * FROM users WHERE role='owner' ORDER BY created_at LIMIT 1")
        if u is None:
            u = db.one("SELECT * FROM users WHERE email=?", (settings.owner_email,))
            if u is None:
                u = {"id": db.new_id("usr"), "email": settings.owner_email, "name": settings.owner_name,
                     "role": "owner", "status": "active", "prefs": "{}", "created_at": db.now()}
                db.insert("users", u)
            else:
                db.update("users", u["id"], {"role": "owner", "status": "active"})
        return db.one("SELECT * FROM users WHERE id=?", (u["id"],))


def get_user(uid: str) -> dict | None:
    return db.one("SELECT * FROM users WHERE id=?", (uid,))


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u.get("name") or u["email"].split("@")[0],
            "avatar_url": u.get("avatar_url"), "role": u["role"], "status": u["status"]}


def sign_in(email: str, method: str, name: str = "", avatar: str | None = None) -> dict:
    email = (email or "").strip().lower()
    u = db.one("SELECT * FROM users WHERE email=?", (email,))
    if u is None or u["status"] == "disabled":
        raise HTTPException(403, f"{email or 'this account'} is not invited to this wardrobe")
    fields: dict = {"status": "active", "last_login_at": db.now()}
    if name and not u.get("name"):
        fields["name"] = name
    if avatar:
        fields["avatar_url"] = avatar
    with db.tx():
        db.update("users", u["id"], fields)
        db.audit(f"web:{email}", "sign_in", u["id"], detail={"method": method})
    return get_user(u["id"])


# ---------------- session cookie ----------------
def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(settings.session_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def _unsign(value: str) -> dict | None:
    try:
        body, mac = value.rsplit(".", 1)
        good = hmac.new(settings.session_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, good):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload if payload.get("exp", 0) > time.time() else None
    except Exception:
        return None


def start_session(response: Response, user: dict, method: str, user_agent: str = "") -> None:
    sid = db.new_id("ses")
    exp = db.now() + SESSION_TTL
    with db.tx():
        db.insert("sessions", {"id": sid, "user_id": user["id"], "method": method, "user_agent": user_agent[:200],
                               "created_at": db.now(), "expires_at": exp})
    response.set_cookie(COOKIE, _sign({"sid": sid, "uid": user["id"], "exp": int(exp)}), max_age=SESSION_TTL,
                        httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")


def end_session(request: Request, response: Response) -> None:
    payload = _unsign(request.cookies.get(COOKIE, ""))
    if payload:
        with db.tx():
            db.run("UPDATE sessions SET revoked=1 WHERE id=?", (payload.get("sid"),))
    response.delete_cookie(COOKIE, path="/")


# ---------------- API tokens ----------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(user_id: str, label: str, scopes: str = "read,write") -> tuple[dict, str]:
    raw = "wd_" + secrets.token_urlsafe(32)
    row = {"id": db.new_id("tok"), "user_id": user_id, "label": label[:40] or "agent", "prefix": raw[:9],
           "token_hash": _hash(raw), "scopes": scopes, "created_at": db.now()}
    with db.tx():
        db.insert("api_tokens", row)
        db.audit(f"user:{user_id}", "token_created", user_id, row["id"], {"label": row["label"], "scopes": scopes})
    row.pop("token_hash")
    return row, raw


def _token_ctx(token: str) -> Ctx | None:
    row = db.one("SELECT * FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL", (_hash(token),))
    if not row:
        return None
    u = get_user(row["user_id"])
    if not u or u["status"] == "disabled":
        return None
    if (row.get("last_used_at") or 0) < db.now() - 300:
        with db.tx():
            db.run("UPDATE api_tokens SET last_used_at=? WHERE id=?", (db.now(), row["id"]))
    return Ctx(u, "token", row["label"], set(row["scopes"].split(",")))


# ---------------- request -> context ----------------
def _base_ctx(request: Request) -> Ctx | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return _token_ctx(auth[7:].strip())
    payload = _unsign(request.cookies.get(COOKIE, ""))
    if payload:
        s = db.one("SELECT * FROM sessions WHERE id=? AND revoked=0 AND expires_at>?", (payload.get("sid"), db.now()))
        if s:
            u = get_user(s["user_id"])
            if u and u["status"] != "disabled":
                return Ctx(u, "session")
    if "none" in settings.auth_modes:
        return Ctx(ensure_owner(), "dev")
    return None


def resolve_owner(ctx: Ctx, wanted: str | None) -> Ctx:
    if not wanted or wanted in ("me", ctx.uid):
        ctx.owner_id, ctx.can_edit = ctx.uid, True
        return ctx
    share = db.one("SELECT * FROM shares WHERE owner_id=? AND member_id=?", (wanted, ctx.uid))
    if not share:
        raise HTTPException(403, "that wardrobe is not shared with you")
    ctx.owner_id, ctx.can_edit = wanted, bool(share["can_edit"])
    return ctx


def optional(request: Request) -> Ctx | None:
    return _base_ctx(request)


def require(request: Request) -> Ctx:
    ctx = _base_ctx(request)
    if ctx is None:
        raise HTTPException(401, "sign in required")
    if ctx.via == "session" and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get(CLIENT_HEADER) != "web":  # CSRF guard for cookie sessions
            raise HTTPException(403, "missing client header")
    return resolve_owner(ctx, request.headers.get("x-wardrobe") or request.query_params.get("wardrobe"))


def require_owner_role(request: Request) -> Ctx:
    ctx = require(request)
    if ctx.user["role"] != "owner":
        raise HTTPException(403, "only the wardrobe owner can do this")
    return ctx


def require_worker(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    expected = settings.worker_token
    if not expected or not auth.lower().startswith("bearer ") or not hmac.compare_digest(auth[7:].strip(), expected):
        raise HTTPException(403, "image worker token required")


# ---------------- Clerk (Google) ----------------
def frontend_api(publishable: str) -> str:
    enc = publishable.split("_", 2)[2] if publishable.count("_") >= 2 else ""
    raw = base64.b64decode(enc + "=" * (-len(enc) % 4)).decode()
    return raw.rstrip("$").lower()


_jwks: dict = {"keys": {}, "at": 0.0}


def _jwk(kid: str):
    if kid in _jwks["keys"]:
        return _jwks["keys"][kid]
    if time.time() - _jwks["at"] < 30:
        raise HTTPException(401, "unknown signing key")
    res = httpx.get(f"https://{frontend_api(settings.clerk_publishable)}/.well-known/jwks.json", timeout=10)
    if res.status_code != 200:
        raise HTTPException(503, "sign-in service unavailable")
    keys = {k["kid"]: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
            for k in res.json().get("keys", []) if k.get("kty") == "RSA" and k.get("kid")}
    _jwks.update(keys=keys, at=time.time())
    if kid not in keys:
        raise HTTPException(401, "unknown signing key")
    return keys[kid]


def verify_clerk(token: str) -> dict:
    """Verify a Clerk session JWT and return {email, name, avatar} of a verified primary email."""
    if "clerk" not in settings.auth_modes:
        raise HTTPException(400, "Google sign-in is not enabled")
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, _jwk(header.get("kid", "")), algorithms=["RS256"], leeway=10,
                            issuer=f"https://{frontend_api(settings.clerk_publishable)}",
                            options={"require": ["exp", "sub", "iss"], "verify_aud": False})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, "invalid sign-in token") from exc
    if (claims.get("azp") or "").rstrip("/").lower() != settings.public_url.lower():
        raise HTTPException(401, "token was issued for another site")
    res = httpx.get(f"https://api.clerk.com/v1/users/{claims['sub']}",
                    headers={"Authorization": f"Bearer {settings.clerk_secret}"}, timeout=10)
    if res.status_code != 200:
        raise HTTPException(503 if res.status_code >= 500 else 403, "could not confirm the account")
    user = res.json()
    if user.get("banned") or user.get("locked"):
        raise HTTPException(403, "account not allowed")
    email = next((e["email_address"] for e in user.get("email_addresses", [])
                  if e.get("id") == user.get("primary_email_address_id")
                  and (e.get("verification") or {}).get("status") == "verified"), "")
    if not email:
        raise HTTPException(403, "the account has no verified email")
    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
    return {"email": email.lower(), "name": name, "avatar": user.get("image_url")}


# ---------------- owner password (simple self-hosting) ----------------
def check_password(email: str, password: str) -> bool:
    if "password" not in settings.auth_modes:
        raise HTTPException(400, "password sign-in is not enabled")
    expected = settings.owner_password
    if not expected:
        return False
    owner = ensure_owner()
    return email.strip().lower() == owner["email"] and hmac.compare_digest(password.encode(), expected.encode())
