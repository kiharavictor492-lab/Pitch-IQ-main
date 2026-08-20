"""
football_bot/database.py
=========================
SQLite database for:
  - subscribers (active VIP users)
  - pending_payments (STK push awaiting confirmation)
No external DB needed — runs as a local file.
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from config import DB_PATH, SUBSCRIPTION_DAYS

logger = logging.getLogger(__name__)


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    """Create tables if they don't exist."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                full_name     TEXT,
                phone         TEXT,
                subscribed_at TEXT,
                expires_at    TEXT,
                active        INTEGER DEFAULT 1
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_payments (
                checkout_request_id TEXT PRIMARY KEY,
                user_id             INTEGER,
                phone               TEXT,
                amount              INTEGER,
                created_at          TEXT,
                status              TEXT DEFAULT 'pending'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                date        TEXT,
                sent_at     TEXT,
                status      TEXT
            )
        """)
        c.commit()
    logger.info("Database initialised")


# ─── Subscribers ──────────────────────────────────────────────────────────────

def add_subscriber(user_id: int, username: str, full_name: str, phone: str):
    """Add or renew a subscriber for SUBSCRIPTION_DAYS days."""
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(days=SUBSCRIPTION_DAYS)
    with _conn() as c:
        c.execute("""
            INSERT INTO subscribers (user_id, username, full_name, phone, subscribed_at, expires_at, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                phone         = excluded.phone,
                subscribed_at = excluded.subscribed_at,
                expires_at    = excluded.expires_at,
                active        = 1
        """, (user_id, username, full_name, phone, now.isoformat(), expires.isoformat()))
        c.commit()
    logger.info(f"Subscriber added/renewed: {user_id} ({full_name}) until {expires.date()}")


def get_active_subscribers() -> list[dict]:
    """Return all subscribers whose subscription hasn't expired."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute("""
            SELECT user_id, username, full_name, phone, expires_at
            FROM subscribers
            WHERE active = 1 AND expires_at > ?
        """, (now,)).fetchall()
    return [
        {"user_id": r[0], "username": r[1], "full_name": r[2],
         "phone": r[3], "expires_at": r[4]}
        for r in rows
    ]


def is_active_subscriber(user_id: int) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("""
            SELECT 1 FROM subscribers
            WHERE user_id = ? AND active = 1 AND expires_at > ?
        """, (user_id, now)).fetchone()
    return row is not None


def get_subscriber_expiry(user_id: int) -> str | None:
    with _conn() as c:
        row = c.execute(
            "SELECT expires_at FROM subscribers WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def is_returning_user(user_id: int) -> bool:
    """True if user has ever subscribed before (even if now expired)."""
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM subscribers WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None


def deactivate_expired():
    """Mark expired subscriptions as inactive."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("UPDATE subscribers SET active = 0 WHERE expires_at <= ?", (now,))
        c.commit()


# ─── Pending Payments ─────────────────────────────────────────────────────────

def save_pending_payment(checkout_request_id: str, user_id: int, phone: str, amount: int):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO pending_payments
            (checkout_request_id, user_id, phone, amount, created_at, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (checkout_request_id, user_id, phone, amount, now))
        c.commit()


def get_pending_payment(checkout_request_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("""
            SELECT checkout_request_id, user_id, phone, amount, created_at, status
            FROM pending_payments WHERE checkout_request_id = ?
        """, (checkout_request_id,)).fetchone()
    if not row:
        return None
    return {
        "checkout_request_id": row[0], "user_id": row[1],
        "phone": row[2], "amount": row[3],
        "created_at": row[4], "status": row[5],
    }


def get_pending_by_user(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("""
            SELECT checkout_request_id, user_id, phone, amount, created_at
            FROM pending_payments
            WHERE user_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)).fetchone()
    if not row:
        return None
    return {
        "checkout_request_id": row[0], "user_id": row[1],
        "phone": row[2], "amount": row[3], "created_at": row[4],
    }


def mark_payment(checkout_request_id: str, status: str):
    with _conn() as c:
        c.execute(
            "UPDATE pending_payments SET status = ? WHERE checkout_request_id = ?",
            (status, checkout_request_id)
        )
        c.commit()


# ─── Delivery log ─────────────────────────────────────────────────────────────

def log_delivery(user_id: int, date: str, status: str = "sent"):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            INSERT INTO delivery_log (user_id, date, sent_at, status)
            VALUES (?, ?, ?, ?)
        """, (user_id, date, now, status))
        c.commit()


def already_delivered_today(user_id: int) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute("""
            SELECT 1 FROM delivery_log
            WHERE user_id = ? AND date = ? AND status = 'sent'
        """, (user_id, today)).fetchone()
    return row is not None


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with _conn() as c:
        total    = c.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
        active   = len(get_active_subscribers())
        payments = c.execute("SELECT COUNT(*) FROM pending_payments WHERE status='confirmed'").fetchone()[0]
        today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sent     = c.execute("SELECT COUNT(*) FROM delivery_log WHERE date=?", (today,)).fetchone()[0]
    return {"total_subscribers": total, "active": active,
            "total_payments": payments, "sent_today": sent}