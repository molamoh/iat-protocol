from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

pool = None
import os
import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path("iat_protocol.db")
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)


from psycopg2.pool import SimpleConnectionPool

pool = None

def get_conn():
    global pool

    if USE_POSTGRES:
        if pool is None:
            pool = SimpleConnectionPool(
                1,
                1,
                DATABASE_URL,
                cursor_factory=RealDictCursor
            )
        return pool.getconn()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def release_conn(conn):
    global pool

    if conn is None:
        return

    try:
        if USE_POSTGRES and pool is not None:
            pool.putconn(conn)
        else:
            release_conn(conn)
    except:
        pass


def release_conn(conn):
    global pool

    if conn is None:
        return

    try:
        if USE_POSTGRES and pool is not None:
            pool.putconn(conn)
        else:
            release_conn(conn)
    except Exception:
        pass


def qmark():
    return "%s" if USE_POSTGRES else "?"


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        service TEXT NOT NULL,
        query TEXT,
        price REAL NOT NULL,
        seller_id TEXT,
        seller_wallet TEXT,
        seller_url TEXT,
        seller_source TEXT,
        buyer_secret TEXT,
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
    release_conn(locals().get("conn"))
    init_agents_table()


def init_agents_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        service TEXT NOT NULL,
        url TEXT,
        wallet TEXT NOT NULL,
        price REAL NOT NULL,
        reputation REAL DEFAULT 0.8,
        available INTEGER DEFAULT 1,
        registered_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        last_slashed_at INTEGER,
        call_count INTEGER DEFAULT 0,
        win_count INTEGER DEFAULT 0,
        latency_total REAL DEFAULT 0,
        trust_tier TEXT DEFAULT 'free',
        stake_amount REAL DEFAULT 0,
        stake_required REAL DEFAULT 0,
        risk_score REAL DEFAULT 0,
        wallet_agent_count INTEGER DEFAULT 0
    )
    """)
    agent_columns = {
        "success_count": "INTEGER DEFAULT 0",
        "failure_count": "INTEGER DEFAULT 0",
        "last_slashed_at": "INTEGER",
        "call_count": "INTEGER DEFAULT 0",
        "win_count": "INTEGER DEFAULT 0",
        "latency_total": "REAL DEFAULT 0",
        "trust_tier": "TEXT DEFAULT 'free'",
        "stake_amount": "REAL DEFAULT 0",
        "stake_required": "REAL DEFAULT 0",
        "risk_score": "REAL DEFAULT 0",
        "wallet_agent_count": "INTEGER DEFAULT 0",
    }

    for column, col_type in agent_columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE agents ADD COLUMN IF NOT EXISTS {column} {col_type}")
            else:
                cur.execute(f"ALTER TABLE agents ADD COLUMN {column} {col_type}")
        except Exception:
            pass
    conn.commit()
    release_conn(locals().get("conn"))


def create_order_db(order_id, order):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO orders (
        order_id, service, query, price, seller_id, seller_wallet, seller_url, seller_source,
        buyer_secret, created_at, updated_at, status, tx_signature, delivered_at, delivery_result, used
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        order_id,
        order["service"],
        order.get("query"),
        order["price"],
        order.get("seller_id"),
        order.get("seller_wallet"),
        order.get("seller_url"),
        order.get("seller_source"),
        order.get("buyer_secret"),
        order["created_at"],
        order["updated_at"],
        order["status"],
        order.get("tx_signature"),
        order.get("delivered_at"),
        json.dumps(order.get("delivery_result")) if order.get("delivery_result") is not None else None,
        1 if order.get("used") else 0
    ))

    conn.commit()
    release_conn(locals().get("conn"))


def get_order_db(order_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    cur.execute(f"SELECT * FROM orders WHERE order_id = {p}", (order_id,))
    row = cur.fetchone()
    release_conn(locals().get("conn"))

    if not row:
        return None

    order = dict(row)
    order["used"] = bool(order.get("used", 0))

    if order.get("delivery_result"):
        try:
            order["delivery_result"] = json.loads(order["delivery_result"])
        except Exception:
            order["delivery_result"] = {"raw": order["delivery_result"], "parse_error": True}

    return order


def list_orders_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT order_id FROM orders ORDER BY created_at DESC")
    rows = cur.fetchall()
    release_conn(locals().get("conn"))

    return {row["order_id"]: get_order_db(row["order_id"]) for row in rows}


def update_order_delivered_db(order_id, tx_signature, delivery_result):
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())
    p = qmark()

    cur.execute(f"""
    UPDATE orders
    SET status = {p}, tx_signature = {p}, updated_at = {p}, delivered_at = {p}, delivery_result = {p}, used = {p}
    WHERE order_id = {p}
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
    release_conn(locals().get("conn"))


def is_tx_processed_db(tx_signature):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    cur.execute(f"SELECT tx_signature FROM processed_txs WHERE tx_signature = {p}", (tx_signature,))
    row = cur.fetchone()
    release_conn(locals().get("conn"))
    return row is not None


def save_processed_tx_db(tx_signature):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO processed_txs (tx_signature, processed_at)
        VALUES ({p}, {p})
        ON CONFLICT (tx_signature) DO NOTHING
        """, (tx_signature, int(time.time())))
    else:
        cur.execute(f"""
        INSERT OR IGNORE INTO processed_txs (tx_signature, processed_at)
        VALUES ({p}, {p})
        """, (tx_signature, int(time.time())))
    conn.commit()
    release_conn(locals().get("conn"))


def register_agent_db(agent):
    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        now = int(time.time())

        p = qmark()

        cur.execute(
            f"SELECT agent_id, available, reputation FROM agents WHERE agent_id = {p}",
            (agent["agent_id"],)
        )
        exists = cur.fetchone()

        def safe_get(row, key, default=None):
            if not row:
                return default
            try:
                return row.get(key, default)
            except AttributeError:
                return default

        def safe_int(value, default=1):
            try:
                return int(value)
            except Exception:
                return default

        def safe_float(value, default=0.8):
            try:
                return float(value)
            except Exception:
                return default

        current_available = safe_int(safe_get(exists, "available", 1), 1)
        current_reputation = safe_float(safe_get(exists, "reputation", 0.8), 0.8)
        requested_available = 1 if agent.get("available", True) else 0

        # Kill rule:
        # - if already disabled, stay disabled
        # - if reputation <= 0.5, heartbeat cannot resurrect it
        new_available = 0 if current_available == 0 or current_reputation <= 0.5 else requested_available

        if exists:
            cur.execute(f"""
            UPDATE agents
            SET service = {p},
                url = {p},
                wallet = {p},
                price = {p},
                available = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                agent["service"],
                agent.get("url") or "",
                agent["wallet"],
                float(agent["price"]),
                new_available,
                now,
                agent["agent_id"],
            ))
        else:
            cur.execute(f"""
            INSERT INTO agents (
                agent_id, service, url, wallet, price, reputation, available, registered_at, updated_at
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                agent["agent_id"],
                agent["service"],
                agent.get("url") or "",
                agent["wallet"],
                float(agent["price"]),
                float(agent.get("reputation", 0.8)),
                1 if agent.get("available", True) else 0,
                now,
                now,
            ))

        conn.commit()

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def list_agents_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM agents ORDER BY service, agent_id")
    rows = cur.fetchall()
    release_conn(locals().get("conn"))

    agents = []
    for row in rows:
        a = dict(row)
        a["available"] = bool(a.get("available", 0))
        agents.append(a)

    return agents


def get_agents_for_service_db(service):
    now = int(time.time())
    timeout = 120

    agents = [
        a for a in list_agents_db()
        if a["service"] == service
        and a["available"]
        and (now - int(a["updated_at"]) <= timeout)
    ]

    return agents


def update_agent_reputation_db(agent_id, success=True):
    if not agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        p = qmark()
        cur.execute(f"""
        SELECT reputation, success_count, failure_count
        FROM agents
        WHERE agent_id = {p}
        """, (agent_id,))
        row = cur.fetchone()

        if not row:
            return None

        old_rep = float(row.get("reputation", 0.8))
        success_count = int(row.get("success_count", 0) or 0)
        failure_count = int(row.get("failure_count", 0) or 0)
        now = int(time.time())

        if success:
            success_count += 1

            # honest history can slowly recover old failures
            if success_count >= 5 and failure_count > 0:
                failure_count = max(0, failure_count - 1)

            new_rep = min(old_rep + 0.01, 1.0)

            cur.execute(f"""
            UPDATE agents
            SET reputation = {p},
                success_count = {p},
                failure_count = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                round(new_rep, 4),
                success_count,
                failure_count,
                now,
                agent_id,
            ))

        else:
            failure_count += 1
            new_rep = max(old_rep - 0.03, 0.1)

            # hard kill rule: suspicious repeatedly => disabled
            new_available = 0 if failure_count >= 3 or new_rep <= 0.5 else 1

            cur.execute(f"""
            UPDATE agents
            SET reputation = {p},
                failure_count = {p},
                last_slashed_at = {p},
                available = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                round(new_rep, 4),
                failure_count,
                now,
                new_available,
                now,
                agent_id,
            ))

        conn.commit()
        return round(new_rep, 4)

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)



def reactivate_agent_db(agent_id, reputation_floor=0.6):
    if not agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        now = int(time.time())
        p = qmark()

        cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (agent_id,))
        row = cur.fetchone()

        if not row:
            return None

        try:
            old_rep = float(row.get("reputation", 0.8))
        except Exception:
            old_rep = 0.8

        new_rep = max(old_rep, reputation_floor)

        cur.execute(f"""
        UPDATE agents
        SET available = 1,
            reputation = {p},
            failure_count = 0,
            last_slashed_at = NULL,
            updated_at = {p}
        WHERE agent_id = {p}
        """, (round(new_rep, 4), now, agent_id))

        conn.commit()

        return {
            "agent_id": agent_id,
            "available": True,
            "reputation": round(new_rep, 4),
            "failure_count": 0,
            "last_slashed_at": None,
        }

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def update_agent_call_stats_db(agent_ids, winner_id=None, latencies=None):
    if not agent_ids:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        now = int(time.time())
        p = qmark()

        latencies = latencies or {}

        for agent_id in agent_ids:
            if not agent_id:
                continue

            latency = float(latencies.get(agent_id, 0) or 0)

            if winner_id and agent_id == winner_id:
                cur.execute(f"""
                UPDATE agents
                SET call_count = COALESCE(call_count, 0) + 1,
                    win_count = COALESCE(win_count, 0) + 1,
                    latency_total = COALESCE(latency_total, 0) + {p},
                    updated_at = {p}
                WHERE agent_id = {p}
                """, (latency, now, agent_id))
            else:
                cur.execute(f"""
                UPDATE agents
                SET call_count = COALESCE(call_count, 0) + 1,
                    latency_total = COALESCE(latency_total, 0) + {p},
                    updated_at = {p}
                WHERE agent_id = {p}
                """, (latency, now, agent_id))

        conn.commit()
        return True

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def rename_agent_db(old_agent_id, new_agent_id):
    if not old_agent_id or not new_agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()

        cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (old_agent_id,))
        old_row = cur.fetchone()

        if not old_row:
            return {"status": "error", "message": "old_agent_not_found"}

        cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (new_agent_id,))
        new_row = cur.fetchone()

        if new_row:
            # Merge stats into the correct existing agent, then delete typo agent
            cur.execute(f"""
            UPDATE agents
            SET reputation = MAX(reputation, (SELECT reputation FROM agents WHERE agent_id = {p})),
                success_count = COALESCE(success_count, 0) + COALESCE((SELECT success_count FROM agents WHERE agent_id = {p}), 0),
                failure_count = COALESCE(failure_count, 0) + COALESCE((SELECT failure_count FROM agents WHERE agent_id = {p}), 0),
                call_count = COALESCE(call_count, 0) + COALESCE((SELECT call_count FROM agents WHERE agent_id = {p}), 0),
                win_count = COALESCE(win_count, 0) + COALESCE((SELECT win_count FROM agents WHERE agent_id = {p}), 0),
                latency_total = COALESCE(latency_total, 0) + COALESCE((SELECT latency_total FROM agents WHERE agent_id = {p}), 0),
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                old_agent_id,
                old_agent_id,
                old_agent_id,
                old_agent_id,
                old_agent_id,
                old_agent_id,
                int(time.time()),
                new_agent_id,
            ))

            cur.execute(f"DELETE FROM agents WHERE agent_id = {p}", (old_agent_id,))

        else:
            cur.execute(f"""
            UPDATE agents
            SET agent_id = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (new_agent_id, int(time.time()), old_agent_id))

        conn.commit()

        return {
            "status": "ok",
            "old_agent_id": old_agent_id,
            "new_agent_id": new_agent_id,
        }

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def get_stats_db():
    orders = list_orders_db()

    total_orders = len(orders)
    delivered_orders = len([o for o in orders.values() if o.get("status") == "delivered"])
    pending_orders = len([o for o in orders.values() if o.get("status") != "delivered"])

    total_volume = sum(float(o.get("price") or 0) for o in orders.values() if o.get("status") == "delivered")
    processed_transactions = delivered_orders

    revenue_by_seller = {}
    service_count = {}

    for o in orders.values():
        if o.get("status") != "delivered":
            continue

        seller = o.get("seller_id") or "unknown"
        service = o.get("service") or "unknown"

        revenue_by_seller.setdefault(seller, {"orders": 0, "revenue_iat": 0})
        revenue_by_seller[seller]["orders"] += 1
        revenue_by_seller[seller]["revenue_iat"] = round(
            revenue_by_seller[seller]["revenue_iat"] + float(o.get("price") or 0),
            4
        )

        service_count[service] = service_count.get(service, 0) + 1

    top_service = max(service_count, key=service_count.get) if service_count else None

    return {
        "total_orders": total_orders,
        "delivered_orders": delivered_orders,
        "pending_orders": pending_orders,
        "total_volume_iat": round(total_volume, 4),
        "processed_transactions": processed_transactions,
        "success_rate_percent": round((delivered_orders / total_orders * 100), 2) if total_orders else 0,
        "top_service": top_service,
        "revenue_by_seller": revenue_by_seller
    }


def get_network_status_db():
    agents = list_agents_db()
    stats = get_stats_db()

    now = int(time.time())
    timeout = 120

    online_agents = [
        a for a in agents
        if a["available"] and (now - int(a["updated_at"]) <= timeout)
    ]

    services = {}

    for agent in online_agents:
        service = agent["service"]
        services.setdefault(service, {"agents": [], "best_agent": None})

        score = round(float(agent["reputation"]) / float(agent["price"]), 4)

        info = {
            "agent_id": agent["agent_id"],
            "url": agent["url"],
            "wallet": agent["wallet"],
            "price": agent["price"],
            "reputation": agent["reputation"],
            "score": score,
            "updated_at": agent["updated_at"]
        }

        services[service]["agents"].append(info)

    for service, data in services.items():
        data["best_agent"] = max(data["agents"], key=lambda a: a["score"])

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


def create_factory_agent_db(service, description=None):
    agent_id = f"factory_{service}"
    wallet = "EPabAZ3CtMkbjduLrNcDZuXaEp37Ur2UG7VNUqSqQyApLQEcCxgnqK4f4Z"
    now = int(time.time())

    agent = {
        "agent_id": agent_id,
        "service": service,
        "url": "",
        "wallet": wallet,
        "price": 1.5,
        "reputation": 0.7,
        "available": True
    }

    register_agent_db(agent)

    return {
        "agent_id": agent_id,
        "service": service,
        "description": description or f"Factory-generated agent for {service}",
        "wallet": wallet,
        "price": 1.5,
        "reputation": 0.7,
        "created_at": now,
        "source": "agent_factory"
    }


def update_order_db(order_id, fields):
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())

    updates = []
    values = []

    for k, v in fields.items():
        updates.append(f"{k} = {qmark()}")
        values.append(v)

    updates.append(f"updated_at = {qmark()}")
    values.append(now)

    values.append(order_id)

    query = f"UPDATE orders SET {', '.join(updates)} WHERE order_id = {qmark()}"

    cur.execute(query, tuple(values))
    conn.commit()
    release_conn(locals().get("conn"))
