"""ASGI app: REST API, MCP, media and the single-page web app.

    uvicorn wardrobe.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from . import api, auth, db, ingest, jobs, mcp, media, studio  # noqa: F401  (ingest/studio register job handlers)
from .config import settings

logging.basicConfig(level=os.environ.get("WARDROBE_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("wardrobe")
WEB_DIR = Path(os.environ.get("WARDROBE_WEB_DIR", Path(__file__).resolve().parents[2] / "web" / "dist"))
_stop = threading.Event()


def _inline_worker() -> None:
    from . import worker
    worker.run(_stop.is_set)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.migrate()
    auth.ensure_owner()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    thread = None
    if settings.run_worker_inline:
        thread = threading.Thread(target=_inline_worker, name="wardrobe-worker", daemon=True)
        thread.start()
    log.info("wardrobe ready: %s (auth: %s)", settings.public_url, ",".join(settings.auth_modes))
    yield
    _stop.set()


app = FastAPI(title="Wardrobe", version="1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")
app.include_router(api.router)
app.include_router(api.worker_router)
app.include_router(mcp.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.get("/healthz")
def healthz():
    db.scalar("SELECT 1")
    return {"ok": True, "jobs": jobs.counts(), "worker": studio.worker_state().get("online", False)}


def _can_see(ctx: auth.Ctx, sha: str) -> bool:
    owners = [ctx.uid] + [r["owner_id"] for r in db.q("SELECT owner_id FROM shares WHERE member_id=?", (ctx.uid,))]
    marks = ",".join("?" * len(owners))
    if db.scalar(f"SELECT 1 FROM photos WHERE sha256=? AND owner_id IN ({marks}) LIMIT 1", (sha, *owners)):
        return True
    return bool(db.scalar(f"SELECT 1 FROM links l JOIN photos p ON p.id=l.photo_id WHERE (l.crop_sha=? OR l.cutout_sha=?) "
                          f"AND p.owner_id IN ({marks}) LIMIT 1", (sha, sha, *owners)))


@app.get("/media/{sha}/{size}")
def media_file(sha: str, size: str, request: Request):
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha) or size not in ("sm", "md", "lg", "full"):
        raise HTTPException(404)
    ctx = auth.optional(request)
    if ctx is None:
        raise HTTPException(401, "sign in required")
    if not _can_see(ctx, sha):
        raise HTTPException(404)
    p = media.path(sha, size) or media.path(sha, "full")
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "private, max-age=31536000, immutable"})


LLMS = """# Wardrobe

A personal wardrobe catalogue with photos, filters and an AI picture studio.

- MCP (streamable HTTP, JSON): POST {url}/mcp with `Authorization: Bearer <token>` (Settings -> Agents)
- REST: {url}/api/v1 (OpenAPI: {url}/api/openapi.json), same bearer token
- Upload a folder: create an import (POST /api/v1/batches or the MCP tool wardrobe_create_import), then
  `curl -F files=@a.jpg -F files=@b.heic <upload_url>`; poll the batch, review, commit.
"""


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    return LLMS.format(url=settings.public_url)


# ---------------- web app ----------------
@app.get("/{path:path}")
def spa(path: str):
    if path.startswith(("api/", "mcp", "media/")):
        raise HTTPException(404)
    if not WEB_DIR.is_dir():
        return PlainTextResponse("Web app not built. Run `npm run build` in web/ or use the API at /api/docs.", 503)
    target = (WEB_DIR / path).resolve()
    if path and target.is_file() and WEB_DIR.resolve() in target.parents:
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache})
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.head("/healthz")
def healthz_head():
    return Response()
