import json
import sqlite3
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from .config import ROOT, settings


def engine():
    (ROOT / "data/processed").mkdir(parents=True, exist_ok=True)
    return create_engine(settings().database_url, pool_pre_ping=True)


def rows(sql, params=None):
    with engine().connect() as conn:
        return [dict(x) for x in conn.execute(text(sql), params or {}).mappings()]


def operational():
    path = ROOT / "data/processed/operations.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL, result TEXT, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS audit (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
    """)
    return conn


def now():
    return datetime.now(timezone.utc).isoformat()


def audit(event, detail):
    # Callers pass structured metadata, never passwords, tokens or request headers.
    with operational() as conn:
        conn.execute("INSERT INTO audit VALUES (?,?,?,?)", (uuid.uuid4().hex, now(), event, json.dumps(detail, ensure_ascii=False)))


def ready():
    try:
        return bool(rows("SELECT COUNT(*) AS n FROM order_fact")[0]["n"])
    except Exception:
        return False
