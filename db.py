import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    enabled INTEGER DEFAULT 1,
    last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS my_posts (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    note TEXT,
    enabled INTEGER DEFAULT 1,
    last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY,
    phrase TEXT UNIQUE NOT NULL,
    enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS negative_keywords (
    id INTEGER PRIMARY KEY,
    word TEXT UNIQUE NOT NULL,
    enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS seen_posts (
    post_url TEXT PRIMARY KEY,
    group_url TEXT,
    matched_phrase TEXT,
    notified INTEGER DEFAULT 0,
    text TEXT,
    posted_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS authorized_chats (
    chat_id INTEGER PRIMARY KEY,
    valid_until TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS favorites (
    post_url TEXT PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS seen_comments (
    comment_id TEXT PRIMARY KEY,
    post_url TEXT,
    author TEXT,
    text TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(authorized_chats)")}
    if "valid_until" not in cols:
        conn.execute("ALTER TABLE authorized_chats ADD COLUMN valid_until TEXT")
        conn.commit()
    return conn


def seed(conn, groups, phrases):
    for url in groups:
        conn.execute("INSERT OR IGNORE INTO groups(url) VALUES(?)", (url,))
    for p in phrases:
        conn.execute("INSERT OR IGNORE INTO keywords(phrase) VALUES(?)", (p,))
    conn.commit()
