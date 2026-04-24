import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path("iat_protocol.db")


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        service TEXT NOT NULL,
        price REAL NOT NULL,
        seller_id TEXT,
        seller_wallet TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        status TEXT NOT NULL,
        tx_signature TEXT,
        delivered_at INTEGER,
        delivery_result TEXT,
        used INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS processed_txs (
        tx_signature TEXT PRIMARY KEY,
        processed_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def create_order_db(order_id, order):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO orders (
        order_id, service, price, seller_id, seller_wallet,
        created_at, updated_at, status, tx_signature,
        delivered_at, delivery_result, used
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id,
        order["service"],
        order["price"],
        order.get("seller_id"),
        order.get("seller_wallet"),
        order["created_at"],
        order["updated_at"],
        order["status"],
        order.get("tx_signature"),
        order.get("delivered_at"),
        json.dumps(order.get("delivery_result")) if order.get("delivery_result") is not None else None,
        1 if order.get("used") else 0
    ))

    conn.commit()
    conn.close()


def get_order_db(order_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    keys = [
        "order_id", "service", "price", "seller_id", "seller_wallet",
        "created_at", "updated_at", "status", "tx_signature",
        "delivered_at", "delivery_result", "used"
    ]

    order = dict(zip(keys, row))
    order["used"] = bool(order["used"])

    if order["delivery_result"]:
        order["delivery_result"] = json.loads(order["delivery_result"])

    return order


def list_orders_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT order_id FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()

    return {
        order_id: get_order_db(order_id)
        for (order_id,) in rows
    }


def update_order_delivered_db(order_id, tx_signature, delivery_result):
    conn = get_conn()
    cur = conn.cursor()

    now = int(time.time())

    cur.execute("""
    UPDATE orders
    SET status = ?, tx_signature = ?, updated_at = ?, delivered_at = ?, delivery_result = ?, used = ?
    WHERE order_id = ?
    """, (
        "delivered",
        tx_signature,
        now,
        now,
        json.dumps(delivery_result),
        1,
        order_id
    ))

    conn.commit()
    conn.close()


def is_tx_processed_db(tx_signature):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT tx_signature FROM processed_txs WHERE tx_signature = ?", (tx_signature,))
    row = cur.fetchone()
    conn.close()

    return row is not None


def save_processed_tx_db(tx_signature):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT OR IGNORE INTO processed_txs (tx_signature, processed_at)
    VALUES (?, ?)
    """, (tx_signature, int(time.time())))

    conn.commit()
    conn.close()
