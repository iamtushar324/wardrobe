#!/usr/bin/env python3
"""Wardrobe image worker: makes Studio pictures with each person's own ChatGPT subscription.

Runs on a machine that has the Codex CLI (`codex`) installed, as a normal user (see the systemd unit
next to this file). It talks to the wardrobe app over HTTPS with a worker token:

* "Sign in with ChatGPT" / "Connect ChatGPT": when the app has a pending request, the worker runs
  `codex login --device-auth` in a fresh CODEX_HOME, sends the link and one-time code to the app (the
  browser shows them), and when the person finishes, reads the account email and asks the app whether to
  keep it. Accepted logins are stored per wardrobe user in WARDROBE_CODEX_HOMES/<user_id>.
* Image jobs: claims one job at a time for users whose ChatGPT is connected, downloads the reference
  pictures, runs `codex exec` with the built-in image tool and uploads the PNG.
* Limits: reads each account's plan limits with `codex app-server` (no model call) and reports them so the
  Studio page can show usage and stop before a limit is hit.

Codex homes are never shared with a developer's own Codex login. Accounts on blocked domains (for example a
work domain) are refused. Standard library only.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

VERSION = "1.0"
HOME = Path.home()
APP = os.environ.get("WARDROBE_URL", "http://localhost:8080").rstrip("/")
TOKEN_FILE = Path(os.environ.get("WARDROBE_WORKER_TOKEN_FILE", HOME / ".config/wardrobe/worker-token"))
CODEX = os.environ.get("CODEX_BIN", "codex")
HOMES = Path(os.environ.get("WARDROBE_CODEX_HOMES", HOME / ".config/wardrobe-codex"))
WORK = Path(os.environ.get("WARDROBE_WORKDIR", HOME / ".cache/wardrobe-worker"))
BLOCKED = {d.strip().lower() for d in os.environ.get("WARDROBE_BLOCKED_DOMAINS", "").split(",") if d.strip()}
TIMEOUT = int(os.environ.get("WARDROBE_JOB_TIMEOUT", "420"))
HEARTBEAT_EVERY = 10
LIMITS_EVERY = 180
LOGIN_TIMEOUT = 15 * 60
LIMIT_WORDS = re.compile(r"usage limit|rate.?limit|too many requests|\b429\b|quota|out of credits|insufficient credits", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,6})\b")
URL_RE = re.compile(r"https://\S+/device\S*")
UID_RE = re.compile(r"^usr_[A-Za-z0-9]+$")

INSTRUCTION = ("Use your image generation tool exactly once to create the image described below. The attached images "
               "are the references the description talks about; pass them to the image tool. Do not run shell commands, "
               "do not read or write files and do not use skills. When the image has been generated, reply with the "
               "single word DONE.\n\n")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------- app API ----------------
def _token() -> str:
    return TOKEN_FILE.read_text().strip()


def call(path: str, body: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(APP + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read() or b"{}")


def download(path: str, dest_stem: Path) -> Path:
    req = urllib.request.Request(APP + path, headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(req, timeout=60) as res:
        ext = mimetypes.guess_extension((res.headers.get("content-type") or "image/jpeg").split(";")[0]) or ".jpg"
        dest = dest_stem.with_suffix(".jpg" if ext == ".jpe" else ext)
        dest.write_bytes(res.read())
    return dest


def upload(job_id: str, png: Path, meta: dict) -> dict:
    boundary = uuid.uuid4().hex
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="meta"\r\n\r\n{json.dumps(meta)}\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image.png"\r\n'
         'Content-Type: image/png\r\n\r\n').encode() + png.read_bytes() + b"\r\n",
        f"--{boundary}--\r\n".encode()])
    req = urllib.request.Request(f"{APP}/api/worker/jobs/{job_id}/complete", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {_token()}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read())


# ---------------- Codex accounts ----------------
def env_for(home: Path) -> dict:
    return {**os.environ, "CODEX_HOME": str(home), "NO_COLOR": "1"}


def codex_version() -> str:
    try:
        return subprocess.run([CODEX, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def blocked(email: str) -> bool:
    email = (email or "").lower()
    return any(email.endswith("@" + d) or email.endswith("." + d) for d in BLOCKED)


def read_account(home: Path) -> tuple[dict, dict]:
    """(account, limits) for one CODEX_HOME via `codex app-server` JSON-RPC (no model call)."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"clientInfo": {"name": "wardrobe-worker", "version": VERSION}}},
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "account/read", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "account/rateLimits/read"}]
    WORK.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([CODEX, "app-server"], env=env_for(home), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, cwd=WORK)
    got: dict[int, dict] = {}
    try:
        proc.stdin.write(b"".join(json.dumps(m).encode() + b"\n" for m in msgs))
        proc.stdin.flush()
        fd, buf, end = proc.stdout.fileno(), b"", time.time() + 25
        while time.time() < end and not (2 in got and 3 in got):
            if not select.select([fd], [], [], 1)[0]:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") in (2, 3):
                    got[msg["id"]] = msg
    finally:
        proc.kill()
        proc.wait()
    acct = ((got.get(2) or {}).get("result") or {}).get("account") or {}
    account = {"type": acct.get("type"), "email": acct.get("email"), "plan": acct.get("planType")} if acct else {}
    res = (got.get(3) or {}).get("result") or {}
    rl = res.get("rateLimits") or {}
    if not rl:
        return account, {}

    def window(w):
        return {"used_percent": w.get("usedPercent"), "window_minutes": w.get("windowDurationMins"),
                "resets_at": w.get("resetsAt")} if w else None

    credits = rl.get("credits") or {}
    return account, {
        "plan": rl.get("planType") or account.get("plan"), "ordinary_allowed": res.get("ordinaryUsageAllowed"),
        "reached": rl.get("rateLimitReachedType"), "primary": window(rl.get("primary")),
        "secondary": window(rl.get("secondary")),
        "credits": {"has_credits": credits.get("hasCredits"), "unlimited": credits.get("unlimited"),
                    "balance": credits.get("balance")},
    }


def account_report(home: Path) -> dict:
    account, limits = read_account(home)
    email = (account.get("email") or "").lower()
    out = {"email": email or None, "plan": account.get("plan"), "limits": limits, "limits_at": time.time()}
    if account.get("type") != "chatgpt":
        return {**out, "status": "error", "message": "ChatGPT sign-in expired; connect ChatGPT again"}
    if blocked(email):
        return {**out, "status": "error", "message": f"{email} is on a blocked domain"}
    reached = limits.get("reached") or any(((limits.get(k) or {}).get("used_percent") or 0) >= 100
                                           for k in ("primary", "secondary"))
    if reached and not (limits.get("credits") or {}).get("has_credits"):
        return {**out, "status": "limited", "message": "ChatGPT plan limit reached"}
    return {**out, "status": "connected", "message": None}


class Accounts:
    """Per-user Codex homes and their last reported state."""

    def __init__(self):
        self.state: dict[str, dict] = {}
        self.checked: dict[str, float] = {}
        self.lock = threading.Lock()

    def users(self) -> list[str]:
        if not HOMES.is_dir():
            return []
        return [p.name for p in HOMES.iterdir() if UID_RE.match(p.name) and (p / "auth.json").exists()]

    def refresh(self, force: bool = False) -> dict[str, dict]:
        for uid in self.users():
            if force or time.time() - self.checked.get(uid, 0) > LIMITS_EVERY:
                try:
                    rep = account_report(HOMES / uid)
                except Exception as exc:
                    rep = {"status": "error", "message": f"could not read account: {exc}"[:200]}
                with self.lock:
                    self.state[uid] = rep
                    self.checked[uid] = time.time()
        with self.lock:
            for uid in list(self.state):
                if uid not in self.users():
                    self.state.pop(uid, None)
            return dict(self.state)

    def mark(self, uid: str) -> None:
        self.checked.pop(uid, None)

    def remove(self, uid: str) -> None:
        if UID_RE.match(uid):
            shutil.rmtree(HOMES / uid, ignore_errors=True)
        with self.lock:
            self.state.pop(uid, None)


# ---------------- device-code sign-in ----------------
def run_login(rid: str, accounts: Accounts, active: set[str]) -> None:
    tmp = HOMES / f".login-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, mode=0o700)
    log("login", rid, "started")
    try:
        proc = subprocess.Popen([CODEX, "login", "--device-auth"], env=env_for(tmp), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=tmp, start_new_session=True)
        fd, buf, sent, started = proc.stdout.fileno(), "", False, time.time()
        while proc.poll() is None:
            if time.time() - started > LOGIN_TIMEOUT:
                os.killpg(proc.pid, signal.SIGTERM)
                raise RuntimeError("the code expired before sign-in finished")
            if select.select([fd], [], [], 1)[0]:
                chunk = os.read(fd, 4096)
                if chunk:
                    buf += ANSI.sub("", chunk.decode(errors="replace"))
            if not sent:
                code, url = CODE_RE.search(buf), URL_RE.search(buf)
                if code and url:
                    call(f"/api/worker/login/{rid}/code", {"url": url.group(0), "code": code.group(1)})
                    sent = True
                    log("login", rid, "code shown to the browser")
        if proc.returncode != 0 or not (tmp / "auth.json").exists():
            raise RuntimeError("ChatGPT sign-in did not complete")
        account, _ = read_account(tmp)
        email = (account.get("email") or "").lower()
        if account.get("type") != "chatgpt" or not email:
            raise RuntimeError("signed in, but the ChatGPT account could not be read")
        if blocked(email):
            call(f"/api/worker/login/{rid}/done", {"email": email, "plan": account.get("plan")})
            raise RuntimeError(f"{email} is on a blocked domain")
        res = call(f"/api/worker/login/{rid}/done", {"email": email, "plan": account.get("plan")})
        uid = res.get("user_id") or ""
        if res.get("accept") and UID_RE.match(uid):
            dest = HOMES / uid
            shutil.rmtree(dest, ignore_errors=True)
            tmp.rename(dest)
            accounts.mark(uid)
            log("login", rid, "connected for", uid)
        else:
            log("login", rid, "refused:", res.get("message"))
    except Exception as exc:
        log("login", rid, "failed:", exc)
        try:
            call(f"/api/worker/login/{rid}/fail", {"message": str(exc)[:200]})
        except Exception:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        active.discard(rid)


# ---------------- one picture ----------------
def generate(job: dict, should_stop) -> tuple[Path | None, dict, str]:
    home = HOMES / job["user_id"]
    run_dir = WORK / job["id"]
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    images = [download(p, run_dir / f"ref-{i + 1}") for i, p in enumerate(job.get("inputs") or [])]
    cmd = [CODEX, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
           "-s", "read-only", "-C", str(run_dir), "-c", "model_reasoning_effort=low"]
    for img in images:
        cmd += ["--image", str(img)]
    started = time.time()
    out_path, err_path = run_dir / "events.jsonl", run_dir / "stderr.txt"
    stopped = None
    with open(out_path, "w") as out, open(err_path, "w") as err:
        proc = subprocess.Popen(cmd, env=env_for(home), stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=run_dir,
                                start_new_session=True)
        proc.stdin.write((INSTRUCTION + job["prompt"]).encode())  # prompt via stdin: --image takes many values
        proc.stdin.close()
        while proc.poll() is None:
            time.sleep(2)
            if time.time() - started > TIMEOUT:
                stopped = "timed out"
            elif should_stop():
                stopped = "cancelled"
            if stopped:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
    stats = {"duration_s": round(time.time() - started, 1), "codex_version": CODEX_VERSION, "references": len(images)}
    thread, errors = None, []
    for line in out_path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            thread = ev.get("thread_id")
        elif ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            stats["tokens"] = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
        elif ev.get("type") in ("error", "turn.failed"):
            errors.append(json.dumps(ev)[:400])
    png = None
    if thread:
        gen = home / "generated_images" / thread
        files = sorted(gen.glob("*.png"), key=lambda p: p.stat().st_mtime) if gen.is_dir() else []
        if files:
            png = run_dir / "result.png"
            shutil.copyfile(files[-1], png)
        shutil.rmtree(gen, ignore_errors=True)
    if stopped:
        return None, stats, stopped
    tail = (err_path.read_text(errors="replace")[-600:] + " " + " ".join(errors)).strip()
    return png, stats, "" if png else (tail or f"codex exited with code {proc.returncode} and no image")


def run_job(job: dict, accounts: Accounts, hb) -> None:
    log("job", job["id"], job.get("template"), "for", job["user_id"])
    last, stop = [time.time()], [False]

    def should_stop():
        if time.time() - last[0] >= HEARTBEAT_EVERY:
            last[0] = time.time()
            try:
                stop[0] = job["id"] in (hb("busy", f"making {job.get('template_name')}", job["id"]).get("cancelled") or [])
            except Exception as exc:
                log("heartbeat failed", exc)
        return stop[0]

    try:
        png, stats, error = generate(job, should_stop)
        if png:
            res = upload(job["id"], png, stats)
            log("done", job["id"], res.get("photo_id"), stats)
        elif error == "cancelled":
            log("cancelled", job["id"])
        else:
            limited = bool(LIMIT_WORDS.search(error))
            call(f"/api/worker/jobs/{job['id']}/fail", {"error": error[-300:], "limited": limited, "retry": not limited})
            log("failed", job["id"], "limited" if limited else "", error[-200:])
    except urllib.error.HTTPError as exc:
        log("upload refused", job["id"], exc.code)  # e.g. 409: cancelled while uploading
    except Exception as exc:
        log("job error", job["id"], exc)
        try:
            call(f"/api/worker/jobs/{job['id']}/fail", {"error": str(exc)[:300], "limited": False, "retry": True})
        except Exception:
            pass
    finally:
        accounts.mark(job["user_id"])
        shutil.rmtree(WORK / job["id"], ignore_errors=True)


# ---------------- main loop ----------------
def main() -> int:
    global CODEX_VERSION
    for d in (HOMES, WORK):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not TOKEN_FILE.exists():
        log("missing worker token file", TOKEN_FILE)
        return 2
    CODEX_VERSION = codex_version()
    log("wardrobe worker", VERSION, "app", APP, "codex", CODEX_VERSION or "missing")
    running = [True]
    signal.signal(signal.SIGTERM, lambda *_: running.__setitem__(0, False))
    signal.signal(signal.SIGINT, lambda *_: running.__setitem__(0, False))
    accounts, logins = Accounts(), set()
    host = socket.gethostname()

    def heartbeat(state: str = "idle", message: str | None = None, current: str | None = None) -> dict:
        res = call("/api/worker/heartbeat", {"state": state, "message": message, "current_job": current,
                                             "version": VERSION, "codex_version": CODEX_VERSION, "host": host,
                                             "accounts": accounts.refresh()})
        BLOCKED.update(d.lower() for d in res.get("blocked_domains") or [])
        for uid in res.get("logout") or []:
            log("disconnect", uid)
            accounts.remove(uid)
        for req in res.get("pending_logins") or []:
            if req["id"] not in logins and len(logins) < 4:
                logins.add(req["id"])
                threading.Thread(target=run_login, args=(req["id"], accounts, logins), daemon=True).start()
        return res

    while running[0]:
        try:
            res = heartbeat()
            if res.get("work"):
                ready = [uid for uid, a in accounts.refresh().items() if a.get("status") == "connected"]
                job = call("/api/worker/claim", {"ready_users": ready}).get("job") if ready else None
                if job:
                    run_job(job, accounts, heartbeat)
                    continue
        except urllib.error.URLError as exc:
            log("app unreachable:", exc)
        except Exception as exc:
            log("loop error:", exc)
        for _ in range(HEARTBEAT_EVERY):
            if not running[0]:
                break
            time.sleep(1)
    log("stopped")
    return 0


CODEX_VERSION = ""

if __name__ == "__main__":
    sys.exit(main())
