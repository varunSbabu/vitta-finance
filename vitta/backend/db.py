"""SQLite database for local Vitta backend."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "vitta.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub    TEXT UNIQUE,
    email         TEXT NOT NULL,
    name          TEXT,
    picture       TEXT,
    password_hash TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
    bank_name     TEXT NOT NULL,
    account_last4 TEXT NOT NULL,
    account_type  TEXT DEFAULT 'savings',
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, bank_name, account_last4)
);

CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
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
CREATE INDEX IF NOT EXISTS idx_txn_user_date ON transactions(user_id, txn_date DESC);
CREATE INDEX IF NOT EXISTS idx_txn_cat  ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_acc  ON transactions(account_id);

CREATE TABLE IF NOT EXISTS merchant_dictionary (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
    merchant_key   TEXT NOT NULL,
    match_type     TEXT DEFAULT 'exact',
    display_name   TEXT,
    category       TEXT NOT NULL,
    is_user_tagged INTEGER DEFAULT 1,
    applied_count  INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, merchant_key)
);

CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
    phone_last10  TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, phone_last10)
);
"""


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    return column in cols


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    """Bring an existing users table up to the current schema. Handles two
    cases from earlier versions of this app: a missing password_hash column,
    and google_sub still being NOT NULL (which SQLite can't ALTER away
    directly, so this rebuilds the table when needed)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if not cols:
        return

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


def _migrate_add_user_id(conn: sqlite3.Connection) -> None:
    """Phase 1 migration: add user_id column to data tables that lack it.
    Backfills existing rows to user_id=1 (the single user from Phase 0).
    SQLite ALTER TABLE ADD COLUMN only supports columns with a DEFAULT, so
    we add with DEFAULT 1 then rebuild tables to get proper UNIQUE constraints
    that include user_id."""
    # On a fresh DB the tables don't exist yet — executescript(SCHEMA) will
    # create them with user_id already present, so nothing to migrate.
    existing_tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "accounts" not in existing_tables:
        return

    tables_needing_migration = []
    for table in ("accounts", "transactions", "merchant_dictionary", "contacts"):
        if table in existing_tables and not _table_has_column(conn, table, "user_id"):
            tables_needing_migration.append(table)

    if not tables_needing_migration:
        return

    # Ensure at least one user exists to satisfy the FK
    existing_user = (
        conn.execute("SELECT id FROM users LIMIT 1").fetchone() if "users" in existing_tables else None
    )
    if not existing_user:
        conn.execute("INSERT INTO users (id, email, name) VALUES (1, 'migrated@local', 'Migrated User')")

    for table in tables_needing_migration:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1 REFERENCES users(id)")

    # Rebuild tables with proper composite UNIQUE constraints.
    # accounts: UNIQUE(user_id, bank_name, account_last4) replaces UNIQUE(bank_name, account_last4)
    if "accounts" in tables_needing_migration:
        conn.executescript("""
            CREATE TABLE accounts_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
                bank_name     TEXT NOT NULL,
                account_last4 TEXT NOT NULL,
                account_type  TEXT DEFAULT 'savings',
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, bank_name, account_last4)
            );
            INSERT INTO accounts_new (id, user_id, bank_name, account_last4, account_type, created_at)
                SELECT id, COALESCE(user_id, 1), bank_name, account_last4, account_type, created_at
                FROM accounts;
            DROP TABLE accounts;
            ALTER TABLE accounts_new RENAME TO accounts;
        """)

    # merchant_dictionary: UNIQUE(user_id, merchant_key) replaces UNIQUE(merchant_key)
    if "merchant_dictionary" in tables_needing_migration:
        conn.executescript("""
            CREATE TABLE merchant_dictionary_new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
                merchant_key   TEXT NOT NULL,
                match_type     TEXT DEFAULT 'exact',
                display_name   TEXT,
                category       TEXT NOT NULL,
                is_user_tagged INTEGER DEFAULT 1,
                applied_count  INTEGER DEFAULT 0,
                created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, merchant_key)
            );
            INSERT INTO merchant_dictionary_new
                (id, user_id, merchant_key, match_type, display_name, category,
                 is_user_tagged, applied_count, created_at)
                SELECT id, COALESCE(user_id, 1), merchant_key, match_type, display_name,
                       category, is_user_tagged, applied_count, created_at
                FROM merchant_dictionary;
            DROP TABLE merchant_dictionary;
            ALTER TABLE merchant_dictionary_new RENAME TO merchant_dictionary;
        """)

    # contacts: UNIQUE(user_id, phone_last10) replaces UNIQUE(phone_last10)
    if "contacts" in tables_needing_migration:
        conn.executescript("""
            CREATE TABLE contacts_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
                phone_last10  TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, phone_last10)
            );
            INSERT INTO contacts_new (id, user_id, phone_last10, display_name, created_at)
                SELECT id, COALESCE(user_id, 1), phone_last10, display_name, created_at
                FROM contacts;
            DROP TABLE contacts;
            ALTER TABLE contacts_new RENAME TO contacts;
        """)

    # transactions: just add the column (no unique constraint change needed,
    # upi_ref stays globally unique which is correct — same UPI ref can't
    # appear for two users)
    if "transactions" in tables_needing_migration:
        conn.executescript("""
            CREATE TABLE transactions_new (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
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
            INSERT INTO transactions_new
                (id, user_id, account_id, txn_date, txn_time, amount, direction,
                 merchant_raw, merchant_clean, upi_ref, vpa, remark, source,
                 category, is_self_transfer, is_recurring, raw_json, created_at)
                SELECT id, COALESCE(user_id, 1), account_id, txn_date, txn_time, amount,
                       direction, merchant_raw, merchant_clean, upi_ref, vpa, remark,
                       source, category, is_self_transfer, is_recurring, raw_json, created_at
                FROM transactions;
            DROP TABLE transactions;
            ALTER TABLE transactions_new RENAME TO transactions;
        """)

    conn.commit()


def init_db():
    conn = get_conn()
    _migrate_users_table(conn)
    _migrate_add_user_id(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def dict_from_row(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


if __name__ == "__main__":
    init_db()
    print(f"DB ready at {DB_PATH}")
