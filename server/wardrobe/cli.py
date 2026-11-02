"""Admin command line.

    python -m wardrobe.cli token create --email you@example.com --label laptop-claude [--read-only]
    python -m wardrobe.cli token list
    python -m wardrobe.cli user invite friend@example.com
    python -m wardrobe.cli user list
"""

from __future__ import annotations

import argparse
import sys

from . import auth, db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wardrobe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tok = sub.add_parser("token").add_subparsers(dest="sub", required=True)
    tc = tok.add_parser("create")
    tc.add_argument("--email", default=None, help="user (default: the owner)")
    tc.add_argument("--label", required=True)
    tc.add_argument("--read-only", action="store_true")
    tok.add_parser("list")
    usr = sub.add_parser("user").add_subparsers(dest="sub", required=True)
    ui = usr.add_parser("invite")
    ui.add_argument("email")
    usr.add_parser("list")
    args = ap.parse_args(argv)

    db.migrate()
    owner = auth.ensure_owner()
    if args.cmd == "token" and args.sub == "create":
        u = db.one("SELECT * FROM users WHERE email=?", (args.email.lower(),)) if args.email else owner
        if not u:
            print(f"no user {args.email}", file=sys.stderr)
            return 1
        _, raw = auth.create_token(u["id"], args.label, "read" if args.read_only else "read,write")
        print(raw)
        return 0
    if args.cmd == "token":
        for r in db.q("SELECT t.id, t.label, t.scopes, t.created_at, t.last_used_at, t.revoked_at, u.email "
                      "FROM api_tokens t JOIN users u ON u.id=t.user_id ORDER BY t.created_at"):
            print(f"{r['id']}  {r['email']:<30} {r['label']:<24} {r['scopes']:<10} "
                  f"{'revoked' if r['revoked_at'] else 'active'}")
        return 0
    if args.cmd == "user" and args.sub == "invite":
        email = args.email.strip().lower()
        if not db.one("SELECT 1 FROM users WHERE email=?", (email,)):
            with db.tx():
                db.insert("users", {"id": db.new_id("usr"), "email": email, "role": "member", "status": "invited",
                                    "prefs": "{}", "created_at": db.now()})
        print(f"invited {email}")
        return 0
    for r in db.q("SELECT id, email, role, status FROM users ORDER BY created_at"):
        print(f"{r['id']}  {r['email']:<32} {r['role']:<7} {r['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
