"""管理订阅邮箱白名单（仅服务端命令行，前端无写权限）。

用法：
    python tools/seed_subscriber.py add demo@example.com [--days 365] [--note "..."]
    python tools/seed_subscriber.py remove demo@example.com
    python tools/seed_subscriber.py list
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="manage subscriber whitelist")
    sub = parser.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add")
    add.add_argument("email")
    add.add_argument("--days", type=int, default=365)
    add.add_argument("--note", default="manual seed")

    rm = sub.add_parser("remove")
    rm.add_argument("email")

    sub.add_parser("list")

    args = parser.parse_args()
    db.init_db()

    if args.action == "add":
        expiry = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat(timespec="seconds")
        db.upsert_subscriber(args.email, expires_at=expiry, source="manual", note=args.note)
        print(f"ADDED/UPDATED {args.email.lower()} expires_at={expiry}")
    elif args.action == "remove":
        db.upsert_subscriber(args.email, status="cancelled", source="manual", note="removed by admin")
        print(f"DISABLED {args.email.lower()}")
    else:
        import sqlite3
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT email,status,expires_at,source,note FROM subscribers ORDER BY email"
            ).fetchall()
        for r in rows:
            print(f"{r['email']:<38} {r['status']:<10} {r['expires_at'] or '-':<26} {r['source']}")
        if not rows:
            print("(empty)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
