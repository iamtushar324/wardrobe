"""Background jobs in a SQLite table (no Redis).

The worker process (`python -m wardrobe.worker`) claims one job at a time. Handlers register with
@handler("kind"). Failed jobs retry with back-off up to MAX_ATTEMPTS.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Callable

from . import db

log = logging.getLogger("wardrobe.jobs")
MAX_ATTEMPTS = 3
STALE_AFTER = 900  # a running job older than this was abandoned (worker restart)
HANDLERS: dict[str, Callable[[dict], None]] = {}


class Retry(Exception):
    """Raise to retry later without counting it as a failure (e.g. waiting for something)."""

    def __init__(self, delay: float = 10.0, message: str = ""):
        super().__init__(message)
        self.delay = delay


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(kind: str, payload: dict, delay: float = 0.0, dedupe: bool = True) -> str:
    body = json.dumps(payload, sort_keys=True)
    if dedupe:
        dup = db.one("SELECT id FROM jobs WHERE kind=? AND payload=? AND status IN ('queued','running')", (kind, body))
        if dup:
            return dup["id"]
    jid = db.new_id("job")
    db.insert("jobs", {"id": jid, "kind": kind, "payload": body, "run_after": db.now() + delay, "created_at": db.now()})
    return jid


def claim() -> dict | None:
    now = db.now()
    with db.tx():
        db.run("UPDATE jobs SET status='queued', locked_at=NULL WHERE status='running' AND locked_at<?", (now - STALE_AFTER,))
        row = db.one("SELECT * FROM jobs WHERE status='queued' AND run_after<=? ORDER BY run_after, created_at LIMIT 1", (now,))
        if not row:
            return None
        db.run("UPDATE jobs SET status='running', locked_at=?, attempts=attempts+1 WHERE id=?", (now, row["id"]))
    row["attempts"] += 1
    return row


def run_one() -> bool:
    job = claim()
    if not job:
        return False
    fn = HANDLERS.get(job["kind"])
    payload = db.loads(job["payload"], {})
    try:
        if fn is None:
            raise RuntimeError(f"no handler for {job['kind']}")
        fn(payload)
        with db.tx():
            db.run("UPDATE jobs SET status='done', finished_at=?, error=NULL WHERE id=?", (db.now(), job["id"]))
    except Retry as r:
        with db.tx():
            db.run("UPDATE jobs SET status='queued', attempts=attempts-1, run_after=?, error=? WHERE id=?",
                   (db.now() + r.delay, str(r)[:500] or None, job["id"]))
    except Exception as exc:
        log.warning("job %s %s failed: %s", job["kind"], job["id"], exc)
        err = f"{type(exc).__name__}: {exc}"[:800]
        done = job["attempts"] >= MAX_ATTEMPTS
        with db.tx():
            if done:
                db.run("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?", (db.now(), err, job["id"]))
            else:
                db.run("UPDATE jobs SET status='queued', run_after=?, error=? WHERE id=?",
                       (db.now() + 20 * job["attempts"] ** 2, err, job["id"]))
        if done:
            on_fail = HANDLERS.get(job["kind"] + ":failed")
            if on_fail:
                try:
                    on_fail({**payload, "_error": err})
                except Exception:
                    log.error("failure hook crashed: %s", traceback.format_exc())
    return True


def loop(stop: Callable[[], bool] = lambda: False, idle: float = 1.5) -> None:
    while not stop():
        try:
            if not run_one():
                time.sleep(idle)
        except Exception:
            log.error("worker loop error: %s", traceback.format_exc())
            time.sleep(5)


def counts() -> dict:
    rows = db.q("SELECT kind, status, COUNT(*) AS n FROM jobs WHERE status IN ('queued','running') GROUP BY kind, status")
    return {f"{r['kind']}:{r['status']}": r["n"] for r in rows}
