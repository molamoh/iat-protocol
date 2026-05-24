from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

pool = None
import os
import sqlite3
import json
import time
import uuid
from pathlib import Path

DB_PATH = Path("iat_protocol.db")
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

def is_postgres():
    return bool(USE_POSTGRES)



from psycopg2.pool import SimpleConnectionPool

pool = None

def get_conn():
    global pool

    if USE_POSTGRES:
        if pool is None:
            pool = SimpleConnectionPool(
                1,
                10,
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
    except Exception as e:
        print("DB_RELEASE_ERROR:", type(e).__name__, str(e), flush=True)


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
    init_sellers_table()
    init_seller_agents_table()
    ensure_seller_agent_runtime_columns()
    init_seller_governance_events_table()
    init_adaptive_defense_tables()
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
        "risk_score": "REAL DEFAULT 0",
        "dynamic_stake_required": "REAL DEFAULT 0",
        "max_order_value": "REAL DEFAULT 0",
        "seller_id": "TEXT",
        "seller_agent_id": "TEXT",
        "seller_status": "TEXT DEFAULT 'pending_review'",
        "verification_status": "TEXT DEFAULT 'unverified'",
        "seller_metadata": "TEXT DEFAULT '{}'",
        "buyer_access": "INTEGER DEFAULT 0",
        "web_access": "INTEGER DEFAULT 0",
        "raw_prompt_access": "INTEGER DEFAULT 0",
        "foundation_verified_at": "INTEGER",
        "foundation_verdict": "TEXT",
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



def init_sellers_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sellers (
        seller_id TEXT PRIMARY KEY,
        seller_name TEXT,
        wallet TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL,
        email_verified INTEGER DEFAULT 0,
        email_verified_at INTEGER,
        api_key TEXT,
        api_key_created_at INTEGER,
        last_contact_at INTEGER,
        onboarding_completed INTEGER DEFAULT 0,

        support_email TEXT,
        website TEXT,
        organization_name TEXT,
        webhook_url TEXT,

        seller_status TEXT DEFAULT 'pending',
        verification_status TEXT DEFAULT 'unverified',

        reputation REAL DEFAULT 0.5,
        risk_score REAL DEFAULT 0,
        trust_tier TEXT DEFAULT 'new',

        total_agents INTEGER DEFAULT 0,
        active_agents INTEGER DEFAULT 0,

        max_agents_allowed INTEGER DEFAULT 1,

        stake_amount REAL DEFAULT 0,
        exposure_limit REAL DEFAULT 0,

        successful_orders INTEGER DEFAULT 0,
        failed_orders INTEGER DEFAULT 0,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        last_risk_review_at INTEGER,
        last_violation_at INTEGER,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def ensure_seller_agent_runtime_columns():
    conn = get_conn()
    cur = conn.cursor()

    columns = {
        "runtime_validation_status": "TEXT DEFAULT 'unknown'",
        "runtime_health_score": "REAL DEFAULT 0",
        "runtime_latency": "REAL DEFAULT 0",
        "runtime_last_checked_at": "INTEGER",
    }

    for column, definition in columns.items():
        try:
            cur.execute(f"ALTER TABLE seller_agents ADD COLUMN {column} {definition}")
        except Exception:
            pass

    conn.commit()
    release_conn(conn)


def init_seller_agents_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agents (
        seller_agent_id TEXT PRIMARY KEY,

        seller_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,

        service TEXT NOT NULL,
        url TEXT,

        capabilities TEXT DEFAULT '[]',
        specialties TEXT DEFAULT '[]',

        seller_agent_status TEXT DEFAULT 'active',

        reputation REAL DEFAULT 0.5,
        risk_score REAL DEFAULT 0,

        successful_orders INTEGER DEFAULT 0,
        failed_orders INTEGER DEFAULT 0,

        latency_avg REAL DEFAULT 0,
        consensus_score REAL DEFAULT 0,

        exposure_limit REAL DEFAULT 0,

        runtime_validation_status TEXT DEFAULT 'unknown',
        runtime_health_score REAL DEFAULT 0,
        runtime_latency REAL DEFAULT 0,
        runtime_last_checked_at INTEGER,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)



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
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
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
                risk_score = {p},
                dynamic_stake_required = {p},
                max_order_value = {p},
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
                seller_id = {p},
                seller_agent_id = {p},
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
                float(agent.get("risk_score", 0) or 0),
                float(agent.get("dynamic_stake_required", 0) or 0),
                float(agent.get("max_order_value", 0) or 0),
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
                agent.get("seller_id"),
                agent.get("seller_agent_id"),
                now,
                agent["agent_id"],
            ))
        else:
            cur.execute(f"""
            INSERT INTO agents (
                agent_id, service, url, wallet, agent_type, price, reputation, available,
                stake_amount, stake_required, max_order_value, trust_tier,
                capabilities, specialties,
                seller_status, verification_status, seller_metadata,
                buyer_access, web_access, raw_prompt_access,
                foundation_verified_at, foundation_verdict,
                seller_id, seller_agent_id,
                registered_at, updated_at
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
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
                float(agent.get("max_order_value", 0) or 0),
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
                agent.get("seller_id"),
                agent.get("seller_agent_id"),
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


def upsert_seller_graph_edge_db(
    source_agent_id,
    target_agent_id,
    edge_type,
    weight=0.1,
    evidence=None,
):
    """
    Persist seller relationship graph edges.
    Used for adversarial cluster detection.
    """
    if not source_agent_id or not target_agent_id:
        return None

    if source_agent_id == target_agent_id:
        return None

    ordered = sorted([
        str(source_agent_id),
        str(target_agent_id),
    ])

    original_source_agent_id = str(source_agent_id)
    original_target_agent_id = str(target_agent_id)

    source_agent_id = ordered[0]
    target_agent_id = ordered[1]

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    # Remove legacy/reverse duplicate edge before canonical upsert.
    cur.execute(f"""
    DELETE FROM seller_graph_edges
    WHERE source_agent_id = {p}
      AND target_agent_id = {p}
      AND edge_type = {p}
      AND NOT (
          source_agent_id = {p}
          AND target_agent_id = {p}
      )
    """, (
        original_source_agent_id,
        original_target_agent_id,
        edge_type,
        source_agent_id,
        target_agent_id,
    ))
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())

    evidence_json = (
        json.dumps(evidence)
        if isinstance(evidence, (dict, list))
        else str(evidence or "")
    )

    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO seller_graph_edges (
            source_agent_id,
            target_agent_id,
            edge_type,
            weight,
            evidence,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        ON CONFLICT (
            source_agent_id,
            target_agent_id,
            edge_type
        )
        DO UPDATE SET
            weight = EXCLUDED.weight,
            evidence = EXCLUDED.evidence,
            updated_at = EXCLUDED.updated_at
        """, (
            source_agent_id,
            target_agent_id,
            edge_type,
            float(weight or 0),
            evidence_json,
            now,
            now,
        ))

    else:
        cur.execute(f"""
        INSERT OR REPLACE INTO seller_graph_edges (
            source_agent_id,
            target_agent_id,
            edge_type,
            weight,
            evidence,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            source_agent_id,
            target_agent_id,
            edge_type,
            float(weight or 0),
            evidence_json,
            now,
            now,
        ))

    conn.commit()
    release_conn(conn)

    return {
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "edge_type": edge_type,
        "weight": weight,
    }


def store_threat_forecast_db(
    scope,
    subject_id,
    forecast,
):
    """
    Store AI threat forecasts into protocol memory.
    Advisory-only memory for future risk decisions.
    """
    if not forecast:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    threat_level = forecast.get("threat_level")
    confidence = float(forecast.get("confidence", 0) or 0)
    source = forecast.get("provider", "unknown")

    # Do not pollute protocol memory with weak fallback forecasts.
    if source != "groq":
        return {
            "status": "ignored",
            "reason": "non_primary_provider",
        }

    if confidence < 0.5:
        return {
            "status": "ignored",
            "reason": "low_confidence",
        }

    attack_vectors = forecast.get("predicted_attack_vectors") or []

    if not attack_vectors:
        return {
            "status": "ignored",
            "reason": "empty_forecast",
        }

    inserted = 0
    guardrails = forecast.get("recommended_guardrails") or []
    signals = forecast.get("signals_to_monitor") or []
    policies = forecast.get("policy_updates") or []

    max_len = max(
        len(attack_vectors),
        len(guardrails),
        len(signals),
        len(policies),
        1,
    )

    for i in range(max_len):
        attack_vector = attack_vectors[i] if i < len(attack_vectors) else None
        guardrail = guardrails[i] if i < len(guardrails) else None
        signal = signals[i] if i < len(signals) else None
        policy = policies[i] if i < len(policies) else None

        cur.execute(f"""
        SELECT id
        FROM threat_memory
        WHERE scope = {p}
          AND subject_id = {p}
          AND status = 'active'
          AND COALESCE(attack_vector, '') = COALESCE({p}, '')
          AND COALESCE(recommended_guardrail, '') = COALESCE({p}, '')
          AND COALESCE(signal_to_monitor, '') = COALESCE({p}, '')
          AND COALESCE(policy_update, '') = COALESCE({p}, '')
        LIMIT 1
        """, (
            scope,
            subject_id,
            attack_vector,
            guardrail,
            signal,
            policy,
        ))

        existing = cur.fetchone()

        if existing:
            cur.execute(f"""
            UPDATE threat_memory
            SET confidence = {p},
                threat_level = {p},
                updated_at = {p}
            WHERE id = {p}
            """, (
                confidence,
                threat_level,
                now,
                row_get(existing, "id"),
            ))

            continue

        cur.execute(f"""
        INSERT INTO threat_memory (
            scope,
            subject_id,
            threat_level,
            attack_vector,
            recommended_guardrail,
            signal_to_monitor,
            policy_update,
            confidence,
            source,
            status,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            scope,
            subject_id,
            threat_level,
            attack_vector,
            guardrail,
            signal,
            policy,
            confidence,
            source,
            "active",
            now,
            now,
        ))

        inserted += 1

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "scope": scope,
        "subject_id": subject_id,
        "inserted": inserted,
    }


def get_active_threat_memory_db(
    scope=None,
    subject_id=None,
    limit=50,
):
    """
    Retrieve active threat memory for protocol reasoning.
    """
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = ["status = 'active'"]
    params = []

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    query = f"""
    SELECT *
    FROM threat_memory
    WHERE {' AND '.join(where)}
    ORDER BY confidence DESC, updated_at DESC
    LIMIT {int(limit)}
    """

    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    release_conn(conn)

    return [dict(r) for r in rows]


def reinforce_threat_memory_db(
    memory_id,
    observed=True,
    reason="",
):
    """
    Reinforce or weaken a threat memory based on real observations.
    """
    if not memory_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM threat_memory
    WHERE id = {p}
    """, (memory_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "memory_id": memory_id,
        }

    confidence = float(row_get(row, "confidence", 0) or 0)
    strength = float(row_get(row, "memory_strength", 0.5) or 0.5)

    times_reinforced = int(row_get(row, "times_reinforced", 0) or 0)
    times_observed = int(row_get(row, "times_observed", 0) or 0)
    times_false_positive = int(row_get(row, "times_false_positive", 0) or 0)

    if observed:
        confidence = min(1.0, confidence + 0.05)
        strength = min(1.0, strength + 0.10)
        times_reinforced += 1
        times_observed += 1
    else:
        confidence = max(0.0, confidence - 0.05)
        strength = max(0.0, strength - 0.10)
        times_false_positive += 1

    status = "active"

    if strength <= 0.15 and confidence <= 0.25:
        status = "archived"
        archived_at = now
    else:
        archived_at = row_get(row, "archived_at")

    cur.execute(f"""
    UPDATE threat_memory
    SET confidence = {p},
        memory_strength = {p},
        times_reinforced = {p},
        times_observed = {p},
        times_false_positive = {p},
        last_validated_at = {p},
        updated_at = {p},
        status = {p},
        archived_at = {p}
    WHERE id = {p}
    """, (
        confidence,
        strength,
        times_reinforced,
        times_observed,
        times_false_positive,
        now,
        now,
        status,
        archived_at,
        memory_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "reinforced" if observed else "weakened",
        "memory_id": memory_id,
        "observed": observed,
        "confidence": confidence,
        "memory_strength": strength,
        "times_reinforced": times_reinforced,
        "times_observed": times_observed,
        "times_false_positive": times_false_positive,
        "reason": reason,
    }


def propagate_threat_memory_db(memory_id, max_confidence=0.45):
    """
    Propagate confirmed threat memory to graph-related sellers.
    Bounded, advisory-only, never automatic guilt transfer.
    """
    if not memory_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM threat_memory
    WHERE id = {p}
      AND status = 'active'
    """, (memory_id,))

    memory = cur.fetchone()

    if not memory:
        release_conn(conn)
        return {
            "status": "not_found_or_inactive",
            "memory_id": memory_id,
        }

    subject_id = row_get(memory, "subject_id")
    scope = row_get(memory, "scope")

    if scope != "seller" or not subject_id:
        release_conn(conn)
        return {
            "status": "not_propagatable",
            "memory_id": memory_id,
        }

    cur.execute(f"""
    SELECT *
    FROM seller_graph_edges
    WHERE source_agent_id = {p}
       OR target_agent_id = {p}
    """, (subject_id, subject_id))

    edges = cur.fetchall()

    propagated = 0

    for edge in edges:
        source_id = row_get(edge, "source_agent_id")
        target_id = row_get(edge, "target_agent_id")

        related_id = target_id if source_id == subject_id else source_id

        if not related_id or related_id == subject_id:
            continue

        weight = float(row_get(edge, "weight", 0) or 0)

        base_confidence = float(row_get(memory, "confidence", 0) or 0)

        propagated_confidence = min(
            max_confidence,
            round(base_confidence * weight, 6),
        )

        if propagated_confidence < 0.05:
            continue

        attack_vector = row_get(memory, "attack_vector")
        guardrail = row_get(memory, "recommended_guardrail")
        signal = row_get(memory, "signal_to_monitor")
        policy = row_get(memory, "policy_update")

        cur.execute(f"""
        SELECT id
        FROM threat_memory
        WHERE scope = 'seller'
          AND subject_id = {p}
          AND status = 'active'
          AND COALESCE(attack_vector, '') = COALESCE({p}, '')
          AND source = 'propagated'
        LIMIT 1
        """, (
            related_id,
            attack_vector,
        ))

        exists = cur.fetchone()

        if exists:
            continue

        cur.execute(f"""
        INSERT INTO threat_memory (
            scope,
            subject_id,
            threat_level,
            attack_vector,
            recommended_guardrail,
            signal_to_monitor,
            policy_update,
            confidence,
            source,
            status,
            created_at,
            updated_at,
            memory_strength
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            "seller",
            related_id,
            row_get(memory, "threat_level"),
            attack_vector,
            guardrail,
            signal,
            policy,
            propagated_confidence,
            "propagated",
            "active",
            now,
            now,
            min(0.4, propagated_confidence),
        ))

        propagated += 1

    conn.commit()
    release_conn(conn)

    return {
        "status": "propagation_complete",
        "memory_id": memory_id,
        "subject_id": subject_id,
        "edges_seen": len(edges),
        "propagated": propagated,
        "max_confidence": max_confidence,
        "advisory_only": True,
    }


def decay_threat_memory_db(
    scope=None,
    subject_id=None,
    min_age_seconds=86400,
):
    """
    Decay old unreinforced threat memory.
    Prevents stale AI forecasts from becoming permanent protocol truth.
    """
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    where = ["status = 'active'"]
    params = []

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    cur.execute(f"""
    SELECT *
    FROM threat_memory
    WHERE {' AND '.join(where)}
    """, tuple(params))

    rows = cur.fetchall()

    decayed = 0
    archived = 0

    for row in rows:
        memory_id = row_get(row, "id")
        updated_at = int(row_get(row, "updated_at", 0) or 0)
        last_decay_at = row_get(row, "last_decay_at")

        if now - updated_at < min_age_seconds:
            continue

        if last_decay_at and now - int(last_decay_at) < min_age_seconds:
            continue

        confidence = float(row_get(row, "confidence", 0) or 0)
        strength = float(row_get(row, "memory_strength", 0.5) or 0.5)

        confidence = max(0.0, round(confidence - 0.03, 6))
        strength = max(0.0, round(strength - 0.05, 6))

        status = "active"
        archived_at = row_get(row, "archived_at")

        if confidence <= 0.25 and strength <= 0.15:
            status = "archived"
            archived_at = now
            archived += 1

        cur.execute(f"""
        UPDATE threat_memory
        SET confidence = {p},
            memory_strength = {p},
            last_decay_at = {p},
            updated_at = {p},
            status = {p},
            archived_at = {p}
        WHERE id = {p}
        """, (
            confidence,
            strength,
            now,
            now,
            status,
            archived_at,
            memory_id,
        ))

        decayed += 1

    conn.commit()
    release_conn(conn)

    return {
        "status": "decay_complete",
        "scope": scope,
        "subject_id": subject_id,
        "decayed": decayed,
        "archived": archived,
    }


def compute_seller_fingerprints_db(agent_id):
    """
    Compute normalized seller fingerprints.
    Fingerprints are advisory signals, not automatic punishment.
    """
    if not agent_id:
        return None

    agent = get_agent_db(agent_id)

    if not agent:
        return None

    import json

    price = float(agent.get("price", 0) or 0)
    stake_amount = float(agent.get("stake_amount", 0) or 0)
    reputation = float(agent.get("reputation", 0) or 0)
    risk_score = float(agent.get("risk_score", 0) or 0)
    max_order_value = float(agent.get("max_order_value", 0) or 0)

    success_count = int(agent.get("success_count", 0) or 0)
    failure_count = int(agent.get("failure_count", 0) or 0)

    honest_volume = float(agent.get("honest_volume", 0) or 0)
    fraud_volume = float(agent.get("fraud_volume", 0) or 0)

    consensus_checks = int(agent.get("consensus_checks", 0) or 0)
    consensus_disagreements = int(agent.get("consensus_disagreements", 0) or 0)
    consensus_disagreement_rate = float(
        agent.get("consensus_disagreement_rate", 0) or 0
    )

    economic_fingerprint = {
        "price_bucket": (
            "very_high" if price >= 5000 else
            "high" if price >= 1000 else
            "medium" if price >= 100 else
            "low"
        ),
        "stake_bucket": (
            "high" if stake_amount >= 1000 else
            "medium" if stake_amount >= 100 else
            "low"
        ),
        "exposure_bucket": (
            "high" if max_order_value >= 1000 else
            "medium" if max_order_value >= 100 else
            "low"
        ),
        "stake_to_price_ratio": round(
            stake_amount / price,
            4
        ) if price > 0 else None,
    }

    behavior_fingerprint = {
        "success_count": success_count,
        "failure_count": failure_count,
        "success_failure_ratio": round(
            success_count / max(failure_count, 1),
            4
        ),
        "risk_bucket": (
            "critical" if risk_score >= 0.8 else
            "high" if risk_score >= 0.5 else
            "medium" if risk_score >= 0.25 else
            "low"
        ),
        "reputation_bucket": (
            "high" if reputation >= 0.9 else
            "medium" if reputation >= 0.7 else
            "low"
        ),
    }

    timing_fingerprint = {
        "last_success_at": agent.get("last_success_at"),
        "last_failure_at": agent.get("last_failure_at"),
        "last_activity_at": agent.get("last_activity_at"),
        "risk_updated_at": agent.get("risk_updated_at"),
    }

    consensus_fingerprint = {
        "consensus_checks": consensus_checks,
        "consensus_disagreements": consensus_disagreements,
        "consensus_disagreement_rate": consensus_disagreement_rate,
        "last_consensus_score": agent.get("last_consensus_score"),
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET economic_fingerprint = {p},
        behavior_fingerprint = {p},
        timing_fingerprint = {p},
        consensus_fingerprint = {p},
        fingerprint_updated_at = {p}
    WHERE agent_id = {p}
    """, (
        json.dumps(economic_fingerprint),
        json.dumps(behavior_fingerprint),
        json.dumps(timing_fingerprint),
        json.dumps(consensus_fingerprint),
        now,
        agent_id,
    ))

    seller_id = row_get(row, "seller_id")
    seller_risk_application = None

    if seller_id and divergence_detected:
        seller_severity = min(0.35, max(0.05, 1.0 - consensus_score))

        seller_risk_application = apply_seller_risk_event_db(
            seller_id=seller_id,
            event_type="consensus_failure",
            severity=seller_severity,
            reason=json.dumps({
                "agent_id": agent_id,
                "seller_agent_id": row_get(row, "seller_agent_id"),
                "consensus_score": consensus_score,
                "disagreement_rate": disagreement_rate,
            }),
        )

    conn.commit()
    release_conn(conn)

    return {
        "agent_id": agent_id,
        "economic_fingerprint": economic_fingerprint,
        "behavior_fingerprint": behavior_fingerprint,
        "timing_fingerprint": timing_fingerprint,
        "consensus_fingerprint": consensus_fingerprint,
        "fingerprint_updated_at": now,
    }


def compute_fingerprint_similarity_score(fp_a, fp_b):
    """
    Multi-signal fingerprint similarity engine.
    Requires multiple behavioral dimensions before creating suspicion.
    Advisory-only.
    """
    if not fp_a or not fp_b:
        return {
            "similarity_score": 0.0,
            "matches": [],
            "matched_dimensions": [],
            "dimension_count": 0,
        }

    import json

    def parse(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return {}
        return {}

    fp_a = parse(fp_a)
    fp_b = parse(fp_b)

    weights = {
        "economic_fingerprint": 0.20,
        "behavior_fingerprint": 0.35,
        "consensus_fingerprint": 0.30,
        "timing_fingerprint": 0.15,
    }

    total_score = 0.0
    matches = []
    matched_dimensions = []

    for dimension, dimension_weight in weights.items():
        a = parse(fp_a.get(dimension))
        b = parse(fp_b.get(dimension))

        if not a or not b:
            continue

        local_matches = 0
        local_total = 0

        for subkey, av in a.items():
            bv = b.get(subkey)

            if av is None or bv is None:
                continue

            local_total += 1

            if av == bv:
                local_matches += 1
                matches.append(f"{dimension}.{subkey}")

        if local_total <= 0:
            continue

        ratio = local_matches / local_total

        if ratio >= 0.5:
            matched_dimensions.append(dimension)

        total_score += ratio * dimension_weight

    total_score = round(min(total_score, 1.0), 4)

    # Require multiple dimensions before suspicion.
    if len(matched_dimensions) < 2:
        total_score = round(total_score * 0.35, 4)

    return {
        "similarity_score": total_score,
        "matches": matches[:25],
        "matched_dimensions": matched_dimensions,
        "dimension_count": len(matched_dimensions),
        "advisory_only": True,
    }


def enrich_seller_graph_db(agent_id):
    """
    Automatically enrich seller graph with deterministic relationship signals.
    Advisory-only. No automatic punishment.
    """
    if not agent_id:
        return None

    target = get_agent_db(agent_id)

    if not target:
        return None

    fingerprints = compute_seller_fingerprints_db(agent_id)
    related = find_related_sellers_db(agent_id)

    edges_created = 0

    for related_seller in related.get("related_sellers", []):
        other_id = related_seller.get("agent_id")

        if not other_id:
            continue

        matches = related_seller.get("matches", []) or []

        for match in matches:
            weight = {
                "same_wallet": 0.20,
                "same_url_host": 0.15,
                "same_business_name": 0.10,
                "same_proof_links": 0.20,
            }.get(match, 0.05)

            result = upsert_seller_graph_edge_db(
                agent_id,
                other_id,
                match,
                weight=weight,
                evidence={
                    "source": "enrich_seller_graph_db",
                    "match": match,
                },
            )

            if result:
                edges_created += 1

    all_agents = list_agents_db()

    for other in all_agents:
        other_id = other.get("agent_id")

        if not other_id or other_id == agent_id:
            continue

        other_fp = compute_seller_fingerprints_db(other_id)

        similarity = compute_fingerprint_similarity_score(
            fingerprints,
            other_fp,
        )

        similarity_score = float(
            similarity.get("similarity_score", 0)
            or 0
        )

        dimension_count = int(
            similarity.get("dimension_count", 0)
            or 0
        )

        if similarity_score < 0.10 or dimension_count < 2:
            continue

        matches = similarity.get("matches", [])

        result = upsert_seller_graph_edge_db(
            agent_id,
            other_id,
            "fingerprint_similarity",
            weight=min(0.45, similarity_score),
            evidence={
                "source": "fingerprint_similarity_engine",
                "similarity_score": similarity_score,
                "matches": matches[:10],
            },
        )

        if result:
            edges_created += 1

    graph = build_seller_graph_context_db(agent_id)

    return {
        "status": "graph_enriched",
        "agent_id": agent_id,
        "fingerprints": fingerprints,
        "related_count": related.get("related_count", 0),
        "edges_created": edges_created,
        "graph": graph,
        "advisory_only": True,
    }


def build_seller_graph_context_db(agent_id):
    """
    Build seller relationship graph context.
    Used for adversarial cluster analysis.
    """
    if not agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT
        source_agent_id,
        target_agent_id,
        edge_type,
        weight,
        evidence,
        updated_at
    FROM seller_graph_edges
    WHERE source_agent_id = {p}
       OR target_agent_id = {p}
    ORDER BY weight DESC, updated_at DESC
    """, (
        agent_id,
        agent_id,
    ))

    rows = cur.fetchall()

    release_conn(conn)

    edges = []

    related_agents = set()

    total_weight = 0.0

    for row in rows:
        edge = dict(row)

        try:
            edge["evidence"] = json.loads(
                edge.get("evidence") or "{}"
            )
        except Exception:
            pass

        edges.append(edge)

        total_weight += float(
            edge.get("weight", 0) or 0
        )

        src = edge.get("source_agent_id")
        dst = edge.get("target_agent_id")

        if src and src != agent_id:
            related_agents.add(src)

        if dst and dst != agent_id:
            related_agents.add(dst)

    cluster_risk = min(
        1.0,
        round(total_weight / 10.0, 4)
    )

    return {
        "agent_id": agent_id,
        "edge_count": len(edges),
        "related_agent_count": len(related_agents),
        "cluster_risk_score": cluster_risk,
        "related_agents": sorted(list(related_agents)),
        "edges": edges,
    }


def record_adaptive_policy_event_db(
    policy_id,
    scope,
    service,
    event_type,
    old_policy=None,
    new_policy=None,
    reason=None,
    source="protocol",
):
    """
    Record adaptive policy lifecycle events for auditability.
    """
    old_policy = old_policy or {}
    new_policy = new_policy or {}

    def multipliers(policy):
        return {
            "min_stake_multiplier": policy.get("min_stake_multiplier"),
            "consensus_multiplier": policy.get("consensus_multiplier"),
            "escrow_delay_multiplier": policy.get("escrow_delay_multiplier"),
            "exposure_multiplier": policy.get("exposure_multiplier"),
            "decay_multiplier": policy.get("decay_multiplier"),
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO adaptive_policy_events (
        policy_id,
        scope,
        service,
        event_type,
        old_risk_level,
        new_risk_level,
        old_confidence,
        new_confidence,
        old_multipliers,
        new_multipliers,
        reason,
        source,
        created_at
    )
    VALUES (
        {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
    )
    """, (
        policy_id,
        scope,
        service,
        event_type,
        old_policy.get("risk_level"),
        new_policy.get("risk_level"),
        old_policy.get("confidence"),
        new_policy.get("confidence"),
        json.dumps(multipliers(old_policy)),
        json.dumps(multipliers(new_policy)),
        json.dumps(reason) if isinstance(reason, (dict, list)) else str(reason or ""),
        source,
        now,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "policy_event_recorded",
        "policy_id": policy_id,
        "event_type": event_type,
    }


def get_active_adaptive_policy_db(
    scope,
    service=None,
):
    """
    Retrieve active adaptive defense policy.
    Service-specific policy first, then global fallback.
    """
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM adaptive_defense_policies
    WHERE scope = {p}
      AND active = 1
      AND (expires_at IS NULL OR expires_at > {p})
      AND (
            service = {p}
            OR service IS NULL
          )
    ORDER BY
        CASE WHEN service = {p} THEN 0 ELSE 1 END,
        confidence DESC,
        updated_at DESC
    LIMIT 1
    """, (
        scope,
        now,
        service,
        service,
    ))

    row = cur.fetchone()

    release_conn(conn)

    if not row:
        return None

    policy = dict(row)

    try:
        policy["activation_reason"] = json.loads(
            policy.get("activation_reason") or "{}"
        )
    except Exception:
        pass

    return policy


def compute_adaptive_defense_policy_db(
    scope,
    service=None,
    cluster=None,
    threat_memory=None,
):
    """
    Compute adaptive defense policy from live protocol intelligence.
    Advisory-only policy hardening.
    """
    import uuid

import secrets


def create_seller_api_key():
    """
    Generate high-entropy seller API keys.
    Seller keys are protocol economic credentials.
    """
    return "iat_sk_" + secrets.token_hex(24)


    cluster = cluster or {}
    threat_memory = threat_memory or []

    cluster_risk = float(
        cluster.get("cluster_risk_score", 0)
        or 0
    )

    coordination = float(
        cluster.get("coordination_probability", 0)
        or 0
    )

    high_threats = [
        m for m in threat_memory
        if str(m.get("threat_level", "")).lower() in ["high", "critical"]
    ]

    threat_density = min(
        1.0,
        len(high_threats) / 10,
    )

    combined_risk = min(
        1.0,
        round(
            (cluster_risk * 0.40)
            + (coordination * 0.35)
            + (threat_density * 0.25),
            6,
        ),
    )

    if combined_risk >= 0.75:
        risk_level = "critical"
        min_stake_multiplier = 2.0
        consensus_multiplier = 2.0
        escrow_delay_multiplier = 1.75
        exposure_multiplier = 0.35
        decay_multiplier = 0.50

    elif combined_risk >= 0.50:
        risk_level = "high"
        min_stake_multiplier = 1.5
        consensus_multiplier = 1.5
        escrow_delay_multiplier = 1.35
        exposure_multiplier = 0.55
        decay_multiplier = 0.70

    elif combined_risk >= 0.25:
        risk_level = "medium"
        min_stake_multiplier = 1.2
        consensus_multiplier = 1.2
        escrow_delay_multiplier = 1.15
        exposure_multiplier = 0.75
        decay_multiplier = 0.85

    else:
        risk_level = "low"
        min_stake_multiplier = 1.0
        consensus_multiplier = 1.0
        escrow_delay_multiplier = 1.0
        exposure_multiplier = 1.0
        decay_multiplier = 1.0

    # Protocol safety floors/ceilings.
    # Prevent autonomous policy overreaction or underreaction.
    min_stake_multiplier = min(max(min_stake_multiplier, 1.0), 3.0)
    consensus_multiplier = min(max(consensus_multiplier, 1.0), 3.0)
    escrow_delay_multiplier = min(max(escrow_delay_multiplier, 1.0), 3.0)
    exposure_multiplier = min(max(exposure_multiplier, 0.20), 1.0)
    decay_multiplier = min(max(decay_multiplier, 0.30), 1.0)

    policy_id = f"policy:{scope}:{service or 'global'}"

    activation_reason = {
        "combined_risk": combined_risk,
        "cluster_risk": cluster_risk,
        "coordination_probability": coordination,
        "high_threat_count": len(high_threats),
        "threat_density": threat_density,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    old_policy = get_active_adaptive_policy_db(
        scope=scope,
        service=service,
    )

    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO adaptive_defense_policies (
            policy_id,
            scope,
            service,
            risk_level,
            min_stake_multiplier,
            consensus_multiplier,
            escrow_delay_multiplier,
            exposure_multiplier,
            decay_multiplier,
            activation_reason,
            confidence,
            source,
            active,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        ON CONFLICT (policy_id)
        DO UPDATE SET
            risk_level = EXCLUDED.risk_level,
            min_stake_multiplier = EXCLUDED.min_stake_multiplier,
            consensus_multiplier = EXCLUDED.consensus_multiplier,
            escrow_delay_multiplier = EXCLUDED.escrow_delay_multiplier,
            exposure_multiplier = EXCLUDED.exposure_multiplier,
            decay_multiplier = EXCLUDED.decay_multiplier,
            activation_reason = EXCLUDED.activation_reason,
            confidence = EXCLUDED.confidence,
            active = EXCLUDED.active,
            updated_at = EXCLUDED.updated_at
        """, (
            policy_id,
            scope,
            service,
            risk_level,
            min_stake_multiplier,
            consensus_multiplier,
            escrow_delay_multiplier,
            exposure_multiplier,
            decay_multiplier,
            json.dumps(activation_reason),
            combined_risk,
            "protocol_adaptive_engine",
            1,
            now,
            now,
        ))

    else:
        cur.execute(f"""
        INSERT OR REPLACE INTO adaptive_defense_policies (
            policy_id,
            scope,
            service,
            risk_level,
            min_stake_multiplier,
            consensus_multiplier,
            escrow_delay_multiplier,
            exposure_multiplier,
            decay_multiplier,
            activation_reason,
            confidence,
            source,
            active,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            policy_id,
            scope,
            service,
            risk_level,
            min_stake_multiplier,
            consensus_multiplier,
            escrow_delay_multiplier,
            exposure_multiplier,
            decay_multiplier,
            json.dumps(activation_reason),
            combined_risk,
            "protocol_adaptive_engine",
            1,
            now,
            now,
        ))

    conn.commit()
    release_conn(conn)

    new_policy = {
        "risk_level": risk_level,
        "confidence": combined_risk,
        "min_stake_multiplier": min_stake_multiplier,
        "consensus_multiplier": consensus_multiplier,
        "escrow_delay_multiplier": escrow_delay_multiplier,
        "exposure_multiplier": exposure_multiplier,
        "decay_multiplier": decay_multiplier,
    }

    event_type = "policy_created" if not old_policy else "policy_updated"

    if old_policy and old_policy.get("risk_level") != risk_level:
        event_type = "risk_level_changed"

    record_adaptive_policy_event_db(
        policy_id=policy_id,
        scope=scope,
        service=service,
        event_type=event_type,
        old_policy=old_policy,
        new_policy=new_policy,
        reason=activation_reason,
        source="protocol_adaptive_engine",
    )

    return {
        "status": "adaptive_policy_computed",
        "policy_id": policy_id,
        "scope": scope,
        "service": service,
        "risk_level": risk_level,
        "combined_risk": combined_risk,
        "multipliers": {
            "min_stake_multiplier": min_stake_multiplier,
            "consensus_multiplier": consensus_multiplier,
            "escrow_delay_multiplier": escrow_delay_multiplier,
            "exposure_multiplier": exposure_multiplier,
            "decay_multiplier": decay_multiplier,
        },
        "activation_reason": activation_reason,
        "advisory_only": True,
    }


def detect_seller_cluster_db(agent_id):
    """
    Detect emerging seller clusters from graph edges and threat memory.
    Advisory only. No automatic punishment.
    """
    if not agent_id:
        return None

    graph = build_seller_graph_context_db(agent_id)

    if not graph:
        return None

    members = set(graph.get("related_agents", []) or [])
    members.add(agent_id)

    edges = graph.get("edges", []) or []

    edge_count = len(edges)
    member_count = len(members)

    weights = [
        float(e.get("weight", 0) or 0)
        for e in edges
    ]

    average_edge_weight = (
        sum(weights) / len(weights)
        if weights else 0
    )

    strongest_edge_weight = (
        max(weights)
        if weights else 0
    )

    threat_memory_count = 0

    for member in members:
        memories = get_active_threat_memory_db(
            scope="seller",
            subject_id=member,
            limit=100,
        )
        threat_memory_count += len(memories)

    coordination_probability = min(
        1.0,
        round(
            (
                (average_edge_weight * 0.45)
                + (strongest_edge_weight * 0.35)
                + (min(threat_memory_count, 10) / 10 * 0.20)
            ),
            6,
        ),
    )

    cluster_risk_score = min(
        1.0,
        round(
            (
                graph.get("cluster_risk_score", 0) * 0.40
                + coordination_probability * 0.60
            ),
            6,
        ),
    )

    cluster_id = f"cluster:{agent_id}"

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    if USE_POSTGRES:
        cur.execute(f"""
        INSERT INTO seller_clusters (
            cluster_id,
            root_agent_id,
            member_count,
            edge_count,
            cluster_risk_score,
            coordination_probability,
            average_edge_weight,
            strongest_edge_weight,
            threat_memory_count,
            status,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        ON CONFLICT (cluster_id)
        DO UPDATE SET
            member_count = EXCLUDED.member_count,
            edge_count = EXCLUDED.edge_count,
            cluster_risk_score = EXCLUDED.cluster_risk_score,
            coordination_probability = EXCLUDED.coordination_probability,
            average_edge_weight = EXCLUDED.average_edge_weight,
            strongest_edge_weight = EXCLUDED.strongest_edge_weight,
            threat_memory_count = EXCLUDED.threat_memory_count,
            updated_at = EXCLUDED.updated_at
        """, (
            cluster_id,
            agent_id,
            member_count,
            edge_count,
            cluster_risk_score,
            coordination_probability,
            average_edge_weight,
            strongest_edge_weight,
            threat_memory_count,
            "active",
            now,
            now,
        ))

    else:
        cur.execute(f"""
        INSERT OR REPLACE INTO seller_clusters (
            cluster_id,
            root_agent_id,
            member_count,
            edge_count,
            cluster_risk_score,
            coordination_probability,
            average_edge_weight,
            strongest_edge_weight,
            threat_memory_count,
            status,
            created_at,
            updated_at
        )
        VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            cluster_id,
            agent_id,
            member_count,
            edge_count,
            cluster_risk_score,
            coordination_probability,
            average_edge_weight,
            strongest_edge_weight,
            threat_memory_count,
            "active",
            now,
            now,
        ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "cluster_detected",
        "cluster_id": cluster_id,
        "root_agent_id": agent_id,
        "members": sorted(list(members)),
        "member_count": member_count,
        "edge_count": edge_count,
        "cluster_risk_score": cluster_risk_score,
        "coordination_probability": coordination_probability,
        "average_edge_weight": round(average_edge_weight, 6),
        "strongest_edge_weight": strongest_edge_weight,
        "threat_memory_count": threat_memory_count,
        "advisory_only": True,
    }


def record_cluster_snapshot_db(
    cluster,
    snapshot_reason="periodic",
    source="protocol",
):
    """
    Store historical cluster state for evolution forecasting.
    """
    if not cluster:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    members = cluster.get("members", []) or []

    # Edges are not always returned directly in cluster.
    graph = build_seller_graph_context_db(
        cluster.get("root_agent_id")
    )

    edges = graph.get("edges", []) if graph else []

    cur.execute(f"""
    INSERT INTO cluster_snapshots (
        cluster_id,
        root_agent_id,
        member_count,
        edge_count,
        cluster_risk_score,
        coordination_probability,
        average_edge_weight,
        strongest_edge_weight,
        threat_memory_count,
        members_json,
        edges_json,
        snapshot_reason,
        source,
        created_at
    )
    VALUES (
        {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
    )
    """, (
        cluster.get("cluster_id"),
        cluster.get("root_agent_id"),
        int(cluster.get("member_count", 0) or 0),
        int(cluster.get("edge_count", 0) or 0),
        float(cluster.get("cluster_risk_score", 0) or 0),
        float(cluster.get("coordination_probability", 0) or 0),
        float(cluster.get("average_edge_weight", 0) or 0),
        float(cluster.get("strongest_edge_weight", 0) or 0),
        int(cluster.get("threat_memory_count", 0) or 0),
        json.dumps(members),
        json.dumps(edges),
        snapshot_reason,
        source,
        now,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "cluster_snapshot_recorded",
        "cluster_id": cluster.get("cluster_id"),
        "root_agent_id": cluster.get("root_agent_id"),
        "member_count": cluster.get("member_count"),
        "edge_count": cluster.get("edge_count"),
        "created_at": now,
    }


def compute_cluster_forecast_db(
    cluster_id,
    limit=20,
):
    """
    Forecast cluster evolution from historical snapshots.
    Advisory-only predictive risk.
    """
    if not cluster_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM cluster_snapshots
    WHERE cluster_id = {p}
    ORDER BY created_at DESC
    LIMIT {p}
    """, (
        cluster_id,
        int(limit),
    ))

    rows = cur.fetchall()
    release_conn(conn)

    snapshots = [dict(r) for r in rows]

    if not snapshots:
        return {
            "status": "no_snapshots",
            "cluster_id": cluster_id,
        }

    latest = snapshots[0]
    oldest = snapshots[-1]

    time_delta = max(
        1,
        int(latest.get("created_at", 0) or 0)
        - int(oldest.get("created_at", 0) or 0),
    )

    member_delta = (
        int(latest.get("member_count", 0) or 0)
        - int(oldest.get("member_count", 0) or 0)
    )

    edge_delta = (
        int(latest.get("edge_count", 0) or 0)
        - int(oldest.get("edge_count", 0) or 0)
    )

    risk_delta = (
        float(latest.get("cluster_risk_score", 0) or 0)
        - float(oldest.get("cluster_risk_score", 0) or 0)
    )

    coordination_delta = (
        float(latest.get("coordination_probability", 0) or 0)
        - float(oldest.get("coordination_probability", 0) or 0)
    )

    growth_velocity = round(member_delta / time_delta, 8)
    edge_velocity = round(edge_delta / time_delta, 8)
    risk_acceleration = round(risk_delta / time_delta, 8)
    coordination_acceleration = round(coordination_delta / time_delta, 8)

    latest_risk = float(
        latest.get("cluster_risk_score", 0)
        or 0
    )

    latest_coordination = float(
        latest.get("coordination_probability", 0)
        or 0
    )

    threat_memory_count = int(
        latest.get("threat_memory_count", 0)
        or 0
    )

    expansion_probability = min(
        1.0,
        round(
            (max(growth_velocity, 0) * 1000 * 0.25)
            + (max(edge_velocity, 0) * 1000 * 0.20)
            + (max(risk_acceleration, 0) * 1000 * 0.20)
            + (latest_coordination * 0.20)
            + (min(threat_memory_count, 10) / 10 * 0.15),
            6,
        ),
    )

    if expansion_probability >= 0.75:
        expansion_risk = "critical"
    elif expansion_probability >= 0.50:
        expansion_risk = "high"
    elif expansion_probability >= 0.25:
        expansion_risk = "medium"
    else:
        expansion_risk = "low"

    recommended_countermeasures = []

    if expansion_risk in ["high", "critical"]:
        recommended_countermeasures.extend([
            "increase_consensus_requirement",
            "reduce_cluster_exposure",
            "increase_minimum_stake",
            "slow_risk_decay",
        ])

    elif expansion_risk == "medium":
        recommended_countermeasures.extend([
            "monitor_cluster_growth",
            "apply_moderate_exposure_reduction",
        ])

    else:
        recommended_countermeasures.append(
            "continue_monitoring"
        )

    return {
        "status": "cluster_forecast_computed",
        "cluster_id": cluster_id,
        "snapshot_count": len(snapshots),
        "latest": latest,
        "oldest": oldest,
        "growth_velocity": growth_velocity,
        "edge_velocity": edge_velocity,
        "risk_acceleration": risk_acceleration,
        "coordination_acceleration": coordination_acceleration,
        "expansion_probability": expansion_probability,
        "expansion_risk": expansion_risk,
        "recommended_countermeasures": recommended_countermeasures,
        "advisory_only": True,
    }


def find_related_sellers_db(agent_id):
    """
    Advisory-only relationship discovery.

    Same wallet/domain/proof/business signals are NOT automatic fraud.
    They are context for Groq + foundation review.
    """
    import json
    from urllib.parse import urlparse

    target = get_agent_db(agent_id)

    if not target:
        return {
            "agent_id": agent_id,
            "related_count": 0,
            "signals": [],
            "related_sellers": [],
        }

    def safe_json(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return {}
        return {}

    def host(url):
        try:
            return urlparse(url or "").netloc.lower()
        except Exception:
            return ""

    target_metadata = safe_json(target.get("seller_metadata"))
    target_wallet = str(target.get("wallet") or "").lower()
    target_host = host(target.get("url"))
    target_business = str(
        target_metadata.get("business_name")
        or target.get("business_name")
        or ""
    ).strip().lower()
    target_proofs = str(
        target_metadata.get("proof_links")
        or target.get("proof_links")
        or ""
    ).strip().lower()

    signals = []
    related = []

    for other in list_agents_db():
        if other.get("agent_id") == agent_id:
            continue

        if str(other.get("agent_type", "")).lower() != "seller":
            continue

        other_metadata = safe_json(other.get("seller_metadata"))

        matches = []

        other_wallet = str(other.get("wallet") or "").lower()
        other_host = host(other.get("url"))
        other_business = str(
            other_metadata.get("business_name")
            or other.get("business_name")
            or ""
        ).strip().lower()
        other_proofs = str(
            other_metadata.get("proof_links")
            or other.get("proof_links")
            or ""
        ).strip().lower()

        if target_wallet and target_wallet == other_wallet:
            matches.append("same_wallet")

        if target_host and target_host == other_host:
            matches.append("same_url_host")

        if target_business and target_business == other_business:
            matches.append("same_business_name")

        if target_proofs and target_proofs == other_proofs:
            matches.append("same_proof_links")

        if matches:
            for match in matches:
                weight = {
                    "same_wallet": 0.20,
                    "same_url_host": 0.15,
                    "same_business_name": 0.10,
                    "same_proof_links": 0.20,
                }.get(match, 0.05)

                upsert_seller_graph_edge_db(
                    agent_id,
                    other.get("agent_id"),
                    match,
                    weight=weight,
                    evidence={
                        "source": "find_related_sellers_db",
                        "match": match,
                    },
                )

            related.append({
                "agent_id": other.get("agent_id"),
                "service": other.get("service"),
                "seller_status": other.get("seller_status"),
                "verification_status": other.get("verification_status"),
                "risk_score": other.get("risk_score"),
                "reputation": other.get("reputation"),
                "wallet": other.get("wallet"),
                "url": other.get("url"),
                "matches": matches,
            })

            for m in matches:
                signals.append(m)

    return {
        "agent_id": agent_id,
        "related_count": len(related),
        "signals": sorted(list(set(signals))),
        "related_sellers": related,
        "advisory_only": True,
    }


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
                last_success_at = {p},
                last_activity_at = {p},
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                round(new_rep, 4),
                success_count,
                failure_count,
                now,
                now,
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

    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET reputation = {p},
        risk_score = {p},
        trust_tier = {p},
        dynamic_stake_required = {p},
        risk_updated_at = {p},
        last_activity_at = {p}
    WHERE agent_id = {p}
    """, (
        reputation,
        risk_score,
        trust_tier,
        dynamic_stake_required,
        now,
        now,
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


def apply_agent_risk_decay_db(agent_id, decay_reason="stable_behavior"):
    """
    Controlled risk recovery.
    Risk decays slowly only after stable positive behavior.
    """
    if not agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT
        risk_score,
        last_failure_at,
        last_consensus_checked_at,
        last_consensus_score,
        last_risk_decay_at,
        risk_decay_events
    FROM agents
    WHERE agent_id = {p}
    """, (agent_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return None

    risk_score = float(row_get(row, "risk_score", 0) or 0)
    last_failure_at = row_get(row, "last_failure_at")
    last_consensus_score = float(row_get(row, "last_consensus_score", 1) or 1)
    last_risk_decay_at = row_get(row, "last_risk_decay_at")
    risk_decay_events = int(row_get(row, "risk_decay_events", 0) or 0)

    # No decay if recent failure in last 7 days.
    if last_failure_at and now - int(last_failure_at) < 7 * 86400:
        release_conn(conn)
        return {
            "status": "blocked",
            "reason": "recent_failure",
            "risk_score": risk_score,
        }

    # No decay if latest consensus was weak.
    if last_consensus_score < 0.65:
        release_conn(conn)
        return {
            "status": "blocked",
            "reason": "weak_recent_consensus",
            "risk_score": risk_score,
        }

    # Prevent rapid repeated decay.
    if last_risk_decay_at and now - int(last_risk_decay_at) < 24 * 3600:
        release_conn(conn)
        return {
            "status": "blocked",
            "reason": "decay_cooldown",
            "risk_score": risk_score,
        }

    decay_amount = 0.03

    new_risk = max(
        0.05,
        round(risk_score - decay_amount, 6),
    )

    risk_decay_events += 1

    cur.execute(f"""
    UPDATE agents
    SET risk_score = {p},
        risk_decay_score = COALESCE(risk_decay_score, 0) + {p},
        risk_decay_events = {p},
        last_risk_decay_at = {p},
        risk_updated_at = {p},
        last_activity_at = {p}
    WHERE agent_id = {p}
    """, (
        new_risk,
        decay_amount,
        risk_decay_events,
        now,
        now,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "risk_decay_applied",
        "agent_id": agent_id,
        "old_risk_score": risk_score,
        "new_risk_score": new_risk,
        "decay_amount": decay_amount,
        "risk_decay_events": risk_decay_events,
        "reason": decay_reason,
    }


def update_agent_consensus_stats_db(
    agent_id,
    consensus_score,
):
    """
    Track divergence from multi-agent consensus.
    Advisory only.
    """
    if not agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())

    cur.execute(f"""
    SELECT
        consensus_checks,
        consensus_disagreements,
        consensus_disagreement_rate,
        risk_score,
        seller_id,
        seller_agent_id
    FROM agents
    WHERE agent_id = {p}
    """, (agent_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return None

    checks = int(row_get(row, "consensus_checks", 0) or 0)
    disagreements = int(
        row_get(row, "consensus_disagreements", 0) or 0
    )

    risk_score = float(
        row_get(row, "risk_score", 0) or 0
    )

    checks += 1

    consensus_score = float(consensus_score or 0)

    divergence_detected = consensus_score < 0.50

    if divergence_detected:
        disagreements += 1

    disagreement_rate = (
        disagreements / checks
        if checks > 0 else 0
    )

    disagreement_rate = round(disagreement_rate, 6)

    seller_id = row_get(row, "seller_id")
    seller_agent_id = row_get(row, "seller_agent_id")
    seller_risk_application = None

    # Progressive economic trust penalty.
    if disagreement_rate >= 0.75:
        risk_score += 0.20

    elif disagreement_rate >= 0.50:
        risk_score += 0.10

    elif disagreement_rate >= 0.25:
        risk_score += 0.05

    risk_score = round(min(risk_score, 1.0), 6)

    cur.execute(f"""
    UPDATE agents
    SET consensus_checks = {p},
        consensus_disagreements = {p},
        consensus_disagreement_rate = {p},
        last_consensus_score = {p},
        last_consensus_checked_at = {p},
        risk_score = {p}
    WHERE agent_id = {p}
    """, (
        checks,
        disagreements,
        disagreement_rate,
        consensus_score,
        now,
        risk_score,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    if seller_id and divergence_detected:
        seller_severity = min(0.35, max(0.05, 1.0 - consensus_score))

        seller_risk_application = apply_seller_risk_event_db(
            seller_id=seller_id,
            event_type="consensus_failure",
            severity=seller_severity,
            reason=json.dumps({
                "agent_id": agent_id,
                "seller_agent_id": seller_agent_id,
                "consensus_score": consensus_score,
                "disagreement_rate": disagreement_rate,
            }),
        )

    return {
        "agent_id": agent_id,
        "consensus_checks": checks,
        "consensus_disagreements": disagreements,
        "consensus_disagreement_rate": disagreement_rate,
        "consensus_score": consensus_score,
        "divergence_detected": divergence_detected,
        "risk_score": risk_score,
        "seller_risk_application": seller_risk_application,
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


def create_seller_db(seller):
    if not seller.get("email"):
        return {
            "status": "error",
            "message": "seller_email_required",
        }

    existing_wallet = get_seller_by_wallet_db(seller.get("wallet"))
    if existing_wallet:
        return {
            "status": "error",
            "message": "seller_wallet_already_registered",
            "seller_id": existing_wallet.get("seller_id"),
        }

    existing_email = get_seller_by_email_db(seller.get("email"))
    if existing_email:
        return {
            "status": "error",
            "message": "seller_email_already_registered",
            "seller_id": existing_email.get("seller_id"),
        }

    if not seller.get("api_key"):
        seller["api_key"] = create_seller_api_key()

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    metadata = seller.get("metadata", "{}")
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)

    cur.execute(f"""
    INSERT INTO sellers (
        seller_id, seller_name, wallet, email, api_key,
        seller_status, verification_status,
        reputation, risk_score, trust_tier,
        total_agents, active_agents, max_agents_allowed,
        stake_amount, exposure_limit,
        successful_orders, failed_orders,
        created_at, updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        seller["seller_id"],
        seller.get("seller_name"),
        seller["wallet"],
        seller.get("email"),
        seller.get("api_key"),
        seller.get("seller_status", "pending"),
        seller.get("verification_status", "unverified"),
        float(seller.get("reputation", 0.5) or 0.5),
        float(seller.get("risk_score", 0) or 0),
        seller.get("trust_tier", "new"),
        int(seller.get("total_agents", 0) or 0),
        int(seller.get("active_agents", 0) or 0),
        int(seller.get("max_agents_allowed", 1) or 1),
        float(seller.get("stake_amount", 0) or 0),
        float(seller.get("exposure_limit", 0) or 0),
        int(seller.get("successful_orders", 0) or 0),
        int(seller.get("failed_orders", 0) or 0),
        now,
        now,
        metadata,
    ))

    conn.commit()
    release_conn(conn)

    return get_seller_db(seller["seller_id"])


def get_seller_db(seller_id):
    if not seller_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM sellers
    WHERE seller_id = {p}
    """, (seller_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None




def get_seller_by_email_db(email):
    if not email:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(
        f"SELECT * FROM sellers WHERE LOWER(email) = LOWER({p}) LIMIT 1",
        (email,)
    )

    row = cur.fetchone()

    release_conn(conn)

    return dict(row) if row else None


def get_seller_by_api_key_db(api_key):
    if not api_key:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(
        f"SELECT * FROM sellers WHERE api_key = {p} LIMIT 1",
        (api_key,)
    )

    row = cur.fetchone()

    release_conn(conn)

    return dict(row) if row else None








def reject_seller_db(
    seller_id,
    reason="foundation_rejected",
    reviewer="foundation_protocol",
):
    if not seller_id:
        return {
            "status": "error",
            "message": "seller_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())

    cur.execute(f"""
    UPDATE sellers
    SET
        seller_status = 'rejected',
        verification_status = 'rejected',
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        now,
        seller_id,
    ))

    cur.execute(f"""
    UPDATE agents
    SET
        available = 0,
        seller_status = 'rejected',
        verification_status = 'rejected'
    WHERE seller_id = {p}
    """, (
        seller_id,
    ))

    audit_metadata = json.dumps({
        "event": "seller_rejected",
        "reviewer": reviewer,
        "reason": reason,
        "timestamp": now,
    })

    cur.execute(f"""
    UPDATE sellers
    SET
        metadata = {p}
    WHERE seller_id = {p}
    """, (
        audit_metadata,
        seller_id,
    ))

    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="seller_rejected",
        reviewer=reviewer,
        reason=reason,
        override_terminal=False,
        old_status="",
        new_status="rejected",
        metadata={
            "verification_status": "rejected",
        },
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "reviewer": reviewer,
        "reason": reason,
        "message": "seller_rejected_under_foundation_governance",
    }


def approve_seller_db(
    seller_id,
    reviewer="foundation_protocol",
    override_terminal=False,
):
    if not seller_id:
        return {
            "status": "error",
            "message": "seller_id_required",
        }

    seller = get_seller_db(seller_id)

    if not seller:
        return {
            "status": "error",
            "message": "seller_not_found",
        }

    if (
        str(seller.get("seller_status", "")).lower() in ["rejected", "banned"]
        and not override_terminal
    ):
        return {
            "status": "error",
            "message": "seller_terminal_state_requires_override",
            "seller_id": seller_id,
            "seller_status": seller.get("seller_status"),
            "verification_status": seller.get("verification_status"),
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())

    cur.execute(f"""
    UPDATE sellers
    SET
        seller_status = 'active',
        verification_status = 'foundation_verified',
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        now,
        seller_id,
    ))

    cur.execute(f"""
    UPDATE agents
    SET
        available = 1,
        trust_tier = 'verified'
    WHERE seller_id = {p}
    """, (
        seller_id,
    ))

    audit_metadata = json.dumps({
        "event": "seller_approved",
        "reviewer": reviewer,
        "override_terminal": override_terminal,
        "timestamp": now,
    })

    cur.execute(f"""
    UPDATE sellers
    SET
        metadata = {p}
    WHERE seller_id = {p}
    """, (
        audit_metadata,
        seller_id,
    ))

    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="seller_approved",
        reviewer=reviewer,
        reason="foundation approval",
        override_terminal=override_terminal,
        old_status=seller.get("seller_status"),
        new_status="active",
        metadata={
            "verification_status": "foundation_verified",
        },
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "reviewer": reviewer,
        "override_terminal": override_terminal,
        "message": "seller_approved_under_foundation_governance",
    }


def authenticate_seller_api_key_db(api_key):
    seller = get_seller_by_api_key_db(api_key)

    if not seller:
        return {
            "status": "error",
            "message": "invalid_api_key",
        }

    seller_status = str(
        seller.get("seller_status", "pending")
    ).lower()

    if seller_status == "banned":
        return {
            "status": "error",
            "message": "seller_banned",
            "seller_id": seller.get("seller_id"),
        }

    if seller_status == "restricted":
        return {
            "status": "error",
            "message": "seller_restricted",
            "seller_id": seller.get("seller_id"),
        }

    return {
        "status": "ok",
        "seller": seller,
    }


def get_seller_by_wallet_db(wallet):
    if not wallet:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM sellers
    WHERE wallet = {p}
    """, (wallet,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def list_sellers_db(limit=100):
    conn = get_conn()
    cur = conn.cursor()

    limit = int(limit or 100)

    cur.execute(f"""
    SELECT *
    FROM sellers
    ORDER BY updated_at DESC
    LIMIT {limit}
    """)

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]


def count_active_seller_agents_db(seller_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT COUNT(*) AS active_count
    FROM seller_agents
    WHERE seller_id = {p}
      AND seller_agent_status = 'active'
    """, (seller_id,))

    row = cur.fetchone()
    release_conn(conn)

    return int(row_get(row, "active_count", 0) or 0)


def can_seller_add_agent_db(seller_id):
    seller = get_seller_db(seller_id)
    if not seller:
        return {
            "allowed": False,
            "reason": "seller_not_found",
            "active_agents": 0,
            "max_agents_allowed": 0,
        }

    active_agents = count_active_seller_agents_db(seller_id)
    max_agents_allowed = int(seller.get("max_agents_allowed", 1) or 1)

    if active_agents >= max_agents_allowed:
        return {
            "allowed": False,
            "reason": "seller_agent_limit_reached",
            "active_agents": active_agents,
            "max_agents_allowed": max_agents_allowed,
        }

    if seller.get("seller_status") not in ("active", "pending"):
        return {
            "allowed": False,
            "reason": "seller_status_not_allowed",
            "active_agents": active_agents,
            "max_agents_allowed": max_agents_allowed,
            "seller_status": seller.get("seller_status"),
        }

    return {
        "allowed": True,
        "reason": "allowed",
        "active_agents": active_agents,
        "max_agents_allowed": max_agents_allowed,
    }


def create_seller_agent_db(seller_agent):
    seller_id = seller_agent["seller_id"]

    permission = can_seller_add_agent_db(seller_id)
    if not permission.get("allowed"):
        return {
            "status": "error",
            "message": permission.get("reason"),
            "details": permission,
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    capabilities = seller_agent.get("capabilities", "[]")
    if not isinstance(capabilities, str):
        capabilities = json.dumps(capabilities)

    specialties = seller_agent.get("specialties", "[]")
    if not isinstance(specialties, str):
        specialties = json.dumps(specialties)

    metadata = seller_agent.get("metadata", "{}")
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)

    cur.execute(f"""
    INSERT INTO seller_agents (
        seller_agent_id, seller_id, agent_id,
        service, url,
        capabilities, specialties,
        seller_agent_status,
        reputation, risk_score,
        successful_orders, failed_orders,
        latency_avg, consensus_score,
        exposure_limit,
        runtime_validation_status,
        runtime_health_score,
        runtime_latency,
        runtime_last_checked_at,
        created_at, updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        seller_agent["seller_agent_id"],
        seller_id,
        seller_agent["agent_id"],
        seller_agent["service"],
        seller_agent.get("url"),
        capabilities,
        specialties,
        seller_agent.get("seller_agent_status", "active"),
        float(seller_agent.get("reputation", 0.5) or 0.5),
        float(seller_agent.get("risk_score", 0) or 0),
        int(seller_agent.get("successful_orders", 0) or 0),
        int(seller_agent.get("failed_orders", 0) or 0),
        float(seller_agent.get("latency_avg", 0) or 0),
        float(seller_agent.get("consensus_score", 0) or 0),
        float(seller_agent.get("exposure_limit", 0) or 0),
        seller_agent.get("runtime_validation_status", "unknown"),
        float(seller_agent.get("runtime_health_score", 0) or 0),
        float(seller_agent.get("runtime_latency", 0) or 0),
        int(seller_agent.get("runtime_last_checked_at", now) or now),
        now,
        now,
        metadata,
    ))

    cur.execute(f"""
    UPDATE sellers
    SET total_agents = total_agents + 1,
        active_agents = active_agents + 1,
        updated_at = {p}
    WHERE seller_id = {p}
    """, (now, seller_id))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_agent": get_seller_agent_db(seller_agent["seller_agent_id"]),
    }


def get_seller_agent_db(seller_agent_id):
    if not seller_agent_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agents
    WHERE seller_agent_id = {p}
    """, (seller_agent_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None





def update_seller_agent_runtime_status_db(
    seller_agent_id,
    runtime_validation_status,
    runtime_health_score,
    runtime_latency=0,
    disable_if_unhealthy=True,
):
    if not seller_agent_id:
        return {
            "status": "error",
            "message": "seller_agent_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    runtime_health_score = max(
        0.0,
        min(float(runtime_health_score or 0), 1.0),
    )

    runtime_validation_status = str(
        runtime_validation_status or "unknown"
    )

    seller_agent_status = None

    if disable_if_unhealthy:
        if runtime_validation_status in ["dead", "quarantined"]:
            seller_agent_status = "disabled"
        elif runtime_validation_status in ["degraded", "unstable"]:
            seller_agent_status = "limited"
        elif runtime_validation_status == "validated" and runtime_health_score >= 0.75:
            seller_agent_status = "active"

    if seller_agent_status is not None:
        cur.execute(f"""
        UPDATE seller_agents
        SET runtime_validation_status = {p},
            runtime_health_score = {p},
            runtime_latency = {p},
            runtime_last_checked_at = {p},
            seller_agent_status = {p},
            updated_at = {p}
        WHERE seller_agent_id = {p}
        """, (
            runtime_validation_status,
            runtime_health_score,
            float(runtime_latency or 0),
            now,
            seller_agent_status,
            now,
            seller_agent_id,
        ))
    else:
        cur.execute(f"""
        UPDATE seller_agents
        SET runtime_validation_status = {p},
            runtime_health_score = {p},
            runtime_latency = {p},
            runtime_last_checked_at = {p},
            updated_at = {p}
        WHERE seller_agent_id = {p}
        """, (
            runtime_validation_status,
            runtime_health_score,
            float(runtime_latency or 0),
            now,
            now,
            seller_agent_id,
        ))

    cur.execute(f"""
    SELECT agent_id, seller_id
    FROM seller_agents
    WHERE seller_agent_id = {p}
    """, (seller_agent_id,))

    row = cur.fetchone()
    agent_id = row_get(row, "agent_id") if row else None
    seller_id = row_get(row, "seller_id") if row else None

    if agent_id:
        marketplace_available = 1 if (
            runtime_validation_status == "validated"
            and runtime_health_score >= 0.75
        ) else 0

        target_risk = max(0.0, 1.0 - runtime_health_score)

        if is_postgres():
            cur.execute(f"""
            UPDATE agents
            SET available = {p},
                risk_score = CASE
                    WHEN {p} = 1 THEN LEAST(
                        COALESCE(risk_score, 0),
                        {p}
                    )
                    ELSE GREATEST(
                        COALESCE(risk_score, 0),
                        {p}
                    )
                END,
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                marketplace_available,
                marketplace_available,
                target_risk,
                target_risk,
                now,
                agent_id,
            ))
        else:
            cur.execute(f"""
            UPDATE agents
            SET available = {p},
                risk_score = CASE
                    WHEN {p} = 1 THEN MIN(
                        COALESCE(risk_score, 0),
                        {p}
                    )
                    ELSE MAX(
                        COALESCE(risk_score, 0),
                        {p}
                    )
                END,
                updated_at = {p}
            WHERE agent_id = {p}
            """, (
                marketplace_available,
                marketplace_available,
                target_risk,
                target_risk,
                now,
                agent_id,
            ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_agent_id": seller_agent_id,
        "seller_id": seller_id,
        "agent_id": agent_id,
        "runtime_validation_status": runtime_validation_status,
        "runtime_health_score": runtime_health_score,
        "runtime_latency": float(runtime_latency or 0),
        "marketplace_available": bool(agent_id and runtime_validation_status not in ["dead", "quarantined", "degraded", "unstable"]),
    }


def list_seller_agents_db(seller_id, limit=100):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    limit = int(limit or 100)

    cur.execute(f"""
    SELECT *
    FROM seller_agents
    WHERE seller_id = {p}
    ORDER BY updated_at DESC
    LIMIT {limit}
    """, (seller_id,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]




def apply_seller_dynamic_exposure_control_with_cursor(
    cur,
    seller_id,
    seller_status,
    risk_score,
    exposure_limit,
    reason="dynamic_exposure_control",
):
    p = qmark()
    now = int(time.time())

    risk_score = max(0.0, min(float(risk_score or 0), 1.0))
    exposure_limit = max(0.0, float(exposure_limit or 0))

    if risk_score >= 0.85 or seller_status in ["restricted", "rejected", "banned"]:
        agent_available = 0
        agent_exposure = 0
        routing_tier = "blocked"

    elif risk_score >= 0.65 or seller_status == "limited":
        agent_available = 0
        agent_exposure = exposure_limit * 0.25
        routing_tier = "limited"

    elif risk_score >= 0.35 or seller_status == "watchlist":
        agent_available = 0
        agent_exposure = exposure_limit * 0.50
        routing_tier = "watchlist"

    else:
        agent_available = 1 if seller_status == "active" else 0
        agent_exposure = exposure_limit
        routing_tier = "normal" if agent_available else "pending"

    cur.execute(f"""
    UPDATE seller_agents
    SET
        exposure_limit = {p},
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        agent_exposure,
        now,
        seller_id,
    ))

    cur.execute(f"""
    UPDATE agents
    SET
        available = {p},
        seller_status = {p},
        risk_score = {p},
        max_order_value = {p}
    WHERE seller_id = {p}
    """, (
        agent_available,
        seller_status,
        risk_score,
        agent_exposure,
        seller_id,
    ))

    return {
        "status": "ok",
        "seller_id": seller_id,
        "seller_status": seller_status,
        "risk_score": risk_score,
        "agent_available": bool(agent_available),
        "agent_exposure_limit": agent_exposure,
        "routing_tier": routing_tier,
        "reason": reason,
    }


def apply_seller_risk_event_db(
    seller_id,
    event_type="generic_risk",
    severity=0.1,
    reason=None,
):
    seller = get_seller_db(seller_id)
    if not seller:
        return {
            "status": "error",
            "message": "seller_not_found",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    current_risk = float(seller.get("risk_score", 0) or 0)
    current_max_agents = int(seller.get("max_agents_allowed", 1) or 1)
    current_exposure = float(seller.get("exposure_limit", 0) or 0)

    severity = max(0.0, min(float(severity or 0), 1.0))

    # Defensive but not paranoid:
    # most signals should add friction, not instantly kill seller capacity.
    event_weights = {
        "generic_risk": 0.25,
        "scam_suspicion": 0.35,
        "failed_delivery": 0.30,
        "consensus_failure": 0.25,
        "cluster_risk": 0.30,
        "threat_memory_sync": 0.40,
        "fake_volume": 0.45,
        "fraud_signal": 0.60,
        "manual_review": 0.50,
        "confirmed_fraud": 1.00,
    }

    event_weight = event_weights.get(str(event_type), 0.25)

    trust_tier = str(seller.get("trust_tier", "new") or "new").lower()

    trust_resistance = {
        "new": 1.00,
        "free": 1.00,
        "basic": 0.90,
        "trusted": 0.70,
        "verified": 0.60,
        "foundation_verified": 0.50,
    }.get(trust_tier, 1.00)

    # Risk naturally decays slightly at each review to avoid permanent death spirals.
    decay_factor = 0.92

    adjusted_severity = severity * event_weight * trust_resistance

    # Only confirmed fraud can produce a full emergency jump.
    if event_type != "confirmed_fraud":
        adjusted_severity = min(adjusted_severity, 0.30)

    new_risk = min(1.0, (current_risk * decay_factor) + adjusted_severity)

    new_max_agents = current_max_agents

    if new_risk >= 0.85:
        new_status = "restricted"
        new_max_agents = 1
        new_exposure = 0
    elif new_risk >= 0.65:
        new_status = "limited"
        new_max_agents = max(1, min(current_max_agents, 2))
        new_exposure = current_exposure * 0.25
    elif new_risk >= 0.35:
        new_status = "watchlist"
        new_max_agents = max(1, current_max_agents - 1)
        new_exposure = current_exposure * 0.5
    else:
        new_status = seller.get("seller_status", "pending")
        new_exposure = current_exposure

    cur.execute(f"""
    UPDATE sellers
    SET risk_score = {p},
        seller_status = {p},
        max_agents_allowed = {p},
        exposure_limit = {p},
        last_violation_at = {p},
        last_risk_review_at = {p},
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        new_risk,
        new_status,
        new_max_agents,
        new_exposure,
        now,
        now,
        now,
        seller_id,
    ))

    cur.execute(f"""
    SELECT COUNT(*) AS active_count
    FROM seller_agents
    WHERE seller_id = {p}
      AND seller_agent_status = 'active'
    """, (
        seller_id,
    ))

    active_row = cur.fetchone()

    active_agents = int(
        row_get(active_row, "active_count", 0)
        if active_row else 0
    )

    limited_agent_ids = []

    if active_agents > new_max_agents:
        excess = active_agents - new_max_agents

        cur.execute(f"""
        SELECT seller_agent_id, agent_id
        FROM seller_agents
        WHERE seller_id = {p}
          AND seller_agent_status = 'active'
        ORDER BY risk_score DESC, failed_orders DESC, updated_at ASC
        LIMIT {excess}
        """, (seller_id,))

        rows = cur.fetchall()
        limited_agent_ids = [
            row_get(r, "seller_agent_id")
            for r in rows
        ]

        marketplace_agent_ids = [
            row_get(r, "agent_id")
            for r in rows
            if row_get(r, "agent_id")
        ]

        for seller_agent_id in limited_agent_ids:
            cur.execute(f"""
            UPDATE seller_agents
            SET seller_agent_status = 'limited',
                exposure_limit = 0,
                updated_at = {p}
            WHERE seller_agent_id = {p}
            """, (now, seller_agent_id))

        for agent_id in marketplace_agent_ids:
            cur.execute(f"""
            UPDATE agents
            SET available = 0,
                seller_status = {p}
            WHERE agent_id = {p}
            """, (
                new_status,
                agent_id,
            ))

    exposure_control = apply_seller_dynamic_exposure_control_with_cursor(
        cur=cur,
        seller_id=seller_id,
        seller_status=new_status,
        risk_score=new_risk,
        exposure_limit=new_exposure,
        reason=str(reason or event_type),
    )

    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="seller_risk_event",
        reviewer="adaptive_risk_engine",
        reason=str(reason or event_type),
        override_terminal=False,
        old_status=seller.get("seller_status"),
        new_status=new_status,
        metadata={
            "risk_event_type": event_type,
            "old_risk_score": current_risk,
            "new_risk_score": new_risk,
            "severity": severity,
            "adjusted_severity": adjusted_severity,
            "old_max_agents_allowed": current_max_agents,
            "new_max_agents_allowed": new_max_agents,
            "old_exposure_limit": current_exposure,
            "new_exposure_limit": new_exposure,
            "limited_agent_ids": limited_agent_ids,
            "exposure_control": exposure_control,
        },
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "event_type": event_type,
        "reason": reason,
        "old_risk_score": current_risk,
        "new_risk_score": new_risk,
        "old_max_agents_allowed": current_max_agents,
        "new_max_agents_allowed": new_max_agents,
        "new_seller_status": new_status,
        "new_exposure_limit": new_exposure,
    }


def sync_seller_risk_from_threat_memory_db(
    seller_id,
    auto_apply=True,
):
    """
    Convert active threat memories into seller risk signals.

    This is one of the first bridges between:
    threat intelligence
    graph intelligence
    adaptive sanctions
    seller exposure governance
    """

    if not seller_id:
        return {
            "status": "error",
            "message": "missing_seller_id",
        }

    memories = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=100,
    )

    if not memories:
        return {
            "status": "ok",
            "seller_id": seller_id,
            "threat_memories": 0,
            "aggregated_risk": 0,
            "action_taken": False,
        }

    total_weight = 0.0
    weighted_score = 0.0

    attack_vectors = []
    guardrails = []

    for memory in memories:
        confidence = float(memory.get("confidence", 0) or 0)
        strength = float(memory.get("memory_strength", 0.5) or 0.5)

        threat_level = str(
            memory.get("threat_level", "medium")
        ).lower()

        level_weight = {
            "low": 0.25,
            "medium": 0.5,
            "high": 0.8,
            "critical": 1.0,
        }.get(threat_level, 0.5)

        score = (
            confidence * 0.45
            + strength * 0.35
            + level_weight * 0.20
        )

        weighted_score += score
        total_weight += 1.0

        attack_vector = memory.get("attack_vector")
        if attack_vector:
            attack_vectors.append(attack_vector)

        guardrail = memory.get("recommended_guardrail")
        if guardrail:
            guardrails.append(guardrail)

    aggregated_risk = round(
        min(1.0, weighted_score / max(total_weight, 1.0)),
        4,
    )

    severity = aggregated_risk

    result = None

    if auto_apply and severity >= 0.15:
        result = apply_seller_risk_event_db(
            seller_id=seller_id,
            event_type="threat_memory_sync",
            severity=severity,
            reason=json.dumps({
                "attack_vectors": attack_vectors[:10],
                "guardrails": guardrails[:10],
                "threat_memory_count": len(memories),
            }),
        )

    return {
        "status": "ok",
        "seller_id": seller_id,
        "threat_memories": len(memories),
        "aggregated_risk": aggregated_risk,
        "severity": severity,
        "attack_vectors": attack_vectors[:10],
        "guardrails": guardrails[:10],
        "action_taken": result is not None,
        "risk_application": result,
    }


def reset_test_seller_risk_db(seller_id):
    """
    DEV/TEST ONLY.
    Reset seller risk state after local experiments.
    Do not expose publicly without admin protection.
    """
    if not seller_id:
        return {"status": "error", "message": "missing_seller_id"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE sellers
    SET risk_score = 0,
        seller_status = 'pending',
        max_agents_allowed = 1,
        exposure_limit = 0,
        last_violation_at = NULL,
        last_risk_review_at = {p},
        updated_at = {p}
    WHERE seller_id = {p}
    """, (now, now, seller_id))

    cur.execute(f"""
    UPDATE seller_agents
    SET seller_agent_status = 'active',
        updated_at = {p}
    WHERE seller_id = {p}
    """, (now, seller_id))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "message": "seller risk reset for dev/test",
    }


def reset_test_agent_consensus_db(agent_id):
    """
    DEV/TEST ONLY.
    Reset agent consensus/risk state after local experiments.
    """
    if not agent_id:
        return {"status": "error", "message": "missing_agent_id"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE agents
    SET consensus_checks = 0,
        consensus_disagreements = 0,
        consensus_disagreement_rate = 0,
        last_consensus_score = NULL,
        last_consensus_checked_at = NULL,
        risk_score = 0,
        updated_at = {p}
    WHERE agent_id = {p}
    """, (now, agent_id))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "agent_id": agent_id,
        "message": "agent consensus/risk reset for dev/test",
    }


def sync_cluster_risk_to_seller_governance_db(agent_id):
    """
    Bridge cluster intelligence into seller governance.

    Cluster intelligence remains advisory, but when risk is persistent/enough,
    it adds progressive governance friction instead of immediate punishment.
    """
    if not agent_id:
        return {"status": "error", "message": "missing_agent_id"}

    cluster = detect_seller_cluster_db(agent_id)

    if not cluster:
        return {
            "status": "ok",
            "agent_id": agent_id,
            "message": "no_cluster_detected",
            "action_taken": False,
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT seller_id, seller_agent_id
    FROM agents
    WHERE agent_id = {p}
    """, (agent_id,))

    row = cur.fetchone()
    release_conn(conn)

    seller_id = row_get(row, "seller_id") if row else None
    seller_agent_id = row_get(row, "seller_agent_id") if row else None

    if not seller_id:
        return {
            "status": "ok",
            "agent_id": agent_id,
            "cluster": cluster,
            "message": "agent_not_linked_to_seller",
            "action_taken": False,
        }

    cluster_risk = float(cluster.get("cluster_risk_score", 0) or 0)
    coordination = float(cluster.get("coordination_probability", 0) or 0)
    threat_memory_count = int(cluster.get("threat_memory_count", 0) or 0)
    member_count = int(cluster.get("member_count", 0) or 0)

    # Soft evidence score. Cluster alone should not destroy seller capacity.
    severity = (
        cluster_risk * 0.35
        + coordination * 0.30
        + min(threat_memory_count, 10) / 10 * 0.20
        + min(member_count, 10) / 10 * 0.15
    )

    severity = round(min(0.60, max(0.0, severity)), 4)

    # Require meaningful signal before applying governance friction.
    if severity < 0.20:
        return {
            "status": "ok",
            "agent_id": agent_id,
            "seller_id": seller_id,
            "cluster": cluster,
            "severity": severity,
            "message": "cluster_signal_below_governance_threshold",
            "action_taken": False,
        }

    application = apply_seller_risk_event_db(
        seller_id=seller_id,
        event_type="cluster_risk",
        severity=severity,
        reason=json.dumps({
            "agent_id": agent_id,
            "seller_agent_id": seller_agent_id,
            "cluster_id": cluster.get("cluster_id"),
            "cluster_risk_score": cluster_risk,
            "coordination_probability": coordination,
            "threat_memory_count": threat_memory_count,
            "member_count": member_count,
        }),
    )

    return {
        "status": "ok",
        "agent_id": agent_id,
        "seller_id": seller_id,
        "cluster": cluster,
        "severity": severity,
        "action_taken": True,
        "risk_application": application,
    }


def run_seller_risk_orchestration_db(agent_id):
    """
    Central seller risk orchestration layer.

    Bridges:
    - threat memory
    - cluster intelligence
    - seller governance
    - future adaptive defense / exposure / escrow logic

    Philosophy:
    - observe first
    - apply progressive friction
    - avoid protocol self-destruction
    """
    if not agent_id:
        return {"status": "error", "message": "missing_agent_id"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT seller_id, seller_agent_id
    FROM agents
    WHERE agent_id = {p}
    """, (agent_id,))

    row = cur.fetchone()
    release_conn(conn)

    seller_id = row_get(row, "seller_id") if row else None
    seller_agent_id = row_get(row, "seller_agent_id") if row else None

    if not seller_id:
        return {
            "status": "ok",
            "agent_id": agent_id,
            "message": "agent_not_linked_to_seller",
            "action_taken": False,
        }

    threat_sync = sync_seller_risk_from_threat_memory_db(
        seller_id=seller_id,
        auto_apply=True,
    )

    cluster_sync = sync_cluster_risk_to_seller_governance_db(
        agent_id=agent_id,
    )

    seller = get_seller_db(seller_id)

    return {
        "status": "ok",
        "agent_id": agent_id,
        "seller_id": seller_id,
        "seller_agent_id": seller_agent_id,
        "threat_memory_sync": threat_sync,
        "cluster_sync": cluster_sync,
        "seller_state": {
            "risk_score": seller.get("risk_score") if seller else None,
            "seller_status": seller.get("seller_status") if seller else None,
            "max_agents_allowed": seller.get("max_agents_allowed") if seller else None,
            "exposure_limit": seller.get("exposure_limit") if seller else None,
            "trust_tier": seller.get("trust_tier") if seller else None,
        },
    }


def deactivate_adaptive_policy_db(scope, service=None):
    """
    Admin/dev utility.
    Deactivate an adaptive policy so test policies do not keep influencing routing.
    """
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    if service:
        cur.execute(f"""
        UPDATE adaptive_defense_policies
        SET active = 0,
            updated_at = {p}
        WHERE scope = {p}
          AND service = {p}
        """, (
            now,
            scope,
            service,
        ))
    else:
        cur.execute(f"""
        UPDATE adaptive_defense_policies
        SET active = 0,
            updated_at = {p}
        WHERE scope = {p}
          AND service IS NULL
        """, (
            now,
            scope,
        ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "scope": scope,
        "service": service or "global",
        "message": "adaptive policy deactivated",
    }


def init_adaptive_defense_tables():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS adaptive_defense_policies (
        policy_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        service TEXT,
        risk_level TEXT DEFAULT 'low',
        min_stake_multiplier REAL DEFAULT 1.0,
        consensus_multiplier REAL DEFAULT 1.0,
        escrow_delay_multiplier REAL DEFAULT 1.0,
        exposure_multiplier REAL DEFAULT 1.0,
        decay_multiplier REAL DEFAULT 1.0,
        activation_reason TEXT DEFAULT '{}',
        confidence REAL DEFAULT 0,
        source TEXT DEFAULT 'protocol',
        active INTEGER DEFAULT 1,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        expires_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS adaptive_policy_events (
        event_id TEXT PRIMARY KEY,
        policy_id TEXT,
        scope TEXT,
        service TEXT,
        event_type TEXT,
        old_policy TEXT DEFAULT '{}',
        new_policy TEXT DEFAULT '{}',
        reason TEXT DEFAULT '{}',
        source TEXT DEFAULT 'protocol',
        created_at INTEGER NOT NULL
    )
    """)

    conn.commit()
    release_conn(conn)



def init_seller_governance_events_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_governance_events (
        event_id TEXT PRIMARY KEY,
        seller_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        reviewer TEXT,
        reason TEXT,
        override_terminal BOOLEAN DEFAULT FALSE,
        old_status TEXT,
        new_status TEXT,
        metadata TEXT DEFAULT '{}',
        created_at BIGINT NOT NULL
    )
    """)

    conn.commit()
    release_conn(conn)



def create_seller_governance_event_with_cursor(
    cur,
    seller_id,
    event_type,
    reviewer="foundation_protocol",
    reason="",
    override_terminal=False,
    old_status="",
    new_status="",
    metadata=None,
):

    p = qmark()

    event_id = "seller_event_" + str(uuid.uuid4())
    now = int(time.time())

    metadata_json = json.dumps(metadata or {})


    cur.execute(f"""
    INSERT INTO seller_governance_events (
        event_id,
        seller_id,
        event_type,
        reviewer,
        reason,
        override_terminal,
        old_status,
        new_status,
        metadata,
        created_at
    ) VALUES (
        {p}, {p}, {p}, {p}, {p},
        {p}, {p}, {p}, {p}, {p}
    )
    """, (
        event_id,
        seller_id,
        event_type,
        reviewer,
        reason,
        bool(override_terminal),
        old_status,
        new_status,
        metadata_json,
        now,
    ))


    return {
        "status": "ok",
        "event_id": event_id,
    }



def create_seller_governance_event_db(
    seller_id,
    event_type,
    reviewer="foundation_protocol",
    reason="",
    override_terminal=False,
    old_status="",
    new_status="",
    metadata=None,
):
    conn = get_conn()
    cur = conn.cursor()

    p = qmark()

    event_id = "seller_event_" + str(uuid.uuid4())
    now = int(time.time())

    metadata_json = json.dumps(metadata or {})

    cur.execute(f"""
    INSERT INTO seller_governance_events (
        event_id,
        seller_id,
        event_type,
        reviewer,
        reason,
        override_terminal,
        old_status,
        new_status,
        metadata,
        created_at
    ) VALUES (
        {p}, {p}, {p}, {p}, {p},
        {p}, {p}, {p}, {p}, {p}
    )
    """, (
        event_id,
        seller_id,
        event_type,
        reviewer,
        reason,
        override_terminal,
        old_status,
        new_status,
        metadata_json,
        now,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "event_id": event_id,
    }


def list_seller_governance_events_db(
    seller_id,
    limit=100,
):
    conn = get_conn()
    cur = conn.cursor()

    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_governance_events
    WHERE seller_id = {p}
    ORDER BY created_at DESC
    LIMIT {p}
    """, (
        seller_id,
        limit,
    ))

    rows = cur.fetchall()

    release_conn(conn)

    return [dict(r) for r in rows]


def list_runtime_monitored_seller_agents_db(limit=100):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT seller_agent_id,
           seller_id,
           agent_id,
           url,
           runtime_validation_status,
           runtime_health_score,
           seller_agent_status
    FROM seller_agents
    WHERE seller_agent_status IN ('active', 'limited')
    ORDER BY updated_at ASC
    LIMIT {p}
    """, (int(limit or 100),))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(r) for r in rows]


