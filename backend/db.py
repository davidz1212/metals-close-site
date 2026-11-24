"""SQLite 持久化层：报告快照、订阅邮箱、验证码、Webhook 事件。"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from . import config

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_date TEXT PRIMARY KEY,
    weekday TEXT,
    mode TEXT,
    payload TEXT NOT NULL,
    heatmap TEXT,
    ratio_history TEXT,
    curves TEXT,
    verification TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date DESC);

CREATE TABLE IF NOT EXISTS subscribers (
    email TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TEXT,
    paddle_subscription_id TEXT,
    source TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_codes_email ON auth_codes(email, created_at DESC);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)


def _dumps(obj: Any) -> str | None:
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def upsert_report(
    report_date: str,
    payload: dict,
    *,
    heatmap: dict | None = None,
    ratio_history: dict | None = None,
    curves: dict | None = None,
    verification: dict | None = None,
) -> bool:
    if not DATE_RE.match(report_date):
        raise ValueError("report_date must be YYYY-MM-DD")
    now = _now()
    with connection() as conn:
        existing = conn.execute(
            "SELECT created_at FROM reports WHERE report_date=?", (report_date,)
        ).fetchone()
        existed = bool(existing)
        created_at = existing["created_at"] if existed else now
        conn.execute(
            """INSERT INTO reports
               (report_date, weekday, mode, payload, heatmap, ratio_history, curves, verification, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(report_date) DO UPDATE SET
                 weekday=excluded.weekday, mode=excluded.mode, payload=excluded.payload,
                 heatmap=excluded.heatmap, ratio_history=excluded.ratio_history,
                 curves=excluded.curves, verification=excluded.verification,
                 updated_at=excluded.updated_at""",
            (
                report_date,
                payload.get("weekday"),
                payload.get("mode"),
                _dumps(payload),
                _dumps(heatmap),
                _dumps(ratio_history),
                _dumps(curves),
                _dumps(verification),
                created_at,
                now,
            ),
        )
    return bool(existed)


def list_report_dates() -> list[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT report_date FROM reports ORDER BY report_date DESC"
        ).fetchall()
    return [r["report_date"] for r in rows]


def get_report(report_date: str) -> dict | None:
    if not DATE_RE.match(report_date):
        return None
    with connection() as conn:
        row = conn.execute("SELECT * FROM reports WHERE report_date=?", (report_date,)).fetchone()
    if not row:
        return None
    return {
        "report_date": row["report_date"],
        "weekday": row["weekday"],
        "mode": row["mode"],
        "snapshot": json.loads(row["payload"]),
        "heatmap": json.loads(row["heatmap"]) if row["heatmap"] else None,
        "ratio_history": json.loads(row["ratio_history"]) if row["ratio_history"] else None,
        "curves": json.loads(row["curves"]) if row["curves"] else None,
        "verification": json.loads(row["verification"]) if row["verification"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def default_report_date(today: str | None = None) -> str | None:
    """默认展示"前一个收盘日"：不晚于今天的最新报告日。"""
    today = today or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    dates = list_report_dates()
    if not dates:
        return None
    eligible = [d for d in dates if d <= today]
    return eligible[0] if eligible else dates[0]


def upsert_subscriber(
    email: str,
    *,
    status: str = "active",
    expires_at: str | None = None,
    paddle_subscription_id: str | None = None,
    source: str = "manual",
    note: str | None = None,
) -> None:
    email = email.strip().lower()
    now = _now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO subscribers
               (email,status,expires_at,paddle_subscription_id,source,note,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET
                 status=excluded.status,
                 expires_at=COALESCE(excluded.expires_at, subscribers.expires_at),
                 paddle_subscription_id=COALESCE(excluded.paddle_subscription_id, subscribers.paddle_subscription_id),
                 source=excluded.source, note=excluded.note, updated_at=excluded.updated_at""",
            (email, status, expires_at, paddle_subscription_id, source, note, now, now),
        )


def is_subscriber_active(email: str) -> bool:
    email = email.strip().lower()
    with connection() as conn:
        row = conn.execute(
            "SELECT status, expires_at FROM subscribers WHERE email=?", (email,)
        ).fetchone()
    if not row or row["status"] != "active":
        return False
    if row["expires_at"]:
        try:
            expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry > datetime.now(timezone.utc)
        except ValueError:
            return False
    return True


def subscriber_info(email: str) -> dict | None:
    email = email.strip().lower()
    with connection() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE email=?", (email,)).fetchone()
    return dict(row) if row else None


def last_code_request(email: str) -> int | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT created_at FROM auth_codes WHERE email=? ORDER BY id DESC LIMIT 1",
            (email.strip().lower(),),
        ).fetchone()
    return int(row["created_at"]) if row else None


def create_code(email: str, code_hash: str, ttl: int, ip: str | None) -> int:
    email = email.strip().lower()
    now = int(time.time())
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO auth_codes (email,code_hash,expires_at,attempts,consumed,created_at,ip)
               VALUES (?,?,?,?,?,?,?)""",
            (email, code_hash, now + ttl, 0, 0, now, ip),
        )
        return int(cur.lastrowid)


def verify_code(email: str, code_hash: str) -> str:
    """返回 ok / expired / attempts / invalid / consumed。"""
    email = email.strip().lower()
    now = int(time.time())
    with connection() as conn:
        row = conn.execute(
            """SELECT * FROM auth_codes WHERE email=? AND consumed=0
               ORDER BY id DESC LIMIT 1""",
            (email,),
        ).fetchone()
        if not row:
            return "invalid"
        if row["expires_at"] < now:
            return "expired"
        if row["attempts"] >= config.CODE_MAX_ATTEMPTS:
            return "attempts"
        if row["code_hash"] != code_hash:
            conn.execute(
                "UPDATE auth_codes SET attempts=attempts+1 WHERE id=?", (row["id"],)
            )
            return "invalid"
        conn.execute("UPDATE auth_codes SET consumed=1 WHERE id=?", (row["id"],))
        return "ok"


def record_webhook_event(event_id: str, event_type: str, payload: str) -> bool:
    """返回 False 表示事件已处理过（幂等）。"""
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM webhook_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO webhook_events (event_id,event_type,payload,created_at) VALUES (?,?,?,?)",
            (event_id, event_type, payload, _now()),
        )
        return True


def log_event(email: str | None, event_type: str, detail: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO events (email,event_type,detail,created_at) VALUES (?,?,?,?)",
            (email, event_type, detail, _now()),
        )


def counts() -> dict[str, int]:
    with connection() as conn:
        return {
            "reports": int(conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]),
            "subscribers": int(conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]),
        }
