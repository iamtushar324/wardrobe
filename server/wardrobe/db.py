"""SQLite storage (WAL mode, one file on the data volume) with forward-only migrations.

The web process and the worker process share the same file; WAL lets them read while the other
writes. Each thread gets its own connection.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable

from .config import settings

MIGRATIONS: list[str] = [
    # 1: everything for the first release
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        name TEXT NOT NULL DEFAULT '',
        avatar_url TEXT,
        role TEXT NOT NULL DEFAULT 'member',          -- owner | member
        status TEXT NOT NULL DEFAULT 'invited',       -- invited | active | disabled
        prefs TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        last_login_at REAL
    );
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        method TEXT NOT NULL,
        user_agent TEXT,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE api_tokens (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        label TEXT NOT NULL,
        prefix TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        scopes TEXT NOT NULL DEFAULT 'read,write',
        created_at REAL NOT NULL,
        last_used_at REAL,
        revoked_at REAL
    );
    CREATE TABLE shares (
        owner_id TEXT NOT NULL,
        member_id TEXT NOT NULL,
        can_edit INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        PRIMARY KEY (owner_id, member_id)
    );
    CREATE TABLE photos (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'unknown',          -- flat_lay product worn tag receipt detail other unknown
        source TEXT NOT NULL DEFAULT 'upload',         -- upload | generated | agent
        ai INTEGER NOT NULL DEFAULT 0,
        template TEXT,
        gen_job_id TEXT,
        width INTEGER, height INTEGER,
        taken_at REAL,
        filename TEXT,
        note TEXT,
        batch_id TEXT,
        status TEXT NOT NULL DEFAULT 'ready',          -- queued | analyzing | ready | error
        analysis TEXT,
        error TEXT,
        created_by TEXT,
        created_at REAL NOT NULL,
        deleted_at REAL
    );
    CREATE UNIQUE INDEX photos_owner_sha ON photos(owner_id, sha256) WHERE deleted_at IS NULL;
    CREATE INDEX photos_owner_kind ON photos(owner_id, kind, created_at);
    CREATE INDEX photos_batch ON photos(batch_id);
    CREATE TABLE photo_people (
        photo_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        PRIMARY KEY (photo_id, user_id)
    );
    CREATE INDEX photo_people_user ON photo_people(user_id);
    CREATE TABLE items (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        category TEXT,
        subcategory TEXT,
        colors TEXT NOT NULL DEFAULT '[]',             -- [{name, hex, share}]
        color_names TEXT NOT NULL DEFAULT '',          -- " navy white " for filtering
        pattern TEXT,
        material TEXT,
        seasons TEXT NOT NULL DEFAULT '[]',
        occasions TEXT NOT NULL DEFAULT '[]',
        styles TEXT NOT NULL DEFAULT '[]',
        tags TEXT NOT NULL DEFAULT '[]',
        formality INTEGER,
        fit TEXT,
        size TEXT,
        size_system TEXT,
        brand TEXT,
        status TEXT NOT NULL DEFAULT 'active',         -- active laundry lent stored donated sold discarded
        location TEXT,
        favorite INTEGER NOT NULL DEFAULT 0,
        notes TEXT,
        cover_link_id TEXT,
        store TEXT, store_url TEXT, purchase_date TEXT,
        price REAL, original_price REAL, currency TEXT, gifted_by TEXT,
        provenance TEXT NOT NULL DEFAULT '{}',         -- field -> where the value came from
        wear_count INTEGER NOT NULL DEFAULT 0,
        last_worn_at REAL,
        created_by TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        deleted_at REAL
    );
    CREATE INDEX items_owner ON items(owner_id, deleted_at, created_at);
    CREATE VIRTUAL TABLE items_fts USING fts5(item_id UNINDEXED, body, tokenize = 'unicode61 remove_diacritics 2');
    CREATE TABLE links (
        id TEXT PRIMARY KEY,
        photo_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'shows',            -- shows worn tag receipt detail generated
        bbox TEXT,                                     -- [x0,y0,x1,y1] normalised 0..1
        crop_sha TEXT,
        cutout_sha TEXT,
        confidence REAL,
        confirmed INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    );
    CREATE INDEX links_item ON links(item_id);
    CREATE INDEX links_photo ON links(photo_id);
    CREATE TABLE batches (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        note TEXT,
        hints TEXT NOT NULL DEFAULT '{}',
        auto_commit TEXT NOT NULL DEFAULT 'none',      -- none | confident | all
        analyze INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'open',           -- open analyzing grouping review done cancelled
        message TEXT,
        created_by TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE proposals (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',        -- pending accepted rejected merged
        data TEXT NOT NULL DEFAULT '{}',
        links TEXT NOT NULL DEFAULT '[]',              -- [{photo_id, role, bbox, crop_sha, cutout_sha, confidence}]
        match_item_id TEXT,
        confidence REAL,
        reason TEXT,
        item_id TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX proposals_batch ON proposals(batch_id);
    CREATE TABLE upload_tokens (
        token_hash TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',         -- queued running done failed
        payload TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0,
        run_after REAL NOT NULL DEFAULT 0,
        error TEXT,
        locked_at REAL,
        created_at REAL NOT NULL,
        finished_at REAL
    );
    CREATE INDEX jobs_ready ON jobs(status, run_after);
    CREATE TABLE gen_jobs (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        requested_by TEXT,
        template TEXT NOT NULL,
        item_ids TEXT NOT NULL DEFAULT '[]',
        person_photo_id TEXT,
        prompt TEXT NOT NULL,
        engine TEXT NOT NULL DEFAULT 'chatgpt',        -- chatgpt | openrouter
        source TEXT NOT NULL DEFAULT 'manual',         -- manual | auto | agent
        status TEXT NOT NULL DEFAULT 'queued',         -- queued running done failed cancelled
        priority INTEGER NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        error TEXT,
        result_photo_id TEXT,
        account_email TEXT,
        duration_s REAL,
        cost_usd REAL,
        created_at REAL NOT NULL,
        claimed_at REAL,
        finished_at REAL
    );
    CREATE INDEX gen_jobs_status ON gen_jobs(status, priority, created_at);
    CREATE INDEX gen_jobs_owner ON gen_jobs(owner_id, created_at);
    CREATE TABLE gen_templates (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        icon TEXT,
        needs_person INTEGER NOT NULL DEFAULT 0,
        multi_item INTEGER NOT NULL DEFAULT 0,
        aspect TEXT NOT NULL DEFAULT 'portrait',
        prompt TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE chatgpt_accounts (
        user_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'not_connected',  -- not_connected pending connected limited error
        email TEXT, plan TEXT,
        limits TEXT NOT NULL DEFAULT '{}',
        limits_at REAL,
        message TEXT,
        connected_at REAL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE login_requests (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,                            -- login | connect
        user_id TEXT,
        nonce_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',        -- pending code approved rejected failed expired consumed
        verification_url TEXT,
        user_code TEXT,
        email TEXT,
        message TEXT,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE usage (
        day TEXT NOT NULL,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,                            -- vision | image:openrouter | image:chatgpt
        count INTEGER NOT NULL DEFAULT 0,
        cost REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (day, user_id, kind)
    );
    CREATE TABLE audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        actor TEXT NOT NULL,
        owner_id TEXT,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT
    );
    CREATE INDEX audit_owner ON audit(owner_id, at);
    """,
]

_local = threading.local()


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def migrate() -> int:
    conn = connect()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split(sql):  # executescript() would commit mid-way, so run statements one by one
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={i}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)


def _split(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        buf.append(line)
        joined = "\n".join(buf).strip()
        if joined.endswith(";") and sqlite3.complete_statement(joined):
            out.append(joined)
            buf = []
    rest = "\n".join(buf).strip()
    if rest:
        out.append(rest)
    return [s for s in out if s.strip(" ;\n")]


@contextmanager
def tx():
    """Write transaction (BEGIN IMMEDIATE so two processes never deadlock on upgrade)."""
    conn = connect()
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def q(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, tuple(args)).fetchall()]


def one(sql: str, args: Iterable[Any] = ()) -> dict | None:
    r = connect().execute(sql, tuple(args)).fetchone()
    return dict(r) if r else None


def scalar(sql: str, args: Iterable[Any] = ()) -> Any:
    r = connect().execute(sql, tuple(args)).fetchone()
    return r[0] if r else None


def run(sql: str, args: Iterable[Any] = ()) -> int:
    cur = connect().execute(sql, tuple(args))
    return cur.rowcount


def insert(table: str, row: dict) -> None:
    cols = ",".join(row)
    marks = ",".join("?" for _ in row)
    connect().execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(_enc(v) for v in row.values()))


def update(table: str, key: str, row: dict, where: str = "id") -> int:
    if not row:
        return 0
    sets = ",".join(f"{k}=?" for k in row)
    return connect().execute(f"UPDATE {table} SET {sets} WHERE {where}=?",
                             (*(_enc(v) for v in row.values()), key)).rowcount


def _enc(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def loads(v: str | None, default: Any = None) -> Any:
    if v in (None, ""):
        return default
    try:
        return json.loads(v)
    except ValueError:
        return default


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


def kv_get(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM kv WHERE key=?", (key,))
    return loads(row["value"], default) if row else default


def kv_set(key: str, value: Any) -> None:
    connect().execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                      "value=excluded.value, updated_at=excluded.updated_at", (key, json.dumps(value), now()))


def audit(actor: str, action: str, owner_id: str | None = None, target: str | None = None, detail: Any = None) -> None:
    insert("audit", {"at": now(), "actor": actor, "owner_id": owner_id, "action": action, "target": target,
                     "detail": json.dumps(detail, ensure_ascii=False) if detail is not None else None})


def bump_usage(user_id: str, kind: str, cost: float | None = None, count: int = 1) -> None:
    day = time.strftime("%Y-%m-%d")
    connect().execute("INSERT INTO usage(day,user_id,kind,count,cost) VALUES(?,?,?,?,?) ON CONFLICT(day,user_id,kind) "
                      "DO UPDATE SET count=count+excluded.count, cost=cost+excluded.cost",
                      (day, user_id, kind, count, cost or 0.0))


def usage_today(user_id: str | None, kind: str) -> dict:
    day = time.strftime("%Y-%m-%d")
    if user_id is None:
        row = one("SELECT COALESCE(SUM(count),0) AS count, COALESCE(SUM(cost),0) AS cost FROM usage WHERE day=? AND kind=?",
                  (day, kind))
    else:
        row = one("SELECT count, cost FROM usage WHERE day=? AND user_id=? AND kind=?", (day, user_id, kind))
    return {"count": (row or {}).get("count") or 0, "cost": round((row or {}).get("cost") or 0.0, 4)}
