"""SQLite database for local Vitta backend."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "vitta.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name     TEXT NOT NULL,
    account_last4 TEXT NOT NULL,
    account_type  TEXT DEFAULT 'savings',
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bank_name, account_last4)
);

CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       INTEGER REFERENCES accounts(id),
    txn_date         TEXT NOT NULL,
    txn_time         TEXT,
    amount           REAL NOT NULL,
    direction        TEXT CHECK(direction IN ('debit','credit')) NOT NULL,
    merchant_raw     TEXT NOT NULL,
    merchant_clean   TEXT,
    upi_ref          TEXT UNIQUE,
    vpa              TEXT,
    remark           TEXT,
    source           TEXT NOT NULL,
    category         TEXT,
    is_self_transfer INTEGER DEFAULT 0,
    is_recurring     INTEGER DEFAULT 0,
    raw_json         TEXT,
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date DESC);
CREATE INDEX IF NOT EXISTS idx_txn_cat  ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_acc  ON transactions(account_id);

CREATE TABLE IF NOT EXISTS merchant_dictionary (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_key   TEXT NOT NULL UNIQUE,
    match_type     TEXT DEFAULT 'exact',
    display_name   TEXT,
    category       TEXT NOT NULL,
    is_user_tagged INTEGER DEFAULT 1,
    applied_count  INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_last10  TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- google_sub is nullable (not every user signs in with Google — see
-- password_hash) and password_hash is nullable (not every user has set a
-- password — Google-only sign-ins never touch it). SQLite treats every
-- NULL as distinct under UNIQUE, so multiple password-only or multiple
-- Google-only rows can coexist without colliding.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub    TEXT UNIQUE,
    email         TEXT NOT NULL,
    name          TEXT,
    picture       TEXT,
    password_hash TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    """Bring an existing users table up to the current schema. Handles two
    cases from earlier versions of this app: a missing password_hash column,
    and google_sub still being NOT NULL (which SQLite can't ALTER away
    directly, so this rebuilds the table when needed)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if not cols:
        return  # table doesn't exist yet — executescript() will create it fresh

    needs_password_col = "password_hash" not in cols
    google_sub_not_null = any(
        r["name"] == "google_sub" and r["notnull"] for r in conn.execute("PRAGMA table_info(users)")
    )

    if not needs_password_col and not google_sub_not_null:
        return

    conn.executescript("""
        ALTER TABLE users RENAME TO users_old;
        CREATE TABLE users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            google_sub    TEXT UNIQUE,
            email         TEXT NOT NULL,
            name          TEXT,
            picture       TEXT,
            password_hash TEXT,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users (id, google_sub, email, name, picture, created_at)
            SELECT id, google_sub, email, name, picture, created_at FROM users_old;
        DROP TABLE users_old;
    """)


def init_db():
    conn = get_conn()
    _migrate_users_table(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def dict_from_row(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


if __name__ == "__main__":
    init_db()
    print(f"DB ready at {DB_PATH}")
