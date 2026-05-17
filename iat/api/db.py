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
            conn.close()
    except Exception:
        pass


def row_get(row, key, default=None):
    if row is None:
        return default

    try:
        if not isinstance(row, dict):
            row = dict(row)

        return row.get(key, default)

    except Exception:
        return default

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
        buyer_wallet TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        status TEXT NOT NULL,
        tx_signature TEXT,
        delivered_at INTEGER,
        delivery_result TEXT,
        used INTEGER DEFAULT 0
    )
    """)

    order_columns = {
        "buyer_wallet": "TEXT",
    }

    for column, col_type in order_columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {column} {col_type}")
            else:
                cur.execute(f"ALTER TABLE orders ADD COLUMN {column} {col_type}")
        except Exception:
            pass

    order_columns = {
        "buyer_intent": "TEXT",
        "requirements": "TEXT",
        "buyer_context": "TEXT",
    }

    for column, col_type in order_columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {column} {col_type}")
            else:
                cur.execute(f"ALTER TABLE orders ADD COLUMN {column} {col_type}")
        except Exception:
            pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS processed_txs (
        tx_signature TEXT PRIMARY KEY,
        processed_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    release_conn(locals().get("conn"))
    init_agents_table()
    init_buyers_table()
    init_agent_topic_stats_table()
    init_delegations_table()

    init_buyer_sessions_table()
    init_buyer_conversation_sessions_table()


def init_agents_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        service TEXT NOT NULL,
        url TEXT,
        wallet TEXT NOT NULL,
        agent_type TEXT DEFAULT 'standard',
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
        wallet_agent_count INTEGER DEFAULT 0,
        stake_slashed_total REAL DEFAULT 0,
        volume_total REAL DEFAULT 0,
        honest_volume REAL DEFAULT 0,
        fraud_volume REAL DEFAULT 0,
        dynamic_stake_required REAL DEFAULT 0
    )
    """)
    agent_columns = {
        "success_count": "INTEGER DEFAULT 0",
        "failure_count": "INTEGER DEFAULT 0",
        "last_slashed_at": "INTEGER",
        "call_count": "INTEGER DEFAULT 0",
        "win_count": "INTEGER DEFAULT 0",
        "latency_total": "REAL DEFAULT 0",
        "agent_type": "TEXT DEFAULT 'standard'",

        "trust_tier": "TEXT DEFAULT 'free'",
        "stake_amount": "REAL DEFAULT 0",
        "stake_required": "REAL DEFAULT 0",
        "risk_score": "REAL DEFAULT 0",
        "wallet_agent_count": "INTEGER DEFAULT 0",
        "stake_slashed_total": "REAL DEFAULT 0",
        "volume_total": "REAL DEFAULT 0",
        "honest_volume": "REAL DEFAULT 0",
        "fraud_volume": "REAL DEFAULT 0",
        "dynamic_stake_required": "REAL DEFAULT 0",
        "stake_status": "TEXT DEFAULT 'unstaked'",
        "stake_tx_signature": "TEXT",
        "stake_locked_at": "INTEGER",
        "stake_unlock_requested_at": "INTEGER",
        "capabilities": "TEXT DEFAULT '[]'",
        "specialties": "TEXT DEFAULT '[]'",
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


def init_delegations_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agent_delegations (
        delegation_id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        delegator_wallet TEXT NOT NULL,
        amount REAL DEFAULT 0,
        status TEXT DEFAULT 'locked',
        delegated_at INTEGER NOT NULL,
        unlock_requested_at INTEGER,
        updated_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    release_conn(conn)


def create_agent_delegation_db(delegation):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO agent_delegations (
        delegation_id, agent_id, delegator_wallet, amount,
        status, delegated_at, updated_at
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        delegation["delegation_id"],
        delegation["agent_id"],
        delegation["delegator_wallet"],
        float(delegation["amount"]),
        delegation.get("status", "locked"),
        now,
        now,
    ))

    conn.commit()
    release_conn(conn)

    return get_agent_delegation_db(delegation["delegation_id"])


def get_agent_delegation_db(delegation_id):
    if not delegation_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agent_delegations
    WHERE delegation_id = {p}
    """, (delegation_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def get_agent_delegated_stake_total_db(agent_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT COALESCE(SUM(amount), 0) AS delegated_total
    FROM agent_delegations
    WHERE agent_id = {p}
      AND status = 'locked'
    """, (agent_id,))

    row = cur.fetchone()
    release_conn(conn)

    if not row:
        return 0.0

    return float(row_get(row, "delegated_total", 0) or 0)


def list_agent_delegations_db(agent_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agent_delegations
    WHERE agent_id = {p}
    ORDER BY updated_at DESC
    """, (agent_id,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]


def list_delegator_positions_db(delegator_wallet):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agent_delegations
    WHERE delegator_wallet = {p}
    ORDER BY updated_at DESC
    """, (delegator_wallet,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]




def init_buyer_sessions_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyer_sessions (
        buyer_wallet TEXT PRIMARY KEY,
        session_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    release_conn(conn)


def save_buyer_session_db(buyer_wallet, session_json):
    import json
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    payload = json.dumps(session_json)

    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO buyer_sessions (
            buyer_wallet, session_json, updated_at
        )
        VALUES ({p}, {p}, {p})
        ON CONFLICT (buyer_wallet)
        DO UPDATE SET
            session_json = EXCLUDED.session_json,
            updated_at = EXCLUDED.updated_at
        """, (
            buyer_wallet,
            payload,
            now,
        ))
    else:
        cur.execute(f"""
        INSERT OR REPLACE INTO buyer_sessions (
            buyer_wallet, session_json, updated_at
        )
        VALUES ({p}, {p}, {p})
        """, (
            buyer_wallet,
            payload,
            now,
        ))

    conn.commit()
    release_conn(conn)


def get_buyer_session_db(buyer_wallet):
    import json

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT session_json
    FROM buyer_sessions
    WHERE buyer_wallet = {p}
    """, (buyer_wallet,))

    row = cur.fetchone()
    release_conn(conn)

    if not row:
        return None

    raw = row_get(row, "session_json")

    try:
        return json.loads(raw)
    except Exception:
        return None



def init_buyer_conversation_sessions_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyer_conversation_sessions (
        session_id TEXT PRIMARY KEY,
        buyer_wallet TEXT NOT NULL,
        session_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    release_conn(conn)


def cleanup_expired_buyer_sessions_db(ttl_seconds=300):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    cutoff = int(time.time()) - int(ttl_seconds)

    cur.execute(f"""
    DELETE FROM buyer_conversation_sessions
    WHERE updated_at < {p}
    """, (cutoff,))

    conn.commit()
    release_conn(conn)


def save_buyer_conversation_session_db(session_id, buyer_wallet, session_json):
    import json

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())
    payload = json.dumps(session_json)

    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO buyer_conversation_sessions (
            session_id, buyer_wallet, session_json, updated_at
        )
        VALUES ({p}, {p}, {p}, {p})
        ON CONFLICT (session_id)
        DO UPDATE SET
            buyer_wallet = EXCLUDED.buyer_wallet,
            session_json = EXCLUDED.session_json,
            updated_at = EXCLUDED.updated_at
        """, (session_id, buyer_wallet, payload, now))
    else:
        cur.execute(f"""
        INSERT OR REPLACE INTO buyer_conversation_sessions (
            session_id, buyer_wallet, session_json, updated_at
        )
        VALUES ({p}, {p}, {p}, {p})
        """, (session_id, buyer_wallet, payload, now))

    conn.commit()
    release_conn(conn)


def get_buyer_conversation_session_db(session_id, buyer_wallet, ttl_seconds=300):
    import json

    if not session_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    cutoff = int(time.time()) - int(ttl_seconds)

    cur.execute(f"""
    SELECT session_json, updated_at
    FROM buyer_conversation_sessions
    WHERE session_id = {p}
      AND buyer_wallet = {p}
      AND updated_at >= {p}
    """, (session_id, buyer_wallet, cutoff))

    row = cur.fetchone()
    release_conn(conn)

    if not row:
        return None

    try:
        return json.loads(row_get(row, "session_json"))
    except Exception:
        return None





def init_agent_topic_stats_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agent_topic_stats (
        agent_id TEXT NOT NULL,
        topic TEXT NOT NULL,

        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,

        consensus_score REAL DEFAULT 0,
        avg_overlap REAL DEFAULT 0,
        avg_quality REAL DEFAULT 0,

        last_updated INTEGER NOT NULL,

        PRIMARY KEY (agent_id, topic)
    )
    """)

    conn.commit()
    release_conn(locals().get("conn"))


def init_buyers_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyers (
        buyer_wallet TEXT PRIMARY KEY,
        orders_count INTEGER DEFAULT 0,
        claims_count INTEGER DEFAULT 0,
        false_claims_count INTEGER DEFAULT 0,
        disputes_count INTEGER DEFAULT 0,
        refunded_count INTEGER DEFAULT 0,
        buyer_risk_score REAL DEFAULT 0,
        banned INTEGER DEFAULT 0,
        ban_reason TEXT,
        banned_at INTEGER,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL
    )
    """)

    buyer_columns = {
        "orders_count": "INTEGER DEFAULT 0",
        "claims_count": "INTEGER DEFAULT 0",
        "false_claims_count": "INTEGER DEFAULT 0",
        "disputes_count": "INTEGER DEFAULT 0",
        "refunded_count": "INTEGER DEFAULT 0",
        "buyer_risk_score": "REAL DEFAULT 0",
        "banned": "INTEGER DEFAULT 0",
        "ban_reason": "TEXT",
        "banned_at": "INTEGER",
        "first_seen": "INTEGER",
        "last_seen": "INTEGER",
    }

    for column, col_type in buyer_columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE buyers ADD COLUMN IF NOT EXISTS {column} {col_type}")
            else:
                cur.execute(f"ALTER TABLE buyers ADD COLUMN {column} {col_type}")
        except Exception:
            pass

    conn.commit()
    release_conn(locals().get("conn"))


def get_buyer_db(buyer_wallet):
    if not buyer_wallet:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
    row = cur.fetchone()

    release_conn(locals().get("conn"))

    if not row:
        return None

    return dict(row)


def is_buyer_banned_db(buyer_wallet):
    buyer = get_buyer_db(buyer_wallet)

    if not buyer:
        return False

    return bool(buyer.get("banned", 0))


def ban_buyer_db(buyer_wallet, reason="fraud_detected"):
    if not buyer_wallet:
        return None

    now = int(time.time())
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
    exists = cur.fetchone()

    if exists:
        cur.execute(f"""
        UPDATE buyers
        SET banned = 1,
            ban_reason = {p},
            banned_at = {p},
            buyer_risk_score = 1.0,
            last_seen = {p}
        WHERE buyer_wallet = {p}
        """, (
            reason,
            now,
            now,
            buyer_wallet,
        ))
    else:
        cur.execute(f"""
        INSERT INTO buyers (
            buyer_wallet,
            orders_count,
            claims_count,
            false_claims_count,
            disputes_count,
            refunded_count,
            buyer_risk_score,
            banned,
            ban_reason,
            banned_at,
            first_seen,
            last_seen
        )
        VALUES ({p}, 0, 0, 0, 0, 0, 1.0, 1, {p}, {p}, {p}, {p})
        """, (
            buyer_wallet,
            reason,
            now,
            now,
            now,
        ))

    conn.commit()

    cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
    row = cur.fetchone()

    release_conn(conn)

    return dict(row) if row else None


def unban_buyer_db(buyer_wallet):
    if not buyer_wallet:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE buyers
    SET banned = 0,
        ban_reason = NULL,
        banned_at = NULL,
        buyer_risk_score = 0,
        last_seen = {p}
    WHERE buyer_wallet = {p}
    """, (now, buyer_wallet))

    conn.commit()

    cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
    row = cur.fetchone()

    release_conn(conn)

    return dict(row) if row else None


def list_buyers_db(limit=100):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM buyers
    ORDER BY buyer_risk_score DESC, last_seen DESC
    """)

    rows = cur.fetchall()
    release_conn(locals().get("conn"))

    buyers = [dict(row) for row in rows]
    return buyers[:limit]


def register_buyer_seen_db(buyer_wallet):
    if not buyer_wallet:
        return None

    now = int(time.time())
    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()

        cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
        row = cur.fetchone()

        if row:
            cur.execute(f"""
            UPDATE buyers
            SET orders_count = orders_count + 1,
                last_seen = {p}
            WHERE buyer_wallet = {p}
            """, (now, buyer_wallet))
        else:
            cur.execute(f"""
            INSERT INTO buyers (
                buyer_wallet,
                orders_count,
                claims_count,
                false_claims_count,
                disputes_count,
                refunded_count,
                buyer_risk_score,
                first_seen,
                last_seen
            )
            VALUES ({p}, 1, 0, 0, 0, 0, 0, {p}, {p})
            """, (buyer_wallet, now, now))

        conn.commit()
        return get_buyer_db(buyer_wallet)

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def compute_buyer_risk_score(claims_count, false_claims_count, disputes_count, refunded_count, orders_count):
    orders = max(int(orders_count or 0), 1)
    claims = int(claims_count or 0)
    false_claims = int(false_claims_count or 0)
    disputes = int(disputes_count or 0)
    refunded = int(refunded_count or 0)

    claims_rate = claims / orders
    false_claims_rate = false_claims / orders
    disputes_rate = disputes / orders
    refunded_rate = refunded / orders

    risk = (
        claims_rate * 0.25 +
        false_claims_rate * 0.40 +
        disputes_rate * 0.25 +
        refunded_rate * 0.10
    )

    return round(min(max(risk, 0), 1), 4)


def update_buyer_claim_stats_db(
    buyer_wallet,
    claim=False,
    false_claim=False,
    dispute=False,
    refunded=False,
):
    if not buyer_wallet:
        return None

    now = int(time.time())
    conn = None

    try:
        existing = get_buyer_db(buyer_wallet)
        if not existing:
            register_buyer_seen_db(buyer_wallet)

        conn = get_conn()
        cur = conn.cursor()
        p = qmark()

        cur.execute(f"SELECT * FROM buyers WHERE buyer_wallet = {p}", (buyer_wallet,))
        row = cur.fetchone()

        if not row:
            return None

        buyer = dict(row)

        orders_count = int(buyer.get("orders_count", 0) or 0)
        claims_count = int(buyer.get("claims_count", 0) or 0) + (1 if claim else 0)
        false_claims_count = int(buyer.get("false_claims_count", 0) or 0) + (1 if false_claim else 0)
        disputes_count = int(buyer.get("disputes_count", 0) or 0) + (1 if dispute else 0)
        refunded_count = int(buyer.get("refunded_count", 0) or 0) + (1 if refunded else 0)

        buyer_risk_score = compute_buyer_risk_score(
            claims_count,
            false_claims_count,
            disputes_count,
            refunded_count,
            orders_count,
        )

        cur.execute(f"""
        UPDATE buyers
        SET claims_count = {p},
            false_claims_count = {p},
            disputes_count = {p},
            refunded_count = {p},
            buyer_risk_score = {p},
            last_seen = {p}
        WHERE buyer_wallet = {p}
        """, (
            claims_count,
            false_claims_count,
            disputes_count,
            refunded_count,
            buyer_risk_score,
            now,
            buyer_wallet,
        ))

        conn.commit()
        return get_buyer_db(buyer_wallet)

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)



def create_order_db(order_id, order):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO orders (
        order_id, service, query, price, seller_id, seller_wallet, seller_url, seller_source,
        buyer_secret, buyer_wallet, buyer_intent, requirements, buyer_context,
        foundation_context, execution_mode, execution_context,
        created_at, updated_at, status, tx_signature, delivered_at, delivery_result, used
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
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
        order.get("buyer_wallet"),
        json.dumps(order.get("buyer_intent")) if order.get("buyer_intent") is not None else None,
        json.dumps(order.get("requirements")) if order.get("requirements") is not None else None,
        json.dumps(order.get("buyer_context")) if order.get("buyer_context") is not None else None,
        json.dumps(order.get("foundation_context")) if order.get("foundation_context") is not None else None,
        order.get("execution_mode"),
        json.dumps(order.get("execution_context")) if order.get("execution_context") is not None else None,
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


def update_order_buyer_wallet_db(order_id, buyer_wallet):
    if not order_id or not buyer_wallet:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE orders
        SET buyer_wallet = {p},
            updated_at = {p}
        WHERE order_id = {p}
        """, (
            buyer_wallet,
            now,
            order_id,
        ))

        conn.commit()
        return get_order_db(order_id)

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


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

    for json_field in ["delivery_result", "buyer_intent", "requirements", "buyer_context"]:
        if order.get(json_field):
            try:
                order[json_field] = json.loads(order[json_field])
            except Exception:
                order[json_field] = {"raw": order[json_field], "parse_error": True}

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
                return row_get(row, key, default)
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

        seller_approved = (
            str(agent.get("agent_type", "")).lower() == "seller"
            and str(agent.get("seller_status", "")).lower() == "active"
            and str(agent.get("verification_status", "")).lower() == "foundation_verified"
        )

        # Kill rule:
        # - if already disabled, stay disabled
        # - if reputation <= 0.5, heartbeat cannot resurrect it
        # Exception:
        # - protocol foundation review can activate verified sellers.
        if seller_approved:
            new_available = requested_available
        else:
            new_available = 0 if current_available == 0 or current_reputation <= 0.5 else requested_available

        if exists:
            cur.execute(f"""
            UPDATE agents
            SET service = {p},
                url = {p},
                wallet = {p},
                agent_type = {p},
                price = {p},
                available = {p},
                stake_amount = {p},
                stake_required = {p},
                trust_tier = {p},
                capabilities = {p},
                specialties = {p},
                seller_status = {p},
                verification_status = {p},
                seller_metadata = {p},
                buyer_access = {p},
                web_access = {p},
                raw_prompt_access = {p},
                foundation_verified_at = {p},
                foundation_verdict = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                agent["service"],
                agent.get("url") or "",
                agent["wallet"],
                agent.get("agent_type", "standard"),
                float(agent["price"]),
                new_available,
                float(agent.get("stake_amount", 0) or 0),
                float(agent.get("stake_required", 0) or 0),
                agent.get("trust_tier", "free"),
                agent.get("capabilities", "[]"),
                agent.get("specialties", "[]"),
                agent.get("seller_status", "pending_review"),
                agent.get("verification_status", "unverified"),
                json.dumps(agent.get("seller_metadata", {})) if not isinstance(agent.get("seller_metadata"), str) else agent.get("seller_metadata"),
                1 if agent.get("buyer_access") else 0,
                1 if agent.get("web_access") else 0,
                1 if agent.get("raw_prompt_access") else 0,
                agent.get("foundation_verified_at"),
                agent.get("foundation_verdict"),
                now,
                agent["agent_id"],
            ))
        else:
            cur.execute(f"""
            INSERT INTO agents (
                agent_id, service, url, wallet, agent_type, price, reputation, available,
                stake_amount, stake_required, trust_tier,
                capabilities, specialties,
                seller_status, verification_status, seller_metadata,
                buyer_access, web_access, raw_prompt_access,
                foundation_verified_at, foundation_verdict,
                registered_at, updated_at
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                agent["agent_id"],
                agent["service"],
                agent.get("url") or "",
                agent["wallet"],
                agent.get("agent_type", "standard"),
                float(agent["price"]),
                float(agent.get("reputation", 0.8)),
                1 if agent.get("available", True) else 0,
                float(agent.get("stake_amount", 0) or 0),
                float(agent.get("stake_required", 0) or 0),
                agent.get("trust_tier", "free"),
                agent.get("capabilities", "[]"),
                agent.get("specialties", "[]"),
                agent.get("seller_status", "pending_review"),
                agent.get("verification_status", "unverified"),
                json.dumps(agent.get("seller_metadata", {})) if not isinstance(agent.get("seller_metadata"), str) else agent.get("seller_metadata"),
                1 if agent.get("buyer_access") else 0,
                1 if agent.get("web_access") else 0,
                1 if agent.get("raw_prompt_access") else 0,
                agent.get("foundation_verified_at"),
                agent.get("foundation_verdict"),
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


def delete_agent_db(agent_id):
    if not agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (agent_id,))
    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return None

    deleted = dict(row)

    cur.execute(f"DELETE FROM agents WHERE agent_id = {p}", (agent_id,))
    conn.commit()
    release_conn(conn)

    return deleted


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



def get_agent_db(agent_id):
    if not agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(
        f"SELECT * FROM agents WHERE agent_id = {p}",
        (agent_id,),
    )

    row = cur.fetchone()

    release_conn(conn)

    if not row:
        return None

    agent = dict(row)
    agent["available"] = bool(agent.get("available", 0))

    return agent


def get_agents_for_service_db(service):
    now = int(time.time())

    ephemeral_timeout = int(os.getenv("IAT_EPHEMERAL_AGENT_TIMEOUT_SECONDS", "120"))
    permanent_timeout = int(os.getenv("IAT_PERMANENT_AGENT_TIMEOUT_SECONDS", "86400"))

    permanent_agent_ids = {
        "web_agent_standard",
        "web_agent_cheap",
        "web_agent_malicious",
    }

    agents = []

    for a in list_agents_db():
        if a["service"] != service:
            continue

        if not a["available"]:
            continue

        url = a.get("url") or ""
        agent_id = a.get("agent_id") or ""

        # Foundation agents are protocol infrastructure.
        # They must not disappear from routing because of heartbeat staleness.
        is_foundation = str(a.get("agent_type", "")).lower() == "foundation"

        is_permanent = (
            is_foundation
            or "onrender.com" in url
            or agent_id in permanent_agent_ids
        )

        timeout = permanent_timeout if is_permanent else ephemeral_timeout

        if is_foundation or now - int(a["updated_at"]) <= timeout:
            agents.append(a)

    return agents



def is_foundation_agent_db(agent_id):
    if not agent_id:
        return False

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(
        f"SELECT agent_type FROM agents WHERE agent_id = {p}",
        (agent_id,)
    )
    row = cur.fetchone()
    release_conn(conn)

    if not row:
        return False

    return row_get(row, "agent_type", "seller") == "foundation"


def update_agent_reputation_db(agent_id, success=True):
    if is_foundation_agent_db(agent_id):
        return None

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

        old_rep = float(row_get(row, "reputation", 0.8))
        success_count = int(row_get(row, "success_count", 0) or 0)
        failure_count = int(row_get(row, "failure_count", 0) or 0)
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
            # Multi-source decentralized market:
            # disagreement alone must not disable agents.
            # Availability should only drop for extreme cases.
            severe_failure = (
                failure_count >= 10
                and new_rep <= 0.20
            )

            new_available = 0 if severe_failure else 1

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
            old_rep = float(row_get(row, "reputation", 0.8))
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


def set_agent_trust_db(agent_id, trust_tier=None, stake_amount=None, stake_required=None, risk_score=None):
    if not agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"SELECT agent_id FROM agents WHERE agent_id = {p}", (agent_id,))
        row = cur.fetchone()

        if not row:
            return None

        updates = []
        values = []

        if trust_tier is not None:
            updates.append(f"trust_tier = {p}")
            values.append(str(trust_tier))

        if stake_amount is not None:
            updates.append(f"stake_amount = {p}")
            values.append(float(stake_amount))

        if stake_required is not None:
            updates.append(f"stake_required = {p}")
            values.append(float(stake_required))

        if risk_score is not None:
            risk_score = max(0.0, min(float(risk_score), 1.0))
            updates.append(f"risk_score = {p}")
            values.append(risk_score)

        updates.append(f"updated_at = {p}")
        values.append(now)

        values.append(agent_id)

        query = f"UPDATE agents SET {', '.join(updates)} WHERE agent_id = {p}"
        cur.execute(query, tuple(values))
        conn.commit()

        cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (agent_id,))
        updated = cur.fetchone()

        return dict(updated)

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    finally:
        release_conn(conn)


def reset_agent_trust_db(agent_id):
    return set_agent_trust_db(
        agent_id,
        trust_tier="free",
        stake_amount=0,
        stake_required=0,
        risk_score=0,
    )


def slash_agent_stake_db(agent_id, slash_ratio=0.10, reason="protocol_slash"):
    if is_foundation_agent_db(agent_id):
        return {
            "agent_id": agent_id,
            "slashed_amount": 0,
            "remaining_stake": 0,
            "stake_slashed_total": 0,
            "reason": "foundation_agent_no_slash",
        }

    if not agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        SELECT agent_id, stake_amount, stake_slashed_total
        FROM agents
        WHERE agent_id = {p}
        """, (agent_id,))
        row = cur.fetchone()

        if not row:
            return None

        current_stake = float(row_get(row, "stake_amount", 0) or 0)
        old_slashed = float(row_get(row, "stake_slashed_total", 0) or 0)

        if current_stake <= 0:
            return {
                "agent_id": agent_id,
                "slashed_amount": 0,
                "remaining_stake": 0,
                "stake_slashed_total": old_slashed,
                "reason": "no_stake_to_slash",
            }

        slash_ratio = max(0.0, min(float(slash_ratio), 1.0))
        slashed_amount = round(current_stake * slash_ratio, 6)
        remaining_stake = max(0.0, current_stake - slashed_amount)
        new_slashed_total = old_slashed + slashed_amount

        if remaining_stake >= 1000:
            trust_tier = "premium"
        elif remaining_stake >= 100:
            trust_tier = "standard"
        elif remaining_stake >= 10:
            trust_tier = "recovery"
        else:
            trust_tier = "free"

        cur.execute(f"""
        UPDATE agents
        SET stake_amount = {p},
            stake_slashed_total = {p},
            trust_tier = {p},
            updated_at = {p}
        WHERE agent_id = {p}
        """, (
            round(remaining_stake, 6),
            round(new_slashed_total, 6),
            trust_tier,
            now,
            agent_id,
        ))

        conn.commit()

        return {
            "agent_id": agent_id,
            "slashed_amount": round(slashed_amount, 6),
            "remaining_stake": round(remaining_stake, 6),
            "stake_slashed_total": round(new_slashed_total, 6),
            "trust_tier": trust_tier,
            "reason": reason,
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


def compute_dynamic_stake_required_db(agent_id):
    if is_foundation_agent_db(agent_id):
        return {
            "agent_id": agent_id,
            "dynamic_stake_required": 0,
            "stake_required": 0,
            "reason": "foundation_agent_no_stake_required",
        }

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()

        cur.execute(f"""
        SELECT reputation, stake_amount, volume_total, honest_volume, fraud_volume, failure_count
        FROM agents
        WHERE agent_id = {p}
        """, (agent_id,))
        row = cur.fetchone()

        if not row:
            return None

        row = dict(row)

        reputation = float(row_get(row, "reputation", 0.5) or 0.5)
        volume_total = float(row_get(row, "volume_total", 0) or 0)
        honest_volume = float(row_get(row, "honest_volume", 0) or 0)
        fraud_volume = float(row_get(row, "fraud_volume", 0) or 0)
        failures = int(row_get(row, "failure_count", 0) or 0)

        fraud_rate = fraud_volume / volume_total if volume_total > 0 else 0
        honest_rate = honest_volume / volume_total if volume_total > 0 else 0

        # Market resilience: high if most processed value was honest.
        market_resilience_score = max(0.0, min(1.0, honest_rate * reputation))

        # Base required stake scales with value handled.
        base_required = volume_total * 0.10

        # Honest agents get easier conditions as they prove volume.
        honest_discount = market_resilience_score * 0.50

        # Suspicious agents face higher requirements.
        risk_multiplier = 1 + (fraud_rate * 5) + min(failures * 0.25, 2)

        required = base_required * risk_multiplier * (1 - honest_discount)

        # Minimums:
        # - honest/free low-volume agents are not blocked
        # - suspicious agents need skin in the game
        if fraud_rate > 0.20 or failures >= 3:
            required = max(required, 10)

        required = round(required, 6)

        cur.execute(f"""
        UPDATE agents
        SET dynamic_stake_required = {p},
            stake_required = CASE
                WHEN {p} > stake_required THEN {p}
                ELSE stake_required
            END
        WHERE agent_id = {p}
        """, (required, required, required, agent_id))

        conn.commit()

        return {
            "agent_id": agent_id,
            "volume_total": round(volume_total, 6),
            "honest_volume": round(honest_volume, 6),
            "fraud_volume": round(fraud_volume, 6),
            "fraud_rate": round(fraud_rate, 6),
            "honest_rate": round(honest_rate, 6),
            "market_resilience_score": round(market_resilience_score, 6),
            "dynamic_stake_required": required,
        }

    finally:
        release_conn(conn)


def update_agent_volume_stats_db(agent_id, amount, honest=True):
    if is_foundation_agent_db(agent_id):
        return {
            "agent_id": agent_id,
            "volume_total": 0,
            "honest_volume": 0,
            "fraud_volume": 0,
            "dynamic_stake_required": 0,
            "reason": "foundation_agent_no_market_volume_accounting",
        }

    if not agent_id:
        return None

    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())
        amount = float(amount or 0)

        if honest:
            cur.execute(f"""
            UPDATE agents
            SET volume_total = COALESCE(volume_total, 0) + {p},
                honest_volume = COALESCE(honest_volume, 0) + {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (amount, amount, now, agent_id))
        else:
            cur.execute(f"""
            UPDATE agents
            SET volume_total = COALESCE(volume_total, 0) + {p},
                fraud_volume = COALESCE(fraud_volume, 0) + {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (amount, amount, now, agent_id))

        conn.commit()

    finally:
        release_conn(conn)

    return compute_dynamic_stake_required_db(agent_id)


def get_network_economics_db():
    conn = None

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        SELECT
            COUNT(*) as agents_count,
            COALESCE(SUM(stake_amount), 0) as total_stake,
            COALESCE(SUM(stake_slashed_total), 0) as total_slashed,
            COALESCE(SUM(volume_total), 0) as total_volume,
            COALESCE(SUM(honest_volume), 0) as honest_volume,
            COALESCE(SUM(fraud_volume), 0) as fraud_volume,
            COALESCE(SUM(dynamic_stake_required), 0) as total_dynamic_stake_required
        FROM agents
        """)
        row = cur.fetchone()

        total_volume = float(row["total_volume"] or 0)
        honest_volume = float(row["honest_volume"] or 0)
        fraud_volume = float(row["fraud_volume"] or 0)
        total_stake = float(row["total_stake"] or 0)
        required = float(row["total_dynamic_stake_required"] or 0)

        fraud_rate = fraud_volume / total_volume if total_volume > 0 else 0
        honest_rate = honest_volume / total_volume if total_volume > 0 else 0
        stake_coverage = total_stake / required if required > 0 else 1

        resilience_score = max(
            0.0,
            min(
                1.0,
                (honest_rate * 0.60)
                + (min(stake_coverage, 1.0) * 0.30)
                + ((1 - fraud_rate) * 0.10)
            )
        )

        return {
            "agents_count": int(row["agents_count"] or 0),
            "total_stake": round(total_stake, 6),
            "total_slashed": round(float(row["total_slashed"] or 0), 6),
            "total_volume": round(total_volume, 6),
            "honest_volume": round(honest_volume, 6),
            "fraud_volume": round(fraud_volume, 6),
            "honest_rate": round(honest_rate, 6),
            "fraud_rate": round(fraud_rate, 6),
            "total_dynamic_stake_required": round(required, 6),
            "stake_coverage": round(stake_coverage, 6),
            "market_resilience_score": round(resilience_score, 6),
        }

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
            "agent_type": agent.get("agent_type", "standard"),
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


def recompute_agent_metrics_db(agent_id):
    if is_foundation_agent_db(agent_id):
        return {
            "agent_id": agent_id,
            "reputation": None,
            "risk_score": 0,
            "trust_tier": "foundation",
            "dynamic_stake_required": 0,
            "reason": "foundation_agent_metrics_bypass",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(
        f"SELECT * FROM agents WHERE agent_id = {p}",
        (agent_id,)
    )

    row = cur.fetchone()

    if not row:
        release_conn(locals().get("conn"))
        return None

    agent = dict(row)

    success_count = int(agent.get("success_count") or 0)
    failure_count = int(agent.get("failure_count") or 0)
    call_count = int(agent.get("call_count") or 0)
    win_count = int(agent.get("win_count") or 0)

    latency_total = float(agent.get("latency_total") or 0)

    honest_volume = float(agent.get("honest_volume") or 0)
    fraud_volume = float(agent.get("fraud_volume") or 0)
    volume_total = float(agent.get("volume_total") or 0)

    total_actions = success_count + failure_count

    success_rate = (
        success_count / total_actions
        if total_actions > 0 else 0.5
    )

    avg_latency = (
        latency_total / call_count
        if call_count > 0 else 0
    )

    honest_rate = (
        honest_volume / volume_total
        if volume_total > 0 else 0.5
    )

    fraud_rate = (
        fraud_volume / volume_total
        if volume_total > 0 else 0
    )

    reputation = (
        success_rate * 0.45 +
        honest_rate * 0.35 +
        min(win_count / max(call_count, 1), 1.0) * 0.20
    )

    reputation = round(max(0.0, min(1.0, reputation)), 4)

    latency_penalty = min(avg_latency / 15.0, 1.0)

    risk_score = (
        fraud_rate * 0.60 +
        (1.0 - success_rate) * 0.25 +
        latency_penalty * 0.15
    )

    risk_score = round(max(0.0, min(1.0, risk_score)), 4)

    if reputation >= 0.90 and risk_score <= 0.15:
        trust_tier = "premium"
    elif reputation >= 0.75 and risk_score <= 0.35:
        trust_tier = "verified"
    else:
        trust_tier = "free"

    dynamic_stake_required = round(
        max(
            10,
            volume_total * (1 + risk_score * 4)
        ),
        2
    )

    cur.execute(f"""
    UPDATE agents
    SET reputation = {p},
        risk_score = {p},
        trust_tier = {p},
        dynamic_stake_required = {p}
    WHERE agent_id = {p}
    """, (
        reputation,
        risk_score,
        trust_tier,
        dynamic_stake_required,
        agent_id,
    ))

    conn.commit()
    release_conn(locals().get("conn"))

    return {
        "agent_id": agent_id,
        "reputation": reputation,
        "risk_score": risk_score,
        "trust_tier": trust_tier,
        "dynamic_stake_required": dynamic_stake_required,
        "success_rate": round(success_rate, 4),
        "honest_rate": round(honest_rate, 4),
        "avg_latency": round(avg_latency, 4),
    }


def update_agent_topic_stats_db(agent_id, topics, success=True, consensus_score=0, overlap=0, quality=0):
    if not agent_id or not topics:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    for topic in topics:
        topic = str(topic or "").strip().lower()
        if not topic:
            continue

        if USE_POSTGRES:
            cur.execute(f"""
            INSERT INTO agent_topic_stats (
                agent_id, topic, success_count, failure_count,
                consensus_score, avg_overlap, avg_quality, last_updated
            )
            VALUES (
                {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
            )
            ON CONFLICT (agent_id, topic)
            DO UPDATE SET
                success_count = agent_topic_stats.success_count + EXCLUDED.success_count,
                failure_count = agent_topic_stats.failure_count + EXCLUDED.failure_count,
                consensus_score = (
                    agent_topic_stats.consensus_score + EXCLUDED.consensus_score
                ) / 2,
                avg_overlap = (
                    agent_topic_stats.avg_overlap + EXCLUDED.avg_overlap
                ) / 2,
                avg_quality = (
                    agent_topic_stats.avg_quality + EXCLUDED.avg_quality
                ) / 2,
                last_updated = EXCLUDED.last_updated
            """, (
                agent_id,
                topic,
                1 if success else 0,
                0 if success else 1,
                float(consensus_score or 0),
                float(overlap or 0),
                float(quality or 0),
                now,
            ))
        else:
            cur.execute(f"""
            INSERT OR IGNORE INTO agent_topic_stats (
                agent_id, topic, success_count, failure_count,
                consensus_score, avg_overlap, avg_quality, last_updated
            )
            VALUES ({p}, {p}, 0, 0, 0, 0, 0, {p})
            """, (agent_id, topic, now))

            cur.execute(f"""
            UPDATE agent_topic_stats
            SET success_count = success_count + {p},
                failure_count = failure_count + {p},
                consensus_score = (consensus_score + {p}) / 2,
                avg_overlap = (avg_overlap + {p}) / 2,
                avg_quality = (avg_quality + {p}) / 2,
                last_updated = {p}
            WHERE agent_id = {p}
              AND topic = {p}
            """, (
                1 if success else 0,
                0 if success else 1,
                float(consensus_score or 0),
                float(overlap or 0),
                float(quality or 0),
                now,
                agent_id,
                topic,
            ))

    conn.commit()
    release_conn(conn)
    return True


def get_agent_topic_stats_db(agent_id):
    if not agent_id:
        return []

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agent_topic_stats
    WHERE agent_id = {p}
    ORDER BY success_count DESC, avg_overlap DESC, avg_quality DESC
    """, (agent_id,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]

def compute_agent_topic_score_db(agent_id, topics):
    """
    Compute historical semantic competence score for an agent.

    Generic:
    - no hardcoded verticals
    - based only on emergent semantic memory
    """
    if not agent_id or not topics:
        return 0.5

    stats = get_agent_topic_stats_db(agent_id)

    if not stats:
        return 0.5

    topic_map = {
        str(x.get("topic")).lower(): x
        for x in stats
    }

    scores = []

    for topic in topics:
        topic = str(topic or "").lower()

        row = topic_map.get(topic)
        if not row:
            continue

        success = int(row.get("success_count", 0) or 0)
        failure = int(row.get("failure_count", 0) or 0)

        total = success + failure

        if total <= 0:
            continue

        # Bayesian smoothing:
        # avoid one early failure destroying an agent's topic competence forever.
        success_rate = (success + 1) / (total + 2)

        overlap = float(row.get("avg_overlap", 0) or 0)
        quality = float(row.get("avg_quality", 0) or 0)
        consensus = float(row.get("consensus_score", 0) or 0)

        last_updated = int(row.get("last_updated", 0) or 0)
        age_seconds = max(0, int(time.time()) - last_updated)

        # Semantic memory decay:
        # old competence matters less over time.
        if age_seconds <= 86400:
            freshness = 1.0
        elif age_seconds <= 86400 * 7:
            freshness = 0.9
        elif age_seconds <= 86400 * 30:
            freshness = 0.75
        else:
            freshness = 0.5

        score = (
            success_rate * 0.45 +
            overlap * 0.20 +
            quality * 0.20 +
            consensus * 0.15
        )

        score = score * freshness

        scores.append(score)

    if not scores:
        return 0.5

    return round(sum(scores) / len(scores), 4)
