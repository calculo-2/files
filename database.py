import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "tracker.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            store TEXT NOT NULL,
            identifier TEXT NOT NULL,
            target_price REAL NOT NULL,
            target_type TEXT NOT NULL DEFAULT 'pix'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            pix_price REAL,
            regular_price REAL,
            installment_price REAL,
            installment_count INTEGER,
            checked_at TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    """)
    conn.commit()
    conn.close()


def add_product(name, store, identifier, target_price, target_type="pix"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO products (name, store, identifier, target_price, target_type) VALUES (?, ?, ?, ?, ?)",
        (name, store, identifier, target_price, target_type),
    )
    conn.commit()
    conn.close()


def delete_product(product_id):
    conn = get_connection()
    conn.execute("DELETE FROM price_history WHERE product_id = ?", (product_id,))
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


def get_products():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_price(product_id, pix_price, regular_price, installment_price, installment_count):
    conn = get_connection()
    conn.execute(
        """INSERT INTO price_history
           (product_id, pix_price, regular_price, installment_price, installment_count, checked_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (product_id, pix_price, regular_price, installment_price, installment_count,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_history(product_id):
    conn = get_connection()
    rows = conn.execute(
        """SELECT pix_price, regular_price, installment_price, installment_count, checked_at
           FROM price_history WHERE product_id = ? ORDER BY checked_at""",
        (product_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest(product_id):
    history = get_history(product_id)
    return history[-1] if history else None
