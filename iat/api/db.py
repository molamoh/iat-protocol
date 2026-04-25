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
        seller_url TEXT,
        seller_source TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        status TEXT NOT NULL,
        tx_signature TEXT,
        delivered_at INTEGER,
        delivery_result TEXT,
        used INTEGER DEFAULT 0
    )
    """)


    # Lightweight migrations for existing SQLite DB
    for column_name, column_type in [
        ("seller_url", "TEXT"),
        ("seller_source", "TEXT")
    ]:
        try:
            cur.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError:
            pass


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
        order_id, service, price, seller_id, seller_wallet, seller_url, seller_source,
        created_at, updated_at, status, tx_signature,
        delivered_at, delivery_result, used
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id,
        order["service"],
        order["price"],
        order.get("seller_id"),
        order.get("seller_wallet"),
        order.get("seller_url"),
        order.get("seller_source"),
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
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    order = dict(row)

    if "used" in order:
        order["used"] = bool(order["used"])

    if order.get("delivery_result"):
        try:
            order["delivery_result"] = json.loads(order["delivery_result"])
        except Exception:
            order["delivery_result"] = {
                "raw": order["delivery_result"],
                "parse_error": True
            }

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


def get_stats_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM orders")
    total_orders = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE status = 'delivered'")
    delivered_orders = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(price), 0) FROM orders WHERE status = 'delivered'")
    total_volume = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM processed_txs")
    processed_txs = cur.fetchone()[0]

    cur.execute("""
        SELECT service, COUNT(*) as count
        FROM orders
        WHERE status = 'delivered'
        GROUP BY service
        ORDER BY count DESC
        LIMIT 1
    """)
    top_service_row = cur.fetchone()

    cur.execute("""
        SELECT seller_id, COUNT(*) as orders_count, COALESCE(SUM(price), 0) as revenue
        FROM orders
        WHERE status = 'delivered'
        GROUP BY seller_id
        ORDER BY revenue DESC
    """)
    seller_rows = cur.fetchall()

    revenue_by_seller = {
        seller_id: {
            "orders": orders_count,
            "revenue_iat": revenue
        }
        for seller_id, orders_count, revenue in seller_rows
    }

    conn.close()

    success_rate = 0
    if total_orders > 0:
        success_rate = round((delivered_orders / total_orders) * 100, 2)

    return {
        "total_orders": total_orders,
        "delivered_orders": delivered_orders,
        "pending_orders": total_orders - delivered_orders,
        "total_volume_iat": total_volume,
        "processed_transactions": processed_txs,
        "success_rate_percent": success_rate,
        "top_service": top_service_row[0] if top_service_row else None,
        "revenue_by_seller": revenue_by_seller
    }


def init_agents_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        service TEXT NOT NULL,
        url TEXT NOT NULL,
        wallet TEXT NOT NULL,
        price REAL NOT NULL,
        reputation REAL NOT NULL,
        available INTEGER DEFAULT 1,
        registered_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def register_agent_db(agent):
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())

    cur.execute("""
    INSERT OR REPLACE INTO agents (
        agent_id, service, url, wallet, price, reputation,
        available, registered_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(
        (SELECT registered_at FROM agents WHERE agent_id = ?),
        ?
    ), ?)
    """, (
        agent["agent_id"],
        agent["service"],
        agent["url"],
        agent["wallet"],
        agent["price"],
        agent["reputation"],
        1 if agent.get("available", True) else 0,
        agent["agent_id"],
        now,
        now
    ))

    conn.commit()
    conn.close()


def list_agents_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT agent_id, service, url, wallet, price, reputation, available, registered_at, updated_at
    FROM agents
    ORDER BY service, price ASC
    """)

    rows = cur.fetchall()
    conn.close()

    return [
        {
            "agent_id": r[0],
            "service": r[1],
            "url": r[2],
            "wallet": r[3],
            "price": r[4],
            "reputation": r[5],
            "available": bool(r[6]),
            "registered_at": r[7],
            "updated_at": r[8]
        }
        for r in rows
    ]


def get_agents_for_service_db(service):
    now = int(time.time())
    TIMEOUT = 30  # seconds

    return [
        a for a in list_agents_db()
        if a["service"] == service
        and a["available"]
        and (now - a["updated_at"] <= TIMEOUT)
    ]


def update_agent_reputation_db(agent_id, success=True):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT reputation FROM agents WHERE agent_id = ?", (agent_id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return None

    current = float(row[0])

    if success:
        new_rep = min(current + 0.01, 1.0)
    else:
        new_rep = max(current - 0.05, 0.1)

    cur.execute("""
    UPDATE agents
    SET reputation = ?, updated_at = ?
    WHERE agent_id = ?
    """, (round(new_rep, 4), int(time.time()), agent_id))

    conn.commit()
    conn.close()

    return round(new_rep, 4)


def get_network_status_db():
    agents = list_agents_db()
    stats = get_stats_db()

    now = int(time.time())
    TIMEOUT = 30

    online_agents = [
        a for a in agents
        if a["available"] and (now - a["updated_at"] <= TIMEOUT)
    ]

    services = {}

    for agent in online_agents:
        service = agent["service"]

        if service not in services:
            services[service] = {
                "agents": [],
                "best_agent": None
            }

        score = round(agent["reputation"] / agent["price"], 4)

        agent_info = {
            "agent_id": agent["agent_id"],
            "url": agent["url"],
            "wallet": agent["wallet"],
            "price": agent["price"],
            "reputation": agent["reputation"],
            "score": score,
            "updated_at": agent["updated_at"]
        }

        services[service]["agents"].append(agent_info)

    for service, data in services.items():
        data["best_agent"] = max(
            data["agents"],
            key=lambda a: a["score"]
        )

    return {
        "network": {
            "status": "online" if online_agents else "degraded",
            "total_agents": len(agents),
            "online_agents": len(online_agents),
            "services_count": len(services)
        },
        "services": services,
        "economy": stats
    }


def get_network_status_db():
    agents = list_agents_db()
    stats = get_stats_db()

    now = int(time.time())
    TIMEOUT = 30

    online_agents = [
        a for a in agents
        if a["available"] and (now - a["updated_at"] <= TIMEOUT)
    ]

    services = {}

    for agent in online_agents:
        service = agent["service"]

        if service not in services:
            services[service] = {
                "agents": [],
                "best_agent": None
            }

        score = round(agent["reputation"] / agent["price"], 4)

        agent_info = {
            "agent_id": agent["agent_id"],
            "url": agent["url"],
            "wallet": agent["wallet"],
            "price": agent["price"],
            "reputation": agent["reputation"],
            "score": score,
            "updated_at": agent["updated_at"]
        }

        services[service]["agents"].append(agent_info)

    for service, data in services.items():
        data["best_agent"] = max(
            data["agents"],
            key=lambda a: a["score"]
        )

    return {
        "network": {
            "status": "online" if online_agents else "degraded",
            "total_agents": len(agents),
            "online_agents": len(online_agents),
            "services_count": len(services)
        },
        "services": services,
        "economy": stats
    }
