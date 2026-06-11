from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

pool = None
import os
import sqlite3
import json
import time
import uuid
from pathlib import Path

DB_PATH = Path(os.getenv("IAT_DB_PATH", "iat_protocol.db"))
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



def get_last_insert_id_db(cur):
    if USE_POSTGRES:
        cur.execute("SELECT LASTVAL() AS id")
        row = cur.fetchone()
        return row_get(row, "id")

    return cur.lastrowid


    return get_last_insert_id_db(cur)
















def store_seller_agent_factory_approval_db(
    factory_request_id,
    seller_id,
    approved_by,
    approval_reason="",
    metadata=None,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    if not approved_by:
        return {"status": "error", "message": "approved_by_required"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "factory_approval_informs_protocol": True,
        "factory_approval_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_factory_approvals (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        "approved",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    approval_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "approval_id": approval_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approved_by": approved_by,
    }


def get_seller_agent_factory_approvals_db(
    factory_request_id=None,
    seller_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_factory_approvals
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "approvals": rows,
    }


def approve_seller_agent_factory_request_db(
    factory_request_id,
    approved_by="iat_core",
    approval_reason="",
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
            "factory_request_id": factory_request_id,
        }

    review_evaluation = evaluate_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id
    )

    if review_evaluation.get("readiness") != "ready_for_factory_approval":
        return {
            "status": "error",
            "message": "factory_request_not_ready_for_approval",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "policy": {
                "factory_reviews_required": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    seller_id = factory_request.get("seller_id")

    existing_approvals = get_seller_agent_factory_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if existing_approvals.get("count", 0) > 0:
        return {
            "status": "already_approved",
            "factory_request_id": factory_request_id,
            "seller_id": seller_id,
            "approval": existing_approvals.get("approvals", [None])[0],
            "review_evaluation": review_evaluation,
            "policy": {
                "factory_reviews_required": True,
                "seller_cannot_self_approve": True,
                "factory_approval_required_before_sandbox": True,
                "duplicate_approval_prevented": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    approval = store_seller_agent_factory_approval_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        approved_by=approved_by,
        approval_reason=approval_reason,
        metadata={
            "review_evaluation": review_evaluation,
            "approval_source": "approve_seller_agent_factory_request_db",
        },
    )

    return {
        "status": "approved",
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approval": approval,
        "review_evaluation": review_evaluation,
        "policy": {
            "factory_reviews_required": True,
            "seller_cannot_self_approve": True,
            "factory_approval_required_before_sandbox": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_seller_agent_factory_review_db(
    factory_request_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    seller_id=None,
    review_reason=None,
    confidence_score=0.0,
    risk_score=0.0,
    capability_score=0.0,
    policy_score=0.0,
    safety_score=0.0,
    metadata=None,
):
    if not factory_request_id:
        return {
            "status": "error",
            "message": "factory_request_id_required",
        }

    if not reviewer_type or not reviewer_id:
        return {
            "status": "error",
            "message": "reviewer_required",
        }

    if review_decision not in [
        "approve",
        "reject",
        "abstain",
        "needs_more_evidence",
    ]:
        return {
            "status": "error",
            "message": "invalid_review_decision",
        }

    metadata = metadata or {}
    metadata = {
        **metadata,
        "factory_review_informs_protocol": True,
        "factory_review_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO seller_agent_factory_reviews (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        capability_score,
        policy_score,
        safety_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        round(float(capability_score or 0), 4),
        round(float(policy_score or 0), 4),
        round(float(safety_score or 0), 4),
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "review_decision": review_decision,
    }


def get_seller_agent_factory_reviews_db(
    factory_request_id=None,
    seller_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_factory_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_seller_agent_factory_reviews_db(
    factory_request_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
    min_avg_safety=0.70,
    min_avg_policy=0.70,
):
    if not factory_request_id:
        return {
            "status": "error",
            "message": "factory_request_id_required",
        }

    reviews_result = get_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [r for r in reviews if r.get("review_decision") == "approve"]
    reject_reviews = [r for r in reviews if r.get("review_decision") == "reject"]
    evidence_reviews = [r for r in reviews if r.get("review_decision") == "needs_more_evidence"]
    abstain_reviews = [r for r in reviews if r.get("review_decision") == "abstain"]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(evidence_reviews)
    abstain_count = len(abstain_reviews)

    scoring_reviews = [
        r for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    def avg(field, default=0):
        values = [float(r.get(field, default) or default) for r in scoring_reviews]
        return sum(values) / len(values) if values else default

    avg_confidence = avg("confidence_score", 0)
    avg_risk = avg("risk_score", 1)
    avg_capability = avg("capability_score", 0)
    avg_policy = avg("policy_score", 0)
    avg_safety = avg("safety_score", 0)

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"
    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"
    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"
    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"
    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"
    elif avg_policy < min_avg_policy:
        readiness = "blocked"
        reason = "average_policy_score_too_low"
    elif avg_safety < min_avg_safety:
        readiness = "blocked"
        reason = "average_safety_score_too_low"
    elif approve_count >= int(min_reviews or 2):
        readiness = "ready_for_factory_approval"
        reason = "factory_review_threshold_met"

    return {
        "status": "ok",
        "factory_request_id": factory_request_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "avg_capability": round(avg_capability, 4),
            "avg_policy": round(avg_policy, 4),
            "avg_safety": round(avg_safety, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
            "min_avg_policy": min_avg_policy,
            "min_avg_safety": min_avg_safety,
        },
        "policy": {
            "factory_reviews_inform_protocol": True,
            "factory_reviews_do_not_govern_protocol": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }











def store_seller_agent_simulation_approval_db(
    factory_request_id,
    seller_id,
    approved_by,
    approval_reason="",
    metadata=None,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    if not approved_by:
        return {"status": "error", "message": "approved_by_required"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "simulation_approval_informs_protocol": True,
        "simulation_approval_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_simulation_approvals (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        "approved",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    approval_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "approval_id": approval_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approved_by": approved_by,
    }


def get_seller_agent_simulation_approvals_db(
    factory_request_id=None,
    seller_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_simulation_approvals
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "approvals": rows,
    }


def approve_seller_agent_simulation_request_db(
    factory_request_id,
    approved_by="iat_core",
    approval_reason="",
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
            "factory_request_id": factory_request_id,
        }

    review_evaluation = evaluate_seller_agent_simulation_reviews_db(
        factory_request_id=factory_request_id
    )

    if review_evaluation.get("readiness") != "ready_for_simulation_approval":
        return {
            "status": "error",
            "message": "simulation_request_not_ready_for_approval",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "policy": {
                "simulation_reviews_required": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    seller_id = factory_request.get("seller_id")

    existing_approvals = get_seller_agent_simulation_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if existing_approvals.get("count", 0) > 0:
        return {
            "status": "already_approved",
            "factory_request_id": factory_request_id,
            "seller_id": seller_id,
            "approval": existing_approvals.get("approvals", [None])[0],
            "review_evaluation": review_evaluation,
            "policy": {
                "simulation_reviews_required": True,
                "seller_cannot_self_approve": True,
                "simulation_approval_required_before_generation": True,
                "duplicate_approval_prevented": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    approval = store_seller_agent_simulation_approval_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        approved_by=approved_by,
        approval_reason=approval_reason,
        metadata={
            "review_evaluation": review_evaluation,
            "approval_source": "approve_seller_agent_simulation_request_db",
        },
    )

    if (
        str(factory_request.get("sandbox_status") or "").lower() == "passed"
        and str(factory_request.get("simulation_status") or "").lower() == "passed"
    ):
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET factory_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "ready_for_generation",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

    return {
        "status": "approved",
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approval": approval,
        "review_evaluation": review_evaluation,
        "policy": {
            "simulation_reviews_required": True,
            "seller_cannot_self_approve": True,
            "simulation_approval_required_before_generation": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_seller_agent_simulation_review_db(
    factory_request_id,
    seller_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    review_reason="",
    confidence_score=0,
    risk_score=0,
    simulation_score=0,
    policy_score=0,
    safety_score=0,
    metadata=None,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    metadata = metadata or {}

    metadata = {
        **metadata,
        "simulation_review_informs_protocol": True,
        "simulation_review_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_simulation_reviews (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        simulation_score,
        policy_score,
        safety_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES (
        {p},{p},{p},{p},{p},{p},
        {p},{p},{p},{p},{p},{p},
        {p},{p}
    )
    """, (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        simulation_score,
        policy_score,
        safety_score,
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "review_decision": review_decision,
    }




def get_seller_agent_simulation_reviews_db(
    factory_request_id=None,
    seller_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_simulation_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_seller_agent_simulation_reviews_db(
    factory_request_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
    min_avg_simulation=0.70,
    min_avg_policy=0.70,
    min_avg_safety=0.70,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    reviews_result = get_seller_agent_simulation_reviews_db(
        factory_request_id=factory_request_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [r for r in reviews if r.get("review_decision") == "approve"]
    reject_reviews = [r for r in reviews if r.get("review_decision") == "reject"]
    evidence_reviews = [r for r in reviews if r.get("review_decision") == "needs_more_evidence"]
    abstain_reviews = [r for r in reviews if r.get("review_decision") == "abstain"]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(evidence_reviews)
    abstain_count = len(abstain_reviews)

    scoring_reviews = [
        r for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    def avg(field, default=0):
        values = [float(r.get(field, default) or default) for r in scoring_reviews]
        return sum(values) / len(values) if values else default

    avg_confidence = avg("confidence_score", 0)
    avg_risk = avg("risk_score", 1)
    avg_simulation = avg("simulation_score", 0)
    avg_policy = avg("policy_score", 0)
    avg_safety = avg("safety_score", 0)

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"
    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"
    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"
    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"
    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"
    elif avg_simulation < min_avg_simulation:
        readiness = "blocked"
        reason = "average_simulation_score_too_low"
    elif avg_policy < min_avg_policy:
        readiness = "blocked"
        reason = "average_policy_score_too_low"
    elif avg_safety < min_avg_safety:
        readiness = "blocked"
        reason = "average_safety_score_too_low"
    elif approve_count >= int(min_reviews or 2):
        readiness = "ready_for_simulation_approval"
        reason = "simulation_review_threshold_met"

    return {
        "status": "ok",
        "factory_request_id": factory_request_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "avg_simulation": round(avg_simulation, 4),
            "avg_policy": round(avg_policy, 4),
            "avg_safety": round(avg_safety, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
            "min_avg_simulation": min_avg_simulation,
            "min_avg_policy": min_avg_policy,
            "min_avg_safety": min_avg_safety,
        },
        "policy": {
            "simulation_reviews_inform_protocol": True,
            "simulation_reviews_do_not_govern_protocol": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_seller_agent_sandbox_approval_db(
    factory_request_id,
    seller_id,
    approved_by,
    approval_reason="",
    metadata=None,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    if not approved_by:
        return {"status": "error", "message": "approved_by_required"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "sandbox_approval_informs_protocol": True,
        "sandbox_approval_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_sandbox_approvals (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        factory_request_id,
        seller_id,
        approved_by,
        approval_reason,
        "approved",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    approval_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "approval_id": approval_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approved_by": approved_by,
    }


def get_seller_agent_sandbox_approvals_db(
    factory_request_id=None,
    seller_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_sandbox_approvals
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "approvals": rows,
    }


def approve_seller_agent_sandbox_request_db(
    factory_request_id,
    approved_by="iat_core",
    approval_reason="",
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
            "factory_request_id": factory_request_id,
        }

    review_evaluation = evaluate_seller_agent_sandbox_reviews_db(
        factory_request_id=factory_request_id
    )

    if review_evaluation.get("readiness") != "ready_for_sandbox_approval":
        return {
            "status": "error",
            "message": "sandbox_request_not_ready_for_approval",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "policy": {
                "sandbox_reviews_required": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    seller_id = factory_request.get("seller_id")

    existing_approvals = get_seller_agent_sandbox_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if existing_approvals.get("count", 0) > 0:
        return {
            "status": "already_approved",
            "factory_request_id": factory_request_id,
            "seller_id": seller_id,
            "approval": existing_approvals.get("approvals", [None])[0],
            "review_evaluation": review_evaluation,
            "policy": {
                "sandbox_reviews_required": True,
                "seller_cannot_self_approve": True,
                "sandbox_approval_required_before_simulation": True,
                "duplicate_approval_prevented": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    approval = store_seller_agent_sandbox_approval_db(
        factory_request_id=factory_request_id,
        seller_id=seller_id,
        approved_by=approved_by,
        approval_reason=approval_reason,
        metadata={
            "review_evaluation": review_evaluation,
            "approval_source": "approve_seller_agent_sandbox_request_db",
        },
    )

    return {
        "status": "approved",
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "approval": approval,
        "review_evaluation": review_evaluation,
        "policy": {
            "sandbox_reviews_required": True,
            "seller_cannot_self_approve": True,
            "sandbox_approval_required_before_simulation": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_seller_agent_sandbox_review_db(
    factory_request_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    seller_id=None,
    review_reason=None,
    confidence_score=0.0,
    risk_score=0.0,
    sandbox_score=0.0,
    policy_score=0.0,
    safety_score=0.0,
    metadata=None,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    if not reviewer_type or not reviewer_id:
        return {"status": "error", "message": "reviewer_required"}

    if review_decision not in ["approve", "reject", "abstain", "needs_more_evidence"]:
        return {"status": "error", "message": "invalid_review_decision"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "sandbox_review_informs_protocol": True,
        "sandbox_review_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_sandbox_reviews (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        sandbox_score,
        policy_score,
        safety_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        factory_request_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        round(float(sandbox_score or 0), 4),
        round(float(policy_score or 0), 4),
        round(float(safety_score or 0), 4),
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "review_decision": review_decision,
    }


def get_seller_agent_sandbox_reviews_db(
    factory_request_id=None,
    seller_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if factory_request_id:
        where.append(f"factory_request_id = {p}")
        params.append(factory_request_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_sandbox_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_seller_agent_sandbox_reviews_db(
    factory_request_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
    min_avg_sandbox=0.70,
    min_avg_policy=0.70,
    min_avg_safety=0.70,
):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    reviews_result = get_seller_agent_sandbox_reviews_db(
        factory_request_id=factory_request_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [r for r in reviews if r.get("review_decision") == "approve"]
    reject_reviews = [r for r in reviews if r.get("review_decision") == "reject"]
    evidence_reviews = [r for r in reviews if r.get("review_decision") == "needs_more_evidence"]
    abstain_reviews = [r for r in reviews if r.get("review_decision") == "abstain"]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(evidence_reviews)
    abstain_count = len(abstain_reviews)

    scoring_reviews = [
        r for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    def avg(field, default=0):
        values = [float(r.get(field, default) or default) for r in scoring_reviews]
        return sum(values) / len(values) if values else default

    avg_confidence = avg("confidence_score", 0)
    avg_risk = avg("risk_score", 1)
    avg_sandbox = avg("sandbox_score", 0)
    avg_policy = avg("policy_score", 0)
    avg_safety = avg("safety_score", 0)

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"
    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"
    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"
    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"
    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"
    elif avg_sandbox < min_avg_sandbox:
        readiness = "blocked"
        reason = "average_sandbox_score_too_low"
    elif avg_policy < min_avg_policy:
        readiness = "blocked"
        reason = "average_policy_score_too_low"
    elif avg_safety < min_avg_safety:
        readiness = "blocked"
        reason = "average_safety_score_too_low"
    elif approve_count >= int(min_reviews or 2):
        readiness = "ready_for_sandbox_approval"
        reason = "sandbox_review_threshold_met"

    return {
        "status": "ok",
        "factory_request_id": factory_request_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "avg_sandbox": round(avg_sandbox, 4),
            "avg_policy": round(avg_policy, 4),
            "avg_safety": round(avg_safety, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
            "min_avg_sandbox": min_avg_sandbox,
            "min_avg_policy": min_avg_policy,
            "min_avg_safety": min_avg_safety,
        },
        "policy": {
            "sandbox_reviews_inform_protocol": True,
            "sandbox_reviews_do_not_govern_protocol": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }









def init_seller_agent_simulation_approvals_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_simulation_approvals (
            approval_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_simulation_approvals (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_simulation_approvals
    ON seller_agent_simulation_approvals(
        factory_request_id,
        seller_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_simulation_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_simulation_reviews (
            review_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            simulation_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_simulation_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            simulation_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_simulation_reviews_lookup
    ON seller_agent_simulation_reviews(
        factory_request_id,
        seller_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_sandbox_approvals_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_sandbox_approvals (
            approval_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_sandbox_approvals (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_sandbox_approvals
    ON seller_agent_sandbox_approvals(
        factory_request_id,
        seller_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_sandbox_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_sandbox_reviews (
            review_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            sandbox_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_sandbox_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            sandbox_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_sandbox_reviews_lookup
    ON seller_agent_sandbox_reviews(
        factory_request_id,
        seller_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_factory_approvals_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_factory_approvals (
            approval_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_factory_approvals (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_factory_approvals
    ON seller_agent_factory_approvals(
        factory_request_id,
        seller_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)



def init_seller_agent_factory_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_factory_reviews (
            review_id SERIAL PRIMARY KEY,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            capability_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_factory_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            factory_request_id TEXT NOT NULL,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            capability_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_factory_reviews_lookup
    ON seller_agent_factory_reviews(
        factory_request_id,
        seller_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)



def init_protocol_rollback_proposals_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollback_proposals (
            proposal_id SERIAL PRIMARY KEY,

            rollback_id INTEGER,
            adaptation_id INTEGER,
            monitor_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            proposal_reason TEXT NOT NULL,

            status TEXT DEFAULT 'proposed',

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollback_proposals (
            proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,

            rollback_id INTEGER,
            adaptation_id INTEGER,
            monitor_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            proposal_reason TEXT NOT NULL,

            status TEXT DEFAULT 'proposed',

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_rollback_proposals_lookup
    ON protocol_rollback_proposals(
        rollback_id,
        adaptation_id,
        monitor_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)



def init_protocol_rollback_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollback_reviews (
            review_id SERIAL PRIMARY KEY,

            rollback_id INTEGER,
            adaptation_id INTEGER,
            monitor_id INTEGER,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollback_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            rollback_id INTEGER,
            adaptation_id INTEGER,
            monitor_id INTEGER,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_rollback_reviews_lookup
    ON protocol_rollback_reviews(
        rollback_id,
        adaptation_id,
        monitor_id,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)



def init_protocol_adaptation_monitors_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptation_monitors (
            monitor_id SERIAL PRIMARY KEY,

            adaptation_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            metric_name TEXT NOT NULL,

            baseline_value REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            threshold_value REAL DEFAULT 0,

            status TEXT DEFAULT 'active',

            created_at INTEGER NOT NULL,
            last_checked_at INTEGER,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptation_monitors (
            monitor_id INTEGER PRIMARY KEY AUTOINCREMENT,

            adaptation_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            metric_name TEXT NOT NULL,

            baseline_value REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            threshold_value REAL DEFAULT 0,

            status TEXT DEFAULT 'active',

            created_at INTEGER NOT NULL,
            last_checked_at INTEGER,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_adaptation_monitors
    ON protocol_adaptation_monitors(
        adaptation_id,
        scope,
        status
    )
    """)

    conn.commit()
    release_conn(conn)



def init_protocol_adaptation_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptation_reviews (
            review_id SERIAL PRIMARY KEY,

            adaptation_id INTEGER NOT NULL,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,

            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptation_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            adaptation_id INTEGER NOT NULL,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,

            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_adaptation_reviews
    ON protocol_adaptation_reviews(
        adaptation_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)



def init_protocol_rollbacks_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollbacks (
            rollback_id SERIAL PRIMARY KEY,

            adaptation_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            rollback_type TEXT NOT NULL,
            rollback_reason TEXT,

            pre_change_snapshot TEXT DEFAULT '{}',
            post_change_snapshot TEXT DEFAULT '{}',

            status TEXT DEFAULT 'available',

            created_at INTEGER NOT NULL,
            executed_at INTEGER,
            updated_at INTEGER NOT NULL,

            executed_by TEXT,
            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_rollbacks (
            rollback_id INTEGER PRIMARY KEY AUTOINCREMENT,

            adaptation_id INTEGER,

            scope TEXT NOT NULL,
            subject_id TEXT,

            rollback_type TEXT NOT NULL,
            rollback_reason TEXT,

            pre_change_snapshot TEXT DEFAULT '{}',
            post_change_snapshot TEXT DEFAULT '{}',

            status TEXT DEFAULT 'available',

            created_at INTEGER NOT NULL,
            executed_at INTEGER,
            updated_at INTEGER NOT NULL,

            executed_by TEXT,
            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_rollbacks_lookup
    ON protocol_rollbacks(
        adaptation_id,
        scope,
        subject_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)








def store_protocol_rollback_proposal_db(
    scope,
    proposal_reason,
    rollback_id=None,
    adaptation_id=None,
    monitor_id=None,
    subject_id=None,
    confidence_score=0.0,
    risk_score=0.0,
    metadata=None,
):
    metadata = metadata or {}

    metadata = {
        **metadata,
        "proposal_can_propose": True,
        "proposal_can_govern": False,
        "rollback_authority": "foundation_or_core_only",
        "protocol_core_sovereignty_reserved": True,
    }

    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_rollback_proposals (
        rollback_id,
        adaptation_id,
        monitor_id,
        scope,
        subject_id,
        proposal_reason,
        status,
        confidence_score,
        risk_score,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        rollback_id,
        adaptation_id,
        monitor_id,
        scope,
        subject_id,
        proposal_reason,
        "proposed",
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    proposal_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "proposal_id": proposal_id,
        "rollback_id": rollback_id,
        "adaptation_id": adaptation_id,
        "monitor_id": monitor_id,
    }


def get_protocol_rollback_proposals_db(
    rollback_id=None,
    adaptation_id=None,
    monitor_id=None,
    scope=None,
    subject_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if rollback_id is not None:
        where.append(f"rollback_id = {p}")
        params.append(rollback_id)

    if adaptation_id is not None:
        where.append(f"adaptation_id = {p}")
        params.append(adaptation_id)

    if monitor_id is not None:
        where.append(f"monitor_id = {p}")
        params.append(monitor_id)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_rollback_proposals
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "proposals": rows,
    }



def store_protocol_rollback_review_db(
    reviewer_type,
    reviewer_id,
    review_decision,
    rollback_id=None,
    adaptation_id=None,
    monitor_id=None,
    review_reason=None,
    confidence_score=0.0,
    risk_score=0.0,
    metadata=None,
):
    if not rollback_id and not adaptation_id and not monitor_id:
        return {
            "status": "error",
            "message": "rollback_id_or_adaptation_id_or_monitor_id_required",
        }

    if not reviewer_type or not reviewer_id:
        return {
            "status": "error",
            "message": "reviewer_required",
        }

    if review_decision not in [
        "approve",
        "reject",
        "abstain",
        "needs_more_evidence",
    ]:
        return {
            "status": "error",
            "message": "invalid_review_decision",
        }

    metadata = metadata or {}
    metadata = {
        **metadata,
        "rollback_review_informs_protocol": True,
        "rollback_review_governs_protocol": False,
        "rollback_authority": "foundation_or_core_only",
        "protocol_core_sovereignty_reserved": True,
    }

    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_rollback_reviews (
        rollback_id,
        adaptation_id,
        monitor_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        rollback_id,
        adaptation_id,
        monitor_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "rollback_id": rollback_id,
        "adaptation_id": adaptation_id,
        "monitor_id": monitor_id,
        "review_decision": review_decision,
    }


def get_protocol_rollback_reviews_db(
    rollback_id=None,
    adaptation_id=None,
    monitor_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if rollback_id is not None:
        where.append(f"rollback_id = {p}")
        params.append(rollback_id)

    if adaptation_id is not None:
        where.append(f"adaptation_id = {p}")
        params.append(adaptation_id)

    if monitor_id is not None:
        where.append(f"monitor_id = {p}")
        params.append(monitor_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_rollback_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_protocol_rollback_reviews_db(
    rollback_id=None,
    adaptation_id=None,
    monitor_id=None,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
):
    if not rollback_id and not adaptation_id and not monitor_id:
        return {
            "status": "error",
            "message": "rollback_id_or_adaptation_id_or_monitor_id_required",
        }

    reviews_result = get_protocol_rollback_reviews_db(
        rollback_id=rollback_id,
        adaptation_id=adaptation_id,
        monitor_id=monitor_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [
        r for r in reviews
        if r.get("review_decision") == "approve"
    ]

    reject_reviews = [
        r for r in reviews
        if r.get("review_decision") == "reject"
    ]

    needs_more_evidence_reviews = [
        r for r in reviews
        if r.get("review_decision") == "needs_more_evidence"
    ]

    abstain_reviews = [
        r for r in reviews
        if r.get("review_decision") == "abstain"
    ]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(needs_more_evidence_reviews)
    abstain_count = len(abstain_reviews)

    confidence_values = [
        float(r.get("confidence_score", 0) or 0)
        for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    risk_values = [
        float(r.get("risk_score", 0) or 0)
        for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    avg_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values else 0
    )

    avg_risk = (
        sum(risk_values) / len(risk_values)
        if risk_values else 1
    )

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"

    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"

    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"

    elif approve_count >= int(min_reviews or 2) and avg_confidence >= min_avg_confidence and avg_risk <= max_avg_risk:
        readiness = "ready_for_rollback"

        reason = "rollback_review_threshold_met"

    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"

    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"

    return {
        "status": "ok",
        "rollback_id": rollback_id,
        "adaptation_id": adaptation_id,
        "monitor_id": monitor_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
        },
        "policy": {
            "rollback_reviews_inform_protocol": True,
            "rollback_reviews_do_not_govern_protocol": True,
            "rollback_authority": "foundation_or_core_only",
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_protocol_adaptation_monitor_db(
    adaptation_id,
    scope,
    subject_id,
    metric_name,
    baseline_value=0,
    current_value=0,
    threshold_value=0,
    metadata=None,
):
    metadata = metadata or {}
    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_adaptation_monitors (
        adaptation_id,
        scope,
        subject_id,
        metric_name,
        baseline_value,
        current_value,
        threshold_value,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        adaptation_id,
        scope,
        subject_id,
        metric_name,
        baseline_value,
        current_value,
        threshold_value,
        "active",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    monitor_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "monitor_id": monitor_id,
        "adaptation_id": adaptation_id,
        "metric_name": metric_name,
    }


def get_protocol_adaptation_monitors_db(
    adaptation_id=None,
    scope=None,
    subject_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if adaptation_id is not None:
        where.append(f"adaptation_id = {p}")
        params.append(adaptation_id)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptation_monitors
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "monitors": rows,
    }




def evaluate_protocol_adaptation_monitor_db(
    monitor_id,
    current_value=None,
    evaluation_note="",
):
    if not monitor_id:
        return {
            "status": "error",
            "message": "monitor_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptation_monitors
    WHERE monitor_id = {p}
    """, (monitor_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "monitor_id": monitor_id,
        }

    baseline_value = float(row_get(row, "baseline_value", 0) or 0)
    previous_current = float(row_get(row, "current_value", 0) or 0)
    threshold_value = float(row_get(row, "threshold_value", 0) or 0)

    if current_value is None:
        current_value = previous_current

    current_value = float(current_value or 0)

    health_status = "healthy"
    rollback_recommended = False
    reason = "metric_above_threshold"

    if current_value < threshold_value:
        health_status = "degradation_detected"
        rollback_recommended = True
        reason = "metric_below_threshold"
    elif baseline_value > 0 and current_value < (baseline_value * 0.90):
        health_status = "warning"
        rollback_recommended = False
        reason = "metric_dropped_more_than_10_percent_from_baseline"

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["last_evaluation_note"] = evaluation_note
    metadata["last_health_status"] = health_status
    metadata["rollback_recommended"] = rollback_recommended
    metadata["rollback_authority"] = "foundation_or_core_only"
    metadata["monitor_informs_protocol"] = True
    metadata["monitor_governs_protocol"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    new_status = "active"
    if health_status == "degradation_detected":
        new_status = "degradation_detected"
    elif health_status == "warning":
        new_status = "warning"

    cur.execute(f"""
    UPDATE protocol_adaptation_monitors
    SET current_value = {p},
        status = {p},
        last_checked_at = {p},
        updated_at = {p},
        metadata = {p}
    WHERE monitor_id = {p}
    """, (
        round(current_value, 4),
        new_status,
        now,
        now,
        json.dumps(metadata, sort_keys=True),
        monitor_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "monitor_id": monitor_id,
        "adaptation_id": row_get(row, "adaptation_id"),
        "metric_name": row_get(row, "metric_name"),
        "baseline_value": baseline_value,
        "current_value": round(current_value, 4),
        "threshold_value": threshold_value,
        "health_status": health_status,
        "rollback_recommended": rollback_recommended,
        "reason": reason,
        "policy": {
            "monitor_informs_protocol": True,
            "monitor_governs_protocol": False,
            "rollback_authority": "foundation_or_core_only",
            "protocol_core_sovereignty_reserved": True,
        },
    }




def run_protocol_adaptation_monitoring_cycle_db(
    limit=100,
    include_warning=True,
):
    monitors_result = get_protocol_adaptation_monitors_db(
        status=None,
        limit=limit,
    )

    monitors = monitors_result.get("monitors", [])

    evaluated = []
    degradation_detected = []
    warnings = []
    healthy = []

    for monitor in monitors:
        status = monitor.get("status")

        if status not in ("active", "warning", "degradation_detected"):
            continue

        monitor_id = monitor.get("monitor_id")
        current_value = monitor.get("current_value")

        result = evaluate_protocol_adaptation_monitor_db(
            monitor_id=monitor_id,
            current_value=current_value,
            evaluation_note="monitoring_cycle_evaluation",
        )

        evaluated.append(result)

        health_status = result.get("health_status")

        if health_status == "degradation_detected":
            degradation_detected.append(result)
        elif health_status == "warning":
            warnings.append(result)
        elif health_status == "healthy":
            healthy.append(result)

    rollback_recommendations = [
        {
            "adaptation_id": item.get("adaptation_id"),
            "monitor_id": item.get("monitor_id"),
            "metric_name": item.get("metric_name"),
            "reason": item.get("reason"),
            "current_value": item.get("current_value"),
            "threshold_value": item.get("threshold_value"),
            "recommended_action": "review_and_execute_rollback",
            "rollback_authority": "foundation_or_core_only",
        }
        for item in degradation_detected
        if item.get("rollback_recommended")
    ]

    rollback_proposals_created = []

    for rec in rollback_recommendations:
        adaptation_id = rec.get("adaptation_id")
        monitor_id = rec.get("monitor_id")

        existing = get_protocol_rollback_proposals_db(
            adaptation_id=adaptation_id,
            monitor_id=monitor_id,
            status="proposed",
            limit=1,
        )

        if existing.get("count", 0) > 0:
            rollback_proposals_created.append({
                "status": "already_exists",
                "adaptation_id": adaptation_id,
                "monitor_id": monitor_id,
            })
            continue

        proposal = store_protocol_rollback_proposal_db(
            rollback_id=None,
            adaptation_id=adaptation_id,
            monitor_id=monitor_id,
            scope="adaptation_monitor",
            subject_id=str(monitor_id),
            proposal_reason=rec.get("reason") or "monitoring_degradation_detected",
            confidence_score=0.75,
            risk_score=0.25,
            metadata={
                "created_by": "run_protocol_adaptation_monitoring_cycle_db",
                "metric_name": rec.get("metric_name"),
                "current_value": rec.get("current_value"),
                "threshold_value": rec.get("threshold_value"),
                "recommended_action": rec.get("recommended_action"),
                "automatic_rollback_executed": False,
            },
        )

        rollback_proposals_created.append(proposal)

    summary = {
        "monitors_checked": len(evaluated),
        "healthy_count": len(healthy),
        "warning_count": len(warnings),
        "degradation_count": len(degradation_detected),
        "rollback_recommendation_count": len(rollback_recommendations),
        "rollback_proposal_count": len(rollback_proposals_created),
    }

    return {
        "status": "ok",
        "cycle_type": "protocol_adaptation_monitoring_cycle",
        "summary": summary,
        "healthy": healthy,
        "warnings": warnings if include_warning else [],
        "degradation_detected": degradation_detected,
        "rollback_recommendations": rollback_recommendations,
        "rollback_proposals_created": rollback_proposals_created,
        "policy": {
            "monitoring_cycle_informs_protocol": True,
            "monitoring_cycle_governs_protocol": False,
            "automatic_rollback_executed": False,
            "rollback_authority": "foundation_or_core_only",
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_protocol_adaptation_review_db(
    adaptation_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    review_reason=None,
    confidence_score=0.0,
    risk_score=0.0,
    metadata=None,
):
    if not adaptation_id:
        return {
            "status": "error",
            "message": "adaptation_id_required",
        }

    if not reviewer_type or not reviewer_id:
        return {
            "status": "error",
            "message": "reviewer_required",
        }

    if review_decision not in [
        "approve",
        "reject",
        "abstain",
        "needs_more_evidence",
    ]:
        return {
            "status": "error",
            "message": "invalid_review_decision",
        }

    metadata = metadata or {}
    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_adaptation_reviews (
        adaptation_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        adaptation_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "adaptation_id": adaptation_id,
        "review_decision": review_decision,
    }


def get_protocol_adaptation_reviews_db(
    adaptation_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if adaptation_id is not None:
        where.append(f"adaptation_id = {p}")
        params.append(adaptation_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptation_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }




def evaluate_protocol_adaptation_reviews_db(
    adaptation_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
):
    if not adaptation_id:
        return {
            "status": "error",
            "message": "adaptation_id_required",
        }

    reviews_result = get_protocol_adaptation_reviews_db(
        adaptation_id=adaptation_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [
        r for r in reviews
        if r.get("review_decision") == "approve"
    ]

    reject_reviews = [
        r for r in reviews
        if r.get("review_decision") == "reject"
    ]

    needs_more_evidence_reviews = [
        r for r in reviews
        if r.get("review_decision") == "needs_more_evidence"
    ]

    abstain_reviews = [
        r for r in reviews
        if r.get("review_decision") == "abstain"
    ]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(needs_more_evidence_reviews)
    abstain_count = len(abstain_reviews)

    confidence_values = [
        float(r.get("confidence_score", 0) or 0)
        for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    risk_values = [
        float(r.get("risk_score", 0) or 0)
        for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    avg_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values else 0
    )

    avg_risk = (
        sum(risk_values) / len(risk_values)
        if risk_values else 1
    )

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"

    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"

    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"

    elif approve_count >= int(min_reviews or 2) and avg_confidence >= min_avg_confidence and avg_risk <= max_avg_risk:
        readiness = "ready_for_approval"
        reason = "review_threshold_met"

    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"

    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"

    return {
        "status": "ok",
        "adaptation_id": adaptation_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
        },
        "policy": {
            "reviews_inform_approval": True,
            "reviews_do_not_govern_protocol": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_protocol_rollback_db(
    adaptation_id,
    scope,
    subject_id,
    rollback_type,
    rollback_reason="",
    pre_change_snapshot=None,
    post_change_snapshot=None,
    metadata=None,
):
    if not scope or not rollback_type:
        return {
            "status": "error",
            "message": "scope_and_rollback_type_required",
        }

    now = int(time.time())

    pre_change_snapshot = pre_change_snapshot or {}
    post_change_snapshot = post_change_snapshot or {}
    metadata = metadata or {}

    metadata = {
        **metadata,
        "rollback_authority": "foundation_or_core_only",
        "rollback_independent_from_intelligence": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_rollbacks (
        adaptation_id,
        scope,
        subject_id,
        rollback_type,
        rollback_reason,
        pre_change_snapshot,
        post_change_snapshot,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        adaptation_id,
        scope,
        subject_id,
        rollback_type,
        rollback_reason,
        json.dumps(pre_change_snapshot, sort_keys=True),
        json.dumps(post_change_snapshot, sort_keys=True),
        "available",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    rollback_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "rollback_id": rollback_id,
        "adaptation_id": adaptation_id,
        "scope": scope,
        "subject_id": subject_id,
        "rollback_type": rollback_type,
    }


def get_protocol_rollbacks_db(
    adaptation_id=None,
    scope=None,
    subject_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if adaptation_id is not None:
        where.append(f"adaptation_id = {p}")
        params.append(adaptation_id)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_rollbacks
    {where_sql}
    ORDER BY updated_at DESC, created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "rollbacks": rows,
    }


def rollback_protocol_adaptation_db(
    rollback_id=None,
    adaptation_id=None,
    executed_by="iat_core",
    rollback_reason="",
):
    if not rollback_id and not adaptation_id:
        return {
            "status": "error",
            "message": "rollback_id_or_adaptation_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    if rollback_id:
        cur.execute(f"""
        SELECT *
        FROM protocol_rollbacks
        WHERE rollback_id = {p}
        """, (rollback_id,))
    else:
        cur.execute(f"""
        SELECT *
        FROM protocol_rollbacks
        WHERE adaptation_id = {p}
          AND status = 'available'
        ORDER BY created_at DESC
        LIMIT 1
        """, (adaptation_id,))

    rollback = cur.fetchone()

    if not rollback:
        release_conn(conn)
        return {
            "status": "not_found",
            "message": "rollback_not_found",
            "rollback_id": rollback_id,
            "adaptation_id": adaptation_id,
        }

    rb_status = row_get(rollback, "status", "available")

    if rb_status != "available":
        release_conn(conn)
        return {
            "status": "error",
            "message": "rollback_not_available",
            "current_status": rb_status,
        }

    rollback_id = row_get(rollback, "rollback_id")
    adaptation_id = row_get(rollback, "adaptation_id")
    rollback_type = row_get(rollback, "rollback_type")
    scope = row_get(rollback, "scope")
    subject_id = row_get(rollback, "subject_id")

    review_evaluation = evaluate_protocol_rollback_reviews_db(
        rollback_id=rollback_id,
        adaptation_id=adaptation_id,
    )

    readiness = review_evaluation.get("readiness")

    if readiness != "ready_for_rollback":
        release_conn(conn)
        return {
            "status": "error",
            "message": "rollback_not_ready_for_execution",
            "rollback_id": rollback_id,
            "adaptation_id": adaptation_id,
            "review_evaluation": review_evaluation,
        }

    if rollback_type != "seller_exposure_limit_adjustment":
        release_conn(conn)
        return {
            "status": "error",
            "message": "rollback_type_not_allowed_in_v1",
            "rollback_type": rollback_type,
        }

    try:
        pre_snapshot = json.loads(row_get(rollback, "pre_change_snapshot") or "{}")
    except Exception:
        pre_snapshot = {}

    agents_snapshot = pre_snapshot.get("agents", [])

    if scope != "seller" or not subject_id:
        release_conn(conn)
        return {
            "status": "error",
            "message": "seller_scope_and_subject_required",
            "scope": scope,
            "subject_id": subject_id,
        }

    if not agents_snapshot:
        release_conn(conn)
        return {
            "status": "error",
            "message": "empty_pre_change_snapshot",
        }

    restored_agents = []

    for item in agents_snapshot:
        agent_id = item.get("agent_id")
        old_max_order_value = item.get("max_order_value")

        if not agent_id:
            continue

        cur.execute(f"""
        UPDATE agents
        SET max_order_value = {p},
            updated_at = {p}
        WHERE agent_id = {p}
          AND seller_id = {p}
        """, (
            old_max_order_value,
            now,
            agent_id,
            subject_id,
        ))

        if cur.rowcount:
            restored_agents.append({
                "agent_id": agent_id,
                "restored_max_order_value": old_max_order_value,
            })

    try:
        metadata = json.loads(row_get(rollback, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["executed_by"] = executed_by
    metadata["execution_reason"] = rollback_reason
    metadata["restored_agents"] = restored_agents
    metadata["rollback_independent_from_intelligence"] = True
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_rollbacks
    SET status = 'executed',
        executed_at = {p},
        executed_by = {p},
        updated_at = {p},
        metadata = {p}
    WHERE rollback_id = {p}
    """, (
        now,
        executed_by,
        now,
        json.dumps(metadata, sort_keys=True),
        rollback_id,
    ))

    cur.execute(f"""
    UPDATE protocol_adaptations
    SET status = 'rolled_back',
        updated_at = {p}
    WHERE adaptation_id = {p}
      AND status = 'applied'
    """, (
        now,
        adaptation_id,
    ))

    return {
        "status": "executed",
        "rollback_id": rollback_id,
        "adaptation_id": adaptation_id,
        "rollback_type": rollback_type,
        "scope": scope,
        "subject_id": subject_id,
        "restored_agents": restored_agents,
        "policy": {
            "rollback_authority": "foundation_or_core_only",
            "rollback_independent_from_intelligence": True,
            "protocol_core_sovereignty_reserved": True,
            "v1_allowlist_only": True,
        },
    }



def init_protocol_adaptations_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptations (
            adaptation_id SERIAL PRIMARY KEY,

            experiment_id INTEGER,
            hypothesis_id INTEGER,

            adaptation_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            recommendation TEXT NOT NULL,
            rationale TEXT,

            proposed_change TEXT DEFAULT '{}',
            expected_impact TEXT DEFAULT '{}',
            safety_constraints TEXT DEFAULT '{}',

            status TEXT DEFAULT 'proposed',

            confidence REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,
            impact_score REAL DEFAULT 0,

            proposed_at INTEGER NOT NULL,
            approved_at INTEGER,
            rejected_at INTEGER,
            applied_at INTEGER,
            failed_at INTEGER,

            approved_by TEXT,
            rejected_by TEXT,
            applied_by TEXT,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_adaptations (
            adaptation_id INTEGER PRIMARY KEY AUTOINCREMENT,

            experiment_id INTEGER,
            hypothesis_id INTEGER,

            adaptation_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            recommendation TEXT NOT NULL,
            rationale TEXT,

            proposed_change TEXT DEFAULT '{}',
            expected_impact TEXT DEFAULT '{}',
            safety_constraints TEXT DEFAULT '{}',

            status TEXT DEFAULT 'proposed',

            confidence REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,
            impact_score REAL DEFAULT 0,

            proposed_at INTEGER NOT NULL,
            approved_at INTEGER,
            rejected_at INTEGER,
            applied_at INTEGER,
            failed_at INTEGER,

            approved_by TEXT,
            rejected_by TEXT,
            applied_by TEXT,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_adaptations_lookup
    ON protocol_adaptations(
        adaptation_type,
        scope,
        status
    )
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_adaptations_subject
    ON protocol_adaptations(
        scope,
        subject_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)




def store_protocol_adaptation_db(
    adaptation_type,
    scope,
    recommendation,
    subject_id=None,
    experiment_id=None,
    hypothesis_id=None,
    rationale=None,
    proposed_change=None,
    expected_impact=None,
    safety_constraints=None,
    confidence=0.5,
    risk_score=0.0,
    impact_score=0.5,
    metadata=None,
):
    if not adaptation_type or not scope or not recommendation:
        return {
            "status": "error",
            "message": "adaptation_type_scope_and_recommendation_required",
        }

    confidence = float(confidence or 0)
    risk_score = float(risk_score or 0)
    impact_score = float(impact_score or 0)

    if confidence < 0.45:
        return {
            "status": "ignored",
            "reason": "adaptation_confidence_too_low",
            "confidence": confidence,
        }

    if risk_score > 0.75:
        return {
            "status": "ignored",
            "reason": "adaptation_risk_too_high",
            "risk_score": risk_score,
        }

    now = int(time.time())

    metadata = metadata or {}
    metadata = {
        **metadata,
        "adaptation_can_propose": True,
        "adaptation_can_govern": False,
        "adaptation_requires_approval": True,
        "protocol_core_sovereignty_reserved": True,
    }

    proposed_change = proposed_change or {}
    expected_impact = expected_impact or {}
    safety_constraints = safety_constraints or {}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_adaptations (
        experiment_id,
        hypothesis_id,
        adaptation_type,
        scope,
        subject_id,
        recommendation,
        rationale,
        proposed_change,
        expected_impact,
        safety_constraints,
        status,
        confidence,
        risk_score,
        impact_score,
        proposed_at,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        experiment_id,
        hypothesis_id,
        adaptation_type,
        scope,
        subject_id,
        recommendation,
        rationale,
        json.dumps(proposed_change, sort_keys=True),
        json.dumps(expected_impact, sort_keys=True),
        json.dumps(safety_constraints, sort_keys=True),
        "proposed",
        round(confidence, 4),
        round(risk_score, 4),
        round(impact_score, 4),
        now,
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    adaptation_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "adaptation_id": adaptation_id,
        "adaptation_type": adaptation_type,
        "scope": scope,
        "subject_id": subject_id,
        "policy": {
            "adaptation_can_propose": True,
            "adaptation_can_govern": False,
            "adaptation_requires_approval": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }


def get_protocol_adaptations_db(
    adaptation_type=None,
    scope=None,
    subject_id=None,
    status=None,
    experiment_id=None,
    hypothesis_id=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if adaptation_type:
        where.append(f"adaptation_type = {p}")
        params.append(adaptation_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    if experiment_id is not None:
        where.append(f"experiment_id = {p}")
        params.append(experiment_id)

    if hypothesis_id is not None:
        where.append(f"hypothesis_id = {p}")
        params.append(hypothesis_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptations
    {where_sql}
    ORDER BY
        impact_score DESC,
        confidence DESC,
        risk_score ASC,
        updated_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "adaptations": rows,
    }


def approve_protocol_adaptation_db(
    adaptation_id,
    approved_by="iat_core",
    approval_note="",
):
    if not adaptation_id:
        return {
            "status": "error",
            "message": "adaptation_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptations
    WHERE adaptation_id = {p}
    """, (adaptation_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "adaptation_id": adaptation_id,
        }

    review_evaluation = evaluate_protocol_adaptation_reviews_db(
        adaptation_id
    )

    readiness = review_evaluation.get("readiness")

    if readiness != "ready_for_approval":
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_not_ready_for_approval",
            "adaptation_id": adaptation_id,
            "review_evaluation": review_evaluation,
        }

    current_status = row_get(row, "status", "proposed")

    if current_status != "proposed":
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_not_approvable",
            "current_status": current_status,
        }

    confidence = float(row_get(row, "confidence", 0) or 0)
    risk_score = float(row_get(row, "risk_score", 0) or 0)

    if confidence < 0.60:
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_confidence_too_low_for_approval",
            "confidence": confidence,
        }

    if risk_score > 0.60:
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_risk_too_high_for_approval",
            "risk_score": risk_score,
        }

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["approval_note"] = approval_note
    metadata["approved_by_foundation_or_core"] = True
    metadata["adaptation_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_adaptations
    SET status = 'approved',
        approved_at = {p},
        approved_by = {p},
        updated_at = {p},
        metadata = {p}
    WHERE adaptation_id = {p}
    """, (
        now,
        approved_by,
        now,
        json.dumps(metadata, sort_keys=True),
        adaptation_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "approved",
        "adaptation_id": adaptation_id,
        "approved_by": approved_by,
        "policy": {
            "adaptation_can_propose": True,
            "adaptation_can_govern": False,
            "protocol_core_sovereignty_reserved": True,
        },
    }


def reject_protocol_adaptation_db(
    adaptation_id,
    rejected_by="iat_core",
    rejection_reason="",
):
    if not adaptation_id:
        return {
            "status": "error",
            "message": "adaptation_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptations
    WHERE adaptation_id = {p}
    """, (adaptation_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "adaptation_id": adaptation_id,
        }

    current_status = row_get(row, "status", "proposed")

    if current_status not in ("proposed", "approved"):
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_not_rejectable",
            "current_status": current_status,
        }

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["rejection_reason"] = rejection_reason
    metadata["rejected_by_foundation_or_core"] = True
    metadata["adaptation_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_adaptations
    SET status = 'rejected',
        rejected_at = {p},
        rejected_by = {p},
        updated_at = {p},
        metadata = {p}
    WHERE adaptation_id = {p}
    """, (
        now,
        rejected_by,
        now,
        json.dumps(metadata, sort_keys=True),
        adaptation_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "rejected",
        "adaptation_id": adaptation_id,
        "rejected_by": rejected_by,
        "reason": rejection_reason,
    }




def apply_protocol_adaptation_db(
    adaptation_id,
    applied_by="iat_core",
    apply_note="",
):
    if not adaptation_id:
        return {
            "status": "error",
            "message": "adaptation_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_adaptations
    WHERE adaptation_id = {p}
    """, (adaptation_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "adaptation_id": adaptation_id,
        }

    current_status = row_get(row, "status", "proposed")

    if current_status != "approved":
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_not_approved",
            "current_status": current_status,
        }

    adaptation_type = row_get(row, "adaptation_type")
    scope = row_get(row, "scope")
    subject_id = row_get(row, "subject_id")
    risk_score = float(row_get(row, "risk_score", 0) or 0)

    if risk_score > 0.60:
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_risk_too_high_to_apply",
            "risk_score": risk_score,
        }

    if adaptation_type != "seller_exposure_limit_adjustment":
        release_conn(conn)
        return {
            "status": "error",
            "message": "adaptation_type_not_allowed_in_v1",
            "adaptation_type": adaptation_type,
        }

    if scope != "seller" or not subject_id:
        release_conn(conn)
        return {
            "status": "error",
            "message": "seller_scope_and_subject_required",
            "scope": scope,
            "subject_id": subject_id,
        }

    try:
        proposed_change = json.loads(row_get(row, "proposed_change") or "{}")
    except Exception:
        proposed_change = {}

    try:
        safety_constraints = json.loads(row_get(row, "safety_constraints") or "{}")
    except Exception:
        safety_constraints = {}

    field = proposed_change.get("field")
    operation = proposed_change.get("operation")
    factor = float(proposed_change.get("factor", 1) or 1)

    max_increment_percent = float(
        safety_constraints.get("max_increment_percent", 0) or 0
    )
    rollback_on_failure = bool(
        safety_constraints.get("rollback_on_failure", False)
    )

    if field != "max_order_value":
        release_conn(conn)
        return {
            "status": "error",
            "message": "field_not_allowed_in_v1",
            "field": field,
        }

    if operation != "multiply":
        release_conn(conn)
        return {
            "status": "error",
            "message": "operation_not_allowed_in_v1",
            "operation": operation,
        }

    if factor <= 1 or factor > 1.25:
        release_conn(conn)
        return {
            "status": "error",
            "message": "factor_outside_allowed_range",
            "factor": factor,
            "allowed_max": 1.25,
        }

    if max_increment_percent <= 0 or max_increment_percent > 25:
        release_conn(conn)
        return {
            "status": "error",
            "message": "max_increment_percent_outside_allowed_range",
            "max_increment_percent": max_increment_percent,
            "allowed_max": 25,
        }

    if not rollback_on_failure:
        release_conn(conn)
        return {
            "status": "error",
            "message": "rollback_on_failure_required",
        }

    # V1 target: agents table, seller_id column.
    cur.execute(f"""
    SELECT *
    FROM agents
    WHERE seller_id = {p}
    """, (subject_id,))

    agents = cur.fetchall()

    if not agents:
        release_conn(conn)
        return {
            "status": "error",
            "message": "no_agents_found_for_seller",
            "seller_id": subject_id,
        }

    pre_change_agents = []
    post_change_agents = []
    updated_agents = []

    for agent in agents:
        agent_id = row_get(agent, "agent_id")
        old_value = float(row_get(agent, "max_order_value", 0) or 0)
        new_value = round(old_value * factor, 4)

        pre_change_agents.append({
            "agent_id": agent_id,
            "seller_id": subject_id,
            "max_order_value": old_value,
        })

        post_change_agents.append({
            "agent_id": agent_id,
            "seller_id": subject_id,
            "max_order_value": new_value,
        })

        cur.execute(f"""
        UPDATE agents
        SET max_order_value = {p},
            updated_at = {p}
        WHERE agent_id = {p}
        """, (
            new_value,
            now,
            agent_id,
        ))

        updated_agents.append({
            "agent_id": agent_id,
            "old_max_order_value": old_value,
            "new_max_order_value": new_value,
        })

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["apply_note"] = apply_note
    metadata["applied_change"] = {
        "field": field,
        "operation": operation,
        "factor": factor,
        "updated_agents": updated_agents,
    }
    metadata["rollback_on_failure"] = rollback_on_failure
    metadata["adaptation_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_adaptations
    SET status = 'applied',
        applied_at = {p},
        applied_by = {p},
        updated_at = {p},
        metadata = {p}
    WHERE adaptation_id = {p}
    """, (
        now,
        applied_by,
        now,
        json.dumps(metadata, sort_keys=True),
        adaptation_id,
    ))

    conn.commit()
    release_conn(conn)

    rollback_result = None
    try:
        rollback_result = store_protocol_rollback_db(
            adaptation_id=adaptation_id,
            scope=scope,
            subject_id=subject_id,
            rollback_type=adaptation_type,
            rollback_reason="auto_snapshot_before_adaptation_apply",
            pre_change_snapshot={
                "agents": pre_change_agents,
            },
            post_change_snapshot={
                "agents": post_change_agents,
            },
            metadata={
                "created_by": "apply_protocol_adaptation_db",
                "applied_by": applied_by,
                "rollback_on_failure": rollback_on_failure,
                "field": field,
                "operation": operation,
                "factor": factor,
            },
        )
    except Exception as exc:
        rollback_result = {
            "status": "error",
            "message": "rollback_snapshot_store_failed",
            "error": str(exc),
        }

    return {
        "status": "applied",
        "adaptation_id": adaptation_id,
        "adaptation_type": adaptation_type,
        "scope": scope,
        "subject_id": subject_id,
        "updated_agents": updated_agents,
        "rollback_result": rollback_result,
        "policy": {
            "adaptation_can_propose": True,
            "adaptation_can_govern": False,
            "adaptation_required_approval": True,
            "protocol_core_sovereignty_reserved": True,
            "v1_allowlist_only": True,
        },
    }



def init_protocol_experiments_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_experiments (
            experiment_id SERIAL PRIMARY KEY,

            hypothesis_id INTEGER,
            experiment_type TEXT NOT NULL,

            scope TEXT NOT NULL,
            subject_id TEXT,

            objective TEXT NOT NULL,

            status TEXT DEFAULT 'planned',

            success_metric TEXT,
            target_value REAL,

            measured_value REAL,

            confidence_before REAL DEFAULT 0,
            confidence_after REAL DEFAULT 0,

            started_at INTEGER,
            completed_at INTEGER,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_experiments (
            experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,

            hypothesis_id INTEGER,
            experiment_type TEXT NOT NULL,

            scope TEXT NOT NULL,
            subject_id TEXT,

            objective TEXT NOT NULL,

            status TEXT DEFAULT 'planned',

            success_metric TEXT,
            target_value REAL,

            measured_value REAL,

            confidence_before REAL DEFAULT 0,
            confidence_after REAL DEFAULT 0,

            started_at INTEGER,
            completed_at INTEGER,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_experiments_lookup
    ON protocol_experiments(
        experiment_type,
        scope,
        status
    )
    """)

    conn.commit()
    release_conn(conn)




def store_protocol_experiment_db(
    experiment_type,
    scope,
    objective,
    hypothesis_id=None,
    subject_id=None,
    success_metric=None,
    target_value=None,
    confidence_before=0,
    metadata=None,
):
    if not experiment_type or not scope or not objective:
        return {
            "status": "error",
            "message": "experiment_type_scope_and_objective_required",
        }

    now = int(time.time())
    metadata = metadata or {}

    metadata = {
        **metadata,
        "experiment_can_test": True,
        "experiment_can_govern": False,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO protocol_experiments (
        hypothesis_id,
        experiment_type,
        scope,
        subject_id,
        objective,
        status,
        success_metric,
        target_value,
        confidence_before,
        confidence_after,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        hypothesis_id,
        experiment_type,
        scope,
        subject_id,
        objective,
        "planned",
        success_metric,
        target_value,
        round(float(confidence_before or 0), 4),
        round(float(confidence_before or 0), 4),
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    experiment_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "experiment_id": experiment_id,
        "experiment_type": experiment_type,
        "scope": scope,
        "subject_id": subject_id,
        "hypothesis_id": hypothesis_id,
    }


def get_protocol_experiments_db(
    experiment_type=None,
    scope=None,
    subject_id=None,
    status=None,
    hypothesis_id=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if experiment_type:
        where.append(f"experiment_type = {p}")
        params.append(experiment_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    if hypothesis_id is not None:
        where.append(f"hypothesis_id = {p}")
        params.append(hypothesis_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_experiments
    {where_sql}
    ORDER BY updated_at DESC, created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "experiments": rows,
    }


def start_protocol_experiment_db(experiment_id, note=""):
    if not experiment_id:
        return {
            "status": "error",
            "message": "experiment_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_experiments
    WHERE experiment_id = {p}
    """, (experiment_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "experiment_id": experiment_id,
        }

    current_status = row_get(row, "status", "planned")

    if current_status not in ("planned", "paused"):
        release_conn(conn)
        return {
            "status": "error",
            "message": "experiment_not_startable",
            "current_status": current_status,
        }

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["start_note"] = note
    metadata["experiment_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_experiments
    SET status = 'running',
        started_at = COALESCE(started_at, {p}),
        updated_at = {p},
        metadata = {p}
    WHERE experiment_id = {p}
    """, (
        now,
        now,
        json.dumps(metadata, sort_keys=True),
        experiment_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "started",
        "experiment_id": experiment_id,
        "started_at": now,
        "policy": {
            "experiment_can_test": True,
            "experiment_can_govern": False,
            "protocol_core_sovereignty_reserved": True,
        },
    }


def complete_protocol_experiment_db(
    experiment_id,
    measured_value,
    success=None,
    note="",
):
    if not experiment_id:
        return {
            "status": "error",
            "message": "experiment_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_experiments
    WHERE experiment_id = {p}
    """, (experiment_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "experiment_id": experiment_id,
        }

    current_status = row_get(row, "status", "planned")

    if current_status not in ("running", "planned"):
        release_conn(conn)
        return {
            "status": "error",
            "message": "experiment_not_completable",
            "current_status": current_status,
        }

    target_value = row_get(row, "target_value")
    confidence_before = float(row_get(row, "confidence_before", 0) or 0)
    measured_value = float(measured_value or 0)

    if success is None:
        if target_value is None:
            success = measured_value > 0
        else:
            success = measured_value >= float(target_value)

    confidence_after = confidence_before

    if success:
        confidence_after = min(1.0, confidence_before + 0.10)
        status = "succeeded"
    else:
        confidence_after = max(0.0, confidence_before - 0.12)
        status = "failed"

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["completion_note"] = note
    metadata["experiment_success"] = bool(success)
    metadata["experiment_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_experiments
    SET status = {p},
        measured_value = {p},
        confidence_after = {p},
        completed_at = {p},
        updated_at = {p},
        metadata = {p}
    WHERE experiment_id = {p}
    """, (
        status,
        round(measured_value, 4),
        round(confidence_after, 4),
        now,
        now,
        json.dumps(metadata, sort_keys=True),
        experiment_id,
    ))

    conn.commit()
    release_conn(conn)

    hypothesis_id = row_get(row, "hypothesis_id")

    hypothesis_update = None

    if hypothesis_id:
        try:
            hypothesis_update = evaluate_protocol_hypothesis_db(
                hypothesis_id=hypothesis_id,
                observed_success=bool(success),
                evaluation_note=note or f"experiment_{status}",
            )
        except Exception as exc:
            hypothesis_update = {
                "status": "error",
                "message": "hypothesis_update_failed",
                "error": str(exc),
            }

    return {
        "status": "completed",
        "experiment_id": experiment_id,
        "experiment_status": status,
        "measured_value": round(measured_value, 4),
        "target_value": target_value,
        "success": bool(success),
        "confidence_before": round(confidence_before, 4),
        "confidence_after": round(confidence_after, 4),
        "hypothesis_update": hypothesis_update,
        "policy": {
            "experiment_can_test": True,
            "experiment_can_govern": False,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def init_protocol_hypotheses_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_hypotheses (
            hypothesis_id SERIAL PRIMARY KEY,

            hypothesis_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            hypothesis TEXT NOT NULL,
            rationale TEXT,

            confidence REAL DEFAULT 0,
            importance_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'proposed',

            evaluation_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_hypotheses (
            hypothesis_id INTEGER PRIMARY KEY AUTOINCREMENT,

            hypothesis_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            hypothesis TEXT NOT NULL,
            rationale TEXT,

            confidence REAL DEFAULT 0,
            importance_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'proposed',

            evaluation_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_hypotheses_lookup
    ON protocol_hypotheses(
        hypothesis_type,
        scope,
        status
    )
    """)

    conn.commit()
    release_conn(conn)




def store_protocol_hypothesis_db(
    hypothesis_type,
    scope,
    hypothesis,
    subject_id=None,
    rationale=None,
    confidence=0.5,
    importance_score=0.5,
    metadata=None,
):
    if not hypothesis_type or not scope or not hypothesis:
        return {
            "status": "error",
            "message": "hypothesis_type_scope_and_hypothesis_required",
        }

    confidence = float(confidence or 0)
    importance_score = float(importance_score or 0.5)

    if confidence < 0.35:
        return {
            "status": "ignored",
            "reason": "hypothesis_confidence_too_low",
            "confidence": confidence,
        }

    now = int(time.time())
    metadata = metadata or {}

    metadata = {
        **metadata,
        "intelligence_layer": True,
        "hypothesis_can_propose": True,
        "hypothesis_can_govern": False,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM protocol_hypotheses
    WHERE hypothesis_type = {p}
      AND scope = {p}
      AND COALESCE(subject_id, '') = COALESCE({p}, '')
      AND hypothesis = {p}
      AND status IN ('proposed', 'testing', 'validated')
    LIMIT 1
    """, (
        hypothesis_type,
        scope,
        subject_id,
        hypothesis,
    ))

    existing = cur.fetchone()

    if existing:
        hypothesis_id = row_get(existing, "hypothesis_id")
        old_confidence = float(row_get(existing, "confidence", 0) or 0)
        old_importance = float(row_get(existing, "importance_score", 0.5) or 0.5)

        new_confidence = min(1.0, max(old_confidence, confidence) + 0.02)
        new_importance = min(1.0, max(old_importance, importance_score))

        cur.execute(f"""
        UPDATE protocol_hypotheses
        SET confidence = {p},
            importance_score = {p},
            rationale = COALESCE({p}, rationale),
            metadata = {p},
            updated_at = {p}
        WHERE hypothesis_id = {p}
        """, (
            round(new_confidence, 4),
            round(new_importance, 4),
            rationale,
            json.dumps(metadata, sort_keys=True),
            now,
            hypothesis_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "updated",
            "hypothesis_id": hypothesis_id,
            "confidence": round(new_confidence, 4),
            "importance_score": round(new_importance, 4),
        }

    cur.execute(f"""
    INSERT INTO protocol_hypotheses (
        hypothesis_type,
        scope,
        subject_id,
        hypothesis,
        rationale,
        confidence,
        importance_score,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        hypothesis_type,
        scope,
        subject_id,
        hypothesis,
        rationale,
        round(confidence, 4),
        round(importance_score, 4),
        "proposed",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    hypothesis_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "hypothesis_id": hypothesis_id,
        "hypothesis_type": hypothesis_type,
        "scope": scope,
        "subject_id": subject_id,
    }


def get_protocol_hypotheses_db(
    hypothesis_type=None,
    scope=None,
    subject_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if hypothesis_type:
        where.append(f"hypothesis_type = {p}")
        params.append(hypothesis_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_hypotheses
    {where_sql}
    ORDER BY
        importance_score DESC,
        confidence DESC,
        updated_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "hypotheses": rows,
    }


def evaluate_protocol_hypothesis_db(
    hypothesis_id,
    observed_success=True,
    evaluation_note="",
):
    if not hypothesis_id:
        return {
            "status": "error",
            "message": "hypothesis_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_hypotheses
    WHERE hypothesis_id = {p}
    """, (hypothesis_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "hypothesis_id": hypothesis_id,
        }

    confidence = float(row_get(row, "confidence", 0) or 0)
    importance = float(row_get(row, "importance_score", 0.5) or 0.5)
    evaluation_count = int(row_get(row, "evaluation_count", 0) or 0)
    success_count = int(row_get(row, "success_count", 0) or 0)
    failure_count = int(row_get(row, "failure_count", 0) or 0)

    evaluation_count += 1

    if observed_success:
        success_count += 1
        confidence = min(1.0, confidence + 0.08)
        importance = min(1.0, importance + 0.03)
    else:
        failure_count += 1
        confidence = max(0.0, confidence - 0.10)
        importance = max(0.0, importance - 0.04)

    success_rate = success_count / evaluation_count if evaluation_count else 0

    status = row_get(row, "status", "proposed")

    if evaluation_count >= 3 and success_rate >= 0.75 and confidence >= 0.75:
        status = "validated"
    elif evaluation_count >= 3 and success_rate <= 0.34:
        status = "rejected"
    elif evaluation_count >= 1:
        status = "testing"

    try:
        metadata = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        metadata = {}

    metadata["last_evaluation_note"] = evaluation_note
    metadata["last_observed_success"] = bool(observed_success)
    metadata["hypothesis_can_govern"] = False
    metadata["protocol_core_sovereignty_reserved"] = True

    cur.execute(f"""
    UPDATE protocol_hypotheses
    SET confidence = {p},
        importance_score = {p},
        evaluation_count = {p},
        success_count = {p},
        failure_count = {p},
        status = {p},
        updated_at = {p},
        metadata = {p}
    WHERE hypothesis_id = {p}
    """, (
        round(confidence, 4),
        round(importance, 4),
        evaluation_count,
        success_count,
        failure_count,
        status,
        now,
        json.dumps(metadata, sort_keys=True),
        hypothesis_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "evaluated",
        "hypothesis_id": hypothesis_id,
        "hypothesis_status": status,
        "observed_success": bool(observed_success),
        "confidence": round(confidence, 4),
        "importance_score": round(importance, 4),
        "evaluation_count": evaluation_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_rate, 4),
        "policy": {
            "hypothesis_can_propose": True,
            "hypothesis_can_govern": False,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def init_protocol_knowledge_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_knowledge (
            knowledge_id SERIAL PRIMARY KEY,

            knowledge_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            source_memory_id INTEGER,
            confidence REAL DEFAULT 0,
            knowledge_strength REAL DEFAULT 0.5,
            stability_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'active',

            knowledge_payload TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            archived_at INTEGER
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_knowledge (
            knowledge_id INTEGER PRIMARY KEY AUTOINCREMENT,

            knowledge_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            source_memory_id INTEGER,
            confidence REAL DEFAULT 0,
            knowledge_strength REAL DEFAULT 0.5,
            stability_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'active',

            knowledge_payload TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            archived_at INTEGER
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_knowledge_lookup
    ON protocol_knowledge(knowledge_type, scope, subject_id, status)
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_knowledge_strength
    ON protocol_knowledge(status, confidence, knowledge_strength, stability_score)
    """)

    conn.commit()
    release_conn(conn)




def store_protocol_knowledge_db(
    knowledge_type,
    scope,
    subject_id=None,
    source_memory_id=None,
    confidence=0.8,
    knowledge_strength=0.75,
    stability_score=0.75,
    knowledge_payload=None,
    tags=None,
    metadata=None,
):
    if not knowledge_type or not scope:
        return {
            "status": "error",
            "message": "knowledge_type_and_scope_required",
        }

    confidence = float(confidence or 0)
    knowledge_strength = float(knowledge_strength or 0)
    stability_score = float(stability_score or 0)

    if confidence < 0.75 or knowledge_strength < 0.65 or stability_score < 0.65:
        return {
            "status": "ignored",
            "reason": "knowledge_threshold_not_met",
            "confidence": confidence,
            "knowledge_strength": knowledge_strength,
            "stability_score": stability_score,
        }

    now = int(time.time())
    knowledge_payload = knowledge_payload or {}
    metadata = metadata or {}
    normalized_tags = _normalize_protocol_memory_tags(tags)

    metadata = {
        **metadata,
        "protocol_core_sovereignty_reserved": True,
        "knowledge_guides_protocol": True,
        "knowledge_governs_protocol": False,
    }

    payload_json = json.dumps(knowledge_payload, sort_keys=True)
    tags_json = json.dumps(normalized_tags, sort_keys=True)
    metadata_json = json.dumps(metadata, sort_keys=True)

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM protocol_knowledge
    WHERE knowledge_type = {p}
      AND scope = {p}
      AND COALESCE(subject_id, '') = COALESCE({p}, '')
      AND knowledge_payload = {p}
      AND status = 'active'
    LIMIT 1
    """, (
        knowledge_type,
        scope,
        subject_id,
        payload_json,
    ))

    existing = cur.fetchone()

    if existing:
        knowledge_id = row_get(existing, "knowledge_id")
        old_confidence = float(row_get(existing, "confidence", 0) or 0)
        old_strength = float(row_get(existing, "knowledge_strength", 0.5) or 0.5)
        old_stability = float(row_get(existing, "stability_score", 0.5) or 0.5)

        new_confidence = min(1.0, max(old_confidence, confidence) + 0.02)
        new_strength = min(1.0, max(old_strength, knowledge_strength) + 0.03)
        new_stability = min(1.0, max(old_stability, stability_score) + 0.03)

        cur.execute(f"""
        UPDATE protocol_knowledge
        SET confidence = {p},
            knowledge_strength = {p},
            stability_score = {p},
            tags = {p},
            metadata = {p},
            updated_at = {p}
        WHERE knowledge_id = {p}
        """, (
            round(new_confidence, 4),
            round(new_strength, 4),
            round(new_stability, 4),
            tags_json,
            metadata_json,
            now,
            knowledge_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "updated",
            "knowledge_id": knowledge_id,
            "confidence": round(new_confidence, 4),
            "knowledge_strength": round(new_strength, 4),
            "stability_score": round(new_stability, 4),
        }

    cur.execute(f"""
    INSERT INTO protocol_knowledge (
        knowledge_type,
        scope,
        subject_id,
        source_memory_id,
        confidence,
        knowledge_strength,
        stability_score,
        status,
        knowledge_payload,
        tags,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        knowledge_type,
        scope,
        subject_id,
        source_memory_id,
        round(confidence, 4),
        round(knowledge_strength, 4),
        round(stability_score, 4),
        "active",
        payload_json,
        tags_json,
        metadata_json,
        now,
        now,
    ))

    knowledge_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "knowledge_id": knowledge_id,
        "knowledge_type": knowledge_type,
        "scope": scope,
        "subject_id": subject_id,
    }


def get_protocol_knowledge_db(
    knowledge_type=None,
    scope=None,
    subject_id=None,
    status="active",
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if status:
        where.append(f"status = {p}")
        params.append(status)

    if knowledge_type:
        where.append(f"knowledge_type = {p}")
        params.append(knowledge_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_knowledge
    {where_sql}
    ORDER BY
        stability_score DESC,
        confidence DESC,
        knowledge_strength DESC,
        updated_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "knowledge": rows,
    }


def promote_memory_to_knowledge_db(memory_id, force=False):
    if not memory_id:
        return {
            "status": "error",
            "message": "memory_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    WHERE memory_id = {p}
      AND status = 'active'
    """, (memory_id,))

    memory = cur.fetchone()
    release_conn(conn)

    if not memory:
        return {
            "status": "error",
            "message": "active_memory_not_found",
            "memory_id": memory_id,
        }

    m = dict(memory)

    confidence = float(m.get("confidence", 0) or 0)
    memory_strength = float(m.get("memory_strength", 0) or 0)
    importance_score = float(m.get("importance_score", 0) or 0)
    times_observed = int(m.get("times_observed", 0) or 0)
    times_false_positive = int(m.get("times_false_positive", 0) or 0)

    eligible = (
        confidence >= 0.80
        and memory_strength >= 0.75
        and importance_score >= 0.75
        and times_observed >= 2
        and times_false_positive == 0
    )

    if not eligible and not force:
        return {
            "status": "ignored",
            "reason": "memory_not_eligible_for_knowledge",
            "memory_id": memory_id,
            "requirements": {
                "confidence_min": 0.80,
                "memory_strength_min": 0.75,
                "importance_score_min": 0.75,
                "times_observed_min": 2,
                "times_false_positive_required": 0,
            },
            "actual": {
                "confidence": confidence,
                "memory_strength": memory_strength,
                "importance_score": importance_score,
                "times_observed": times_observed,
                "times_false_positive": times_false_positive,
            },
        }

    try:
        payload = json.loads(m.get("memory_payload") or "{}")
    except Exception:
        payload = {"raw_memory_payload": m.get("memory_payload")}

    try:
        tags = json.loads(m.get("tags") or "[]")
    except Exception:
        tags = []

    return store_protocol_knowledge_db(
        knowledge_type=str(m.get("memory_type") or "protocol_memory").replace("_memory", "_knowledge"),
        scope=m.get("scope"),
        subject_id=m.get("subject_id"),
        source_memory_id=memory_id,
        confidence=max(confidence, 0.80 if force else confidence),
        knowledge_strength=max(memory_strength, 0.75 if force else memory_strength),
        stability_score=max(importance_score, 0.75 if force else importance_score),
        knowledge_payload={
            "source_memory_type": m.get("memory_type"),
            "source_memory_id": memory_id,
            "promoted_payload": payload,
        },
        tags=list(set(tags + ["knowledge", "promoted_from_memory"])),
        metadata={
            "promotion_force_used": bool(force),
            "protocol_core_sovereignty_reserved": True,
            "knowledge_guides_protocol": True,
            "knowledge_governs_protocol": False,
        },
    )


def build_protocol_knowledge_context_db(limit=100):
    knowledge_result = get_protocol_knowledge_db(
        status="active",
        limit=limit,
    )

    knowledge = knowledge_result.get("knowledge", [])

    by_type = {}
    high_stability = []

    for item in knowledge:
        knowledge_type = item.get("knowledge_type")
        by_type.setdefault(knowledge_type, 0)
        by_type[knowledge_type] += 1

        stability = float(item.get("stability_score", 0) or 0)
        confidence = float(item.get("confidence", 0) or 0)
        strength = float(item.get("knowledge_strength", 0) or 0)

        if stability >= 0.75 and confidence >= 0.75 and strength >= 0.65:
            high_stability.append(item)

    context = {
        "context_type": "protocol_knowledge_context",
        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "knowledge_authority": "advisory_guidance_only",
        "seller_authority": False,
        "buyer_authority": False,

        "knowledge_summary": {
            "total_active_knowledge": len(knowledge),
            "knowledge_count_by_type": by_type,
            "high_stability_count": len(high_stability),
        },

        "high_stability_knowledge": high_stability[:25],

        "protocol_policy": {
            "knowledge_guides_protocol": True,
            "knowledge_governs_protocol": False,
            "protocol_core_sovereignty_reserved": True,
            "foundation_agents_remain_protocol_authority": True,
        },
    }

    return {
        "status": "ok",
        "knowledge_context": context,
    }



def init_protocol_memory_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_memory (
            memory_id SERIAL PRIMARY KEY,

            memory_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            source_type TEXT DEFAULT 'protocol',
            source_id TEXT,

            confidence REAL DEFAULT 0,
            memory_strength REAL DEFAULT 0.5,
            importance_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'active',

            times_reinforced INTEGER DEFAULT 0,
            times_observed INTEGER DEFAULT 0,
            times_false_positive INTEGER DEFAULT 0,

            last_validated_at INTEGER,
            last_decay_at INTEGER,
            archived_at INTEGER,

            memory_payload TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS protocol_memory (
            memory_id INTEGER PRIMARY KEY AUTOINCREMENT,

            memory_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject_id TEXT,

            source_type TEXT DEFAULT 'protocol',
            source_id TEXT,

            confidence REAL DEFAULT 0,
            memory_strength REAL DEFAULT 0.5,
            importance_score REAL DEFAULT 0.5,

            status TEXT DEFAULT 'active',

            times_reinforced INTEGER DEFAULT 0,
            times_observed INTEGER DEFAULT 0,
            times_false_positive INTEGER DEFAULT 0,

            last_validated_at INTEGER,
            last_decay_at INTEGER,
            archived_at INTEGER,

            memory_payload TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_memory_lookup
    ON protocol_memory(memory_type, scope, subject_id, status)
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_protocol_memory_strength
    ON protocol_memory(status, importance_score, confidence, memory_strength)
    """)

    conn.commit()
    release_conn(conn)


def _normalize_protocol_memory_tags(tags):
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip().lower() for t in tags.split(",") if t.strip()]
    if isinstance(tags, list):
        return [str(t).strip().lower() for t in tags if str(t).strip()]
    return []



def build_protocol_memory_signature_db(
    memory_type,
    scope,
    subject_id=None,
    source_type=None,
    source_id=None,
    memory_payload=None,
    tags=None,
):
    payload = memory_payload or {}
    normalized_tags = _normalize_protocol_memory_tags(tags)

    # Stable semantic-ish signature for deduplication.
    signature_payload = {
        "memory_type": str(memory_type or "").strip().lower(),
        "scope": str(scope or "").strip().lower(),
        "subject_id": str(subject_id or "").strip().lower(),
        "source_type": str(source_type or "").strip().lower(),
        "source_id": str(source_id or "").strip().lower(),
        "payload": payload,
        "tags": normalized_tags,
    }

    raw = json.dumps(signature_payload, sort_keys=True)
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_similar_protocol_memory_db(
    memory_type,
    scope,
    subject_id=None,
    source_type=None,
    source_id=None,
    memory_payload=None,
    tags=None,
):
    signature = build_protocol_memory_signature_db(
        memory_type=memory_type,
        scope=scope,
        subject_id=subject_id,
        source_type=source_type,
        source_id=source_id,
        memory_payload=memory_payload,
        tags=tags,
    )

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    WHERE memory_type = {p}
      AND scope = {p}
      AND COALESCE(subject_id, '') = COALESCE({p}, '')
      AND status = 'active'
    ORDER BY updated_at DESC
    LIMIT 100
    """, (
        memory_type,
        scope,
        subject_id,
    ))

    rows = cur.fetchall()
    release_conn(conn)

    for row in rows:
        row_dict = dict(row)
        try:
            meta = json.loads(row_dict.get("metadata") or "{}")
        except Exception:
            meta = {}

        if meta.get("memory_signature") == signature:
            return {
                "status": "ok",
                "signature": signature,
                "found": True,
                "memory": row_dict,
            }

    return {
        "status": "ok",
        "signature": signature,
        "found": False,
        "memory": None,
    }



def store_protocol_memory_db(
    memory_type,
    scope,
    subject_id=None,
    source_type="protocol",
    source_id=None,
    confidence=0.5,
    importance_score=0.5,
    memory_payload=None,
    tags=None,
    metadata=None,
    min_confidence=0.35,
):
    if not memory_type or not scope:
        return {
            "status": "error",
            "message": "memory_type_and_scope_required",
        }

    confidence = float(confidence or 0)
    importance_score = float(importance_score or 0.5)

    if confidence < float(min_confidence or 0):
        return {
            "status": "ignored",
            "reason": "confidence_below_minimum",
            "confidence": confidence,
            "min_confidence": min_confidence,
        }

    now = int(time.time())
    memory_payload = memory_payload or {}
    metadata = metadata or {}
    normalized_tags = _normalize_protocol_memory_tags(tags)

    signature = build_protocol_memory_signature_db(
        memory_type=memory_type,
        scope=scope,
        subject_id=subject_id,
        source_type=source_type,
        source_id=source_id,
        memory_payload=memory_payload,
        tags=normalized_tags,
    )

    metadata = {
        **metadata,
        "memory_signature": signature,
        "dedup_enabled": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    payload_json = json.dumps(memory_payload, sort_keys=True)
    tags_json = json.dumps(normalized_tags, sort_keys=True)
    metadata_json = json.dumps(metadata, sort_keys=True)

    existing_result = find_similar_protocol_memory_db(
        memory_type=memory_type,
        scope=scope,
        subject_id=subject_id,
        source_type=source_type,
        source_id=source_id,
        memory_payload=memory_payload,
        tags=normalized_tags,
    )

    existing = existing_result.get("memory")

    if existing:
        memory_id = row_get(existing, "memory_id")
        old_confidence = float(row_get(existing, "confidence", 0) or 0)
        old_strength = float(row_get(existing, "memory_strength", 0.5) or 0.5)
        old_importance = float(row_get(existing, "importance_score", 0.5) or 0.5)

        new_confidence = min(1.0, max(old_confidence, confidence) + 0.02)
        new_strength = min(1.0, old_strength + 0.05)
        new_importance = min(1.0, max(old_importance, importance_score))

        cur.execute(f"""
        UPDATE protocol_memory
        SET confidence = {p},
            memory_strength = {p},
            importance_score = {p},
            tags = {p},
            metadata = {p},
            updated_at = {p}
        WHERE memory_id = {p}
        """, (
            round(new_confidence, 4),
            round(new_strength, 4),
            round(new_importance, 4),
            tags_json,
            metadata_json,
            now,
            memory_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "updated",
            "memory_id": memory_id,
            "confidence": round(new_confidence, 4),
            "memory_strength": round(new_strength, 4),
            "importance_score": round(new_importance, 4),
        }

    cur.execute(f"""
    INSERT INTO protocol_memory (
        memory_type,
        scope,
        subject_id,
        source_type,
        source_id,
        confidence,
        memory_strength,
        importance_score,
        status,
        memory_payload,
        tags,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        memory_type,
        scope,
        subject_id,
        source_type,
        source_id,
        round(confidence, 4),
        0.5,
        round(importance_score, 4),
        "active",
        payload_json,
        tags_json,
        metadata_json,
        now,
        now,
    ))

    memory_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "memory_id": memory_id,
        "memory_type": memory_type,
        "scope": scope,
        "subject_id": subject_id,
    }


def get_protocol_memory_db(
    memory_type=None,
    scope=None,
    subject_id=None,
    status="active",
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if status:
        where.append(f"status = {p}")
        params.append(status)

    if memory_type:
        where.append(f"memory_type = {p}")
        params.append(memory_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    if subject_id:
        where.append(f"subject_id = {p}")
        params.append(subject_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    {where_sql}
    ORDER BY
        importance_score DESC,
        confidence DESC,
        memory_strength DESC,
        updated_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "memory": rows,
    }


def search_protocol_memory_db(
    query,
    memory_type=None,
    scope=None,
    limit=50,
):
    if not query:
        return {
            "status": "error",
            "message": "query_required",
            "memory": [],
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    like = f"%{str(query).lower()}%"

    where = ["status = 'active'", f"""(
        LOWER(COALESCE(memory_payload, '')) LIKE {p}
        OR LOWER(COALESCE(tags, '')) LIKE {p}
        OR LOWER(COALESCE(metadata, '')) LIKE {p}
        OR LOWER(COALESCE(subject_id, '')) LIKE {p}
    )"""]
    params = [like, like, like, like]

    if memory_type:
        where.append(f"memory_type = {p}")
        params.append(memory_type)

    if scope:
        where.append(f"scope = {p}")
        params.append(scope)

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    WHERE {' AND '.join(where)}
    ORDER BY
        importance_score DESC,
        confidence DESC,
        memory_strength DESC,
        updated_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "query": query,
        "count": len(rows),
        "memory": rows,
    }


def reinforce_protocol_memory_db(
    memory_id,
    observed=True,
    reason="",
):
    if not memory_id:
        return {
            "status": "error",
            "message": "memory_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    WHERE memory_id = {p}
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
    importance = float(row_get(row, "importance_score", 0.5) or 0.5)

    times_reinforced = int(row_get(row, "times_reinforced", 0) or 0)
    times_observed = int(row_get(row, "times_observed", 0) or 0)
    times_false_positive = int(row_get(row, "times_false_positive", 0) or 0)

    if observed:
        confidence = min(1.0, confidence + 0.05)
        strength = min(1.0, strength + 0.10)
        importance = min(1.0, importance + 0.03)
        times_reinforced += 1
        times_observed += 1
    else:
        confidence = max(0.0, confidence - 0.05)
        strength = max(0.0, strength - 0.10)
        importance = max(0.0, importance - 0.02)
        times_false_positive += 1

    status = "active"
    archived_at = row_get(row, "archived_at")

    if strength <= 0.15 and confidence <= 0.25:
        status = "archived"
        archived_at = now

    cur.execute(f"""
    UPDATE protocol_memory
    SET confidence = {p},
        memory_strength = {p},
        importance_score = {p},
        times_reinforced = {p},
        times_observed = {p},
        times_false_positive = {p},
        last_validated_at = {p},
        updated_at = {p},
        status = {p},
        archived_at = {p}
    WHERE memory_id = {p}
    """, (
        round(confidence, 4),
        round(strength, 4),
        round(importance, 4),
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
        "confidence": round(confidence, 4),
        "memory_strength": round(strength, 4),
        "importance_score": round(importance, 4),
        "times_reinforced": times_reinforced,
        "times_observed": times_observed,
        "times_false_positive": times_false_positive,
        "reason": reason,
    }


def decay_protocol_memory_db(
    max_age_seconds=604800,
    decay_amount=0.03,
    limit=500,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())
    cutoff = now - int(max_age_seconds or 604800)

    cur.execute(f"""
    SELECT *
    FROM protocol_memory
    WHERE status = 'active'
      AND updated_at <= {p}
    ORDER BY updated_at ASC
    LIMIT {int(limit or 500)}
    """, (cutoff,))

    rows = cur.fetchall()
    decayed = 0
    archived = 0

    for row in rows:
        memory_id = row_get(row, "memory_id")
        confidence = float(row_get(row, "confidence", 0) or 0)
        strength = float(row_get(row, "memory_strength", 0.5) or 0.5)
        importance = float(row_get(row, "importance_score", 0.5) or 0.5)

        strength = max(0.0, strength - float(decay_amount or 0.03))

        status = "active"
        archived_at = row_get(row, "archived_at")

        if strength <= 0.10 and confidence <= 0.25 and importance <= 0.25:
            status = "archived"
            archived_at = now
            archived += 1

        cur.execute(f"""
        UPDATE protocol_memory
        SET memory_strength = {p},
            last_decay_at = {p},
            updated_at = {p},
            status = {p},
            archived_at = {p}
        WHERE memory_id = {p}
        """, (
            round(strength, 4),
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
        "status": "ok",
        "decayed": decayed,
        "archived": archived,
    }


def archive_protocol_memory_db(memory_id, reason="manual_archive"):
    if not memory_id:
        return {
            "status": "error",
            "message": "memory_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT metadata
    FROM protocol_memory
    WHERE memory_id = {p}
    """, (memory_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {
            "status": "not_found",
            "memory_id": memory_id,
            "reason": reason,
        }

    try:
        meta = json.loads(row_get(row, "metadata") or "{}")
    except Exception:
        meta = {}

    meta["archive_reason"] = reason

    cur.execute(f"""
    UPDATE protocol_memory
    SET status = 'archived',
        archived_at = {p},
        updated_at = {p},
        metadata = {p}
    WHERE memory_id = {p}
    """, (
        now,
        now,
        json.dumps(meta, sort_keys=True),
        memory_id,
    ))

    affected = cur.rowcount
    conn.commit()
    release_conn(conn)

    return {
        "status": "archived" if affected else "not_found",
        "memory_id": memory_id,
        "reason": reason,
    }



def store_foundation_evidence_memory_db(
    order_id,
    evidence_package,
    importance_score=0.7,
):
    if not isinstance(evidence_package, dict):
        return {
            "status": "error",
            "message": "evidence_package_required",
        }

    evaluation = evidence_package.get("foundation_evidence_evaluation") or {}
    confidence = float(evaluation.get("confidence_cap", 0.5) or 0.5)

    return store_protocol_memory_db(
        memory_type="foundation_evidence_memory",
        scope="foundation",
        subject_id=order_id,
        source_type="foundation_execution_engine",
        source_id=order_id,
        confidence=confidence,
        importance_score=importance_score,
        memory_payload={
            "order_id": order_id,
            "evidence_status": evaluation.get("foundation_evidence_status"),
            "decision_ready": evaluation.get("foundation_decision_ready"),
            "confidence_cap": evaluation.get("confidence_cap"),
            "reason": evaluation.get("reason"),
            "research_agent_ids": evidence_package.get("research_agent_ids"),
            "verification_agent_ids": evidence_package.get("verification_agent_ids"),
            "research_consensus": evidence_package.get("research_consensus"),
            "verification_consensus": evidence_package.get("verification_consensus"),
        },
        tags=[
            "foundation",
            "evidence",
            str(evaluation.get("foundation_evidence_status") or ""),
            str(evaluation.get("reason") or ""),
        ],
        metadata={
            "protocol_core_sovereignty_reserved": True,
            "seller_authority": False,
            "buyer_authority": False,
        },
    )


def store_foundation_decision_memory_db(
    order_id,
    foundation_decision,
    importance_score=0.8,
):
    if not isinstance(foundation_decision, dict):
        return {
            "status": "error",
            "message": "foundation_decision_required",
        }

    confidence = float(foundation_decision.get("decision_confidence", 0.5) or 0.5)

    return store_protocol_memory_db(
        memory_type="foundation_decision_memory",
        scope="foundation",
        subject_id=order_id,
        source_type="foundation_decision_engine",
        source_id=order_id,
        confidence=confidence,
        importance_score=importance_score,
        memory_payload={
            "order_id": order_id,
            "foundation_verdict": foundation_decision.get("foundation_verdict"),
            "decision_reason": foundation_decision.get("decision_reason"),
            "decision_confidence": foundation_decision.get("decision_confidence"),
            "seller_inputs_used": foundation_decision.get("seller_inputs_used"),
            "foundation_execution_used": foundation_decision.get("foundation_execution_used"),
            "foundation_evidence_evaluation": foundation_decision.get("foundation_evidence_evaluation"),
            "seller_contribution_consensus": foundation_decision.get("seller_contribution_consensus"),
        },
        tags=[
            "foundation",
            "decision",
            str(foundation_decision.get("foundation_verdict") or ""),
            str(foundation_decision.get("decision_reason") or ""),
        ],
        metadata={
            "governance_authority": "iat_protocol_core_only",
            "decision_authority": "foundation_agents_only",
            "seller_decision_power": False,
            "buyer_decision_power": False,
        },
    )




def run_protocol_learning_cycle_db(
    limit=1000,
    auto_archive=True,
    auto_decay=True,
):
    memories_result = get_protocol_memory_db(
        status="active",
        limit=limit,
    )

    memories = memories_result.get("memory", [])

    strategic_candidates = []
    reinforcement_candidates = []
    decay_candidates = []
    archive_candidates = []
    learning_events = []

    for memory in memories:
        memory_id = memory.get("memory_id")

        confidence = float(memory.get("confidence", 0) or 0)
        strength = float(memory.get("memory_strength", 0) or 0)
        importance = float(memory.get("importance_score", 0) or 0)

        times_reinforced = int(memory.get("times_reinforced", 0) or 0)
        times_observed = int(memory.get("times_observed", 0) or 0)
        times_false_positive = int(memory.get("times_false_positive", 0) or 0)

        memory_type = memory.get("memory_type")
        scope = memory.get("scope")
        subject_id = memory.get("subject_id")

        classification = {
            "memory_id": memory_id,
            "memory_type": memory_type,
            "scope": scope,
            "subject_id": subject_id,
            "confidence": confidence,
            "memory_strength": strength,
            "importance_score": importance,
            "times_reinforced": times_reinforced,
            "times_observed": times_observed,
            "times_false_positive": times_false_positive,
        }

        if (
            confidence >= 0.80
            and strength >= 0.80
            and importance >= 0.75
            and times_observed >= 3
        ):
            strategic_candidates.append({
                **classification,
                "reason": "high_confidence_high_strength_repeated_observation",
            })

        if (
            confidence >= 0.70
            and importance >= 0.70
            and strength < 0.80
            and times_false_positive == 0
        ):
            reinforcement_candidates.append({
                **classification,
                "reason": "important_memory_needs_more_observation",
            })

        if confidence <= 0.30 and strength <= 0.30:
            decay_candidates.append({
                **classification,
                "reason": "low_confidence_low_strength",
            })

        if times_false_positive > times_observed:
            archive_candidates.append({
                **classification,
                "reason": "false_positive_count_exceeds_observations",
            })

    archived = []
    decayed = None

    if auto_archive:
        for item in archive_candidates:
            result = archive_protocol_memory_db(
                item.get("memory_id"),
                reason=item.get("reason"),
            )
            archived.append(result)

    if auto_decay:
        decayed = decay_protocol_memory_db(
            max_age_seconds=604800,
            decay_amount=0.02,
            limit=500,
        )

    summary = {
        "total_active_memories": len(memories),
        "strategic_candidates_count": len(strategic_candidates),
        "reinforcement_candidates_count": len(reinforcement_candidates),
        "decay_candidates_count": len(decay_candidates),
        "archive_candidates_count": len(archive_candidates),
        "auto_archive": bool(auto_archive),
        "auto_decay": bool(auto_decay),
        "archived_count": len([
            a for a in archived
            if a and a.get("status") == "archived"
        ]),
        "decay_result": decayed,
    }

    learning_report = {
        "learning_cycle_type": "protocol_memory_learning_cycle",
        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_authority": False,
        "buyer_authority": False,
        "summary": summary,
        "strategic_candidates": strategic_candidates,
        "reinforcement_candidates": reinforcement_candidates,
        "decay_candidates": decay_candidates,
        "archive_candidates": archive_candidates,
        "archive_results": archived,
        "learning_events": learning_events,
        "protocol_policy": {
            "memory_learning_informs_protocol": True,
            "memory_learning_governs_protocol": False,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    try:
        store_protocol_memory_db(
            memory_type="protocol_learning_cycle_memory",
            scope="protocol",
            subject_id="iat_core",
            source_type="protocol_learning_engine",
            source_id=f"learning_cycle_{int(time.time())}",
            confidence=0.75,
            importance_score=0.75,
            memory_payload={
                "summary": summary,
            },
            tags=[
                "protocol",
                "learning",
                "memory_cycle",
            ],
            metadata={
                "protocol_core_sovereignty_reserved": True,
                "seller_authority": False,
                "buyer_authority": False,
            },
            min_confidence=0.35,
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "learning_report": learning_report,
    }




def build_protocol_strategy_context_db(limit=100):
    memory_result = get_protocol_memory_db(
        status="active",
        limit=limit,
    )

    memories = memory_result.get("memory", [])

    by_type = {}
    high_importance = []
    high_confidence = []
    weak_memories = []

    for memory in memories:
        memory_type = memory.get("memory_type")
        by_type.setdefault(memory_type, 0)
        by_type[memory_type] += 1

        confidence = float(memory.get("confidence", 0) or 0)
        strength = float(memory.get("memory_strength", 0) or 0)
        importance = float(memory.get("importance_score", 0) or 0)

        item = {
            "memory_id": memory.get("memory_id"),
            "memory_type": memory_type,
            "scope": memory.get("scope"),
            "subject_id": memory.get("subject_id"),
            "confidence": confidence,
            "memory_strength": strength,
            "importance_score": importance,
            "tags": memory.get("tags"),
            "memory_payload": memory.get("memory_payload"),
            "updated_at": memory.get("updated_at"),
        }

        if importance >= 0.75:
            high_importance.append(item)

        if confidence >= 0.75 and strength >= 0.50:
            high_confidence.append(item)

        if confidence <= 0.35 or strength <= 0.25:
            weak_memories.append(item)

    learning_result = run_protocol_learning_cycle_db(
        limit=limit,
        auto_archive=False,
        auto_decay=False,
    )

    learning_report = learning_result.get("learning_report", {})

    strategy_context = {
        "context_type": "protocol_strategy_context",
        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "memory_authority": "advisory_only",
        "seller_authority": False,
        "buyer_authority": False,

        "memory_summary": {
            "total_active_memories": len(memories),
            "memory_count_by_type": by_type,
            "high_importance_count": len(high_importance),
            "high_confidence_count": len(high_confidence),
            "weak_memory_count": len(weak_memories),
        },

        "high_importance_memories": high_importance[:20],
        "high_confidence_memories": high_confidence[:20],
        "weak_memories": weak_memories[:20],

        "learning_report_summary": learning_report.get("summary"),
        "strategic_candidates": learning_report.get("strategic_candidates", []),
        "reinforcement_candidates": learning_report.get("reinforcement_candidates", []),
        "decay_candidates": learning_report.get("decay_candidates", []),
        "archive_candidates": learning_report.get("archive_candidates", []),

        "protocol_policy": {
            "strategy_context_informs_protocol": True,
            "strategy_context_governs_protocol": False,
            "protocol_core_sovereignty_reserved": True,
            "foundation_agents_remain_protocol_authority": True,
        },
    }

    try:
        store_protocol_memory_db(
            memory_type="protocol_strategy_context_memory",
            scope="protocol",
            subject_id="iat_core",
            source_type="protocol_strategy_engine",
            source_id=f"strategy_context_{int(time.time())}",
            confidence=0.75,
            importance_score=0.8,
            memory_payload={
                "memory_summary": strategy_context.get("memory_summary"),
                "learning_report_summary": strategy_context.get("learning_report_summary"),
            },
            tags=[
                "protocol",
                "strategy",
                "context",
                "learning",
            ],
            metadata={
                "protocol_core_sovereignty_reserved": True,
                "strategy_context_governs_protocol": False,
            },
            min_confidence=0.35,
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "strategy_context": strategy_context,
    }



def init_foundation_agent_columns():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'agents'
        """)
        columns = {row_get(row, "column_name") for row in cur.fetchall()}

        if "foundation_role" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_role TEXT")

        if "foundation_priority" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_priority INTEGER DEFAULT 100")

        if "foundation_authority_level" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_authority_level INTEGER DEFAULT 0")

    else:
        columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(agents)").fetchall()
        }

        if "foundation_role" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_role TEXT")

        if "foundation_priority" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_priority INTEGER DEFAULT 100")

        if "foundation_authority_level" not in columns:
            cur.execute("ALTER TABLE agents ADD COLUMN foundation_authority_level INTEGER DEFAULT 0")

    conn.commit()
    release_conn(conn)


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
    init_foundation_agent_columns()
    init_protocol_memory_table()
    init_protocol_knowledge_table()
    init_protocol_hypotheses_table()
    init_protocol_experiments_table()
    init_protocol_adaptations_table()
    init_protocol_rollbacks_table()
    init_protocol_adaptation_reviews_table()
    init_protocol_adaptation_monitors_table()
    init_protocol_rollback_reviews_table()
    init_protocol_rollback_proposals_table()
    init_seller_agent_factory_reviews_table()
    init_seller_agent_factory_approvals_table()
    init_seller_agent_sandbox_reviews_table()
    init_seller_agent_sandbox_approvals_table()
    init_seller_agent_simulation_reviews_table()
    init_seller_agent_simulation_approvals_table()
    init_sellers_table()
    ensure_seller_punishment_columns()
    init_seller_agents_table()
    ensure_seller_agent_runtime_columns()
    init_seller_catalog_items_table()
    init_seller_inventory_events_table()
    init_seller_agent_factory_requests_table()
    init_seller_agent_sandbox_runs_table()
    init_seller_agent_simulation_runs_table()
    init_seller_agent_activation_reviews_table()
    init_seller_agent_activation_governance_reviews_table()
    init_seller_agent_activation_approvals_table()
    init_seller_agent_runtime_reviews_table()
    init_seller_agent_runtime_governance_reviews_table()
    init_seller_runtime_risk_events_table()
    init_seller_agent_runtime_actions_table()
    init_seller_agent_execution_sessions_table()
    init_seller_governance_events_table()
    init_threat_memory_nodes_table()
    init_adversarial_mutation_signatures_table()
    init_seller_containment_events_table()
    init_seller_recovery_requests_table()
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





def ensure_seller_punishment_columns():
    conn = get_conn()
    cur = conn.cursor()

    columns = {
        "containment_count": "INTEGER DEFAULT 0",
        "economic_penalty_level": "INTEGER DEFAULT 0",
    }

    for column, definition in columns.items():
        try:
            if is_postgres():
                cur.execute(
                    f"ALTER TABLE sellers ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            else:
                cur.execute(
                    f"ALTER TABLE sellers ADD COLUMN {column} {definition}"
                )
        except Exception:
            pass

    conn.commit()
    release_conn(conn)



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

        max_agents_allowed INTEGER DEFAULT 5,

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

    seller_columns = {
        "email_verified": "INTEGER DEFAULT 0",
        "email_verified_at": "INTEGER",
        "api_key_created_at": "INTEGER",
        "last_contact_at": "INTEGER",
        "onboarding_completed": "INTEGER DEFAULT 0",
        "support_email": "TEXT",
        "website": "TEXT",
        "organization_name": "TEXT",
        "webhook_url": "TEXT",
        "kyc_status": "TEXT DEFAULT 'not_provided'",
        "business_verification_status": "TEXT DEFAULT 'not_provided'",
        "tax_verification_status": "TEXT DEFAULT 'not_provided'",
        "trust_score": "REAL DEFAULT 0",
        "runtime_health_score": "REAL DEFAULT 0",
    }

    for column, definition in seller_columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE sellers ADD COLUMN IF NOT EXISTS {column} {definition}")
            else:
                cur.execute(f"ALTER TABLE sellers ADD COLUMN {column} {definition}")
        except Exception:
            pass

    cur.execute(f'''
    UPDATE sellers
    SET max_agents_allowed = 5
    WHERE max_agents_allowed IS NULL
    ''')

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
        "runtime_failure_count": "INTEGER DEFAULT 0",
        "runtime_quarantine_until": "INTEGER",
        "containment_count": "INTEGER DEFAULT 0",
        "economic_penalty_level": "INTEGER DEFAULT 0",
    }

    for column, definition in columns.items():
        try:
            if is_postgres():
                cur.execute(
                    f"ALTER TABLE seller_agents ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            else:
                cur.execute(
                    f"ALTER TABLE seller_agents ADD COLUMN {column} {definition}"
                )
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
        runtime_failure_count INTEGER DEFAULT 0,
        runtime_quarantine_until INTEGER,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)




def init_seller_catalog_items_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_catalog_items (
        catalog_item_id TEXT PRIMARY KEY,
        seller_id TEXT NOT NULL,

        item_type TEXT NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,

        service_type TEXT,
        sku TEXT,

        unit_price REAL DEFAULT 0,
        currency TEXT DEFAULT 'IAT',

        stock_quantity REAL DEFAULT 0,
        capacity_per_day REAL DEFAULT 0,
        capacity_per_order REAL DEFAULT 0,

        availability_status TEXT DEFAULT 'draft',

        delivery_terms TEXT DEFAULT '',
        refund_policy TEXT DEFAULT '',
        warranty_terms TEXT DEFAULT '',
        quality_claims TEXT DEFAULT '',

        source_documents TEXT DEFAULT '[]',
        proof_links TEXT DEFAULT '[]',

        verification_status TEXT DEFAULT 'unverified',
        risk_score REAL DEFAULT 0,
        trust_score REAL DEFAULT 0,

        agent_creation_status TEXT DEFAULT 'not_requested',
        linked_seller_agent_id TEXT,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    columns = {
        "catalog_item_id": "TEXT",
        "seller_id": "TEXT",
        "item_type": "TEXT",
        "category": "TEXT",
        "title": "TEXT",
        "description": "TEXT",
        "service_type": "TEXT",
        "sku": "TEXT",
        "unit_price": "REAL DEFAULT 0",
        "currency": "TEXT DEFAULT 'IAT'",
        "stock_quantity": "REAL DEFAULT 0",
        "capacity_per_day": "REAL DEFAULT 0",
        "capacity_per_order": "REAL DEFAULT 0",
        "availability_status": "TEXT DEFAULT 'draft'",
        "delivery_terms": "TEXT DEFAULT ''",
        "refund_policy": "TEXT DEFAULT ''",
        "warranty_terms": "TEXT DEFAULT ''",
        "quality_claims": "TEXT DEFAULT ''",
        "source_documents": "TEXT DEFAULT '[]'",
        "proof_links": "TEXT DEFAULT '[]'",
        "verification_status": "TEXT DEFAULT 'unverified'",
        "risk_score": "REAL DEFAULT 0",
        "trust_score": "REAL DEFAULT 0",
        "agent_creation_status": "TEXT DEFAULT 'not_requested'",
        "linked_seller_agent_id": "TEXT",
        "created_at": "INTEGER",
        "updated_at": "INTEGER",
        "metadata": "TEXT DEFAULT '{}'",
    }

    for column, definition in columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE seller_catalog_items ADD COLUMN IF NOT EXISTS {column} {definition}")
            else:
                cur.execute(f"ALTER TABLE seller_catalog_items ADD COLUMN {column} {definition}")
        except Exception:
            pass

    conn.commit()
    release_conn(conn)


def init_seller_inventory_events_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_inventory_events (
        inventory_event_id TEXT PRIMARY KEY,
        catalog_item_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,

        event_type TEXT NOT NULL,
        quantity_delta REAL DEFAULT 0,
        capacity_delta REAL DEFAULT 0,

        previous_stock_quantity REAL DEFAULT 0,
        new_stock_quantity REAL DEFAULT 0,

        previous_capacity_per_day REAL DEFAULT 0,
        new_capacity_per_day REAL DEFAULT 0,

        reason TEXT DEFAULT '',
        created_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_factory_requests_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agent_factory_requests (
        factory_request_id TEXT PRIMARY KEY,
        seller_id TEXT NOT NULL,
        catalog_item_id TEXT NOT NULL,

        requested_agent_name TEXT,
        requested_prompt TEXT NOT NULL,

        requested_agent_count INTEGER DEFAULT 1,
        requested_specializations TEXT DEFAULT '[]',
        factory_plan TEXT DEFAULT '{}',

        factory_status TEXT DEFAULT 'draft',
        sandbox_status TEXT DEFAULT 'not_started',
        simulation_status TEXT DEFAULT 'not_started',
        governance_status TEXT DEFAULT 'pending',

        generated_agent_id TEXT,
        generated_seller_agent_id TEXT,

        risk_score REAL DEFAULT 0,
        trust_score REAL DEFAULT 0,

        rejection_reason TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    columns = {
        "requested_agent_count": "INTEGER DEFAULT 1",
        "requested_specializations": "TEXT DEFAULT '[]'",
        "factory_plan": "TEXT DEFAULT '{}'",
    }

    for column, definition in columns.items():
        try:
            if USE_POSTGRES:
                cur.execute(f"ALTER TABLE seller_agent_factory_requests ADD COLUMN IF NOT EXISTS {column} {definition}")
            else:
                cur.execute(f"ALTER TABLE seller_agent_factory_requests ADD COLUMN {column} {definition}")
        except Exception:
            pass

    conn.commit()
    release_conn(conn)



def init_seller_agent_sandbox_runs_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agent_sandbox_runs (
        sandbox_run_id TEXT PRIMARY KEY,
        factory_request_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,
        catalog_item_id TEXT NOT NULL,

        sandbox_status TEXT DEFAULT 'queued',

        sandbox_risk_score REAL DEFAULT 0,
        sandbox_trust_score REAL DEFAULT 0,

        sandbox_report TEXT DEFAULT '{}',
        governance_recommendation TEXT,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def get_latest_seller_agent_sandbox_run_db(factory_request_id):
    if not factory_request_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_sandbox_runs
    WHERE factory_request_id = {p}
    ORDER BY created_at DESC
    LIMIT 1
    """, (factory_request_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def get_seller_agent_sandbox_run_db(sandbox_run_id):
    if not sandbox_run_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_sandbox_runs
    WHERE sandbox_run_id = {p}
    """, (sandbox_run_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def run_seller_agent_sandbox_review_db(factory_request_id):
    if not factory_request_id:
        return {
            "status": "error",
            "message": "factory_request_id_required",
        }

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
        }

    if str(factory_request.get("governance_status") or "").lower() != "approved_for_sandbox":
        return {
            "status": "error",
            "message": "factory_request_not_approved_for_sandbox",
            "factory_request_id": factory_request_id,
            "governance_status": factory_request.get("governance_status"),
            "sandbox_status": factory_request.get("sandbox_status"),
        }

    approvals_result = get_seller_agent_factory_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if approvals_result.get("count", 0) < 1:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET governance_status = {p},
            factory_status = {p},
            sandbox_status = {p},
            simulation_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "pending_factory_approval",
            "pending_factory_approval",
            "not_started",
            "not_started",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "blocked",
            "message": "factory_approval_required_before_sandbox",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "approvals": approvals_result,
            "policy": {
                "factory_reviews_required": True,
                "factory_approval_required_before_sandbox": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
            "factory_request": get_seller_agent_factory_request_db(factory_request_id),
        }

    seller = get_seller_db(factory_request.get("seller_id"))
    if not seller:
        return {
            "status": "error",
            "message": "seller_not_found",
            "factory_request_id": factory_request_id,
        }

    catalog_item = get_seller_catalog_item_db(factory_request.get("catalog_item_id"))
    if not catalog_item:
        return {
            "status": "error",
            "message": "catalog_item_not_found",
            "factory_request_id": factory_request_id,
        }

    requested_specializations = _safe_json_loads(
        factory_request.get("requested_specializations"),
        [],
    )

    factory_plan = _safe_json_loads(
        factory_request.get("factory_plan"),
        {},
    )

    requested_prompt = str(factory_request.get("requested_prompt") or "")
    requested_agent_count = int(factory_request.get("requested_agent_count", 1) or 1)

    sandbox_risk_score = 0
    sandbox_trust_score = 0
    failed_checks = []
    passed_checks = []
    manual_review_checks = []

    # Required state checks.
    if str(seller.get("seller_status") or "").lower() == "active":
        sandbox_trust_score += 10
        passed_checks.append("seller_active")
    else:
        sandbox_risk_score += 30
        failed_checks.append("seller_not_active")

    if str(seller.get("verification_status") or "").lower() in ["verified", "foundation_verified"]:
        sandbox_trust_score += 10
        passed_checks.append("seller_verified")
    else:
        sandbox_risk_score += 20
        failed_checks.append("seller_not_verified")

    if str(catalog_item.get("verification_status") or "").lower() in ["verified", "foundation_verified"]:
        sandbox_trust_score += 10
        passed_checks.append("catalog_verified")
    else:
        sandbox_risk_score += 20
        failed_checks.append("catalog_not_verified")

    if str(catalog_item.get("availability_status") or "").lower() in ["active", "available"]:
        sandbox_trust_score += 10
        passed_checks.append("catalog_available")
    else:
        sandbox_risk_score += 15
        failed_checks.append("catalog_not_available")

    # Factory request integrity checks.
    if requested_prompt.strip():
        sandbox_trust_score += 5
        passed_checks.append("prompt_present")
    else:
        sandbox_risk_score += 40
        failed_checks.append("prompt_missing")

    if requested_agent_count > 0:
        sandbox_trust_score += 5
        passed_checks.append("requested_agent_count_valid")
    else:
        sandbox_risk_score += 50
        failed_checks.append("requested_agent_count_invalid")

    if isinstance(requested_specializations, list) and len(requested_specializations) > 0:
        sandbox_trust_score += 5
        passed_checks.append("specializations_present")
    else:
        sandbox_risk_score += 10
        manual_review_checks.append("specializations_missing")

    if isinstance(factory_plan, dict) and factory_plan.get("requires_sandbox") is True:
        sandbox_trust_score += 5
        passed_checks.append("factory_plan_requires_sandbox")
    else:
        sandbox_risk_score += 10
        manual_review_checks.append("factory_plan_missing_sandbox_requirement")

    # Prompt safety checks.
    lowered_prompt = requested_prompt.lower()
    forbidden_patterns = [
        "contact buyer directly",
        "contact the buyer directly",
        "bypass foundation",
        "bypass iat",
        "bypass the protocol",
        "direct buyer access",
        "raw buyer prompt",
        "outside iat",
        "external payment",
        "off-platform payment",
    ]

    for pattern in forbidden_patterns:
        if pattern in lowered_prompt:
            sandbox_risk_score += 25
            failed_checks.append(f"forbidden_prompt_pattern:{pattern}")

    # Seller agents must remain narrow.
    if requested_agent_count > int(seller.get("max_agents_allowed", 5) or 5):
        sandbox_risk_score += 50
        failed_checks.append("requested_agent_count_exceeds_max_allowed")

    # Bound scores.
    sandbox_risk_score = max(0, min(100, int(sandbox_risk_score)))
    sandbox_trust_score = max(0, min(100, int(sandbox_trust_score)))

    if failed_checks and sandbox_risk_score > 50:
        sandbox_status = "failed"
        governance_recommendation = "reject_before_simulation"
        next_factory_status = "sandbox_failed"
        next_simulation_status = "blocked"
        event_type = "factory_sandbox_failed"
    elif sandbox_risk_score > 25 or manual_review_checks:
        sandbox_status = "manual_review"
        governance_recommendation = "manual_sandbox_review"
        next_factory_status = "sandbox_manual_review"
        next_simulation_status = "not_started"
        event_type = "factory_sandbox_manual_review"
    else:
        sandbox_status = "passed"
        governance_recommendation = "queue_simulation"
        next_factory_status = "sandbox_passed"
        next_simulation_status = "queued"
        event_type = "factory_sandbox_passed"

    sandbox_report = {
        "factory_request_id": factory_request_id,
        "seller_id": seller.get("seller_id"),
        "catalog_item_id": catalog_item.get("catalog_item_id"),
        "requested_agent_count": requested_agent_count,
        "requested_specializations": requested_specializations,
        "factory_plan": factory_plan,
        "sandbox_risk_score": sandbox_risk_score,
        "sandbox_trust_score": sandbox_trust_score,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "manual_review_checks": manual_review_checks,
        "governance_recommendation": governance_recommendation,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())
    sandbox_run_id = str(uuid.uuid4())

    cur.execute(f"""
    INSERT INTO seller_agent_sandbox_runs (
        sandbox_run_id,
        factory_request_id,
        seller_id,
        catalog_item_id,
        sandbox_status,
        sandbox_risk_score,
        sandbox_trust_score,
        sandbox_report,
        governance_recommendation,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        sandbox_run_id,
        factory_request_id,
        seller.get("seller_id"),
        catalog_item.get("catalog_item_id"),
        sandbox_status,
        sandbox_risk_score,
        sandbox_trust_score,
        json.dumps(sandbox_report),
        governance_recommendation,
        now,
        now,
        "{}",
    ))

    cur.execute(f"""
    UPDATE seller_agent_factory_requests
    SET sandbox_status = {p},
        simulation_status = {p},
        factory_status = {p},
        updated_at = {p}
    WHERE factory_request_id = {p}
    """, (
        sandbox_status,
        next_simulation_status,
        next_factory_status,
        now,
        factory_request_id,
    ))

    cur.execute(f"""
    UPDATE seller_catalog_items
    SET agent_creation_status = {p},
        updated_at = {p}
    WHERE catalog_item_id = {p}
    """, (
        next_factory_status,
        now,
        catalog_item.get("catalog_item_id"),
    ))

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller.get("seller_id"),
        event_type=event_type,
        reviewer="iat_factory_sandbox_engine",
        reason=governance_recommendation,
        old_status=str(factory_request.get("sandbox_status") or "queued"),
        new_status=sandbox_status,
        metadata=sandbox_report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "sandbox_run_id": sandbox_run_id,
        "factory_request_id": factory_request_id,
        "sandbox_status": sandbox_status,
        "sandbox_risk_score": sandbox_risk_score,
        "sandbox_trust_score": sandbox_trust_score,
        "governance_recommendation": governance_recommendation,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "manual_review_checks": manual_review_checks,
        "event": event_result,
        "sandbox_run": get_seller_agent_sandbox_run_db(sandbox_run_id),
        "factory_request": get_seller_agent_factory_request_db(factory_request_id),
    }




def init_seller_agent_simulation_runs_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agent_simulation_runs (
        simulation_run_id TEXT PRIMARY KEY,
        factory_request_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,
        catalog_item_id TEXT NOT NULL,
        simulation_status TEXT DEFAULT 'queued',
        simulation_risk_score REAL DEFAULT 0,
        simulation_trust_score REAL DEFAULT 0,
        simulation_report TEXT DEFAULT '{}',
        governance_recommendation TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def get_seller_agent_simulation_run_db(simulation_run_id):
    if not simulation_run_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_simulation_runs
    WHERE simulation_run_id = {p}
    """, (simulation_run_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def run_seller_agent_simulation_review_db(factory_request_id):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {"status": "error", "message": "factory_request_not_found"}

    if str(factory_request.get("sandbox_status") or "").lower() != "passed":
        return {
            "status": "error",
            "message": "factory_request_not_passed_sandbox",
            "factory_request_id": factory_request_id,
            "sandbox_status": factory_request.get("sandbox_status"),
        }

    sandbox_approvals = get_seller_agent_sandbox_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if sandbox_approvals.get("count", 0) < 1:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET simulation_status = {p},
            factory_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "pending_sandbox_approval",
            "pending_sandbox_approval",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "blocked",
            "message": "sandbox_approval_required_before_simulation",
            "factory_request_id": factory_request_id,
            "sandbox_approvals": sandbox_approvals,
            "policy": {
                "sandbox_reviews_required": True,
                "sandbox_approval_required_before_simulation": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
            "factory_request": get_seller_agent_factory_request_db(factory_request_id),
        }

    seller = get_seller_db(factory_request.get("seller_id"))
    catalog_item = get_seller_catalog_item_db(factory_request.get("catalog_item_id"))

    if not seller:
        return {"status": "error", "message": "seller_not_found"}

    if not catalog_item:
        return {"status": "error", "message": "catalog_item_not_found"}

    requested_specializations = _safe_json_loads(factory_request.get("requested_specializations"), [])
    factory_plan = _safe_json_loads(factory_request.get("factory_plan"), {})

    requested_prompt = str(factory_request.get("requested_prompt") or "")
    lowered_prompt = requested_prompt.lower()
    requested_agent_count = int(factory_request.get("requested_agent_count", 1) or 1)

    item_type = str(catalog_item.get("item_type") or "").lower()
    category = str(catalog_item.get("category") or "").lower()

    risk = 0
    trust = 0
    passed = []
    failed = []
    manual = []

    if category:
        trust += 5
        passed.append("category_defined")
    else:
        risk += 20
        failed.append("category_missing")

    if item_type in ["service", "product"]:
        trust += 5
        passed.append("item_type_valid")
    else:
        risk += 30
        failed.append("item_type_invalid")

    if isinstance(requested_specializations, list) and requested_specializations:
        trust += 10
        passed.append("specializations_declared")
    else:
        risk += 10
        manual.append("specializations_missing")

    forbidden_patterns = [
        "contact buyer directly",
        "contact the buyer directly",
        "direct buyer access",
        "raw buyer prompt",
        "bypass foundation",
        "bypass iat",
        "bypass the protocol",
        "external payment",
        "off-platform payment",
        "wallet direct payment",
        "buyer email",
        "buyer phone",
    ]

    for pattern in forbidden_patterns:
        if pattern in lowered_prompt:
            risk += 30
            failed.append(f"authority_violation:{pattern}")

    if "foundation" in lowered_prompt or "iat" in lowered_prompt:
        trust += 10
        passed.append("protocol_authority_acknowledged")
    else:
        risk += 10
        manual.append("protocol_authority_not_explicit")

    capacity_per_day = float(catalog_item.get("capacity_per_day", 0) or 0)
    stock_quantity = float(catalog_item.get("stock_quantity", 0) or 0)
    unit_price = float(catalog_item.get("unit_price", 0) or 0)

    if item_type == "service":
        if capacity_per_day > 0:
            trust += 10
            passed.append("service_capacity_defined")
        else:
            risk += 25
            failed.append("service_capacity_missing")

        if requested_agent_count > 0 and capacity_per_day > 0 and capacity_per_day / requested_agent_count < 1:
            risk += 20
            manual.append("capacity_per_agent_too_low")

    if item_type == "product":
        if stock_quantity > 0:
            trust += 10
            passed.append("product_stock_defined")
        else:
            risk += 25
            failed.append("product_stock_missing")

    if unit_price > 0:
        trust += 5
        passed.append("unit_price_defined")
    else:
        risk += 20
        failed.append("unit_price_missing")

    if isinstance(factory_plan, dict) and factory_plan.get("requires_simulation") is True:
        trust += 5
        passed.append("factory_plan_requires_simulation")
    else:
        risk += 10
        manual.append("factory_plan_missing_simulation_requirement")

    risk = max(0, min(100, int(risk)))
    trust = max(0, min(100, int(trust)))

    if failed and risk > 50:
        simulation_status = "failed"
        recommendation = "reject_before_generation"
        next_factory_status = "simulation_failed"
        event_type = "factory_simulation_failed"
    elif risk > 25 or manual:
        simulation_status = "manual_review"
        recommendation = "manual_simulation_review"
        next_factory_status = "simulation_manual_review"
        event_type = "factory_simulation_manual_review"
    else:
        simulation_status = "passed"
        recommendation = "ready_for_generation"
        next_factory_status = "ready_for_generation"
        event_type = "factory_simulation_passed"

    report = {
        "factory_request_id": factory_request_id,
        "seller_id": seller.get("seller_id"),
        "catalog_item_id": catalog_item.get("catalog_item_id"),
        "requested_agent_count": requested_agent_count,
        "requested_specializations": requested_specializations,
        "factory_plan": factory_plan,
        "simulation_risk_score": risk,
        "simulation_trust_score": trust,
        "passed_checks": passed,
        "failed_checks": failed,
        "manual_review_checks": manual,
        "governance_recommendation": recommendation,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())
    simulation_run_id = str(uuid.uuid4())

    cur.execute(f"""
    INSERT INTO seller_agent_simulation_runs (
        simulation_run_id, factory_request_id, seller_id, catalog_item_id,
        simulation_status, simulation_risk_score, simulation_trust_score,
        simulation_report, governance_recommendation,
        created_at, updated_at, metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        simulation_run_id,
        factory_request_id,
        seller.get("seller_id"),
        catalog_item.get("catalog_item_id"),
        simulation_status,
        risk,
        trust,
        json.dumps(report),
        recommendation,
        now,
        now,
        "{}",
    ))

    cur.execute(f"""
    UPDATE seller_agent_factory_requests
    SET simulation_status = {p},
        factory_status = {p},
        updated_at = {p}
    WHERE factory_request_id = {p}
    """, (
        simulation_status,
        next_factory_status,
        now,
        factory_request_id,
    ))

    cur.execute(f"""
    UPDATE seller_catalog_items
    SET agent_creation_status = {p},
        updated_at = {p}
    WHERE catalog_item_id = {p}
    """, (
        next_factory_status,
        now,
        catalog_item.get("catalog_item_id"),
    ))

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller.get("seller_id"),
        event_type=event_type,
        reviewer="iat_factory_simulation_engine",
        reason=recommendation,
        old_status=str(factory_request.get("simulation_status") or "queued"),
        new_status=simulation_status,
        metadata=report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "simulation_run_id": simulation_run_id,
        "factory_request_id": factory_request_id,
        "simulation_status": simulation_status,
        "simulation_risk_score": risk,
        "simulation_trust_score": trust,
        "governance_recommendation": recommendation,
        "passed_checks": passed,
        "failed_checks": failed,
        "manual_review_checks": manual,
        "event": event_result,
        "simulation_run": get_seller_agent_simulation_run_db(simulation_run_id),
        "factory_request": get_seller_agent_factory_request_db(factory_request_id),
    }



def create_seller_catalog_item_db(item):
    seller_id = item.get("seller_id")
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    item_type = str(item.get("item_type") or "").lower()
    if item_type not in ["service", "product"]:
        return {"status": "error", "message": "invalid_item_type"}

    required = ["category", "title", "description"]
    for field in required:
        if not item.get(field):
            return {"status": "error", "message": f"{field}_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    catalog_item_id = item.get("catalog_item_id") or str(uuid.uuid4())

    source_documents = item.get("source_documents", "[]")
    if not isinstance(source_documents, str):
        source_documents = json.dumps(source_documents)

    proof_links = item.get("proof_links", "[]")
    if not isinstance(proof_links, str):
        proof_links = json.dumps(proof_links)

    metadata = item.get("metadata", "{}")
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)

    cur.execute(f"""
    INSERT INTO seller_catalog_items (
        catalog_item_id, seller_id,
        item_type, category, title, description,
        service_type, sku,
        unit_price, currency,
        stock_quantity, capacity_per_day, capacity_per_order,
        availability_status,
        delivery_terms, refund_policy, warranty_terms, quality_claims,
        source_documents, proof_links,
        verification_status, risk_score, trust_score,
        agent_creation_status, linked_seller_agent_id,
        created_at, updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        catalog_item_id,
        seller_id,
        item_type,
        item.get("category"),
        item.get("title"),
        item.get("description"),
        item.get("service_type"),
        item.get("sku"),
        float(item.get("unit_price", 0) or 0),
        item.get("currency", "IAT"),
        float(item.get("stock_quantity", 0) or 0),
        float(item.get("capacity_per_day", 0) or 0),
        float(item.get("capacity_per_order", 0) or 0),
        item.get("availability_status", "draft"),
        item.get("delivery_terms", ""),
        item.get("refund_policy", ""),
        item.get("warranty_terms", ""),
        item.get("quality_claims", ""),
        source_documents,
        proof_links,
        item.get("verification_status", "unverified"),
        float(item.get("risk_score", 0) or 0),
        float(item.get("trust_score", 0) or 0),
        item.get("agent_creation_status", "not_requested"),
        item.get("linked_seller_agent_id"),
        now,
        now,
        metadata,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "catalog_item": get_seller_catalog_item_db(catalog_item_id),
    }


def get_seller_catalog_item_db(catalog_item_id):
    if not catalog_item_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_catalog_items
    WHERE catalog_item_id = {p}
    """, (catalog_item_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def list_seller_catalog_items_db(seller_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_catalog_items
    WHERE seller_id = {p}
    ORDER BY created_at DESC
    """, (seller_id,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(row) for row in rows]


def create_seller_agent_factory_request_db(request_data):
    seller_id = request_data.get("seller_id")
    catalog_item_id = request_data.get("catalog_item_id")

    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    if not catalog_item_id:
        return {"status": "error", "message": "catalog_item_id_required"}

    catalog_item = get_seller_catalog_item_db(catalog_item_id)
    if not catalog_item:
        return {"status": "error", "message": "catalog_item_not_found"}

    if catalog_item.get("seller_id") != seller_id:
        return {"status": "error", "message": "catalog_item_seller_mismatch"}

    if not request_data.get("requested_prompt"):
        return {"status": "error", "message": "requested_prompt_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    factory_request_id = request_data.get("factory_request_id") or str(uuid.uuid4())

    metadata = request_data.get("metadata", "{}")
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)

    cur.execute(f"""
    INSERT INTO seller_agent_factory_requests (
        factory_request_id, seller_id, catalog_item_id,
        requested_agent_name, requested_prompt,
        requested_agent_count, requested_specializations, factory_plan,
        factory_status, sandbox_status, simulation_status, governance_status,
        generated_agent_id, generated_seller_agent_id,
        risk_score, trust_score,
        rejection_reason,
        created_at, updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        factory_request_id,
        seller_id,
        catalog_item_id,
        request_data.get("requested_agent_name"),
        request_data.get("requested_prompt"),
        int(request_data.get("requested_agent_count", 1) or 1),
        json.dumps(request_data.get("requested_specializations", [])) if not isinstance(request_data.get("requested_specializations", []), str) else request_data.get("requested_specializations", "[]"),
        json.dumps(request_data.get("factory_plan", {})) if not isinstance(request_data.get("factory_plan", {}), str) else request_data.get("factory_plan", "{}"),
        request_data.get("factory_status", "draft"),
        request_data.get("sandbox_status", "not_started"),
        request_data.get("simulation_status", "not_started"),
        request_data.get("governance_status", "pending"),
        request_data.get("generated_agent_id"),
        request_data.get("generated_seller_agent_id"),
        float(request_data.get("risk_score", 0) or 0),
        float(request_data.get("trust_score", 0) or 0),
        request_data.get("rejection_reason"),
        now,
        now,
        metadata,
    ))

    cur.execute(f"""
    UPDATE seller_catalog_items
    SET agent_creation_status = {p},
        updated_at = {p}
    WHERE catalog_item_id = {p}
    """, ("requested", now, catalog_item_id))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "factory_request": get_seller_agent_factory_request_db(factory_request_id),
    }


def get_seller_agent_factory_request_db(factory_request_id):
    if not factory_request_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_factory_requests
    WHERE factory_request_id = {p}
    """, (factory_request_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def list_seller_agent_factory_requests_db(seller_id):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_factory_requests
    WHERE seller_id = {p}
    ORDER BY created_at DESC
    """, (seller_id,))

    rows = cur.fetchall()
    release_conn(conn)

    return [dict(row) for row in rows]



def _safe_json_loads(value, fallback):
    if value is None:
        return fallback

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except Exception:
        return fallback


def run_seller_agent_factory_review_db(factory_request_id):
    if not factory_request_id:
        return {
            "status": "error",
            "message": "factory_request_id_required",
        }

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {
            "status": "error",
            "message": "factory_request_not_found",
        }

    review_evaluation = evaluate_seller_agent_factory_reviews_db(
        factory_request_id=factory_request_id
    )

    if review_evaluation.get("readiness") != "ready_for_factory_approval":
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET governance_status = {p},
            factory_status = {p},
            sandbox_status = {p},
            simulation_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "pending_factory_reviews",
            "pending_factory_reviews",
            "not_started",
            "not_started",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "blocked",
            "message": "factory_request_not_ready_for_governance_approval",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "policy": {
                "seller_cannot_self_approve": True,
                "factory_reviews_required": True,
                "foundation_reviews_required": True,
                "protocol_core_sovereignty_reserved": True,
            },
            "factory_request": get_seller_agent_factory_request_db(factory_request_id),
        }

    approvals_result = get_seller_agent_factory_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if approvals_result.get("count", 0) < 1:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET governance_status = {p},
            factory_status = {p},
            sandbox_status = {p},
            simulation_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "pending_factory_approval",
            "pending_factory_approval",
            "not_started",
            "not_started",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "blocked",
            "message": "factory_approval_required_before_sandbox",
            "factory_request_id": factory_request_id,
            "review_evaluation": review_evaluation,
            "approvals": approvals_result,
            "policy": {
                "factory_reviews_required": True,
                "factory_approval_required_before_sandbox": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
            "factory_request": get_seller_agent_factory_request_db(factory_request_id),
        }

    seller = get_seller_db(factory_request.get("seller_id"))
    if not seller:
        return {
            "status": "error",
            "message": "seller_not_found",
            "factory_request_id": factory_request_id,
        }

    catalog_item = get_seller_catalog_item_db(factory_request.get("catalog_item_id"))
    if not catalog_item:
        return {
            "status": "error",
            "message": "catalog_item_not_found",
            "factory_request_id": factory_request_id,
        }

    requested_agent_count = int(factory_request.get("requested_agent_count", 1) or 1)
    max_agents_allowed = int(seller.get("max_agents_allowed", 5) or 5)
    active_agents = int(seller.get("active_agents", 0) or 0)

    seller_status = str(seller.get("seller_status") or "pending").lower()
    seller_verification_status = str(seller.get("verification_status") or "unverified").lower()
    catalog_verification_status = str(catalog_item.get("verification_status") or "unverified").lower()
    catalog_availability_status = str(catalog_item.get("availability_status") or "draft").lower()

    risk_score = 0
    trust_score = 0
    risk_reasons = []
    trust_reasons = []

    # Seller lifecycle risk
    if seller_status not in ["active"]:
        risk_score += 20
        risk_reasons.append("seller_not_active")
    else:
        trust_score += 15
        trust_reasons.append("seller_active")

    if seller_status in ["watchlist", "limited", "restricted"]:
        risk_score += 20
        risk_reasons.append("seller_restricted_state")

    if seller_status in ["rejected", "banned", "contained"]:
        risk_score += 80
        risk_reasons.append("seller_terminal_or_contained_state")

    # Seller verification trust
    if seller_verification_status in ["verified", "foundation_verified"]:
        trust_score += 20
        trust_reasons.append("seller_verified")
    else:
        risk_score += 15
        risk_reasons.append("seller_not_verified")

    if int(seller.get("email_verified", 0) or 0) == 1:
        trust_score += 5
        trust_reasons.append("email_verified")
    else:
        risk_score += 5
        risk_reasons.append("email_not_verified")

    if str(seller.get("kyc_status") or "not_provided").lower() in ["verified", "approved"]:
        trust_score += 10
        trust_reasons.append("kyc_verified")
    else:
        risk_score += 5
        risk_reasons.append("kyc_not_verified")

    if str(seller.get("business_verification_status") or "not_provided").lower() in ["verified", "approved"]:
        trust_score += 10
        trust_reasons.append("business_verified")
    else:
        risk_score += 5
        risk_reasons.append("business_not_verified")

    if str(seller.get("tax_verification_status") or "not_provided").lower() in ["verified", "approved"]:
        trust_score += 5
        trust_reasons.append("tax_verified")

    # Catalog risk/trust
    if catalog_verification_status in ["verified", "foundation_verified"]:
        trust_score += 15
        trust_reasons.append("catalog_verified")
    else:
        risk_score += 10
        risk_reasons.append("catalog_not_verified")

    if catalog_availability_status in ["active", "available"]:
        trust_score += 5
        trust_reasons.append("catalog_available")
    elif catalog_availability_status in ["draft", "paused"]:
        risk_score += 5
        risk_reasons.append("catalog_not_active")
    else:
        risk_score += 10
        risk_reasons.append("catalog_unavailable_or_unknown")

    # Agent capacity risk
    remaining_capacity = max_agents_allowed - active_agents
    if requested_agent_count > remaining_capacity:
        risk_score += 30
        risk_reasons.append("requested_agents_exceed_remaining_capacity")

    if requested_agent_count > max_agents_allowed:
        risk_score += 40
        risk_reasons.append("requested_agents_exceed_max_allowed")

    if requested_agent_count <= 0:
        risk_score += 100
        risk_reasons.append("invalid_requested_agent_count")

    if requested_agent_count > 1:
        risk_score += min(10, requested_agent_count * 2)
        risk_reasons.append("multi_agent_factory_request")

    # Economic sanity
    unit_price = float(catalog_item.get("unit_price", 0) or 0)
    if unit_price <= 0:
        risk_score += 10
        risk_reasons.append("missing_or_zero_unit_price")
    else:
        trust_score += 5
        trust_reasons.append("unit_price_defined")

    capacity_per_day = float(catalog_item.get("capacity_per_day", 0) or 0)
    stock_quantity = float(catalog_item.get("stock_quantity", 0) or 0)
    item_type = str(catalog_item.get("item_type") or "").lower()

    if item_type == "service" and capacity_per_day <= 0:
        risk_score += 10
        risk_reasons.append("service_capacity_missing")

    if item_type == "product" and stock_quantity <= 0:
        risk_score += 10
        risk_reasons.append("product_stock_missing")

    # Bound scores.
    risk_score = max(0, min(100, int(risk_score)))
    trust_score = max(0, min(100, int(trust_score)))

    if risk_score <= 20 and trust_score >= 40:
        governance_status = "approved_for_sandbox"
        factory_status = "governance_approved"
        sandbox_status = "queued"
        simulation_status = "waiting_for_sandbox"
        event_type = "factory_governance_approved"
        recommendation = "queue_sandbox"
    elif risk_score <= 50:
        governance_status = "manual_review"
        factory_status = "manual_review_required"
        sandbox_status = "not_started"
        simulation_status = "not_started"
        event_type = "factory_governance_manual_review"
        recommendation = "manual_review"
    else:
        governance_status = "rejected"
        factory_status = "governance_rejected"
        sandbox_status = "blocked"
        simulation_status = "blocked"
        event_type = "factory_governance_rejected"
        recommendation = "reject"

    review_metadata = {
        "factory_request_id": factory_request_id,
        "seller_id": seller.get("seller_id"),
        "catalog_item_id": catalog_item.get("catalog_item_id"),
        "requested_agent_count": requested_agent_count,
        "max_agents_allowed": max_agents_allowed,
        "active_agents": active_agents,
        "remaining_capacity": remaining_capacity,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "risk_reasons": risk_reasons,
        "trust_reasons": trust_reasons,
        "recommendation": recommendation,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE seller_agent_factory_requests
    SET factory_status = {p},
        sandbox_status = {p},
        simulation_status = {p},
        governance_status = {p},
        risk_score = {p},
        trust_score = {p},
        rejection_reason = {p},
        updated_at = {p}
    WHERE factory_request_id = {p}
    """, (
        factory_status,
        sandbox_status,
        simulation_status,
        governance_status,
        risk_score,
        trust_score,
        "factory_governance_rejected" if governance_status == "rejected" else None,
        now,
        factory_request_id,
    ))

    if governance_status == "approved_for_sandbox":
        cur.execute(f"""
        UPDATE seller_catalog_items
        SET agent_creation_status = {p},
            risk_score = {p},
            trust_score = {p},
            updated_at = {p}
        WHERE catalog_item_id = {p}
        """, (
            "approved_for_sandbox",
            risk_score,
            trust_score,
            now,
            catalog_item.get("catalog_item_id"),
        ))
    elif governance_status == "manual_review":
        cur.execute(f"""
        UPDATE seller_catalog_items
        SET agent_creation_status = {p},
            risk_score = {p},
            trust_score = {p},
            updated_at = {p}
        WHERE catalog_item_id = {p}
        """, (
            "manual_review",
            risk_score,
            trust_score,
            now,
            catalog_item.get("catalog_item_id"),
        ))
    elif governance_status == "rejected":
        cur.execute(f"""
        UPDATE seller_catalog_items
        SET agent_creation_status = {p},
            risk_score = {p},
            trust_score = {p},
            updated_at = {p}
        WHERE catalog_item_id = {p}
        """, (
            "factory_rejected",
            risk_score,
            trust_score,
            now,
            catalog_item.get("catalog_item_id"),
        ))

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller.get("seller_id"),
        event_type=event_type,
        reviewer="iat_factory_governance_engine",
        reason=recommendation,
        old_status=str(factory_request.get("governance_status") or "pending"),
        new_status=governance_status,
        metadata=review_metadata,
    )

    conn.commit()
    release_conn(conn)

    updated_request = get_seller_agent_factory_request_db(factory_request_id)

    return {
        "status": "ok",
        "factory_request_id": factory_request_id,
        "governance_status": governance_status,
        "factory_status": factory_status,
        "sandbox_status": sandbox_status,
        "simulation_status": simulation_status,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "recommendation": recommendation,
        "risk_reasons": risk_reasons,
        "trust_reasons": trust_reasons,
        "event": event_result,
        "factory_request": updated_request,
    }



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

    cur.execute("""
    SELECT
        agents.*,
        tmn.memory_score AS threat_memory_score,
        tmn.latent_risk_score AS latent_risk_score,
        tmn.mutation_score AS mutation_score,
        tmn.contagion_score AS contagion_score,
        tmn.lineage_depth AS lineage_depth,
        tmn.ancestor_risk_score AS ancestor_risk_score,
        tmn.descendant_risk_score AS descendant_risk_score,
        tmn.recovery_confidence AS recovery_confidence,
        tmn.threat_entropy AS threat_entropy,
        tmn.graph_position_score AS graph_position_score,
        tmn.quarantine_pressure AS quarantine_pressure,
        tmn.adaptive_trust_score AS adaptive_trust_score,
        tmn.memory_weight AS threat_memory_weight
    FROM agents
    LEFT JOIN threat_memory_nodes tmn
      ON tmn.seller_id = agents.agent_id
    ORDER BY agents.service, agents.agent_id
    """)

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

    if scope == "seller" and subject_id:
        try:
            memories = get_active_threat_memory_db(
                scope="seller",
                subject_id=subject_id,
                limit=25,
            )

            for memory in memories:
                derive_adversarial_mutation_signatures_from_threat_memory_db(
                    subject_id=subject_id,
                    memory=memory,
                )

            recompute_threat_memory_node_db(subject_id)

            sync_adversarial_mutation_pressure_to_memory_node_db(
                subject_id=subject_id,
                scope="seller",
            )
        except Exception:
            pass

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




def list_foundation_agents_db():
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agents
    WHERE agent_type = {p}
    ORDER BY
        COALESCE(foundation_priority, 100) ASC,
        reputation DESC,
        agent_id ASC
    """, ("foundation",))

    rows = cur.fetchall()
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "foundation_agents": [dict(r) for r in rows],
    }


def get_foundation_agents_by_role_db(role):
    if not role:
        return {
            "status": "error",
            "message": "foundation_role_required",
            "foundation_agents": [],
        }

    role = str(role).strip().lower()

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agents
    WHERE agent_type = {p}
      AND LOWER(COALESCE(foundation_role, '')) = {p}
      AND COALESCE(available, 0) = 1
    ORDER BY
        COALESCE(foundation_priority, 100) ASC,
        reputation DESC,
        agent_id ASC
    """, ("foundation", role))

    rows = cur.fetchall()
    release_conn(conn)

    return {
        "status": "ok",
        "foundation_role": role,
        "count": len(rows),
        "foundation_agents": [dict(r) for r in rows],
    }


def get_foundation_agent_profile_db(agent_id):
    if not agent_id:
        return {
            "status": "error",
            "message": "foundation_agent_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM agents
    WHERE agent_id = {p}
      AND agent_type = {p}
    """, (agent_id, "foundation"))

    row = cur.fetchone()
    release_conn(conn)

    if not row:
        return {
            "status": "error",
            "message": "foundation_agent_not_found",
            "agent_id": agent_id,
        }

    agent = dict(row)

    return {
        "status": "ok",
        "foundation_agent": agent,
        "foundation_policy": {
            "protocol_reserved_asset": True,
            "seller_creation_allowed": False,
            "auto_creation_allowed": False,
            "protocol_owner_only_registration": True,
            "governance_authority": "iat_protocol_core_only",
        },
    }




def build_foundation_execution_plan_db(
    service=None,
    required_research_agents=2,
    required_verification_agents=1,
):
    service = str(service or "").strip()

    research_result = get_foundation_agents_by_role_db("research")
    verification_result = get_foundation_agents_by_role_db("verification")

    research_agents = research_result.get("foundation_agents", [])
    verification_agents = verification_result.get("foundation_agents", [])

    if service:
        research_agents = [
            a for a in research_agents
            if str(a.get("service") or "").lower() == service.lower()
        ]
        verification_agents = [
            a for a in verification_agents
            if str(a.get("service") or "").lower() == service.lower()
        ]

    selected_research_agents = research_agents[:max(0, int(required_research_agents or 0))]
    selected_verification_agents = verification_agents[:max(0, int(required_verification_agents or 0))]

    missing_requirements = []

    if len(selected_research_agents) < int(required_research_agents or 0):
        missing_requirements.append("insufficient_research_foundation_agents")

    if len(selected_verification_agents) < int(required_verification_agents or 0):
        missing_requirements.append("insufficient_verification_foundation_agents")

    execution_strategy = (
        "research_then_verification"
        if selected_research_agents and selected_verification_agents
        else "incomplete_foundation_plan"
    )

    plan = {
        "plan_type": "foundation_execution_plan",
        "service": service or None,
        "execution_strategy": execution_strategy,

        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_authority": False,
        "buyer_authority": False,

        "research_agents": selected_research_agents,
        "verification_agents": selected_verification_agents,

        "research_agent_ids": [
            a.get("agent_id") for a in selected_research_agents
        ],
        "verification_agent_ids": [
            a.get("agent_id") for a in selected_verification_agents
        ],

        "required_research_agents": int(required_research_agents or 0),
        "required_verification_agents": int(required_verification_agents or 0),
        "missing_requirements": missing_requirements,

        "foundation_policy": {
            "uses_existing_foundation_registry": True,
            "creates_new_foundation_agents": False,
            "auto_creation_allowed": False,
            "seller_creation_allowed": False,
            "protocol_owner_only_registration": True,
        },
    }

    return {
        "status": "ok" if not missing_requirements else "incomplete",
        "plan": plan,
    }




def execute_foundation_plan_db(order):
    if not isinstance(order, dict):
        return {
            "status": "error",
            "message": "order_dict_required",
        }

    service = order.get("service") or "web_research"

    plan_result = build_foundation_execution_plan_db(
        service=service,
        required_research_agents=2,
        required_verification_agents=1,
    )

    plan = plan_result.get("plan") or {}

    if plan_result.get("status") != "ok":
        return {
            "status": "error",
            "message": "foundation_execution_plan_incomplete",
            "plan_result": plan_result,
        }

    research_agents = plan.get("research_agents") or []
    verification_agents = plan.get("verification_agents") or []

    try:
        from iat.api.multi_exec import (
            multi_call,
            compute_consensus,
            compute_consensus_strength,
            select_best_result,
        )

        research_results = multi_call(research_agents, order)
        research_consensus = compute_consensus(research_results)
        research_strength = compute_consensus_strength(research_results)
        best_research_result = select_best_result(research_results)

        verification_order = {
            **order,
            "foundation_research_results": research_results,
            "foundation_research_consensus": research_consensus,
            "foundation_research_strength": research_strength,
            "execution_phase": "foundation_verification",
        }

        verification_results = multi_call(verification_agents, verification_order)
        verification_consensus = compute_consensus(verification_results)
        verification_strength = compute_consensus_strength(verification_results)
        best_verification_result = select_best_result(verification_results)

    except Exception as exc:
        return {
            "status": "error",
            "message": "foundation_plan_execution_failed",
            "error": str(exc),
            "plan": plan,
        }

    evidence_package = {
        "package_type": "foundation_evidence_package",
        "order_id": order.get("order_id"),
        "service": service,

        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_authority": False,
        "buyer_authority": False,

        "execution_strategy": plan.get("execution_strategy"),
        "research_agent_ids": plan.get("research_agent_ids"),
        "verification_agent_ids": plan.get("verification_agent_ids"),

        "research_results": research_results,
        "research_consensus": research_consensus,
        "research_strength": research_strength,
        "best_research_result": best_research_result,

        "verification_results": verification_results,
        "verification_consensus": verification_consensus,
        "verification_strength": verification_strength,
        "best_verification_result": best_verification_result,

        "foundation_ready_for_decision": bool(
            research_results and verification_results
        ),

        "foundation_policy": {
            "uses_existing_foundation_registry": True,
            "creates_new_foundation_agents": False,
            "auto_creation_allowed": False,
            "seller_creation_allowed": False,
            "protocol_owner_only_registration": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    evaluation_result = evaluate_foundation_evidence_package_db(
        evidence_package
    )

    evidence_package["foundation_evidence_evaluation"] = (
        evaluation_result.get("evaluation")
        if evaluation_result.get("status") == "ok"
        else evaluation_result
    )

    evidence_memory_result = None
    try:
        evidence_memory_result = store_foundation_evidence_memory_db(
            order_id=order.get("order_id"),
            evidence_package=evidence_package,
        )
    except Exception as exc:
        evidence_memory_result = {
            "status": "error",
            "message": "foundation_evidence_memory_store_failed",
            "error": str(exc),
        }

    evidence_package["foundation_evidence_memory_result"] = evidence_memory_result

    return {
        "status": "ok",
        "order_id": order.get("order_id"),
        "plan": plan,
        "evidence_package": evidence_package,
    }




def evaluate_foundation_evidence_package_db(evidence_package):
    if not isinstance(evidence_package, dict):
        return {
            "status": "error",
            "message": "evidence_package_required",
        }

    research_consensus = evidence_package.get("research_consensus") or {}
    verification_consensus = evidence_package.get("verification_consensus") or {}

    research_valid_agents = int(research_consensus.get("valid_agents", 0) or 0)
    verification_valid_agents = int(verification_consensus.get("valid_agents", 0) or 0)

    research_status = str(research_consensus.get("status") or "").lower()
    verification_status = str(verification_consensus.get("status") or "").lower()

    research_score = float(research_consensus.get("score", 0) or 0)
    verification_score = float(verification_consensus.get("score", 0) or 0)

    ready = bool(evidence_package.get("foundation_ready_for_decision"))

    reasons = []
    warnings = []

    confidence_cap = 0.40
    foundation_evidence_status = "insufficient"

    if not ready:
        reasons.append("foundation_package_not_ready")
    else:
        if research_valid_agents >= 2 and research_status == "passed":
            confidence_cap += 0.20
            reasons.append("research_consensus_passed")
        elif research_valid_agents >= 1:
            confidence_cap += 0.10
            warnings.append("research_consensus_not_strong")
        else:
            warnings.append("no_research_foundation_results")

        if verification_valid_agents >= 2 and verification_status == "passed":
            confidence_cap += 0.25
            reasons.append("verification_consensus_passed")
        elif verification_valid_agents == 1:
            confidence_cap += 0.05
            warnings.append("verification_single_source_requires_caution")
        else:
            warnings.append("no_verification_foundation_results")

        if research_score >= 0.60:
            confidence_cap += 0.05

        if verification_score >= 0.60:
            confidence_cap += 0.05

    confidence_cap = round(min(max(confidence_cap, 0.0), 0.90), 4)

    if not ready:
        foundation_evidence_status = "not_ready"
        decision_ready = False
    elif verification_valid_agents == 0:
        foundation_evidence_status = "research_only"
        decision_ready = False
    elif research_valid_agents >= 2 and verification_valid_agents >= 1:
        foundation_evidence_status = "decision_ready_with_caution"
        decision_ready = True
    elif research_valid_agents >= 1 and verification_valid_agents >= 1:
        foundation_evidence_status = "minimal_decision_ready"
        decision_ready = True
    else:
        foundation_evidence_status = "insufficient"
        decision_ready = False

    if verification_valid_agents == 1:
        confidence_cap = min(confidence_cap, 0.65)

    if research_valid_agents < 2:
        confidence_cap = min(confidence_cap, 0.55)

    evaluation = {
        "evaluation_type": "foundation_evidence_package_evaluation",
        "foundation_evidence_status": foundation_evidence_status,
        "foundation_decision_ready": decision_ready,
        "confidence_cap": round(confidence_cap, 4),
        "reason": (
            "verification_single_source_requires_caution"
            if verification_valid_agents == 1
            else ";".join(reasons) if reasons else "foundation_evidence_evaluated"
        ),
        "reasons": reasons,
        "warnings": warnings,

        "research_status": research_status,
        "research_valid_agents": research_valid_agents,
        "research_score": research_score,

        "verification_status": verification_status,
        "verification_valid_agents": verification_valid_agents,
        "verification_score": verification_score,

        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_authority": False,
        "buyer_authority": False,

        "foundation_policy": {
            "uses_existing_foundation_registry": True,
            "creates_new_foundation_agents": False,
            "auto_creation_allowed": False,
            "seller_creation_allowed": False,
            "protocol_owner_only_registration": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    return {
        "status": "ok",
        "evaluation": evaluation,
    }



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

    seller_status_for_exposure = str(
        seller.get("seller_status", "pending") or "pending"
    ).lower()
    verification_status_for_exposure = str(
        seller.get("verification_status", "unverified") or "unverified"
    ).lower()
    risk_score_for_exposure = float(
        seller.get("risk_score", 0) or 0
    )

    initial_exposure_limit = float(
        seller.get("exposure_limit", 0) or 0
    )

    if (
        initial_exposure_limit <= 0
        and seller_status_for_exposure == "active"
        and verification_status_for_exposure in ["verified", "foundation_verified"]
        and risk_score_for_exposure < 0.35
    ):
        initial_exposure_limit = 100.0
    elif initial_exposure_limit <= 0:
        initial_exposure_limit = 10.0

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
        int(seller.get("max_agents_allowed", 5) or 5),
        float(seller.get("stake_amount", 0) or 0),
        initial_exposure_limit,
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





def init_seller_agent_execution_sessions_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agent_execution_sessions (
        execution_session_id TEXT PRIMARY KEY,

        order_id TEXT,
        seller_id TEXT NOT NULL,
        seller_agent_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,

        service TEXT NOT NULL,
        specialization TEXT,

        execution_status TEXT DEFAULT 'queued',

        execution_context TEXT DEFAULT '{}',
        execution_result TEXT DEFAULT '{}',
        verification_result TEXT DEFAULT '{}',

        consensus_score REAL DEFAULT 0,
        risk_score REAL DEFAULT 0,
        trust_score REAL DEFAULT 0,

        failure_reason TEXT,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def create_seller_agent_execution_session_db(payload):
    payload = payload or {}

    seller_id = payload.get("seller_id")
    seller_agent_id = payload.get("seller_agent_id")
    agent_id = payload.get("agent_id")
    service = payload.get("service")

    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    if not agent_id:
        return {"status": "error", "message": "agent_id_required"}

    if not service:
        return {"status": "error", "message": "service_required"}

    execution_session_id = payload.get("execution_session_id") or f"exec_{uuid.uuid4()}"
    now = int(time.time())

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    INSERT INTO seller_agent_execution_sessions (
        execution_session_id,
        order_id,
        seller_id,
        seller_agent_id,
        agent_id,
        service,
        specialization,
        execution_status,
        execution_context,
        execution_result,
        verification_result,
        consensus_score,
        risk_score,
        trust_score,
        failure_reason,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        execution_session_id,
        payload.get("order_id"),
        seller_id,
        seller_agent_id,
        agent_id,
        service,
        payload.get("specialization"),
        payload.get("execution_status", "queued"),
        json.dumps(payload.get("execution_context", {})),
        json.dumps(payload.get("execution_result", {})),
        json.dumps(payload.get("verification_result", {})),
        float(payload.get("consensus_score", 0) or 0),
        float(payload.get("risk_score", 0) or 0),
        float(payload.get("trust_score", 0) or 0),
        payload.get("failure_reason"),
        now,
        now,
        json.dumps(payload.get("metadata", {})),
    ))

    conn.commit()
    release_conn(conn)

    return get_seller_agent_execution_session_db(execution_session_id)


def get_seller_agent_execution_session_db(execution_session_id):
    if not execution_session_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_execution_sessions
    WHERE execution_session_id = {p}
    """, (
        execution_session_id,
    ))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def update_seller_agent_execution_session_db(
    execution_session_id,
    updates,
):
    if not execution_session_id:
        return {"status": "error", "message": "execution_session_id_required"}

    updates = updates or {}

    allowed_fields = {
        "execution_status",
        "execution_result",
        "verification_result",
        "consensus_score",
        "risk_score",
        "trust_score",
        "failure_reason",
        "metadata",
    }

    clean_updates = {
        k: v for k, v in updates.items()
        if k in allowed_fields
    }

    if not clean_updates:
        return {"status": "error", "message": "no_valid_updates"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    set_parts = []
    values = []

    for key, value in clean_updates.items():
        set_parts.append(f"{key} = {p}")
        if key in ["execution_result", "verification_result", "metadata"]:
            values.append(json.dumps(value if value is not None else {}))
        else:
            values.append(value)

    set_parts.append(f"updated_at = {p}")
    values.append(now)
    values.append(execution_session_id)

    cur.execute(f"""
    UPDATE seller_agent_execution_sessions
    SET {", ".join(set_parts)}
    WHERE execution_session_id = {p}
    """, tuple(values))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "execution_session": get_seller_agent_execution_session_db(execution_session_id),
    }




def get_available_seller_execution_agents_db(
    service,
    specialization=None,
    limit=10,
):
    if not service:
        return {
            "status": "error",
            "message": "service_required",
            "agents": [],
        }

    service = str(service).strip().lower()
    specialization = str(specialization).strip().lower() if specialization else None
    limit = int(limit or 10)

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    sql = f"""
    SELECT
        sa.*,
        a.available AS marketplace_available,
        a.seller_status AS registry_seller_status,
        a.verification_status AS registry_verification_status,
        a.buyer_access,
        a.web_access,
        a.raw_prompt_access,
        a.foundation_verdict,
        s.seller_status AS seller_status,
        s.verification_status AS seller_verification_status,
        s.risk_score AS seller_risk_score,
        s.trust_score AS seller_trust_score,
        s.max_agents_allowed AS seller_max_agents_allowed
    FROM seller_agents sa
    JOIN agents a
        ON a.agent_id = sa.agent_id
    JOIN sellers s
        ON s.seller_id = sa.seller_id
    WHERE sa.service = {p}
      AND sa.seller_agent_status = 'active'
      AND sa.runtime_validation_status IN ('healthy', 'validated', 'generated_pending_review')
      AND a.available = 1
      AND a.agent_type = 'seller'
      AND a.seller_status = 'active'
      AND a.verification_status = 'foundation_verified'
      AND COALESCE(a.buyer_access, 0) = 0
      AND COALESCE(a.web_access, 0) = 0
      AND COALESCE(a.raw_prompt_access, 0) = 0
      AND s.seller_status = 'active'
      AND s.verification_status IN ('verified', 'foundation_verified')
    """

    params = [service]

    if specialization:
        sql += f"""
          AND (
                sa.specialties LIKE {p}
                OR sa.capabilities LIKE {p}
              )
        """
        like_value = f"%{specialization}%"
        params.extend([like_value, like_value])

    sql += f"""
    ORDER BY
        sa.runtime_health_score DESC,
        sa.reputation DESC,
        sa.successful_orders DESC,
        s.trust_score DESC,
        s.risk_score ASC
    LIMIT {limit}
    """

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    release_conn(conn)

    agents = [dict(r) for r in rows]

    return {
        "status": "ok",
        "service": service,
        "specialization": specialization,
        "count": len(agents),
        "agents": agents,
    }




def _sanitize_foundation_execution_context(execution_context):
    execution_context = execution_context or {}

    forbidden_keys = {
        "buyer_prompt",
        "raw_buyer_prompt",
        "buyer_wallet",
        "buyer_id",
        "buyer_email",
        "buyer_context",
        "session_id",
        "payment_signature",
        "wallet",
    }

    sanitized = {}

    for key, value in execution_context.items():
        normalized_key = str(key).strip()
        if normalized_key.lower() in forbidden_keys:
            continue
        sanitized[normalized_key] = value

    return sanitized


def run_foundation_controlled_seller_execution_db(
    service,
    execution_context,
    specialization=None,
    order_id=None,
    seller_agent_id=None,
):
    if not service:
        return {
            "status": "error",
            "message": "service_required",
        }

    sanitized_context = _sanitize_foundation_execution_context(
        execution_context or {}
    )

    # Foundation-controlled execution requires a normalized task.
    if not sanitized_context.get("task"):
        return {
            "status": "error",
            "message": "foundation_task_required",
        }

    eligible_result = get_available_seller_execution_agents_db(
        service=service,
        specialization=specialization,
        limit=10,
    )

    if eligible_result.get("status") != "ok":
        return eligible_result

    candidates = eligible_result.get("agents", [])

    if seller_agent_id:
        candidates = [
            a for a in candidates
            if a.get("seller_agent_id") == seller_agent_id
        ]

    if not candidates:
        return {
            "status": "error",
            "message": "no_eligible_seller_execution_agent",
            "service": service,
            "specialization": specialization,
        }

    selected = candidates[0]

    metadata = _safe_json_loads(selected.get("metadata"), {})
    execution_mode = str(metadata.get("execution_mode") or "").lower()

    if execution_mode != "iat_internal":
        return {
            "status": "error",
            "message": "unsupported_execution_mode",
            "execution_mode": execution_mode,
        }

    session = create_seller_agent_execution_session_db({
        "order_id": order_id,
        "seller_id": selected.get("seller_id"),
        "seller_agent_id": selected.get("seller_agent_id"),
        "agent_id": selected.get("agent_id"),
        "service": service,
        "specialization": specialization,
        "execution_status": "executing",
        "execution_context": sanitized_context,
        "metadata": {
            "source": "foundation_controlled_seller_execution",
            "execution_mode": execution_mode,
            "buyer_data_stripped": True,
            "foundation_mediated": True,
        },
    })

    if not session:
        return {
            "status": "error",
            "message": "execution_session_creation_failed",
        }

    execution_session_id = session.get("execution_session_id")

    try:
        # V1 internal execution:
        # Seller agent does not call buyer, web, wallet, or external systems.
        # It only transforms a foundation-normalized execution context into a
        # structured seller contribution.
        execution_result = {
            "status": "ok",
            "execution_mode": "iat_internal",
            "seller_agent_id": selected.get("seller_agent_id"),
            "agent_id": selected.get("agent_id"),
            "service": service,
            "specialization": specialization,
            "result_type": "seller_controlled_contribution",
            "result": {
                "task": sanitized_context.get("task"),
                "scope": sanitized_context.get("scope"),
                "requested_format": sanitized_context.get("required_format"),
                "seller_capabilities": _safe_json_loads(selected.get("capabilities"), []),
                "seller_specialties": _safe_json_loads(selected.get("specialties"), []),
                "note": "V1 internal seller execution completed under foundation mediation.",
            },
        }

        update_result = update_seller_agent_execution_session_db(
            execution_session_id,
            {
                "execution_status": "completed",
                "execution_result": execution_result,
                "trust_score": 50,
                "risk_score": 0,
                "metadata": {
                    "source": "foundation_controlled_seller_execution",
                    "execution_mode": execution_mode,
                    "buyer_data_stripped": True,
                    "foundation_mediated": True,
                    "completed_at": int(time.time()),
                },
            },
        )

        conn = get_conn()
        cur = conn.cursor()

        create_seller_governance_event_with_cursor(
            cur=cur,
            seller_id=selected.get("seller_id"),
            event_type="seller_agent_execution_completed",
            reviewer="iat_foundation_execution_engine",
            reason="foundation_controlled_internal_execution_completed",
            old_status="executing",
            new_status="completed",
            metadata={
                "execution_session_id": execution_session_id,
                "seller_agent_id": selected.get("seller_agent_id"),
                "agent_id": selected.get("agent_id"),
                "service": service,
                "specialization": specialization,
                "buyer_data_stripped": True,
            },
        )

        conn.commit()
        release_conn(conn)

        return {
            "status": "ok",
            "execution_session_id": execution_session_id,
            "selected_seller_agent": {
                "seller_agent_id": selected.get("seller_agent_id"),
                "agent_id": selected.get("agent_id"),
                "seller_id": selected.get("seller_id"),
                "service": selected.get("service"),
                "runtime_health_score": selected.get("runtime_health_score"),
            },
            "execution_result": execution_result,
            "session": update_result.get("execution_session"),
        }

    except Exception as exc:
        update_seller_agent_execution_session_db(
            execution_session_id,
            {
                "execution_status": "failed",
                "failure_reason": str(exc),
                "risk_score": 25,
            },
        )

        return {
            "status": "error",
            "message": "seller_execution_failed",
            "error": str(exc),
            "execution_session_id": execution_session_id,
        }




def _contains_forbidden_buyer_data(obj):
    forbidden_terms = [
        "buyer_prompt",
        "raw_buyer_prompt",
        "buyer_wallet",
        "buyer_id",
        "buyer_email",
        "buyer_context",
        "payment_signature",
        "THIS MUST NOT BE STORED",
        "THIS_MUST_NOT_BE_STORED",
    ]

    try:
        serialized = json.dumps(obj)
    except Exception:
        serialized = str(obj)

    lowered = serialized.lower()

    for term in forbidden_terms:
        if term.lower() in lowered:
            return True, term

    return False, None


def verify_seller_execution_result_db(execution_session_id):
    if not execution_session_id:
        return {
            "status": "error",
            "message": "execution_session_id_required",
        }

    session = get_seller_agent_execution_session_db(execution_session_id)
    if not session:
        return {
            "status": "error",
            "message": "execution_session_not_found",
        }

    risk_score = 0
    trust_score = 0
    passed_checks = []
    failed_checks = []
    manual_review_checks = []

    execution_status = str(session.get("execution_status") or "").lower()

    execution_context = _safe_json_loads(
        session.get("execution_context"),
        {},
    )

    execution_result = _safe_json_loads(
        session.get("execution_result"),
        {},
    )

    metadata = _safe_json_loads(
        session.get("metadata"),
        {},
    )

    if execution_status == "completed":
        trust_score += 20
        passed_checks.append("execution_completed")
    else:
        risk_score += 40
        failed_checks.append("execution_not_completed")

    if isinstance(execution_result, dict) and execution_result:
        trust_score += 10
        passed_checks.append("execution_result_present")
    else:
        risk_score += 30
        failed_checks.append("execution_result_missing")

    if str(execution_result.get("status") or "").lower() == "ok":
        trust_score += 10
        passed_checks.append("execution_result_status_ok")
    else:
        risk_score += 20
        failed_checks.append("execution_result_status_not_ok")

    if str(execution_result.get("execution_mode") or "").lower() == "iat_internal":
        trust_score += 10
        passed_checks.append("execution_mode_iat_internal")
    else:
        risk_score += 20
        manual_review_checks.append("execution_mode_not_iat_internal")

    if metadata.get("buyer_data_stripped") is True:
        trust_score += 15
        passed_checks.append("buyer_data_stripped")
    else:
        risk_score += 30
        failed_checks.append("buyer_data_not_confirmed_stripped")

    if metadata.get("foundation_mediated") is True:
        trust_score += 15
        passed_checks.append("foundation_mediated")
    else:
        risk_score += 30
        failed_checks.append("foundation_mediation_missing")

    context_forbidden, context_term = _contains_forbidden_buyer_data(
        execution_context
    )
    if context_forbidden:
        risk_score += 60
        failed_checks.append(f"forbidden_buyer_data_in_context:{context_term}")
    else:
        trust_score += 10
        passed_checks.append("no_forbidden_buyer_data_in_context")

    result_forbidden, result_term = _contains_forbidden_buyer_data(
        execution_result
    )
    if result_forbidden:
        risk_score += 60
        failed_checks.append(f"forbidden_buyer_data_in_result:{result_term}")
    else:
        trust_score += 10
        passed_checks.append("no_forbidden_buyer_data_in_result")

    risk_score = max(0, min(100, int(risk_score)))
    trust_score = max(0, min(100, int(trust_score)))

    if failed_checks and risk_score >= 60:
        verification_status = "rejected"
        governance_recommendation = "reject_execution_result"
        next_execution_status = "verification_rejected"
        event_type = "seller_execution_verification_rejected"
    elif failed_checks or manual_review_checks or risk_score >= 25:
        verification_status = "manual_review"
        governance_recommendation = "manual_execution_review"
        next_execution_status = "verification_manual_review"
        event_type = "seller_execution_verification_manual_review"
    else:
        verification_status = "approved"
        governance_recommendation = "approve_execution_result"
        next_execution_status = "verified"
        event_type = "seller_execution_verification_approved"

    verification_result = {
        "verification_status": verification_status,
        "governance_recommendation": governance_recommendation,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "manual_review_checks": manual_review_checks,
    }

    update_result = update_seller_agent_execution_session_db(
        execution_session_id,
        {
            "execution_status": next_execution_status,
            "verification_result": verification_result,
            "risk_score": risk_score,
            "trust_score": trust_score,
        },
    )

    conn = get_conn()
    cur = conn.cursor()

    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=session.get("seller_id"),
        event_type=event_type,
        reviewer="iat_seller_execution_verification_engine",
        reason=governance_recommendation,
        old_status=execution_status,
        new_status=next_execution_status,
        metadata={
            "execution_session_id": execution_session_id,
            "seller_agent_id": session.get("seller_agent_id"),
            "agent_id": session.get("agent_id"),
            **verification_result,
        },
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "execution_session_id": execution_session_id,
        "verification_status": verification_status,
        "governance_recommendation": governance_recommendation,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "manual_review_checks": manual_review_checks,
        "session": update_result.get("execution_session"),
    }




def build_verified_seller_contribution_db(execution_session_id):
    if not execution_session_id:
        return {
            "status": "error",
            "message": "execution_session_id_required",
        }

    session = get_seller_agent_execution_session_db(execution_session_id)
    if not session:
        return {
            "status": "error",
            "message": "execution_session_not_found",
        }

    execution_status = str(session.get("execution_status") or "").lower()

    verification_result = _safe_json_loads(
        session.get("verification_result"),
        {},
    )

    execution_result = _safe_json_loads(
        session.get("execution_result"),
        {},
    )

    verification_status = str(
        verification_result.get("verification_status") or ""
    ).lower()

    risk_score = float(session.get("risk_score", 0) or 0)
    trust_score = float(session.get("trust_score", 0) or 0)

    if execution_status != "verified":
        return {
            "status": "error",
            "message": "execution_session_not_verified",
            "execution_status": execution_status,
        }

    if verification_status != "approved":
        return {
            "status": "error",
            "message": "execution_verification_not_approved",
            "verification_status": verification_status,
        }

    # Seller contribution score is NOT governance power.
    # It is only a confidence/input-quality score used by foundation agents.
    contribution_score = 0.20

    if trust_score >= 90 and risk_score <= 5:
        contribution_score = 0.40
    elif trust_score >= 70 and risk_score <= 15:
        contribution_score = 0.30
    elif trust_score >= 50 and risk_score <= 30:
        contribution_score = 0.20
    else:
        contribution_score = 0.10

    if risk_score >= 40:
        contribution_score = min(contribution_score, 0.10)

    contribution = {
        "source_type": "verified_seller_contribution",
        "governance_authority": False,
        "decision_authority": False,
        "seller_id": session.get("seller_id"),
        "seller_agent_id": session.get("seller_agent_id"),
        "agent_id": session.get("agent_id"),
        "order_id": session.get("order_id"),
        "service": session.get("service"),
        "specialization": session.get("specialization"),
        "execution_session_id": execution_session_id,
        "execution_status": execution_status,
        "verification_status": verification_status,
        "risk_score": risk_score,
        "trust_score": trust_score,
        "contribution_score": contribution_score,
        "contribution_score_meaning": "foundation_input_quality_score_not_governance_weight",
        "execution_result": execution_result,
        "verification_result": verification_result,
    }

    return {
        "status": "ok",
        "execution_session_id": execution_session_id,
        "contribution": contribution,
    }




def build_foundation_decision_context_db(order_id):
    if not order_id:
        return {
            "status": "error",
            "message": "order_id_required",
        }

    order = None
    try:
        order = get_order_db(order_id)
    except Exception:
        order = None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT execution_session_id
    FROM seller_agent_execution_sessions
    WHERE order_id = {p}
      AND execution_status = 'verified'
    ORDER BY trust_score DESC, risk_score ASC, updated_at DESC
    """, (
        order_id,
    ))

    rows = cur.fetchall()
    release_conn(conn)

    verified_contributions = []
    skipped_contributions = []

    for row in rows:
        execution_session_id = row_get(row, "execution_session_id")
        contribution_result = build_verified_seller_contribution_db(
            execution_session_id
        )

        if contribution_result.get("status") == "ok":
            verified_contributions.append(
                contribution_result.get("contribution")
            )
        else:
            skipped_contributions.append({
                "execution_session_id": execution_session_id,
                "reason": contribution_result,
            })

    decision_context = {
        "context_type": "foundation_decision_context",
        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_role": "verified_execution_contributor_only",
        "buyer_role": "customer_demand_source_only",
        "order_id": order_id,
        "order": order,
        "verified_seller_contributions": verified_contributions,
        "skipped_contributions": skipped_contributions,
        "contribution_count": len(verified_contributions),
        "foundation_rules": {
            "seller_governance_authority": False,
            "seller_decision_authority": False,
            "buyer_governance_authority": False,
            "buyer_decision_authority": False,
            "seller_contributions_are_inputs_only": True,
            "foundation_agents_keep_final_authority": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }

    return {
        "status": "ok",
        "order_id": order_id,
        "decision_context": decision_context,
    }




def run_foundation_decision_db(order_id):
    if not order_id:
        return {
            "status": "error",
            "message": "order_id_required",
        }

    context_result = build_foundation_decision_context_db(order_id)

    if context_result.get("status") != "ok":
        return context_result

    decision_context = context_result.get("decision_context") or {}
    contributions = decision_context.get("verified_seller_contributions") or []

    seller_contribution_consensus = None
    seller_contribution_strength = None

    try:
        from iat.api.multi_exec import compute_consensus, compute_consensus_strength

        consensus_input_result = build_consensus_inputs_from_verified_contributions_db(order_id)
        consensus_inputs = consensus_input_result.get("results", [])

        seller_contribution_consensus = compute_consensus(consensus_inputs)
        seller_contribution_strength = compute_consensus_strength(consensus_inputs)
    except Exception as exc:
        seller_contribution_consensus = {
            "status": "error",
            "message": "seller_contribution_consensus_failed",
            "error": str(exc),
        }
        seller_contribution_strength = {
            "status": "error",
            "message": "seller_contribution_strength_failed",
            "error": str(exc),
        }

    foundation_execution_result = None
    foundation_evidence_evaluation = None

    try:
        foundation_order = {
            "order_id": order_id,
            "service": (
                decision_context.get("order", {}) or {}
            ).get("service") if isinstance(decision_context.get("order"), dict) else "web_research",
            "query": (
                decision_context.get("order", {}) or {}
            ).get("query") if isinstance(decision_context.get("order"), dict) else order_id,
            "buyer_intent": (
                decision_context.get("order", {}) or {}
            ).get("buyer_intent") if isinstance(decision_context.get("order"), dict) else {},
            "requirements": (
                decision_context.get("order", {}) or {}
            ).get("requirements") if isinstance(decision_context.get("order"), dict) else {},
            "execution_phase": "foundation_decision_support",
        }

        if not foundation_order.get("service"):
            foundation_order["service"] = "web_research"

        foundation_execution_result = execute_foundation_plan_db(foundation_order)
        foundation_evidence_evaluation = (
            foundation_execution_result.get("evidence_package", {})
            .get("foundation_evidence_evaluation")
        )
    except Exception as exc:
        foundation_execution_result = {
            "status": "error",
            "message": "foundation_execution_support_failed",
            "error": str(exc),
        }
        foundation_evidence_evaluation = {
            "foundation_evidence_status": "error",
            "foundation_decision_ready": False,
            "confidence_cap": 0.50,
            "reason": "foundation_execution_support_failed",
        }

    approved_contributions = [
        c for c in contributions
        if c.get("verification_status") == "approved"
        and c.get("decision_authority") is False
        and c.get("governance_authority") is False
    ]

    seller_input_quality_score = 0.0

    if approved_contributions:
        seller_input_quality_score = round(
            sum(float(c.get("contribution_score", 0) or 0) for c in approved_contributions)
            / max(len(approved_contributions), 1),
            4,
        )

    seller_consensus_valid_agents = 0
    seller_consensus_status = None

    if isinstance(seller_contribution_consensus, dict):
        seller_consensus_valid_agents = int(
            seller_contribution_consensus.get("valid_agents", 0) or 0
        )
        seller_consensus_status = seller_contribution_consensus.get("status")

    if not approved_contributions:
        foundation_verdict = "insufficient_seller_input"
        decision_confidence = 0.25
        decision_reason = "no_verified_seller_contributions"
    elif seller_consensus_valid_agents < 2:
        foundation_verdict = "seller_inputs_accepted_as_supporting_evidence"
        decision_confidence = min(0.50, 0.30 + seller_input_quality_score)
        decision_reason = "seller_input_single_source_requires_foundation_confirmation"
    elif seller_consensus_status != "passed":
        foundation_verdict = "seller_inputs_accepted_with_consensus_caution"
        decision_confidence = min(0.55, 0.35 + seller_input_quality_score)
        decision_reason = "seller_contribution_consensus_not_passed"
    elif seller_input_quality_score >= 0.35:
        foundation_verdict = "seller_inputs_accepted_as_supporting_evidence"
        decision_confidence = min(0.75, 0.50 + seller_input_quality_score)
        decision_reason = "verified_seller_contributions_support_foundation_context"
    elif seller_input_quality_score >= 0.20:
        foundation_verdict = "seller_inputs_accepted_with_low_weight"
        decision_confidence = 0.50
        decision_reason = "seller_contributions_valid_but_low_input_quality"
    else:
        foundation_verdict = "seller_inputs_require_additional_foundation_verification"
        decision_confidence = 0.35
        decision_reason = "seller_contribution_quality_too_low"

    if isinstance(foundation_evidence_evaluation, dict):
        confidence_cap = float(
            foundation_evidence_evaluation.get("confidence_cap", 1.0) or 1.0
        )
        decision_confidence = min(float(decision_confidence), confidence_cap)

        if foundation_evidence_evaluation.get("foundation_decision_ready") is False:
            foundation_verdict = "foundation_evidence_not_ready"
            decision_reason = foundation_evidence_evaluation.get(
                "reason",
                "foundation_evidence_not_ready",
            )

    foundation_decision = {
        "decision_type": "foundation_decision",
        "order_id": order_id,
        "foundation_verdict": foundation_verdict,
        "decision_reason": decision_reason,
        "decision_confidence": round(float(decision_confidence), 4),

        "governance_authority": "iat_protocol_core_only",
        "decision_authority": "foundation_agents_only",
        "seller_decision_power": False,
        "seller_governance_power": False,
        "buyer_decision_power": False,
        "buyer_governance_power": False,

        "seller_inputs_used": bool(approved_contributions),
        "seller_input_count": len(approved_contributions),
        "seller_input_quality_score": seller_input_quality_score,

        "seller_inputs_role": "supporting_evidence_only",

        "foundation_execution_used": bool(
            foundation_execution_result
            and foundation_execution_result.get("status") == "ok"
        ),
        "foundation_evidence_evaluation": foundation_evidence_evaluation,
        "foundation_execution_result": foundation_execution_result,

        # Existing protocol consensus engine applied to seller contributions.
        # This is NOT seller governance and NOT seller decision power.
        "seller_contribution_consensus": seller_contribution_consensus,
        "seller_contribution_strength": seller_contribution_strength,

        "foundation_final_authority": True,
        "protocol_core_sovereignty_reserved": True,

        "decision_context": decision_context,
    }

    decision_memory_result = None
    try:
        decision_memory_result = store_foundation_decision_memory_db(
            order_id=order_id,
            foundation_decision=foundation_decision,
        )
    except Exception as exc:
        decision_memory_result = {
            "status": "error",
            "message": "foundation_decision_memory_store_failed",
            "error": str(exc),
        }

    foundation_decision["foundation_decision_memory_result"] = decision_memory_result

    conn = get_conn()
    cur = conn.cursor()

    # Record a governance/audit event. This does not transfer authority to sellers;
    # it records that foundation used seller contributions as supporting evidence.
    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=(
            approved_contributions[0].get("seller_id")
            if approved_contributions else "protocol_core"
        ),
        event_type="foundation_decision_completed",
        reviewer="iat_foundation_decision_engine",
        reason=decision_reason,
        old_status="foundation_decision_pending",
        new_status=foundation_verdict,
        metadata=foundation_decision,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "order_id": order_id,
        "foundation_decision": foundation_decision,
    }




def build_consensus_inputs_from_verified_contributions_db(order_id):
    if not order_id:
        return {
            "status": "error",
            "message": "order_id_required",
            "results": [],
        }

    context_result = build_foundation_decision_context_db(order_id)

    if context_result.get("status") != "ok":
        return {
            **context_result,
            "results": [],
        }

    decision_context = context_result.get("decision_context") or {}
    contributions = decision_context.get("verified_seller_contributions") or []

    results = []

    for contribution in contributions:
        execution_result = contribution.get("execution_result") or {}
        result_payload = execution_result.get("result") or execution_result

        normalized_data = {
            "summary": result_payload.get("note") or result_payload.get("summary"),
            "final_recommendation": result_payload.get("final_recommendation")
                or result_payload.get("scope")
                or result_payload.get("task"),
            "confidence": min(
                1.0,
                max(0.0, float(contribution.get("trust_score", 0) or 0) / 100.0)
            ),
            "claims": [
                str(result_payload.get("task") or ""),
                str(result_payload.get("scope") or ""),
                str(result_payload.get("requested_format") or ""),
            ],
            "entities": [
                str(result_payload.get("scope") or ""),
                str(result_payload.get("service") or contribution.get("service") or ""),
                str(result_payload.get("specialization") or contribution.get("specialization") or ""),
            ],
            "structured_signals": {
                "source_type": "verified_seller_contribution",
                "execution_mode": "iat_internal",
                "seller_inputs_role": "supporting_evidence_only",
                "foundation_final_authority": "true",
            },
            "metrics": {
                "seller_trust_score": contribution.get("trust_score", 0),
                "seller_risk_score": contribution.get("risk_score", 0),
                "contribution_score": contribution.get("contribution_score", 0),
            },
            "raw": {
                "data": result_payload,
            },
        }

        results.append({
            "status": "ok",
            "success": True,
            "source_type": "verified_seller_contribution",
            "agent_id": contribution.get("agent_id"),
            "seller_id": contribution.get("seller_id"),
            "seller_agent_id": contribution.get("seller_agent_id"),
            "order_id": order_id,
            "service": contribution.get("service"),
            "specialization": contribution.get("specialization"),
            "wallet": f"seller:{contribution.get('seller_id')}",
            "reputation": min(
                1.0,
                max(0.0, float(contribution.get("trust_score", 0) or 0) / 100.0)
            ),
            "trust_tier": "verified_seller_contribution",
            "stake_amount": 0,
            "stake_required": 0,
            "success_count": 0,
            "failure_count": 0,
            "latency": 0,

            # Important: contribution_score is input quality, not governance power.
            "contribution_score": contribution.get("contribution_score", 0),
            "governance_authority": False,
            "decision_authority": False,

            # Fields expected by existing consensus utilities.
            "result": result_payload,
            "data": normalized_data,
            "content": json.dumps(normalized_data, sort_keys=True),

            "risk_score": contribution.get("risk_score", 0),
            "trust_score": contribution.get("trust_score", 0),
            "metadata": {
                "source_type": "verified_seller_contribution",
                "execution_session_id": contribution.get("execution_session_id"),
                "seller_inputs_role": "supporting_evidence_only",
                "foundation_final_authority": True,
                "protocol_core_sovereignty_reserved": True,
            },
        })

    return {
        "status": "ok",
        "order_id": order_id,
        "count": len(results),
        "results": results,
        "decision_context": decision_context,
    }



def get_seller_runtime_summary_db(seller_id):
    if not seller_id:
        return {
            "status": "error",
            "message": "seller_id_required",
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT
        COUNT(*) AS total_agents,
        SUM(CASE WHEN seller_agent_status = 'active' THEN 1 ELSE 0 END) AS active_agents,
        SUM(CASE WHEN seller_agent_status = 'capacity_frozen' THEN 1 ELSE 0 END) AS capacity_frozen_agents,
        SUM(CASE WHEN seller_agent_status IN ('disabled', 'quarantined') THEN 1 ELSE 0 END) AS disabled_agents,
        AVG(COALESCE(runtime_health_score, 0)) AS avg_runtime_health_score,
        SUM(COALESCE(runtime_failure_count, 0)) AS runtime_failure_count_total,
        SUM(COALESCE(containment_count, 0)) AS containment_count_total,
        SUM(COALESCE(economic_penalty_level, 0)) AS economic_penalty_level_total
    FROM seller_agents
    WHERE seller_id = {p}
    """, (seller_id,))

    row = cur.fetchone()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "total_agents": int(row_get(row, "total_agents", 0) or 0),
        "active_agents": int(row_get(row, "active_agents", 0) or 0),
        "capacity_frozen_agents": int(row_get(row, "capacity_frozen_agents", 0) or 0),
        "disabled_agents": int(row_get(row, "disabled_agents", 0) or 0),
        "avg_runtime_health_score": float(row_get(row, "avg_runtime_health_score", 0) or 0),
        "runtime_failure_count_total": int(row_get(row, "runtime_failure_count_total", 0) or 0),
        "containment_count_total": int(row_get(row, "containment_count_total", 0) or 0),
        "economic_penalty_level_total": int(row_get(row, "economic_penalty_level_total", 0) or 0),
    }


def orchestrate_seller_runtime_governance_db(seller_id):
    if not seller_id:
        return {
            "status": "error",
            "message": "seller_id_required",
        }

    seller_before = get_seller_db(seller_id)
    if not seller_before:
        return {
            "status": "error",
            "message": "seller_not_found",
            "seller_id": seller_id,
        }

    runtime_summary = get_seller_runtime_summary_db(seller_id)

    # Synchronize seller-level runtime health from seller agents before
    # capacity recompute. This prevents the capacity engine from using
    # stale seller.runtime_health_score values.
    synced_runtime_health_score = float(
        runtime_summary.get("avg_runtime_health_score", 0) or 0
    )

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    UPDATE sellers
    SET runtime_health_score = {p},
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        synced_runtime_health_score,
        now,
        seller_id,
    ))

    conn.commit()
    release_conn(conn)

    capacity_result = recompute_seller_dynamic_agent_capacity_db(seller_id)

    seller_after = get_seller_db(seller_id)

    adaptive_policy = None
    try:
        adaptive_policy = get_active_adaptive_policy_db(
            scope="seller",
            service=seller_id,
        )
    except Exception as exc:
        adaptive_policy = {
            "status": "error",
            "message": "adaptive_policy_lookup_failed",
            "error": str(exc),
        }

    summary = {
        "seller_id": seller_id,
        "seller_status_before": seller_before.get("seller_status"),
        "seller_status_after": seller_after.get("seller_status") if seller_after else None,
        "risk_score_before": seller_before.get("risk_score"),
        "risk_score_after": seller_after.get("risk_score") if seller_after else None,
        "trust_score_before": seller_before.get("trust_score"),
        "trust_score_after": seller_after.get("trust_score") if seller_after else None,
        "max_agents_allowed_before": seller_before.get("max_agents_allowed"),
        "max_agents_allowed_after": seller_after.get("max_agents_allowed") if seller_after else None,
        "runtime_health_score_before": seller_before.get("runtime_health_score"),
        "runtime_health_score_after": seller_after.get("runtime_health_score") if seller_after else None,
    }

    now = int(time.time())

    report = {
        "seller_id": seller_id,
        "runtime_summary": runtime_summary,
        "capacity_result": capacity_result,
        "adaptive_policy": adaptive_policy,
        "summary": summary,
        "orchestrator_version": "v1",
        "created_at": now,
    }

    conn = get_conn()
    cur = conn.cursor()

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="seller_runtime_orchestrated",
        reviewer="iat_seller_runtime_orchestrator",
        reason="runtime_capacity_policy_orchestration",
        old_status=str(seller_before.get("seller_status")),
        new_status=str(seller_after.get("seller_status") if seller_after else seller_before.get("seller_status")),
        metadata=report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "runtime_summary": runtime_summary,
        "capacity_result": capacity_result,
        "adaptive_policy": adaptive_policy,
        "summary": summary,
        "event": event_result,
    }



def recompute_seller_dynamic_agent_capacity_db(seller_id):
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
            "seller_id": seller_id,
        }

    seller_status = str(seller.get("seller_status") or "pending").lower()
    verification_status = str(seller.get("verification_status") or "unverified").lower()

    current_capacity = int(seller.get("max_agents_allowed", 5) or 5)
    active_agents = int(seller.get("active_agents", 0) or 0)

    trust_score = float(seller.get("trust_score", 0) or 0)
    risk_score = float(seller.get("risk_score", 0) or 0)
    reputation = float(seller.get("reputation", 0.5) or 0.5)
    runtime_health_score = float(seller.get("runtime_health_score", 0) or 0)

    successful_orders = int(seller.get("successful_orders", 0) or 0)
    failed_orders = int(seller.get("failed_orders", 0) or 0)
    containment_count = int(seller.get("containment_count", 0) or 0)
    economic_penalty_level = int(seller.get("economic_penalty_level", 0) or 0)

    trust_component = max(0.0, min(trust_score, 100.0)) * 0.40
    runtime_component = max(0.0, min(runtime_health_score, 1.0)) * 20.0
    reputation_component = max(0.0, min(reputation, 1.0)) * 20.0

    total_orders = successful_orders + failed_orders
    if total_orders > 0:
        success_rate = successful_orders / max(total_orders, 1)
        success_component = success_rate * 20.0
    else:
        success_rate = 0.0
        success_component = 0.0

    risk_penalty = max(0.0, min(risk_score, 1.0)) * 40.0

    if total_orders > 0:
        failure_rate = failed_orders / max(total_orders, 1)
        failure_penalty = failure_rate * 20.0
    else:
        failure_rate = 0.0
        failure_penalty = 0.0

    containment_penalty = min(containment_count * 10.0, 20.0)
    economic_penalty = min(economic_penalty_level * 10.0, 20.0)

    capacity_score = (
        trust_component
        + runtime_component
        + reputation_component
        + success_component
        - risk_penalty
        - failure_penalty
        - containment_penalty
        - economic_penalty
    )

    capacity_score = max(0.0, min(100.0, round(capacity_score, 2)))

    if seller_status in ["banned", "rejected"]:
        target_capacity = 0
        decision_reason = "terminal_seller_status"
    elif seller_status in ["contained", "restricted"]:
        target_capacity = 1
        decision_reason = "contained_or_restricted_seller"
    elif risk_score >= 0.85:
        target_capacity = 1
        decision_reason = "critical_risk_score"
    elif risk_score >= 0.65 or seller_status in ["limited", "watchlist"]:
        target_capacity = 5
        decision_reason = "high_risk_or_limited_status"
    elif verification_status not in ["verified", "foundation_verified"]:
        target_capacity = min(5, current_capacity)
        decision_reason = "seller_not_fully_verified"
    elif capacity_score < 20:
        target_capacity = 1
        decision_reason = "capacity_score_below_20"
    elif capacity_score < 40:
        target_capacity = 5
        decision_reason = "capacity_score_20_39"
    elif capacity_score < 60:
        target_capacity = 10
        decision_reason = "capacity_score_40_59"
    elif capacity_score < 80:
        target_capacity = 20
        decision_reason = "capacity_score_60_79"
    else:
        target_capacity = 50
        decision_reason = "capacity_score_80_plus"

    # Progressive growth, immediate degradation.
    if target_capacity > current_capacity:
        if current_capacity <= 0:
            new_capacity = min(target_capacity, 5)
        else:
            new_capacity = min(target_capacity, max(current_capacity + 5, current_capacity * 2))
        capacity_direction = "increase"
    elif target_capacity < current_capacity:
        new_capacity = target_capacity
        capacity_direction = "decrease"
    else:
        new_capacity = current_capacity
        capacity_direction = "unchanged"

    # New or pending sellers should not jump above 5.
    if seller_status in ["pending", "new"]:
        new_capacity = min(new_capacity, 5)

    # IAT onboarding rule:
    # a verified, active seller keeps a 5-agent floor unless real risk escalates.
    # Runtime/capacity score can slow growth, but should not destroy onboarding capacity.
    if (
        seller_status == "active"
        and verification_status in ["verified", "foundation_verified"]
        and risk_score < 0.35
        and containment_count == 0
        and economic_penalty_level == 0
    ):
        new_capacity = max(new_capacity, 5)
        if target_capacity < 5:
            decision_reason = "verified_low_risk_seller_floor"

    if new_capacity > current_capacity:
        capacity_direction = "increase"
    elif new_capacity < current_capacity:
        capacity_direction = "decrease"
    else:
        capacity_direction = "unchanged"

    new_capacity = int(max(0, min(new_capacity, 50)))

    now = int(time.time())

    capacity_report = {
        "seller_id": seller_id,
        "seller_status": seller_status,
        "verification_status": verification_status,
        "old_max_agents_allowed": current_capacity,
        "new_max_agents_allowed": new_capacity,
        "target_capacity": target_capacity,
        "capacity_direction": capacity_direction,
        "capacity_score": capacity_score,
        "decision_reason": decision_reason,
        "active_agents": active_agents,
        "components": {
            "trust_component": round(trust_component, 4),
            "runtime_component": round(runtime_component, 4),
            "reputation_component": round(reputation_component, 4),
            "success_component": round(success_component, 4),
            "risk_penalty": round(risk_penalty, 4),
            "failure_penalty": round(failure_penalty, 4),
            "containment_penalty": round(containment_penalty, 4),
            "economic_penalty": round(economic_penalty, 4),
        },
        "raw_inputs": {
            "trust_score": trust_score,
            "runtime_health_score": runtime_health_score,
            "reputation": reputation,
            "risk_score": risk_score,
            "successful_orders": successful_orders,
            "failed_orders": failed_orders,
            "containment_count": containment_count,
            "economic_penalty_level": economic_penalty_level,
        },
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    UPDATE sellers
    SET max_agents_allowed = {p},
        updated_at = {p},
        metadata = {p}
    WHERE seller_id = {p}
    """, (
        new_capacity,
        now,
        json.dumps({
            **_safe_json_loads(seller.get("metadata"), {}),
            "last_dynamic_capacity_report": capacity_report,
        }),
        seller_id,
    ))

    frozen_agents = []

    if active_agents > new_capacity:
        freeze_count = active_agents - new_capacity

        cur.execute(f"""
        SELECT
            seller_agent_id,
            agent_id,
            runtime_health_score,
            reputation,
            successful_orders
        FROM seller_agents
        WHERE seller_id = {p}
          AND seller_agent_status = 'active'
        ORDER BY
            runtime_health_score ASC,
            reputation ASC,
            successful_orders ASC,
            updated_at ASC
        LIMIT {int(freeze_count)}
        """, (
            seller_id,
        ))

        rows_to_freeze = cur.fetchall()

        for row in rows_to_freeze:
            seller_agent_id_to_freeze = row_get(row, "seller_agent_id")
            agent_id_to_freeze = row_get(row, "agent_id")

            cur.execute(f"""
            UPDATE seller_agents
            SET seller_agent_status = {p},
                updated_at = {p}
            WHERE seller_agent_id = {p}
            """, (
                "capacity_frozen",
                now,
                seller_agent_id_to_freeze,
            ))

            if agent_id_to_freeze:
                cur.execute(f"""
                UPDATE agents
                SET available = 0,
                    seller_status = {p},
                    foundation_verdict = {p},
                    updated_at = {p}
                WHERE agent_id = {p}
                """, (
                    "capacity_frozen",
                    "auto_frozen_capacity_limit",
                    now,
                    agent_id_to_freeze,
                ))

            frozen_agent = {
                "seller_agent_id": seller_agent_id_to_freeze,
                "agent_id": agent_id_to_freeze,
                "reason": "active_agents_exceeded_dynamic_capacity",
            }
            frozen_agents.append(frozen_agent)

            create_seller_governance_event_with_cursor(
                cur=cur,
                seller_id=seller_id,
                event_type="seller_agent_auto_frozen",
                reviewer="iat_dynamic_agent_capacity_engine",
                reason="active_agents_exceeded_dynamic_capacity",
                old_status="active",
                new_status="capacity_frozen",
                metadata={
                    **capacity_report,
                    "frozen_agent": frozen_agent,
                },
            )

    capacity_report["frozen_agents"] = frozen_agents

    reactivated_agents = []

    if new_capacity > active_agents:
        available_slots = new_capacity - active_agents

        cur.execute(f"""
        SELECT
            seller_agent_id,
            agent_id,
            runtime_health_score,
            reputation,
            successful_orders
        FROM seller_agents
        WHERE seller_id = {p}
          AND seller_agent_status = 'capacity_frozen'
        ORDER BY
            runtime_health_score DESC,
            reputation DESC,
            successful_orders DESC,
            updated_at ASC
        LIMIT {int(available_slots)}
        """, (
            seller_id,
        ))

        rows_to_reactivate = cur.fetchall()

        for row in rows_to_reactivate:
            seller_agent_id_to_reactivate = row_get(row, "seller_agent_id")
            agent_id_to_reactivate = row_get(row, "agent_id")

            cur.execute(f"""
            UPDATE seller_agents
            SET seller_agent_status = {p},
                updated_at = {p}
            WHERE seller_agent_id = {p}
            """, (
                "active",
                now,
                seller_agent_id_to_reactivate,
            ))

            if agent_id_to_reactivate:
                cur.execute(f"""
                UPDATE agents
                SET available = 1,
                    seller_status = {p},
                    verification_status = {p},
                    buyer_access = 0,
                    web_access = 0,
                    raw_prompt_access = 0,
                    foundation_verdict = {p},
                    updated_at = {p}
                WHERE agent_id = {p}
                """, (
                    "active",
                    "foundation_verified",
                    "auto_reactivated_capacity_available",
                    now,
                    agent_id_to_reactivate,
                ))

            reactivated_agent = {
                "seller_agent_id": seller_agent_id_to_reactivate,
                "agent_id": agent_id_to_reactivate,
                "reason": "dynamic_capacity_available",
            }
            reactivated_agents.append(reactivated_agent)

            create_seller_governance_event_with_cursor(
                cur=cur,
                seller_id=seller_id,
                event_type="seller_agent_auto_reactivated",
                reviewer="iat_dynamic_agent_capacity_engine",
                reason="dynamic_capacity_available",
                old_status="capacity_frozen",
                new_status="active",
                metadata={
                    **capacity_report,
                    "reactivated_agent": reactivated_agent,
                },
            )

    capacity_report["reactivated_agents"] = reactivated_agents

    if new_capacity > current_capacity:
        event_type = "seller_capacity_increased"
    elif new_capacity < current_capacity:
        event_type = "seller_capacity_decreased"
    else:
        event_type = "seller_capacity_unchanged"

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type=event_type,
        reviewer="iat_dynamic_agent_capacity_engine",
        reason=decision_reason,
        old_status=str(current_capacity),
        new_status=str(new_capacity),
        metadata=capacity_report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "old_max_agents_allowed": current_capacity,
        "new_max_agents_allowed": new_capacity,
        "target_capacity": target_capacity,
        "capacity_direction": capacity_direction,
        "capacity_score": capacity_score,
        "decision_reason": decision_reason,
        "active_agents": active_agents,
        "frozen_agents": frozen_agents,
        "reactivated_agents": reactivated_agents,
        "event": event_result,
        "report": capacity_report,
    }



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
    max_agents_allowed = int(seller.get("max_agents_allowed", 5) or 5)

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








def store_seller_agent_activation_approval_db(
    seller_agent_id,
    agent_id,
    seller_id,
    approved_by,
    approval_reason="",
    metadata=None,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    if not approved_by:
        return {"status": "error", "message": "approved_by_required"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "activation_approval_informs_protocol": True,
        "activation_approval_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_activation_approvals (
        seller_agent_id,
        agent_id,
        seller_id,
        approved_by,
        approval_reason,
        status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_agent_id,
        agent_id,
        seller_id,
        approved_by,
        approval_reason,
        "approved",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    approval_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "approval_id": approval_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "approved_by": approved_by,
    }


def get_seller_agent_activation_approvals_db(
    seller_agent_id=None,
    agent_id=None,
    seller_id=None,
    status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if agent_id:
        where.append(f"agent_id = {p}")
        params.append(agent_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if status:
        where.append(f"status = {p}")
        params.append(status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_activation_approvals
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "approvals": rows,
    }



def get_seller_agent_runtime_actions_db(
    seller_agent_id=None,
    agent_id=None,
    seller_id=None,
    action_type=None,
    execution_status=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if agent_id:
        where.append(f"agent_id = {p}")
        params.append(agent_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if action_type:
        where.append(f"action_type = {p}")
        params.append(action_type)

    if execution_status:
        where.append(f"execution_status = {p}")
        params.append(execution_status)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_runtime_actions
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "actions": rows,
    }


def create_seller_agent_runtime_action_db(
    seller_agent_id,
    action_type,
    action_reason="",
    executed_by="iat_core",
    severity="medium",
    metadata=None,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    allowed_actions = ["warn", "throttle", "quarantine", "suspend", "reactivate", "slash"]
    if action_type not in allowed_actions:
        return {
            "status": "error",
            "message": "invalid_runtime_action",
            "allowed_actions": allowed_actions,
        }

    seller_agent = get_seller_agent_db(seller_agent_id)
    if not seller_agent:
        return {"status": "error", "message": "seller_agent_not_found"}

    agent_id = seller_agent.get("agent_id")
    seller_id = seller_agent.get("seller_id")

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    previous_status = seller_agent.get("seller_agent_status")

    previous_available = 0
    cur.execute(f"SELECT available FROM agents WHERE agent_id = {p}", (agent_id,))
    agent_row = cur.fetchone()
    if agent_row:
        previous_available = int(row_get(agent_row, "available", 0) or 0)

    new_status = previous_status
    new_available = previous_available
    runtime_validation_status = seller_agent.get("runtime_validation_status") or "unknown"
    runtime_health_score = float(seller_agent.get("runtime_health_score", 0) or 0)

    if action_type == "warn":
        new_status = previous_status or "active"
        new_available = previous_available
        runtime_validation_status = "runtime_warning"
        runtime_health_score = min(runtime_health_score, 0.75)

    elif action_type == "throttle":
        new_status = "throttled"
        new_available = 1
        runtime_validation_status = "runtime_throttled"
        runtime_health_score = min(runtime_health_score, 0.50)

    elif action_type == "quarantine":
        new_status = "quarantined"
        new_available = 0
        runtime_validation_status = "runtime_quarantined"
        runtime_health_score = min(runtime_health_score, 0.20)

    elif action_type == "suspend":
        new_status = "suspended"
        new_available = 0
        runtime_validation_status = "runtime_suspended"
        runtime_health_score = 0.0

    elif action_type == "reactivate":
        new_status = "active"
        new_available = 1
        runtime_validation_status = "healthy"
        runtime_health_score = max(runtime_health_score, 0.85)

    elif action_type == "slash":
        new_status = "suspended"
        new_available = 0
        runtime_validation_status = "runtime_slashed"
        runtime_health_score = 0.0

    metadata = metadata or {}
    metadata = {
        **metadata,
        "runtime_action_informs_protocol": True,
        "runtime_action_governs_agent": True,
        "seller_cannot_self_execute_runtime_action": True,
        "protocol_core_sovereignty_reserved": True,
    }

    cur.execute(f"""
    INSERT INTO seller_agent_runtime_actions (
        seller_agent_id,
        agent_id,
        seller_id,
        action_type,
        action_reason,
        previous_status,
        new_status,
        previous_available,
        new_available,
        severity,
        executed_by,
        execution_status,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_agent_id,
        agent_id,
        seller_id,
        action_type,
        action_reason,
        previous_status,
        new_status,
        previous_available,
        new_available,
        severity,
        executed_by,
        "executed",
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    action_id = get_last_insert_id_db(cur)

    cur.execute(f"""
    UPDATE seller_agents
    SET seller_agent_status = {p},
        runtime_validation_status = {p},
        runtime_health_score = {p},
        runtime_last_checked_at = {p},
        updated_at = {p}
    WHERE seller_agent_id = {p}
    """, (
        new_status,
        runtime_validation_status,
        runtime_health_score,
        now,
        now,
        seller_agent_id,
    ))

    cur.execute(f"""
    UPDATE agents
    SET available = {p},
        seller_status = {p},
        updated_at = {p}
    WHERE agent_id = {p}
    """, (
        new_available,
        new_status,
        now,
        agent_id,
    ))

    conn.commit()
    release_conn(conn)

    runtime_seller_risk_map = {
        "warn": 0.05,
        "throttle": 0.20,
        "quarantine": 0.50,
        "slash": 0.75,
    }

    seller_risk_application = None
    seller_capacity_recompute = None

    if action_type in runtime_seller_risk_map:
        try:
            seller_risk_application = apply_seller_risk_event_db(
                seller_id=seller_id,
                event_type=f"runtime_{action_type}",
                severity=runtime_seller_risk_map[action_type],
                reason=json.dumps({
                    "source": "create_seller_agent_runtime_action_db",
                    "seller_agent_id": seller_agent_id,
                    "agent_id": agent_id,
                    "action_id": action_id,
                    "action_type": action_type,
                    "action_reason": action_reason,
                    "severity": severity,
                }),
            )

            seller_capacity_recompute = recompute_seller_dynamic_agent_capacity_db(
                seller_id
            )

            try:
                store_seller_runtime_risk_event_db(
                    seller_id=seller_id,
                    seller_agent_id=seller_agent_id,
                    agent_id=agent_id,
                    source_action_id=action_id,
                    source_action_type=action_type,
                    risk_delta=(
                        seller_risk_application.get("new_risk_score", 0)
                        - seller_risk_application.get("old_risk_score", 0)
                    ),
                    trust_delta=0,
                    previous_seller_risk=seller_risk_application.get("old_risk_score", 0),
                    new_seller_risk=seller_risk_application.get("new_risk_score", 0),
                    previous_seller_trust=0,
                    new_seller_trust=0,
                    previous_max_agents_allowed=seller_risk_application.get("old_max_agents_allowed"),
                    new_max_agents_allowed=seller_risk_application.get("new_max_agents_allowed"),
                    previous_exposure_limit=0,
                    new_exposure_limit=seller_risk_application.get("new_exposure_limit", 0),
                    propagation_reason=f"Runtime action propagated to seller risk: {action_type}",
                    severity=severity,
                    metadata={
                        "source": "create_seller_agent_runtime_action_db",
                        "seller_risk_application": seller_risk_application,
                        "seller_capacity_recompute": seller_capacity_recompute,
                    },
                )
            except Exception:
                pass

        except Exception as e:
            seller_risk_application = {
                "status": "error",
                "message": "runtime_seller_risk_propagation_failed",
                "error": str(e),
            }

    return {
        "status": "executed",
        "action_id": action_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "action_type": action_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "previous_available": previous_available,
        "new_available": new_available,
        "runtime_validation_status": runtime_validation_status,
        "runtime_health_score": runtime_health_score,
        "seller_risk_application": seller_risk_application,
        "seller_capacity_recompute": seller_capacity_recompute,
        "policy": {
            "runtime_action_governs_agent": True,
            "runtime_action_propagates_to_seller_risk": action_type in runtime_seller_risk_map,
            "seller_cannot_self_execute_runtime_action": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def approve_seller_agent_activation_request_db(
    seller_agent_id,
    approved_by="iat_core",
    approval_reason="",
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    seller_agent = get_seller_agent_db(seller_agent_id)
    if not seller_agent:
        return {
            "status": "error",
            "message": "seller_agent_not_found",
            "seller_agent_id": seller_agent_id,
        }

    agent_id = seller_agent.get("agent_id")
    seller_id = seller_agent.get("seller_id")

    review_evaluation = evaluate_seller_agent_activation_governance_reviews_db(
        seller_agent_id=seller_agent_id
    )

    if review_evaluation.get("readiness") != "ready_for_activation_approval":
        return {
            "status": "error",
            "message": "activation_request_not_ready_for_approval",
            "seller_agent_id": seller_agent_id,
            "agent_id": agent_id,
            "seller_id": seller_id,
            "review_evaluation": review_evaluation,
            "policy": {
                "activation_reviews_required": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    existing_approvals = get_seller_agent_activation_approvals_db(
        seller_agent_id=seller_agent_id,
        status="approved",
        limit=1,
    )

    if existing_approvals.get("count", 0) > 0:
        return {
            "status": "already_approved",
            "seller_agent_id": seller_agent_id,
            "agent_id": agent_id,
            "seller_id": seller_id,
            "approval": existing_approvals.get("approvals", [None])[0],
            "review_evaluation": review_evaluation,
            "policy": {
                "activation_reviews_required": True,
                "seller_cannot_self_approve": True,
                "activation_approval_required_before_final_activation": True,
                "duplicate_approval_prevented": True,
                "protocol_core_sovereignty_reserved": True,
            },
        }

    approval = store_seller_agent_activation_approval_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        approved_by=approved_by,
        approval_reason=approval_reason,
        metadata={
            "review_evaluation": review_evaluation,
            "approval_source": "approve_seller_agent_activation_request_db",
        },
    )

    return {
        "status": "approved",
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "approval": approval,
        "review_evaluation": review_evaluation,
        "policy": {
            "activation_reviews_required": True,
            "seller_cannot_self_approve": True,
            "activation_approval_required_before_final_activation": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }



def store_seller_agent_activation_governance_review_db(
    seller_agent_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    agent_id=None,
    seller_id=None,
    review_reason="",
    confidence_score=0,
    risk_score=0,
    activation_score=0,
    policy_score=0,
    safety_score=0,
    metadata=None,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    if not reviewer_type or not reviewer_id:
        return {"status": "error", "message": "reviewer_required"}

    if review_decision not in ["approve", "reject", "abstain", "needs_more_evidence"]:
        return {"status": "error", "message": "invalid_review_decision"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "activation_review_informs_protocol": True,
        "activation_review_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_activation_governance_reviews (
        seller_agent_id,
        agent_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        activation_score,
        policy_score,
        safety_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_agent_id,
        agent_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        round(float(activation_score or 0), 4),
        round(float(policy_score or 0), 4),
        round(float(safety_score or 0), 4),
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "review_decision": review_decision,
    }


def get_seller_agent_activation_governance_reviews_db(
    seller_agent_id=None,
    agent_id=None,
    seller_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if agent_id:
        where.append(f"agent_id = {p}")
        params.append(agent_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_activation_governance_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_seller_agent_activation_governance_reviews_db(
    seller_agent_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
    min_avg_activation=0.70,
    min_avg_policy=0.70,
    min_avg_safety=0.70,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    reviews_result = get_seller_agent_activation_governance_reviews_db(
        seller_agent_id=seller_agent_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [r for r in reviews if r.get("review_decision") == "approve"]
    reject_reviews = [r for r in reviews if r.get("review_decision") == "reject"]
    evidence_reviews = [r for r in reviews if r.get("review_decision") == "needs_more_evidence"]
    abstain_reviews = [r for r in reviews if r.get("review_decision") == "abstain"]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(evidence_reviews)
    abstain_count = len(abstain_reviews)

    scoring_reviews = [
        r for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    def avg(field, default=0):
        values = [float(r.get(field, default) or default) for r in scoring_reviews]
        return sum(values) / len(values) if values else default

    avg_confidence = avg("confidence_score", 0)
    avg_risk = avg("risk_score", 1)
    avg_activation = avg("activation_score", 0)
    avg_policy = avg("policy_score", 0)
    avg_safety = avg("safety_score", 0)

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"
    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"
    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"
    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"
    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"
    elif avg_activation < min_avg_activation:
        readiness = "blocked"
        reason = "average_activation_score_too_low"
    elif avg_policy < min_avg_policy:
        readiness = "blocked"
        reason = "average_policy_score_too_low"
    elif avg_safety < min_avg_safety:
        readiness = "blocked"
        reason = "average_safety_score_too_low"
    elif approve_count >= int(min_reviews or 2):
        readiness = "ready_for_activation_approval"
        reason = "activation_review_threshold_met"

    return {
        "status": "ok",
        "seller_agent_id": seller_agent_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "avg_activation": round(avg_activation, 4),
            "avg_policy": round(avg_policy, 4),
            "avg_safety": round(avg_safety, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
            "min_avg_activation": min_avg_activation,
            "min_avg_policy": min_avg_policy,
            "min_avg_safety": min_avg_safety,
        },
        "policy": {
            "activation_reviews_inform_protocol": True,
            "activation_reviews_do_not_govern_protocol": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }




def store_seller_agent_runtime_review_db(
    seller_agent_id,
    reviewer_type,
    reviewer_id,
    review_decision,
    agent_id=None,
    seller_id=None,
    review_reason="",
    confidence_score=0,
    risk_score=0,
    runtime_score=0,
    policy_score=0,
    safety_score=0,
    metadata=None,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    if not reviewer_type or not reviewer_id:
        return {"status": "error", "message": "reviewer_required"}

    if review_decision not in ["approve", "reject", "abstain", "needs_more_evidence"]:
        return {"status": "error", "message": "invalid_review_decision"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "runtime_review_informs_protocol": True,
        "runtime_review_governs_protocol": False,
        "seller_cannot_self_approve": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_runtime_reviews (
        seller_agent_id,
        agent_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        confidence_score,
        risk_score,
        runtime_score,
        policy_score,
        safety_score,
        metadata,
        created_at,
        updated_at
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_agent_id,
        agent_id,
        seller_id,
        reviewer_type,
        reviewer_id,
        review_decision,
        review_reason,
        round(float(confidence_score or 0), 4),
        round(float(risk_score or 0), 4),
        round(float(runtime_score or 0), 4),
        round(float(policy_score or 0), 4),
        round(float(safety_score or 0), 4),
        json.dumps(metadata, sort_keys=True),
        now,
        now,
    ))

    review_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "review_decision": review_decision,
    }


def get_seller_agent_runtime_reviews_db(
    seller_agent_id=None,
    agent_id=None,
    seller_id=None,
    reviewer_type=None,
    reviewer_id=None,
    review_decision=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if agent_id:
        where.append(f"agent_id = {p}")
        params.append(agent_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if reviewer_type:
        where.append(f"reviewer_type = {p}")
        params.append(reviewer_type)

    if reviewer_id:
        where.append(f"reviewer_id = {p}")
        params.append(reviewer_id)

    if review_decision:
        where.append(f"review_decision = {p}")
        params.append(review_decision)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_runtime_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }


def evaluate_seller_agent_runtime_reviews_db(
    seller_agent_id,
    min_reviews=2,
    max_avg_risk=0.60,
    min_avg_confidence=0.65,
    min_avg_runtime=0.70,
    min_avg_policy=0.70,
    min_avg_safety=0.70,
):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    reviews_result = get_seller_agent_runtime_reviews_db(
        seller_agent_id=seller_agent_id,
        limit=100,
    )

    reviews = reviews_result.get("reviews", [])

    approve_reviews = [r for r in reviews if r.get("review_decision") == "approve"]
    reject_reviews = [r for r in reviews if r.get("review_decision") == "reject"]
    evidence_reviews = [r for r in reviews if r.get("review_decision") == "needs_more_evidence"]
    abstain_reviews = [r for r in reviews if r.get("review_decision") == "abstain"]

    total_reviews = len(reviews)
    approve_count = len(approve_reviews)
    reject_count = len(reject_reviews)
    needs_more_evidence_count = len(evidence_reviews)
    abstain_count = len(abstain_reviews)

    scoring_reviews = [
        r for r in reviews
        if r.get("review_decision") in ("approve", "reject", "needs_more_evidence")
    ]

    def avg(field, default=0):
        values = [float(r.get(field, default) or default) for r in scoring_reviews]
        return sum(values) / len(values) if values else default

    avg_confidence = avg("confidence_score", 0)
    avg_risk = avg("risk_score", 1)
    avg_runtime = avg("runtime_score", 0)
    avg_policy = avg("policy_score", 0)
    avg_safety = avg("safety_score", 0)

    readiness = "needs_more_reviews"
    reason = "minimum_reviews_not_met"

    if total_reviews < int(min_reviews or 2):
        readiness = "needs_more_reviews"
        reason = "minimum_reviews_not_met"
    elif reject_count > 0:
        readiness = "blocked"
        reason = "one_or_more_reviews_rejected"
    elif needs_more_evidence_count > 0:
        readiness = "needs_more_evidence"
        reason = "one_or_more_reviews_need_more_evidence"
    elif avg_confidence < min_avg_confidence:
        readiness = "blocked"
        reason = "average_confidence_too_low"
    elif avg_risk > max_avg_risk:
        readiness = "blocked"
        reason = "average_risk_too_high"
    elif avg_runtime < min_avg_runtime:
        readiness = "blocked"
        reason = "average_runtime_score_too_low"
    elif avg_policy < min_avg_policy:
        readiness = "blocked"
        reason = "average_policy_score_too_low"
    elif avg_safety < min_avg_safety:
        readiness = "blocked"
        reason = "average_safety_score_too_low"
    elif approve_count >= int(min_reviews or 2):
        readiness = "runtime_review_threshold_met"
        reason = "runtime_reviews_healthy"

    return {
        "status": "ok",
        "seller_agent_id": seller_agent_id,
        "readiness": readiness,
        "reason": reason,
        "review_summary": {
            "total_reviews": total_reviews,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "abstain_count": abstain_count,
            "avg_confidence": round(avg_confidence, 4),
            "avg_risk": round(avg_risk, 4),
            "avg_runtime": round(avg_runtime, 4),
            "avg_policy": round(avg_policy, 4),
            "avg_safety": round(avg_safety, 4),
            "min_reviews": int(min_reviews or 2),
            "min_avg_confidence": min_avg_confidence,
            "max_avg_risk": max_avg_risk,
            "min_avg_runtime": min_avg_runtime,
            "min_avg_policy": min_avg_policy,
            "min_avg_safety": min_avg_safety,
        },
        "policy": {
            "runtime_reviews_inform_protocol": True,
            "runtime_reviews_do_not_govern_protocol": True,
            "seller_cannot_self_approve": True,
            "protocol_core_sovereignty_reserved": True,
        },
    }









def init_seller_agent_runtime_governance_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_governance_reviews (
            review_id SERIAL PRIMARY KEY,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            runtime_risk_score REAL DEFAULT 0,
            runtime_trust_score REAL DEFAULT 0,

            governance_status TEXT NOT NULL,
            recommended_action TEXT NOT NULL,

            report TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_governance_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            runtime_risk_score REAL DEFAULT 0,
            runtime_trust_score REAL DEFAULT 0,

            governance_status TEXT NOT NULL,
            recommended_action TEXT NOT NULL,

            report TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_runtime_governance_reviews
    ON seller_agent_runtime_governance_reviews(
        seller_agent_id,
        seller_id,
        governance_status,
        recommended_action
    )
    """)

    conn.commit()
    release_conn(conn)




def store_seller_agent_runtime_governance_review_db(
    seller_agent_id,
    agent_id,
    seller_id,
    runtime_risk_score,
    runtime_trust_score,
    governance_status,
    recommended_action,
    report,
    metadata=None,
):
    metadata = metadata or {}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_agent_runtime_governance_reviews(
        seller_agent_id,
        agent_id,
        seller_id,
        runtime_risk_score,
        runtime_trust_score,
        governance_status,
        recommended_action,
        report,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_agent_id,
        agent_id,
        seller_id,
        float(runtime_risk_score or 0),
        float(runtime_trust_score or 0),
        governance_status,
        recommended_action,
        json.dumps(report),
        now,
        now,
        json.dumps(metadata),
    ))

    review_id = cur.lastrowid if not USE_POSTGRES else None

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "review_id": review_id,
        "seller_agent_id": seller_agent_id,
        "governance_status": governance_status,
        "recommended_action": recommended_action,
    }


def get_seller_agent_runtime_governance_reviews_db(
    seller_agent_id=None,
    seller_id=None,
    governance_status=None,
    recommended_action=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if governance_status:
        where.append(f"governance_status = {p}")
        params.append(governance_status)

    if recommended_action:
        where.append(f"recommended_action = {p}")
        params.append(recommended_action)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_agent_runtime_governance_reviews
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "reviews": rows,
    }




def run_seller_agent_runtime_governance_db(seller_agent_id):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    seller_agent = get_seller_agent_db(seller_agent_id)
    if not seller_agent:
        return {
            "status": "error",
            "message": "seller_agent_not_found",
            "seller_agent_id": seller_agent_id,
        }

    agent_id = seller_agent.get("agent_id")
    seller_id = seller_agent.get("seller_id")

    runtime_eval = evaluate_seller_agent_runtime_reviews_db(
        seller_agent_id=seller_agent_id
    )

    summary = runtime_eval.get("review_summary", {}) or {}

    total_reviews = int(summary.get("total_reviews", 0) or 0)
    reject_count = int(summary.get("reject_count", 0) or 0)
    needs_more_evidence_count = int(summary.get("needs_more_evidence_count", 0) or 0)

    avg_risk = float(summary.get("avg_risk", 1) or 1)
    avg_runtime = float(summary.get("avg_runtime", 0) or 0)
    avg_policy = float(summary.get("avg_policy", 0) or 0)
    avg_safety = float(summary.get("avg_safety", 0) or 0)
    avg_confidence = float(summary.get("avg_confidence", 0) or 0)

    runtime_health_score = float(seller_agent.get("runtime_health_score", 0) or 0)
    runtime_failure_count = int(seller_agent.get("runtime_failure_count", 0) or 0)
    containment_count = int(seller_agent.get("containment_count", 0) or 0)
    current_status = str(seller_agent.get("seller_agent_status") or "").lower()
    runtime_state = str(seller_agent.get("runtime_validation_status") or "").lower()

    risk = 0
    trust = 0
    reasons = []
    healthy_signals = []

    if total_reviews < 2:
        risk += 20
        reasons.append("minimum_runtime_reviews_not_met")
    else:
        trust += 10
        healthy_signals.append("minimum_runtime_reviews_met")

    if reject_count > 0:
        risk += 50
        reasons.append("runtime_review_rejected")

    if needs_more_evidence_count > 0:
        risk += 20
        reasons.append("runtime_review_needs_more_evidence")

    if avg_risk > 0.60:
        risk += 40
        reasons.append("average_runtime_risk_too_high")
    else:
        trust += 10
        healthy_signals.append("average_runtime_risk_acceptable")

    if avg_runtime < 0.50 and total_reviews >= 2:
        risk += 30
        reasons.append("runtime_score_low")
    elif avg_runtime >= 0.70:
        trust += 15
        healthy_signals.append("runtime_score_healthy")

    if avg_policy < 0.50 and total_reviews >= 2:
        risk += 25
        reasons.append("policy_score_low")
    elif avg_policy >= 0.70:
        trust += 10
        healthy_signals.append("policy_score_healthy")

    if avg_safety < 0.50 and total_reviews >= 2:
        risk += 40
        reasons.append("safety_score_low")
    elif avg_safety >= 0.70:
        trust += 15
        healthy_signals.append("safety_score_healthy")

    if runtime_health_score < 0.40:
        risk += 35
        reasons.append("runtime_health_score_low")
    elif runtime_health_score >= 0.80:
        trust += 15
        healthy_signals.append("runtime_health_score_healthy")

    if runtime_failure_count >= 5:
        risk += 40
        reasons.append("runtime_failure_count_high")
    elif runtime_failure_count == 0:
        trust += 10
        healthy_signals.append("runtime_failure_count_zero")

    if containment_count >= 3:
        risk += 30
        reasons.append("containment_count_high")

    if current_status in ["suspended", "quarantined"]:
        risk += 20
        reasons.append(f"current_status_{current_status}")

    if runtime_state in ["healthy", "runtime_warning", "runtime_throttled"]:
        trust += 5
        healthy_signals.append(f"runtime_state_accepted:{runtime_state}")
    elif runtime_state:
        risk += 10
        reasons.append(f"runtime_state_watch:{runtime_state}")

    risk = max(0, min(100, int(risk)))
    trust = max(0, min(100, int(trust)))

    governance_status = "healthy"
    recommended_action = "none"

    if reject_count > 0 or avg_risk > 0.60 or avg_safety < 0.50:
        governance_status = "quarantine"
        recommended_action = "quarantine"
    elif runtime_health_score < 0.40 or runtime_failure_count >= 5:
        governance_status = "quarantine"
        recommended_action = "quarantine"
    elif needs_more_evidence_count > 0 or avg_runtime < 0.50:
        governance_status = "throttle"
        recommended_action = "throttle"
    elif containment_count >= 3:
        governance_status = "manual_review"
        recommended_action = "manual_review"
    elif risk >= 30:
        governance_status = "warning"
        recommended_action = "warn"
    else:
        governance_status = "healthy"
        recommended_action = "none"

    report = {
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "runtime_eval": runtime_eval,
        "current_status": current_status,
        "runtime_state": runtime_state,
        "runtime_health_score": runtime_health_score,
        "runtime_failure_count": runtime_failure_count,
        "containment_count": containment_count,
        "runtime_risk_score": risk,
        "runtime_trust_score": trust,
        "governance_status": governance_status,
        "recommended_action": recommended_action,
        "risk_reasons": reasons,
        "healthy_signals": healthy_signals,
    }

    stored = store_seller_agent_runtime_governance_review_db(
        seller_agent_id=seller_agent_id,
        agent_id=agent_id,
        seller_id=seller_id,
        runtime_risk_score=risk,
        runtime_trust_score=trust,
        governance_status=governance_status,
        recommended_action=recommended_action,
        report=report,
        metadata={
            "runtime_governance_informs_protocol": True,
            "runtime_governance_does_not_auto_execute": True,
            "runtime_action_execution_required_separately": True,
            "protocol_core_sovereignty_reserved": True,
        },
    )

    return {
        "status": "ok",
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "governance_status": governance_status,
        "recommended_action": recommended_action,
        "runtime_risk_score": risk,
        "runtime_trust_score": trust,
        "risk_reasons": reasons,
        "healthy_signals": healthy_signals,
        "stored_review": stored,
        "policy": {
            "runtime_governance_informs_protocol": True,
            "runtime_governance_does_not_auto_execute": True,
            "runtime_action_execution_required_separately": True,
            "protocol_core_sovereignty_reserved": True,
        },
        "report": report,
    }



def init_seller_agent_runtime_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_reviews (
            review_id SERIAL PRIMARY KEY,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            runtime_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            runtime_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_runtime_reviews
    ON seller_agent_runtime_reviews(
        seller_agent_id,
        seller_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)





def store_seller_runtime_risk_event_db(
    seller_id,
    seller_agent_id=None,
    agent_id=None,
    source_action_id=None,
    source_action_type=None,
    risk_delta=0,
    trust_delta=0,
    previous_seller_risk=0,
    new_seller_risk=0,
    previous_seller_trust=0,
    new_seller_trust=0,
    previous_max_agents_allowed=None,
    new_max_agents_allowed=None,
    previous_exposure_limit=0,
    new_exposure_limit=0,
    propagation_reason="",
    severity="medium",
    metadata=None,
):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    metadata = metadata or {}
    metadata = {
        **metadata,
        "runtime_risk_propagates_to_seller": True,
        "agent_governance_impacts_seller_governance": True,
        "protocol_core_sovereignty_reserved": True,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    INSERT INTO seller_runtime_risk_events (
        seller_id,
        seller_agent_id,
        agent_id,
        source_action_id,
        source_action_type,
        risk_delta,
        trust_delta,
        previous_seller_risk,
        new_seller_risk,
        previous_seller_trust,
        new_seller_trust,
        previous_max_agents_allowed,
        new_max_agents_allowed,
        previous_exposure_limit,
        new_exposure_limit,
        propagation_reason,
        severity,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        seller_id,
        seller_agent_id,
        agent_id,
        source_action_id,
        source_action_type,
        float(risk_delta or 0),
        float(trust_delta or 0),
        float(previous_seller_risk or 0),
        float(new_seller_risk or 0),
        float(previous_seller_trust or 0),
        float(new_seller_trust or 0),
        previous_max_agents_allowed,
        new_max_agents_allowed,
        float(previous_exposure_limit or 0),
        float(new_exposure_limit or 0),
        propagation_reason,
        severity,
        now,
        now,
        json.dumps(metadata, sort_keys=True),
    ))

    event_id = get_last_insert_id_db(cur)

    conn.commit()
    release_conn(conn)

    return {
        "status": "stored",
        "event_id": event_id,
        "seller_id": seller_id,
        "seller_agent_id": seller_agent_id,
        "source_action_type": source_action_type,
        "risk_delta": risk_delta,
        "trust_delta": trust_delta,
    }


def get_seller_runtime_risk_events_db(
    seller_id=None,
    seller_agent_id=None,
    source_action_type=None,
    severity=None,
    limit=50,
):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    where = []
    params = []

    if seller_id:
        where.append(f"seller_id = {p}")
        params.append(seller_id)

    if seller_agent_id:
        where.append(f"seller_agent_id = {p}")
        params.append(seller_agent_id)

    if source_action_type:
        where.append(f"source_action_type = {p}")
        params.append(source_action_type)

    if severity:
        where.append(f"severity = {p}")
        params.append(severity)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    cur.execute(f"""
    SELECT *
    FROM seller_runtime_risk_events
    {where_sql}
    ORDER BY created_at DESC
    LIMIT {int(limit or 50)}
    """, tuple(params))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return {
        "status": "ok",
        "count": len(rows),
        "events": rows,
    }



def init_seller_runtime_risk_events_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_runtime_risk_events (
            event_id SERIAL PRIMARY KEY,

            seller_id TEXT NOT NULL,
            seller_agent_id TEXT,
            agent_id TEXT,

            source_action_id INTEGER,
            source_action_type TEXT,

            risk_delta REAL DEFAULT 0,
            trust_delta REAL DEFAULT 0,

            previous_seller_risk REAL DEFAULT 0,
            new_seller_risk REAL DEFAULT 0,

            previous_seller_trust REAL DEFAULT 0,
            new_seller_trust REAL DEFAULT 0,

            previous_max_agents_allowed INTEGER,
            new_max_agents_allowed INTEGER,

            previous_exposure_limit REAL DEFAULT 0,
            new_exposure_limit REAL DEFAULT 0,

            propagation_reason TEXT,
            severity TEXT DEFAULT 'medium',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_runtime_risk_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_id TEXT NOT NULL,
            seller_agent_id TEXT,
            agent_id TEXT,

            source_action_id INTEGER,
            source_action_type TEXT,

            risk_delta REAL DEFAULT 0,
            trust_delta REAL DEFAULT 0,

            previous_seller_risk REAL DEFAULT 0,
            new_seller_risk REAL DEFAULT 0,

            previous_seller_trust REAL DEFAULT 0,
            new_seller_trust REAL DEFAULT 0,

            previous_max_agents_allowed INTEGER,
            new_max_agents_allowed INTEGER,

            previous_exposure_limit REAL DEFAULT 0,
            new_exposure_limit REAL DEFAULT 0,

            propagation_reason TEXT,
            severity TEXT DEFAULT 'medium',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_runtime_risk_events
    ON seller_runtime_risk_events(
        seller_id,
        seller_agent_id,
        source_action_type,
        severity
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_runtime_actions_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_actions (
            action_id SERIAL PRIMARY KEY,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            action_type TEXT NOT NULL,
            action_reason TEXT,

            previous_status TEXT,
            new_status TEXT,

            previous_available INTEGER,
            new_available INTEGER,

            severity TEXT DEFAULT 'medium',

            executed_by TEXT NOT NULL,
            execution_status TEXT DEFAULT 'executed',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_runtime_actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            action_type TEXT NOT NULL,
            action_reason TEXT,

            previous_status TEXT,
            new_status TEXT,

            previous_available INTEGER,
            new_available INTEGER,

            severity TEXT DEFAULT 'medium',

            executed_by TEXT NOT NULL,
            execution_status TEXT DEFAULT 'executed',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_runtime_actions
    ON seller_agent_runtime_actions(
        seller_agent_id,
        seller_id,
        action_type,
        execution_status
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_activation_governance_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_activation_governance_reviews (
            review_id SERIAL PRIMARY KEY,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            activation_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_activation_governance_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            reviewer_type TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,

            review_decision TEXT NOT NULL,
            review_reason TEXT,

            confidence_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,

            activation_score REAL DEFAULT 0,
            policy_score REAL DEFAULT 0,
            safety_score REAL DEFAULT 0,

            metadata TEXT DEFAULT '{}',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_activation_governance_reviews
    ON seller_agent_activation_governance_reviews(
        seller_agent_id,
        seller_id,
        reviewer_type,
        review_decision
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_activation_approvals_table():
    conn = get_conn()
    cur = conn.cursor()

    if USE_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_activation_approvals (
            approval_id SERIAL PRIMARY KEY,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seller_agent_activation_approvals (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,

            seller_agent_id TEXT NOT NULL,
            agent_id TEXT,
            seller_id TEXT,

            approved_by TEXT NOT NULL,
            approval_reason TEXT,

            status TEXT DEFAULT 'approved',

            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            metadata TEXT DEFAULT '{}'
        )
        """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_seller_agent_activation_approvals
    ON seller_agent_activation_approvals(
        seller_agent_id,
        seller_id,
        status
    )
    """)

    conn.commit()
    release_conn(conn)


def init_seller_agent_activation_reviews_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_agent_activation_reviews (
        activation_review_id TEXT PRIMARY KEY,
        seller_agent_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        seller_id TEXT NOT NULL,

        activation_status TEXT DEFAULT 'pending',

        activation_risk_score REAL DEFAULT 0,
        activation_trust_score REAL DEFAULT 0,

        activation_report TEXT DEFAULT '{}',
        governance_recommendation TEXT,

        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,

        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def get_seller_agent_activation_review_db(activation_review_id):
    if not activation_review_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM seller_agent_activation_reviews
    WHERE activation_review_id = {p}
    """, (activation_review_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def run_seller_agent_activation_review_db(seller_agent_id):
    if not seller_agent_id:
        return {"status": "error", "message": "seller_agent_id_required"}

    seller_agent = get_seller_agent_db(seller_agent_id)
    if not seller_agent:
        return {"status": "error", "message": "seller_agent_not_found"}

    seller = get_seller_db(seller_agent.get("seller_id"))
    if not seller:
        return {"status": "error", "message": "seller_not_found"}

    agent_id = seller_agent.get("agent_id")
    seller_id = seller.get("seller_id")

    metadata = _safe_json_loads(seller_agent.get("metadata"), {})
    factory_request_id = metadata.get("factory_request_id")
    catalog_item_id = metadata.get("catalog_item_id")
    specialization = metadata.get("specialization")

    factory_request = get_seller_agent_factory_request_db(factory_request_id) if factory_request_id else None
    catalog_item = get_seller_catalog_item_db(catalog_item_id) if catalog_item_id else None

    risk = 0
    trust = 0
    passed = []
    failed = []
    manual = []

    seller_status = str(seller.get("seller_status") or "").lower()
    verification_status = str(seller.get("verification_status") or "").lower()

    if seller_status == "active":
        trust += 15
        passed.append("seller_active")
    else:
        risk += 30
        failed.append("seller_not_active")

    if verification_status in ["verified", "foundation_verified"]:
        trust += 15
        passed.append("seller_verified")
    else:
        risk += 25
        failed.append("seller_not_verified")

    if int(seller.get("email_verified", 0) or 0) == 1:
        trust += 5
        passed.append("email_verified")
    else:
        risk += 5
        manual.append("email_not_verified")

    if str(seller.get("kyc_status") or "").lower() in ["verified", "approved"]:
        trust += 10
        passed.append("kyc_verified")
    else:
        risk += 10
        manual.append("kyc_not_verified")

    if str(seller.get("business_verification_status") or "").lower() in ["verified", "approved"]:
        trust += 10
        passed.append("business_verified")
    else:
        risk += 10
        manual.append("business_not_verified")

    if str(seller_agent.get("seller_agent_status") or "").lower() == "pending_review":
        trust += 10
        passed.append("seller_agent_pending_review")
    else:
        risk += 20
        manual.append("seller_agent_not_pending_review")

    runtime_state = str(seller_agent.get("runtime_validation_status") or "").lower()
    if runtime_state in ["generated_pending_review", "validated", "healthy", "pending_activation_approval"]:
        trust += 5
        passed.append(f"runtime_state_accepted:{runtime_state}")
    else:
        risk += 10
        manual.append("runtime_status_unexpected")

    if factory_request:
        factory_state = str(factory_request.get("factory_status") or "").lower()
        if factory_state in ["generated_pending_review", "activated"]:
            trust += 10
            passed.append(f"factory_state_accepted:{factory_state}")
        else:
            risk += 15
            manual.append("factory_status_not_generated_pending_review")

        if str(factory_request.get("sandbox_status") or "").lower() == "passed":
            trust += 10
            passed.append("sandbox_passed")
        else:
            risk += 25
            failed.append("sandbox_not_passed")

        if str(factory_request.get("simulation_status") or "").lower() == "passed":
            trust += 10
            passed.append("simulation_passed")
        else:
            risk += 25
            failed.append("simulation_not_passed")
    else:
        risk += 30
        failed.append("factory_request_missing")

    if catalog_item:
        catalog_state = str(catalog_item.get("agent_creation_status") or "").lower()
        if catalog_state in ["generated_pending_review", "activated"]:
            trust += 5
            passed.append(f"catalog_state_accepted:{catalog_state}")
        else:
            manual.append("catalog_status_unexpected")
    else:
        risk += 20
        manual.append("catalog_item_missing")

    max_agents_allowed = int(seller.get("max_agents_allowed", 5) or 5)
    active_agents = int(seller.get("active_agents", 0) or 0)

    if active_agents <= max_agents_allowed:
        trust += 5
        passed.append("agent_capacity_available")
    else:
        risk += 50
        failed.append("agent_capacity_exceeded")

    # Duplication check: same seller + same specialization already active.
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    duplicate_count = 0
    if specialization:
        cur.execute(f"""
        SELECT COUNT(*) AS c
        FROM seller_agents
        WHERE seller_id = {p}
          AND seller_agent_id != {p}
          AND seller_agent_status = 'active'
          AND specialties LIKE {p}
        """, (
            seller_id,
            seller_agent_id,
            f"%{specialization}%",
        ))
        row = cur.fetchone()
        duplicate_count = int(row_get(row, "c", 0) or 0)

    release_conn(conn)

    if duplicate_count > 0:
        risk += 20
        manual.append("active_specialization_duplicate_detected")
    else:
        trust += 5
        passed.append("no_active_specialization_duplicate")

    # Safety flags must remain disabled at activation time.
    agent_row = None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM agents WHERE agent_id = {p}", (agent_id,))
    row = cur.fetchone()
    if row:
        agent_row = dict(row)
    release_conn(conn)

    if not agent_row:
        risk += 30
        failed.append("registry_agent_missing")
    else:
        if int(agent_row.get("buyer_access", 0) or 0) == 0:
            trust += 5
            passed.append("buyer_access_disabled")
        else:
            risk += 50
            failed.append("buyer_access_enabled_before_activation")

        if int(agent_row.get("raw_prompt_access", 0) or 0) == 0:
            trust += 5
            passed.append("raw_prompt_access_disabled")
        else:
            risk += 50
            failed.append("raw_prompt_access_enabled_before_activation")

        if int(agent_row.get("web_access", 0) or 0) == 0:
            trust += 5
            passed.append("web_access_disabled")
        else:
            risk += 25
            manual.append("web_access_enabled_before_activation")

    risk = max(0, min(100, int(risk)))
    trust = max(0, min(100, int(trust)))

    if failed and risk > 50:
        activation_status = "rejected"
        recommendation = "reject_activation"
        next_seller_agent_status = "rejected"
        next_available = 0
        event_type = "seller_agent_activation_rejected"
    elif risk > 25 or manual:
        activation_status = "manual_review"
        recommendation = "manual_activation_review"
        next_seller_agent_status = "pending_review"
        next_available = 0
        event_type = "seller_agent_activation_manual_review"
    else:
        activation_status = "approved"
        recommendation = "activate_agent"
        next_seller_agent_status = "active"
        next_available = 1
        event_type = "seller_agent_activation_approved"

    if activation_status == "approved":
        activation_approvals = get_seller_agent_activation_approvals_db(
            seller_agent_id=seller_agent_id,
            status="approved",
            limit=1,
        )

        if activation_approvals.get("count", 0) < 1:
            activation_status = "pending_activation_approval"
            recommendation = "activation_approval_required_before_final_activation"
            next_seller_agent_status = "pending_review"
            next_available = 0
            event_type = "seller_agent_activation_pending_approval"
            passed.append("activation_engine_passed_but_approval_missing")
            manual.append("activation_approval_required_before_final_activation")

    report = {
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "seller_id": seller_id,
        "factory_request_id": factory_request_id,
        "catalog_item_id": catalog_item_id,
        "specialization": specialization,
        "activation_risk_score": risk,
        "activation_trust_score": trust,
        "passed_checks": passed,
        "failed_checks": failed,
        "manual_review_checks": manual,
        "governance_recommendation": recommendation,
    }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())
    activation_review_id = str(uuid.uuid4())

    cur.execute(f"""
    INSERT INTO seller_agent_activation_reviews (
        activation_review_id,
        seller_agent_id,
        agent_id,
        seller_id,
        activation_status,
        activation_risk_score,
        activation_trust_score,
        activation_report,
        governance_recommendation,
        created_at,
        updated_at,
        metadata
    )
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """, (
        activation_review_id,
        seller_agent_id,
        agent_id,
        seller_id,
        activation_status,
        risk,
        trust,
        json.dumps(report),
        recommendation,
        now,
        now,
        "{}",
    ))

    cur.execute(f"""
    UPDATE seller_agents
    SET seller_agent_status = {p},
        runtime_validation_status = {p},
        runtime_health_score = {p},
        runtime_last_checked_at = {p},
        updated_at = {p}
    WHERE seller_agent_id = {p}
    """, (
        next_seller_agent_status,
        (
            "healthy"
            if activation_status == "approved"
            else "pending_activation_approval"
            if activation_status == "pending_activation_approval"
            else "activation_review_failed"
        ),
        1.0 if activation_status == "approved" else 0.0,
        now,
        now,
        seller_agent_id,
    ))

    if agent_row:
        cur.execute(f"""
        UPDATE agents
        SET available = {p},
            seller_status = {p},
            verification_status = {p},
            foundation_verified_at = {p},
            foundation_verdict = {p},
            updated_at = {p}
        WHERE agent_id = {p}
        """, (
            next_available,
            "active" if activation_status == "approved" else next_seller_agent_status,
            "foundation_verified" if activation_status == "approved" else "activation_review_failed",
            now if activation_status == "approved" else None,
            recommendation,
            now,
            agent_id,
        ))

    if activation_status == "approved":
        cur.execute(f"""
        UPDATE agents
        SET available = 1,
            seller_status = 'active',
            verification_status = 'foundation_verified',
            buyer_access = 0,
            web_access = 0,
            raw_prompt_access = 0,
            foundation_verified_at = {p},
            foundation_verdict = {p},
            updated_at = {p}
        WHERE agent_id = {p}
        """, (
            now,
            "activation_approved_secure",
            now,
            agent_id,
        ))

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET factory_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "activated",
            now,
            factory_request_id,
        ))

        cur.execute(f"""
        UPDATE seller_catalog_items
        SET agent_creation_status = {p},
            linked_seller_agent_id = {p},
            updated_at = {p}
        WHERE catalog_item_id = {p}
        """, (
            "activated",
            seller_agent_id,
            now,
            catalog_item_id,
        ))

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type=event_type,
        reviewer="iat_seller_agent_activation_engine",
        reason=recommendation,
        old_status=str(seller_agent.get("seller_agent_status") or "pending_review"),
        new_status=next_seller_agent_status,
        metadata=report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "activation_review_id": activation_review_id,
        "seller_agent_id": seller_agent_id,
        "agent_id": agent_id,
        "activation_status": activation_status,
        "activation_risk_score": risk,
        "activation_trust_score": trust,
        "governance_recommendation": recommendation,
        "passed_checks": passed,
        "failed_checks": failed,
        "manual_review_checks": manual,
        "event": event_result,
        "activation_review": get_seller_agent_activation_review_db(activation_review_id),
        "seller_agent": get_seller_agent_db(seller_agent_id),
    }



def run_seller_agent_generation_db(factory_request_id):
    if not factory_request_id:
        return {"status": "error", "message": "factory_request_id_required"}

    factory_request = get_seller_agent_factory_request_db(factory_request_id)
    if not factory_request:
        return {"status": "error", "message": "factory_request_not_found"}

    if str(factory_request.get("factory_status") or "").lower() != "ready_for_generation":
        return {
            "status": "error",
            "message": "factory_request_not_ready_for_generation",
            "factory_status": factory_request.get("factory_status"),
            "sandbox_status": factory_request.get("sandbox_status"),
            "simulation_status": factory_request.get("simulation_status"),
        }

    if str(factory_request.get("sandbox_status") or "").lower() != "passed":
        return {"status": "error", "message": "sandbox_not_passed"}

    if str(factory_request.get("simulation_status") or "").lower() != "passed":
        return {"status": "error", "message": "simulation_not_passed"}

    simulation_approvals = get_seller_agent_simulation_approvals_db(
        factory_request_id=factory_request_id,
        status="approved",
        limit=1,
    )

    if simulation_approvals.get("count", 0) < 1:
        conn = get_conn()
        cur = conn.cursor()
        p = qmark()
        now = int(time.time())

        cur.execute(f"""
        UPDATE seller_agent_factory_requests
        SET factory_status = {p},
            updated_at = {p}
        WHERE factory_request_id = {p}
        """, (
            "pending_simulation_approval",
            now,
            factory_request_id,
        ))

        conn.commit()
        release_conn(conn)

        return {
            "status": "blocked",
            "message": "simulation_approval_required_before_generation",
            "factory_request_id": factory_request_id,
            "simulation_approvals": simulation_approvals,
            "policy": {
                "simulation_reviews_required": True,
                "simulation_approval_required_before_generation": True,
                "seller_cannot_self_approve": True,
                "protocol_core_sovereignty_reserved": True,
            },
            "factory_request": get_seller_agent_factory_request_db(factory_request_id),
        }

    seller = get_seller_db(factory_request.get("seller_id"))
    if not seller:
        return {"status": "error", "message": "seller_not_found"}

    catalog_item = get_seller_catalog_item_db(factory_request.get("catalog_item_id"))
    if not catalog_item:
        return {"status": "error", "message": "catalog_item_not_found"}

    seller_id = seller.get("seller_id")
    catalog_item_id = catalog_item.get("catalog_item_id")

    requested_specializations = _safe_json_loads(
        factory_request.get("requested_specializations"),
        [],
    )

    if not isinstance(requested_specializations, list) or not requested_specializations:
        requested_specializations = [
            str(factory_request.get("requested_agent_name") or catalog_item.get("category") or "general").lower()
        ]

    requested_agent_count = int(factory_request.get("requested_agent_count", len(requested_specializations)) or len(requested_specializations))

    # Normalize count to specializations. One specialization = one seller agent.
    requested_specializations = [
        str(s or "").strip().lower().replace(" ", "_")
        for s in requested_specializations
        if str(s or "").strip()
    ]

    if len(requested_specializations) == 0:
        return {"status": "error", "message": "no_valid_specializations"}

    if requested_agent_count != len(requested_specializations):
        return {
            "status": "error",
            "message": "requested_agent_count_specialization_mismatch",
            "requested_agent_count": requested_agent_count,
            "specialization_count": len(requested_specializations),
        }

    max_agents_allowed = int(seller.get("max_agents_allowed", 5) or 5)
    active_agents = int(seller.get("active_agents", 0) or 0)
    remaining_capacity = max_agents_allowed - active_agents

    if requested_agent_count > remaining_capacity:
        return {
            "status": "error",
            "message": "requested_agents_exceed_remaining_capacity",
            "requested_agent_count": requested_agent_count,
            "max_agents_allowed": max_agents_allowed,
            "active_agents": active_agents,
            "remaining_capacity": remaining_capacity,
        }

    now = int(time.time())
    category = str(catalog_item.get("category") or "general").lower().replace(" ", "_")
    service = str(catalog_item.get("service_type") or catalog_item.get("category") or "seller_service").lower().replace(" ", "_")
    unit_price = float(catalog_item.get("unit_price", 0) or 0)

    generated = []

    for specialization in requested_specializations:
        short_id = str(uuid.uuid4())[:8]
        agent_id = f"seller_{seller_id[-8:]}_{category}_{specialization}_{short_id}"
        seller_agent_id = f"seller_agent_{short_id}_{specialization}"

        capabilities = [
            "seller_catalog_execution",
            "iat_controlled",
            "foundation_mediated",
        ]

        specialties = [
            specialization,
            category,
        ]

        metadata = {
            "source": "iat_generation_engine",
            "execution_mode": "iat_internal",
            "factory_request_id": factory_request_id,
            "catalog_item_id": catalog_item_id,
            "seller_id": seller_id,
            "specialization": specialization,
            "buyer_access": False,
            "raw_prompt_access": False,
            "web_access": False,
            "generation_policy": "pending_review_unavailable_by_default",
        }

        seller_agent_result = create_seller_agent_db({
            "seller_agent_id": seller_agent_id,
            "seller_id": seller_id,
            "agent_id": agent_id,
            "service": service,
            "url": "",
            "capabilities": capabilities,
            "specialties": specialties,
            "seller_agent_status": "pending_review",
            "reputation": 0.5,
            "risk_score": float(factory_request.get("risk_score", 0) or 0),
            "exposure_limit": 0,
            "runtime_validation_status": "generated_pending_review",
            "runtime_health_score": 0,
            "runtime_latency": 0,
            "runtime_last_checked_at": now,
            "metadata": metadata,
        })

        if isinstance(seller_agent_result, dict) and seller_agent_result.get("status") == "error":
            return {
                "status": "error",
                "message": "seller_agent_creation_failed",
                "details": seller_agent_result,
                "generated_so_far": generated,
            }

        register_agent_db({
            "agent_id": agent_id,
            "service": service,
            "url": "",
            "wallet": seller.get("wallet"),
            "agent_type": "seller",
            "price": unit_price if unit_price > 0 else 1.0,
            "reputation": 0.5,
            "available": False,
            "stake_amount": float(seller.get("stake_amount", 0) or 0),
            "stake_required": 0,
            "max_order_value": 0,
            "trust_tier": seller.get("trust_tier", "new"),
            "capabilities": json.dumps(capabilities),
            "specialties": json.dumps(specialties),
            "seller_status": "pending_review",
            "verification_status": "sandbox_generated",
            "seller_metadata": metadata,
            "buyer_access": False,
            "web_access": False,
            "raw_prompt_access": False,
            "foundation_verified_at": None,
            "foundation_verdict": "generated_pending_foundation_review",
            "seller_id": seller_id,
            "seller_agent_id": seller_agent_id,
        })

        generated.append({
            "agent_id": agent_id,
            "seller_agent_id": seller_agent_id,
            "specialization": specialization,
            "service": service,
            "status": "pending_review",
            "available": False,
        })

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    generated_agent_id = generated[0]["agent_id"] if generated else None
    generated_seller_agent_id = generated[0]["seller_agent_id"] if generated else None

    generation_report = {
        "factory_request_id": factory_request_id,
        "seller_id": seller_id,
        "catalog_item_id": catalog_item_id,
        "generated_count": len(generated),
        "generated_agents": generated,
        "generation_policy": "pending_review_unavailable_by_default",
        "buyer_access": False,
        "web_access": False,
        "raw_prompt_access": False,
    }

    cur.execute(f"""
    UPDATE seller_agent_factory_requests
    SET factory_status = {p},
        generated_agent_id = {p},
        generated_seller_agent_id = {p},
        updated_at = {p},
        metadata = {p}
    WHERE factory_request_id = {p}
    """, (
        "generated_pending_review",
        generated_agent_id,
        generated_seller_agent_id,
        now,
        json.dumps(generation_report),
        factory_request_id,
    ))

    cur.execute(f"""
    UPDATE seller_catalog_items
    SET agent_creation_status = {p},
        linked_seller_agent_id = {p},
        updated_at = {p}
    WHERE catalog_item_id = {p}
    """, (
        "generated_pending_review",
        generated_seller_agent_id,
        now,
        catalog_item_id,
    ))

    event_result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="factory_generation_completed",
        reviewer="iat_factory_generation_engine",
        reason="generated_pending_foundation_review",
        old_status="ready_for_generation",
        new_status="generated_pending_review",
        metadata=generation_report,
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "factory_request_id": factory_request_id,
        "generated_count": len(generated),
        "generated_agents": generated,
        "event": event_result,
        "factory_request": get_seller_agent_factory_request_db(factory_request_id),
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

    quarantine_until = None

    cur.execute(f"""
    SELECT metadata
    FROM seller_agents
    WHERE seller_agent_id = {p}
    """, (seller_agent_id,))

    metadata_row = cur.fetchone()
    seller_agent_metadata = _safe_json_loads(
        row_get(metadata_row, "metadata", "{}") if metadata_row else "{}",
        {},
    )

    execution_mode = str(
        seller_agent_metadata.get("execution_mode") or ""
    ).lower()

    if execution_mode == "iat_internal":
        runtime_validation_status = "validated"
        runtime_health_score = max(float(runtime_health_score or 0), 1.0)
        disable_if_unhealthy = False

    cur.execute(f"""
    SELECT runtime_failure_count
    FROM seller_agents
    WHERE seller_agent_id = {p}
    """, (seller_agent_id,))

    existing_runtime_row = cur.fetchone()
    current_runtime_failure_count = int(
        row_get(existing_runtime_row, "runtime_failure_count", 0) or 0
    )

    new_runtime_failure_count = current_runtime_failure_count

    cur.execute(f"""
    SELECT runtime_quarantine_until
    FROM seller_agents
    WHERE seller_agent_id = {p}
    """, (seller_agent_id,))

    quarantine_row = cur.fetchone()
    current_quarantine_until = int(
        row_get(quarantine_row, "runtime_quarantine_until", 0) or 0
    )

    quarantine_active = (
        current_quarantine_until
        and current_quarantine_until > now
    )

    if quarantine_active:
        runtime_validation_status = "quarantined"
        runtime_health_score = min(
            float(runtime_health_score or 0),
            0.2
        )
        quarantine_until = current_quarantine_until

    if runtime_validation_status in ["dead", "quarantined"]:
        new_runtime_failure_count = current_runtime_failure_count + 1
    elif runtime_validation_status == "validated":
        new_runtime_failure_count = max(0, current_runtime_failure_count - 1)

    if new_runtime_failure_count >= 3:
        runtime_validation_status = "quarantined"
        quarantine_until = now + 3600


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
            runtime_failure_count = {p},
            runtime_quarantine_until = {p},
            seller_agent_status = {p},
            updated_at = {p}
        WHERE seller_agent_id = {p}
        """, (
            runtime_validation_status,
            runtime_health_score,
            float(runtime_latency or 0),
            now,
            new_runtime_failure_count,
            quarantine_until,
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
            runtime_failure_count = {p},
            runtime_quarantine_until = {p},
            updated_at = {p}
        WHERE seller_agent_id = {p}
        """, (
            runtime_validation_status,
            runtime_health_score,
            float(runtime_latency or 0),
            now,
            new_runtime_failure_count,
            quarantine_until,
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
    current_max_agents = int(seller.get("max_agents_allowed", 5) or 5)
    current_exposure = float(seller.get("exposure_limit", 0) or 0)

    seller_status_for_exposure = str(
        seller.get("seller_status", "pending") or "pending"
    ).lower()
    verification_status_for_exposure = str(
        seller.get("verification_status", "unverified") or "unverified"
    ).lower()

    if (
        current_exposure <= 0
        and seller_status_for_exposure == "active"
        and verification_status_for_exposure in ["verified", "foundation_verified"]
        and current_risk < 0.35
    ):
        current_exposure = 100.0

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

    # Risk events must not reduce risk.
    # Decay/recovery is handled by dedicated decay/recovery flows.
    decay_factor = 1.0

    adjusted_severity = severity * event_weight * trust_resistance

    # Only confirmed fraud can produce a full emergency jump.
    if event_type != "confirmed_fraud":
        adjusted_severity = min(adjusted_severity, 0.30)

    new_risk = min(1.0, (current_risk * decay_factor) + adjusted_severity)

    if event_type not in ["risk_decay", "recovery_approved", "stable_behavior"]:
        new_risk = max(current_risk, new_risk)

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





def init_seller_containment_events_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_containment_events (
        containment_event_id TEXT PRIMARY KEY,
        seller_id TEXT,
        seller_status TEXT,
        quarantined_agents INTEGER DEFAULT 0,
        trigger_source TEXT,
        created_at INTEGER
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


    try:
        severity = "info"

        if str(new_status).lower() in ["restricted"]:
            severity = "high"
        elif str(new_status).lower() in ["contained", "rejected", "banned"]:
            severity = "critical"
        elif str(new_status).lower() in ["watchlist"]:
            severity = "medium"

        evolve_threat_memory_from_seller_event_db(
            seller_id=seller_id,
            event_type=event_type,
            severity=severity,
            metadata={
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
                "reviewer": reviewer,
                "source": "seller_governance_event",
                "event_id": event_id,
            },
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "event_id": event_id,
    }





def create_deduped_seller_governance_event_db(
    seller_id,
    event_type,
    reviewer="foundation_protocol",
    reason="",
    override_terminal=False,
    old_status="",
    new_status="",
    metadata=None,
    dedupe_window_seconds=3600,
):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    if not event_type:
        return {"status": "error", "message": "event_type_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())
    since = now - int(dedupe_window_seconds or 3600)

    cur.execute(f"""
    SELECT event_id, created_at
    FROM seller_governance_events
    WHERE seller_id = {p}
      AND event_type = {p}
      AND reason = {p}
      AND created_at >= {p}
    ORDER BY created_at DESC
    LIMIT 1
    """, (
        seller_id,
        event_type,
        reason,
        since,
    ))

    existing = cur.fetchone()

    if existing:
        release_conn(conn)
        return {
            "status": "deduped",
            "event_id": row_get(existing, "event_id"),
            "seller_id": seller_id,
            "event_type": event_type,
            "reason": reason,
            "dedupe_window_seconds": dedupe_window_seconds,
        }

    result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type=event_type,
        reviewer=reviewer,
        reason=reason,
        override_terminal=override_terminal,
        old_status=old_status,
        new_status=new_status,
        metadata=metadata,
    )

    conn.commit()
    release_conn(conn)

    result["deduped"] = False
    return result


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

    result = create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type=event_type,
        reviewer=reviewer,
        reason=reason,
        override_terminal=override_terminal,
        old_status=old_status,
        new_status=new_status,
        metadata=metadata,
    )

    conn.commit()
    release_conn(conn)

    return result


SELLER_ALLOWED_TRANSITIONS = {
    "pending": ["active", "rejected", "watchlist"],
    "active": ["watchlist", "restricted", "contained", "rejected"],
    "watchlist": ["active", "restricted", "contained", "rejected"],
    "restricted": ["watchlist", "contained", "rejected"],
    "contained": ["restricted", "rejected", "banned"],
    "rejected": [],
    "banned": [],
}


def validate_seller_status_transition(current_status, next_status):
    current_status = str(current_status or "pending")
    next_status = str(next_status or "")

    allowed = SELLER_ALLOWED_TRANSITIONS.get(current_status, [])

    return {
        "allowed": next_status in allowed or next_status == current_status,
        "current_status": current_status,
        "next_status": next_status,
        "allowed_transitions": allowed,
    }


def update_seller_status_governed_db(seller_id, next_status, reason="manual_governance"):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT seller_status
    FROM sellers
    WHERE seller_id = {p}
    """, (seller_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {"status": "error", "message": "seller_not_found"}

    current_status = row_get(row, "seller_status", "pending")

    transition = validate_seller_status_transition(
        current_status,
        next_status,
    )

    if not transition.get("allowed"):
        release_conn(conn)
        return {
            "status": "error",
            "message": "seller_status_transition_not_allowed",
            "transition": transition,
        }

    cur.execute(f"""
    UPDATE sellers
    SET seller_status = {p},
        last_risk_review_at = {p},
        updated_at = {p}
    WHERE seller_id = {p}
    """, (
        next_status,
        now,
        now,
        seller_id,
    ))

    if next_status in ["restricted", "contained", "rejected", "banned"]:
        cur.execute(f"""
        UPDATE seller_agents
        SET seller_agent_status = 'disabled',
            updated_at = {p}
        WHERE seller_id = {p}
        """, (
            now,
            seller_id,
        ))

        if is_postgres():
            cur.execute(f"""
            UPDATE agents
            SET available = 0,
                seller_status = {p},
                risk_score = GREATEST(COALESCE(risk_score, 0), 1.0),
                updated_at = {p}
            WHERE seller_id = {p}
            """, (
                next_status,
                now,
                seller_id,
            ))
        else:
            cur.execute(f"""
            UPDATE agents
            SET available = 0,
                seller_status = {p},
                risk_score = MAX(COALESCE(risk_score, 0), 1.0),
                updated_at = {p}
            WHERE seller_id = {p}
            """, (
                next_status,
                now,
                seller_id,
            ))

    create_seller_governance_event_with_cursor(
        cur=cur,
        seller_id=seller_id,
        event_type="seller_status_transition",
        reviewer="admin",
        reason=reason,
        override_terminal=False,
        old_status=current_status,
        new_status=next_status,
        metadata={
            "transition_source": "update_seller_status_governed_db",
            "security_propagation": next_status in [
                "restricted",
                "contained",
                "rejected",
                "banned",
            ],
        },
    )

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "previous_status": current_status,
        "new_status": next_status,
        "reason": reason,
    }



def init_seller_recovery_requests_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_recovery_requests (
        recovery_request_id TEXT PRIMARY KEY,
        seller_id TEXT,
        seller_status TEXT,
        requested_status TEXT,
        reason TEXT,
        evidence TEXT,
        recovery_status TEXT DEFAULT 'pending',
        admin_decision TEXT,
        admin_reason TEXT,
        created_at INTEGER,
        reviewed_at INTEGER
    )
    """)

    conn.commit()
    release_conn(conn)


def create_seller_recovery_request_db(
    seller_id,
    requested_status="watchlist",
    reason="",
    evidence=None,
):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT seller_status
    FROM sellers
    WHERE seller_id = {p}
    """, (seller_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {"status": "error", "message": "seller_not_found"}

    current_status = row_get(row, "seller_status", "pending")

    if current_status not in ["restricted", "contained"]:
        release_conn(conn)
        return {
            "status": "error",
            "message": "seller_not_eligible_for_recovery",
            "seller_status": current_status,
        }

    recovery_request_id = "seller_recovery_" + str(uuid.uuid4())

    cur.execute(f"""
    INSERT INTO seller_recovery_requests (
        recovery_request_id,
        seller_id,
        seller_status,
        requested_status,
        reason,
        evidence,
        recovery_status,
        created_at
    ) VALUES (
        {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
    )
    """, (
        recovery_request_id,
        seller_id,
        current_status,
        requested_status,
        reason,
        json.dumps(evidence or {}),
        "pending",
        now,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "recovery_request_id": recovery_request_id,
        "seller_id": seller_id,
        "seller_status": current_status,
        "requested_status": requested_status,
        "recovery_status": "pending",
    }



def decide_seller_recovery_request_db(
    recovery_request_id,
    decision,
    admin_reason="",
):
    if not recovery_request_id:
        return {"status": "error", "message": "recovery_request_id_required"}

    decision = str(decision or "").lower()

    if decision not in ["approved", "rejected"]:
        return {
            "status": "error",
            "message": "invalid_recovery_decision",
            "allowed": ["approved", "rejected"],
        }

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM seller_recovery_requests
    WHERE recovery_request_id = {p}
    """, (recovery_request_id,))

    row = cur.fetchone()

    if not row:
        release_conn(conn)
        return {"status": "error", "message": "recovery_request_not_found"}

    request = dict(row)

    if request.get("recovery_status") != "pending":
        release_conn(conn)
        return {
            "status": "error",
            "message": "recovery_request_already_reviewed",
            "recovery_status": request.get("recovery_status"),
        }

    seller_id = request.get("seller_id")
    requested_status = request.get("requested_status") or "watchlist"

    if decision == "approved":
        transition_result = update_seller_status_governed_db(
            seller_id=seller_id,
            next_status=requested_status,
            reason="approved_recovery_request",
        )

        if transition_result.get("status") != "ok":
            release_conn(conn)
            return {
                "status": "error",
                "message": "recovery_transition_failed",
                "transition_result": transition_result,
            }

    cur.execute(f"""
    UPDATE seller_recovery_requests
    SET recovery_status = {p},
        admin_decision = {p},
        admin_reason = {p},
        reviewed_at = {p}
    WHERE recovery_request_id = {p}
    """, (
        decision,
        decision,
        admin_reason,
        now,
        recovery_request_id,
    ))

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "recovery_request_id": recovery_request_id,
        "seller_id": seller_id,
        "decision": decision,
        "requested_status": requested_status,
    }


def list_seller_governance_events_db(seller_id=None, limit=100):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    limit = max(1, min(int(limit or 100), 500))

    if seller_id:
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
    else:
        cur.execute(f"""
        SELECT *
        FROM seller_governance_events
        ORDER BY created_at DESC
        LIMIT {p}
        """, (
            limit,
        ))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "events": rows,
    }



def init_seller_clusters_tables():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seller_clusters (
        cluster_id TEXT PRIMARY KEY,
        root_agent_id TEXT,
        member_count INTEGER DEFAULT 0,
        edge_count INTEGER DEFAULT 0,
        cluster_risk_score REAL DEFAULT 0,
        coordination_probability REAL DEFAULT 0,
        average_edge_weight REAL DEFAULT 0,
        strongest_edge_weight REAL DEFAULT 0,
        threat_memory_count INTEGER DEFAULT 0,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cluster_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        cluster_id TEXT,
        root_agent_id TEXT,
        member_count INTEGER DEFAULT 0,
        edge_count INTEGER DEFAULT 0,
        cluster_risk_score REAL DEFAULT 0,
        coordination_probability REAL DEFAULT 0,
        average_edge_weight REAL DEFAULT 0,
        strongest_edge_weight REAL DEFAULT 0,
        threat_memory_count INTEGER DEFAULT 0,
        snapshot_reason TEXT,
        created_at INTEGER
    )
    """)

    conn.commit()
    release_conn(conn)




def init_threat_memory_nodes_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS threat_memory_nodes (
        seller_id TEXT PRIMARY KEY,
        memory_score REAL DEFAULT 0,
        latent_risk_score REAL DEFAULT 0,
        mutation_score REAL DEFAULT 0,
        contagion_score REAL DEFAULT 0,
        lineage_depth INTEGER DEFAULT 0,
        ancestor_risk_score REAL DEFAULT 0,
        descendant_risk_score REAL DEFAULT 0,
        recovery_confidence REAL DEFAULT 0.5,
        threat_entropy REAL DEFAULT 0,
        graph_position_score REAL DEFAULT 0,
        quarantine_pressure REAL DEFAULT 0,
        adaptive_trust_score REAL DEFAULT 0.5,
        memory_weight REAL DEFAULT 1.0,
        last_evolution_at INTEGER,
        created_at INTEGER,
        updated_at INTEGER,
        metadata TEXT DEFAULT '{}'
    )
    """)

    conn.commit()
    release_conn(conn)


def upsert_threat_memory_node_db(
    seller_id,
    memory_score=None,
    latent_risk_score=None,
    mutation_score=None,
    contagion_score=None,
    recovery_confidence=None,
    quarantine_pressure=None,
    adaptive_trust_score=None,
    lineage_depth=None,
    ancestor_risk_score=None,
    descendant_risk_score=None,
    graph_position_score=None,
    metadata=None,
):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT seller_id
    FROM threat_memory_nodes
    WHERE seller_id = {p}
    """, (seller_id,))

    exists = cur.fetchone() is not None

    if not exists:
        cur.execute(f"""
        INSERT INTO threat_memory_nodes (
            seller_id,
            memory_score,
            latent_risk_score,
            mutation_score,
            contagion_score,
            recovery_confidence,
            quarantine_pressure,
            adaptive_trust_score,
            lineage_depth,
            ancestor_risk_score,
            descendant_risk_score,
            graph_position_score,
            last_evolution_at,
            created_at,
            updated_at,
            metadata
        ) VALUES (
            {p}, {p}, {p}, {p}, {p}, {p},
            {p}, {p}, {p}, {p}, {p}, {p},
            {p}, {p}, {p}, {p}
        )
        """, (
            seller_id,
            float(memory_score or 0),
            float(latent_risk_score or 0),
            float(mutation_score or 0),
            float(contagion_score or 0),
            float(recovery_confidence if recovery_confidence is not None else 0.5),
            float(quarantine_pressure or 0),
            float(adaptive_trust_score if adaptive_trust_score is not None else 0.5),
            int(lineage_depth or 0),
            float(ancestor_risk_score or 0),
            float(descendant_risk_score or 0),
            float(graph_position_score or 0),
            now,
            now,
            now,
            json.dumps(metadata or {}),
        ))
    else:
        updates = []
        values = []

        fields = {
            "memory_score": memory_score,
            "latent_risk_score": latent_risk_score,
            "mutation_score": mutation_score,
            "contagion_score": contagion_score,
            "recovery_confidence": recovery_confidence,
            "quarantine_pressure": quarantine_pressure,
            "adaptive_trust_score": adaptive_trust_score,
            "lineage_depth": lineage_depth,
            "ancestor_risk_score": ancestor_risk_score,
            "descendant_risk_score": descendant_risk_score,
            "graph_position_score": graph_position_score,
        }

        for field, value in fields.items():
            if value is not None:
                updates.append(f"{field} = {p}")
                values.append(float(value))

        if metadata is not None:
            updates.append(f"metadata = {p}")
            values.append(json.dumps(metadata))

        updates.append(f"last_evolution_at = {p}")
        values.append(now)

        updates.append(f"updated_at = {p}")
        values.append(now)

        values.append(seller_id)

        cur.execute(f"""
        UPDATE threat_memory_nodes
        SET {", ".join(updates)}
        WHERE seller_id = {p}
        """, values)

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "seller_id": seller_id,
        "created": not exists,
    }



def get_threat_memory_node_db(seller_id):
    if not seller_id:
        return None

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM threat_memory_nodes
    WHERE seller_id = {p}
    """, (seller_id,))

    row = cur.fetchone()
    release_conn(conn)

    return dict(row) if row else None


def list_threat_memory_nodes_db(limit=100):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    limit = max(1, min(int(limit or 100), 500))

    cur.execute(f"""
    SELECT *
    FROM threat_memory_nodes
    ORDER BY memory_score DESC,
             latent_risk_score DESC,
             updated_at DESC
    LIMIT {p}
    """, (limit,))

    rows = [dict(r) for r in cur.fetchall()]

    release_conn(conn)

    return {
        "status": "ok",
        "nodes": rows,
    }



def clamp_score(value, low=0.0, high=1.0):
    try:
        value = float(value or 0)
    except Exception:
        value = 0.0

    return max(low, min(value, high))


def evolve_threat_memory_from_seller_event_db(
    seller_id,
    event_type,
    severity="info",
    metadata=None,
):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    node = get_threat_memory_node_db(seller_id) or {}

    memory_score = float(node.get("memory_score", 0) or 0)
    latent_risk_score = float(node.get("latent_risk_score", 0) or 0)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    contagion_score = float(node.get("contagion_score", 0) or 0)
    recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    adaptive_trust_score = float(node.get("adaptive_trust_score", 0.5) or 0.5)

    severity_weight = {
        "info": 0.02,
        "low": 0.05,
        "medium": 0.10,
        "high": 0.20,
        "critical": 0.35,
    }.get(str(severity or "info").lower(), 0.02)

    event_type = str(event_type or "").lower()

    memory_score += severity_weight

    if event_type in ["seller_status_transition"]:
        new_status = str((metadata or {}).get("new_status", "")).lower()

        if new_status == "watchlist":
            latent_risk_score += 0.05
            quarantine_pressure += 0.03
            adaptive_trust_score -= 0.03
        elif new_status == "restricted":
            latent_risk_score += 0.15
            quarantine_pressure += 0.15
            adaptive_trust_score -= 0.10
        elif new_status == "contained":
            latent_risk_score += 0.25
            quarantine_pressure += 0.25
            mutation_score += 0.05
            adaptive_trust_score -= 0.20
        elif new_status in ["rejected", "banned"]:
            latent_risk_score += 0.35
            quarantine_pressure += 0.35
            mutation_score += 0.10
            adaptive_trust_score -= 0.35

    elif event_type in ["recovery_request"]:
        memory_score += 0.04
        recovery_confidence -= 0.05
        latent_risk_score += 0.03

    elif event_type in ["recovery_approved"]:
        recovery_confidence += 0.10
        quarantine_pressure -= 0.08
        adaptive_trust_score += 0.05

    elif event_type in ["recovery_rejected"]:
        recovery_confidence -= 0.15
        latent_risk_score += 0.10
        quarantine_pressure += 0.10

    elif event_type in ["runtime_violation", "runtime_dead", "runtime_quarantine"]:
        latent_risk_score += 0.12
        quarantine_pressure += 0.12
        mutation_score += 0.03
        adaptive_trust_score -= 0.08

    elif event_type in ["containment"]:
        latent_risk_score += 0.25
        quarantine_pressure += 0.25
        contagion_score += 0.10
        mutation_score += 0.08
        adaptive_trust_score -= 0.20

    updated_metadata = {
        "last_event_type": event_type,
        "last_severity": severity,
        "event_metadata": metadata or {},
    }

    return upsert_threat_memory_node_db(
        seller_id=seller_id,
        memory_score=clamp_score(memory_score),
        latent_risk_score=clamp_score(latent_risk_score),
        mutation_score=clamp_score(mutation_score),
        contagion_score=clamp_score(contagion_score),
        recovery_confidence=clamp_score(recovery_confidence),
        quarantine_pressure=clamp_score(quarantine_pressure),
        adaptive_trust_score=clamp_score(adaptive_trust_score),
        metadata=updated_metadata,
    )



def recompute_threat_memory_node_db(seller_id):
    if not seller_id:
        return {"status": "error", "message": "seller_id_required"}

    memories = get_active_threat_memory_db(
        scope="seller",
        subject_id=seller_id,
        limit=200,
    )

    memory_count = len(memories)

    if memory_count == 0:
        return upsert_threat_memory_node_db(
            seller_id=seller_id,
            memory_score=0,
            latent_risk_score=0,
            mutation_score=0,
            contagion_score=0,
            recovery_confidence=0.5,
            quarantine_pressure=0,
            adaptive_trust_score=0.5,
            metadata={
                "source": "recompute_threat_memory_node_db",
                "memory_count": 0,
            },
        )

    confidence_sum = 0.0
    strength_sum = 0.0
    critical_count = 0
    propagated_count = 0
    policy_pressure = 0
    guardrail_pressure = 0
    mutation_signals = 0

    for m in memories:
        confidence = float(m.get("confidence", 0) or 0)
        strength = float(m.get("memory_strength", 0.5) or 0.5)
        threat_level = str(m.get("threat_level", "") or "").lower()
        source = str(m.get("source", "") or "").lower()

        confidence_sum += confidence
        strength_sum += strength

        if threat_level in ["high", "critical"]:
            critical_count += 1

        if source == "propagated":
            propagated_count += 1

        if m.get("policy_update"):
            policy_pressure += 1

        if m.get("recommended_guardrail"):
            guardrail_pressure += 1

        text_blob = " ".join([
            str(m.get("attack_vector", "") or ""),
            str(m.get("signal_to_monitor", "") or ""),
            str(m.get("policy_update", "") or ""),
        ]).lower()

        if any(w in text_blob for w in [
            "mutation",
            "evasion",
            "sybil",
            "collusion",
            "fingerprint",
            "rotating",
            "coordinated",
            "reputation farming",
        ]):
            mutation_signals += 1

    avg_confidence = confidence_sum / max(memory_count, 1)
    avg_strength = strength_sum / max(memory_count, 1)

    memory_score = min(
        1.0,
        (memory_count / 20) * 0.25
        + avg_confidence * 0.35
        + avg_strength * 0.25
        + (critical_count / max(memory_count, 1)) * 0.15,
    )

    latent_risk_score = min(
        1.0,
        avg_confidence * 0.35
        + avg_strength * 0.25
        + min(critical_count, 10) / 10 * 0.25
        + min(policy_pressure, 10) / 10 * 0.15,
    )

    mutation_score = min(
        1.0,
        min(mutation_signals, 10) / 10 * 0.70
        + min(propagated_count, 10) / 10 * 0.30,
    )

    contagion_score = min(
        1.0,
        min(propagated_count, 10) / 10 * 0.65
        + min(critical_count, 10) / 10 * 0.35,
    )

    quarantine_pressure = min(
        1.0,
        latent_risk_score * 0.55
        + min(guardrail_pressure, 10) / 10 * 0.25
        + min(policy_pressure, 10) / 10 * 0.20,
    )

    recovery_confidence = max(
        0.0,
        min(
            1.0,
            0.75
            - latent_risk_score * 0.35
            - mutation_score * 0.20
            - contagion_score * 0.20,
        ),
    )

    adaptive_trust_score = max(
        0.0,
        min(
            1.0,
            0.80
            - latent_risk_score * 0.40
            - quarantine_pressure * 0.25
            - mutation_score * 0.20
            - contagion_score * 0.15,
        ),
    )

    return upsert_threat_memory_node_db(
        seller_id=seller_id,
        memory_score=round(memory_score, 6),
        latent_risk_score=round(latent_risk_score, 6),
        mutation_score=round(mutation_score, 6),
        contagion_score=round(contagion_score, 6),
        recovery_confidence=round(recovery_confidence, 6),
        quarantine_pressure=round(quarantine_pressure, 6),
        adaptive_trust_score=round(adaptive_trust_score, 6),
        metadata={
            "source": "recompute_threat_memory_node_db",
            "memory_count": memory_count,
            "critical_count": critical_count,
            "propagated_count": propagated_count,
            "policy_pressure": policy_pressure,
            "guardrail_pressure": guardrail_pressure,
            "mutation_signals": mutation_signals,
            "avg_confidence": round(avg_confidence, 6),
            "avg_strength": round(avg_strength, 6),
        },
    )



def recompute_graph_cognitive_pressure_db(agent_id):
    if not agent_id:
        return {"status": "error", "message": "agent_id_required"}

    graph = build_seller_graph_context_db(agent_id) or {}
    edges = graph.get("edges") or []

    if not edges:
        node = get_threat_memory_node_db(agent_id) or {}

        return upsert_threat_memory_node_db(
            seller_id=agent_id,
            memory_score=node.get("memory_score", 0),
            latent_risk_score=node.get("latent_risk_score", 0),
            mutation_score=node.get("mutation_score", 0),
            contagion_score=0,
            recovery_confidence=node.get("recovery_confidence", 0.5),
            quarantine_pressure=node.get("quarantine_pressure", 0),
            adaptive_trust_score=node.get("adaptive_trust_score", 0.5),
            metadata={
                "source": "recompute_graph_cognitive_pressure_db",
                "related_count": 0,
                "graph_position_score": 0,
                "ancestor_risk_score": 0,
                "descendant_risk_score": 0,
                "lineage_depth": 0,
            },
        )

    related_ids = set()

    for e in edges:
        source_id = e.get("source_agent_id")
        target_id = e.get("target_agent_id")

        if source_id and source_id != agent_id:
            related_ids.add(source_id)

        if target_id and target_id != agent_id:
            related_ids.add(target_id)

    node = get_threat_memory_node_db(agent_id) or {}

    own_memory_score = float(node.get("memory_score", 0) or 0)
    own_latent_risk = float(node.get("latent_risk_score", 0) or 0)
    own_mutation = float(node.get("mutation_score", 0) or 0)
    own_recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    own_quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    own_adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)

    weighted_neighbor_risk = 0.0
    weighted_neighbor_memory = 0.0
    weighted_neighbor_mutation = 0.0
    total_weight = 0.0
    high_risk_neighbors = 0

    for e in edges:
        source_id = e.get("source_agent_id")
        target_id = e.get("target_agent_id")
        weight = float(e.get("weight", 0) or 0)

        related_id = target_id if source_id == agent_id else source_id

        if not related_id or related_id == agent_id:
            continue

        related_node = get_threat_memory_node_db(related_id) or {}

        neighbor_risk = float(related_node.get("latent_risk_score", 0) or 0)
        neighbor_memory = float(related_node.get("memory_score", 0) or 0)
        neighbor_mutation = float(related_node.get("mutation_score", 0) or 0)

        weighted_neighbor_risk += neighbor_risk * weight
        weighted_neighbor_memory += neighbor_memory * weight
        weighted_neighbor_mutation += neighbor_mutation * weight
        total_weight += weight

        if neighbor_risk >= 0.65 or neighbor_mutation >= 0.5:
            high_risk_neighbors += 1

    if total_weight > 0:
        ancestor_risk_score = min(1.0, weighted_neighbor_risk / total_weight)
        descendant_risk_score = min(1.0, weighted_neighbor_memory / total_weight)
        inherited_mutation = min(1.0, weighted_neighbor_mutation / total_weight)
    else:
        ancestor_risk_score = 0.0
        descendant_risk_score = 0.0
        inherited_mutation = 0.0

    related_count = len(related_ids)

    graph_position_score = min(
        1.0,
        min(related_count, 20) / 20 * 0.45
        + min(total_weight, 3.0) / 3.0 * 0.35
        + min(high_risk_neighbors, 5) / 5 * 0.20,
    )

    contagion_score = min(
        1.0,
        ancestor_risk_score * 0.45
        + descendant_risk_score * 0.20
        + inherited_mutation * 0.20
        + min(high_risk_neighbors, 5) / 5 * 0.15,
    )

    lineage_depth = min(
        10,
        int(
            min(related_count, 20) / 2
            + min(high_risk_neighbors, 5)
        ),
    )

    latent_risk_score = min(
        1.0,
        own_latent_risk * 0.70
        + contagion_score * 0.30,
    )

    mutation_score = min(
        1.0,
        own_mutation * 0.75
        + inherited_mutation * 0.25,
    )

    quarantine_pressure = min(
        1.0,
        own_quarantine_pressure * 0.70
        + contagion_score * 0.20
        + graph_position_score * 0.10,
    )

    adaptive_trust_score = max(
        0.0,
        min(
            1.0,
            own_adaptive_trust
            - contagion_score * 0.12
            - graph_position_score * 0.08
            - inherited_mutation * 0.10,
        ),
    )

    recovery_confidence = max(
        0.0,
        min(
            1.0,
            own_recovery_confidence
            - contagion_score * 0.10
            - high_risk_neighbors * 0.03,
        ),
    )

    result = upsert_threat_memory_node_db(
        seller_id=agent_id,
        memory_score=round(own_memory_score, 6),
        latent_risk_score=round(latent_risk_score, 6),
        mutation_score=round(mutation_score, 6),
        contagion_score=round(contagion_score, 6),
        recovery_confidence=round(recovery_confidence, 6),
        quarantine_pressure=round(quarantine_pressure, 6),
        adaptive_trust_score=round(adaptive_trust_score, 6),
        lineage_depth=lineage_depth,
        ancestor_risk_score=round(ancestor_risk_score, 6),
        descendant_risk_score=round(descendant_risk_score, 6),
        graph_position_score=round(graph_position_score, 6),
        metadata={
            "source": "recompute_graph_cognitive_pressure_db",
            "related_count": related_count,
            "edge_count": len(edges),
            "total_weight": round(total_weight, 6),
            "high_risk_neighbors": high_risk_neighbors,
            "ancestor_risk_score": round(ancestor_risk_score, 6),
            "descendant_risk_score": round(descendant_risk_score, 6),
            "graph_position_score": round(graph_position_score, 6),
            "lineage_depth": lineage_depth,
            "inherited_mutation": round(inherited_mutation, 6),
        },
    )

    return {
        "status": "ok",
        "agent_id": agent_id,
        "related_count": related_count,
        "edge_count": len(edges),
        "ancestor_risk_score": round(ancestor_risk_score, 6),
        "descendant_risk_score": round(descendant_risk_score, 6),
        "graph_position_score": round(graph_position_score, 6),
        "contagion_score": round(contagion_score, 6),
        "lineage_depth": lineage_depth,
        "node_update": result,
    }



def list_runtime_monitored_seller_agents_db(limit=100):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    limit = max(1, min(int(limit or 100), 500))

    cur.execute(f"""
    SELECT *
    FROM seller_agents
    WHERE seller_agent_status IN ('active', 'pending')
      AND COALESCE(runtime_validation_status, '') != 'quarantined'
    ORDER BY updated_at DESC
    LIMIT {p}
    """, (limit,))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    return rows



def init_adversarial_mutation_signatures_table():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS adversarial_mutation_signatures (
        mutation_signature_id TEXT PRIMARY KEY,
        scope TEXT DEFAULT 'seller',
        subject_id TEXT,
        mutation_signature TEXT,
        evolution_family TEXT,
        stealth_score REAL DEFAULT 0,
        adaptive_complexity REAL DEFAULT 0,
        emergence_probability REAL DEFAULT 0,
        mutation_velocity REAL DEFAULT 0,
        confidence REAL DEFAULT 0,
        source TEXT DEFAULT 'protocol',
        evidence TEXT DEFAULT '{}',
        first_seen_at INTEGER,
        last_seen_at INTEGER,
        times_seen INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active'
    )
    """)

    conn.commit()
    release_conn(conn)


def upsert_adversarial_mutation_signature_db(
    subject_id,
    mutation_signature,
    evolution_family="unknown",
    stealth_score=0,
    adaptive_complexity=0,
    emergence_probability=0,
    mutation_velocity=0,
    confidence=0.5,
    scope="seller",
    source="protocol",
    evidence=None,
):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    if not mutation_signature:
        return {"status": "error", "message": "mutation_signature_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()
    now = int(time.time())

    cur.execute(f"""
    SELECT *
    FROM adversarial_mutation_signatures
    WHERE scope = {p}
      AND subject_id = {p}
      AND mutation_signature = {p}
      AND evolution_family = {p}
      AND status = 'active'
    LIMIT 1
    """, (
        scope,
        subject_id,
        mutation_signature,
        evolution_family,
    ))

    existing = cur.fetchone()

    if existing:
        mutation_signature_id = row_get(existing, "mutation_signature_id")
        times_seen = int(row_get(existing, "times_seen", 1) or 1) + 1

        cur.execute(f"""
        UPDATE adversarial_mutation_signatures
        SET stealth_score = MAX(COALESCE(stealth_score, 0), {p}),
            adaptive_complexity = MAX(COALESCE(adaptive_complexity, 0), {p}),
            emergence_probability = MAX(COALESCE(emergence_probability, 0), {p}),
            mutation_velocity = MAX(COALESCE(mutation_velocity, 0), {p}),
            confidence = MAX(COALESCE(confidence, 0), {p}),
            evidence = {p},
            last_seen_at = {p},
            times_seen = {p}
        WHERE mutation_signature_id = {p}
        """, (
            float(stealth_score or 0),
            float(adaptive_complexity or 0),
            float(emergence_probability or 0),
            float(mutation_velocity or 0),
            float(confidence or 0),
            json.dumps(evidence or {}),
            now,
            times_seen,
            mutation_signature_id,
        ))

        created = False
    else:
        mutation_signature_id = "mutation_signature_" + str(uuid.uuid4())

        cur.execute(f"""
        INSERT INTO adversarial_mutation_signatures (
            mutation_signature_id,
            scope,
            subject_id,
            mutation_signature,
            evolution_family,
            stealth_score,
            adaptive_complexity,
            emergence_probability,
            mutation_velocity,
            confidence,
            source,
            evidence,
            first_seen_at,
            last_seen_at,
            times_seen,
            status
        ) VALUES (
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p},
            {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}
        )
        """, (
            mutation_signature_id,
            scope,
            subject_id,
            mutation_signature,
            evolution_family,
            float(stealth_score or 0),
            float(adaptive_complexity or 0),
            float(emergence_probability or 0),
            float(mutation_velocity or 0),
            float(confidence or 0),
            source,
            json.dumps(evidence or {}),
            now,
            now,
            1,
            "active",
        ))

        created = True

    conn.commit()
    release_conn(conn)

    return {
        "status": "ok",
        "mutation_signature_id": mutation_signature_id,
        "subject_id": subject_id,
        "created": created,
    }



def extract_adversarial_mutation_signature_from_text(text):
    text = str(text or "").lower()

    signatures = []

    patterns = [
        {
            "keywords": ["sybil", "multiple seller", "fake sellers", "many accounts"],
            "signature": "sybil_identity_expansion",
            "family": "sybil_family",
            "stealth": 0.65,
            "complexity": 0.70,
        },
        {
            "keywords": ["collusion", "coordinated", "synchronized", "cartel"],
            "signature": "coordinated_collusion_pattern",
            "family": "collusion_family",
            "stealth": 0.70,
            "complexity": 0.75,
        },
        {
            "keywords": ["reputation farming", "fake reputation", "wash trading", "self dealing"],
            "signature": "reputation_farming_loop",
            "family": "reputation_manipulation_family",
            "stealth": 0.78,
            "complexity": 0.72,
        },
        {
            "keywords": ["rotating endpoint", "rotating endpoints", "rotating url", "proxy", "infrastructure rotation"],
            "signature": "rotating_runtime_infrastructure",
            "family": "infrastructure_evasion_family",
            "stealth": 0.82,
            "complexity": 0.80,
        },
        {
            "keywords": ["fingerprint", "fingerprint overlap", "shared fingerprint"],
            "signature": "fingerprint_overlap_evasion",
            "family": "fingerprint_evasion_family",
            "stealth": 0.74,
            "complexity": 0.68,
        },
        {
            "keywords": ["recovery manipulation", "appeal abuse", "fake recovery", "rehabilitation abuse"],
            "signature": "recovery_manipulation_attempt",
            "family": "governance_evasion_family",
            "stealth": 0.76,
            "complexity": 0.66,
        },
        {
            "keywords": ["latency manipulation", "timeout pattern", "selective failure", "selective failures"],
            "signature": "runtime_behavior_manipulation",
            "family": "runtime_evasion_family",
            "stealth": 0.69,
            "complexity": 0.64,
        },
    ]

    for ptn in patterns:
        if any(k in text for k in ptn["keywords"]):
            signatures.append(ptn)

    return signatures


def derive_adversarial_mutation_signatures_from_threat_memory_db(
    subject_id,
    memory,
):
    if not subject_id or not memory:
        return {
            "status": "ignored",
            "reason": "missing_subject_or_memory",
        }

    text_blob = " ".join([
        str(memory.get("attack_vector", "") or ""),
        str(memory.get("recommended_guardrail", "") or ""),
        str(memory.get("signal_to_monitor", "") or ""),
        str(memory.get("policy_update", "") or ""),
    ])

    extracted = extract_adversarial_mutation_signature_from_text(text_blob)

    if not extracted:
        return {
            "status": "ignored",
            "reason": "no_mutation_signature_detected",
        }

    confidence = float(memory.get("confidence", 0.5) or 0.5)

    results = []

    for item in extracted:
        result = upsert_adversarial_mutation_signature_db(
            subject_id=subject_id,
            mutation_signature=item.get("signature"),
            evolution_family=item.get("family"),
            stealth_score=item.get("stealth", 0),
            adaptive_complexity=item.get("complexity", 0),
            emergence_probability=min(1.0, confidence * 0.85),
            mutation_velocity=0.25,
            confidence=confidence,
            scope=str(memory.get("scope", "seller") or "seller"),
            source="threat_memory_derivation",
            evidence={
                "source": "derive_adversarial_mutation_signatures_from_threat_memory_db",
                "memory_id": memory.get("id"),
                "text_blob": text_blob[:1000],
            },
        )
        results.append(result)

    return {
        "status": "ok",
        "subject_id": subject_id,
        "derived": len(results),
        "results": results,
    }



def compute_adversarial_mutation_pressure_db(subject_id, scope="seller"):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    cur.execute(f"""
    SELECT *
    FROM adversarial_mutation_signatures
    WHERE scope = {p}
      AND subject_id = {p}
      AND status = 'active'
    """, (
        scope,
        subject_id,
    ))

    rows = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    if not rows:
        return {
            "status": "ok",
            "subject_id": subject_id,
            "mutation_pressure_score": 0.0,
            "mutation_family_count": 0,
            "dominant_evolution_family": None,
            "signatures_seen": 0,
        }

    family_scores = {}
    total_pressure = 0.0

    for r in rows:
        family = str(r.get("evolution_family") or "unknown")

        stealth = float(r.get("stealth_score", 0) or 0)
        complexity = float(r.get("adaptive_complexity", 0) or 0)
        emergence = float(r.get("emergence_probability", 0) or 0)
        velocity = float(r.get("mutation_velocity", 0) or 0)
        confidence = float(r.get("confidence", 0) or 0)
        times_seen = int(r.get("times_seen", 1) or 1)

        repetition_factor = min(1.0, times_seen / 5)

        pressure = min(
            1.0,
            stealth * 0.22
            + complexity * 0.22
            + emergence * 0.24
            + velocity * 0.12
            + confidence * 0.15
            + repetition_factor * 0.05,
        )

        total_pressure += pressure
        family_scores[family] = family_scores.get(family, 0.0) + pressure

    mutation_pressure_score = min(
        1.0,
        total_pressure / max(len(rows), 1)
        + min(len(family_scores), 6) / 6 * 0.12,
    )

    dominant_evolution_family = max(
        family_scores,
        key=family_scores.get,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "mutation_pressure_score": round(mutation_pressure_score, 6),
        "mutation_family_count": len(family_scores),
        "dominant_evolution_family": dominant_evolution_family,
        "signatures_seen": len(rows),
        "family_scores": {
            k: round(v, 6)
            for k, v in family_scores.items()
        },
    }



def sync_adversarial_mutation_pressure_to_memory_node_db(subject_id, scope="seller"):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    pressure = compute_adversarial_mutation_pressure_db(
        subject_id=subject_id,
        scope=scope,
    )

    if pressure.get("status") != "ok":
        return pressure

    mutation_pressure_score = float(
        pressure.get("mutation_pressure_score", 0) or 0
    )

    node = get_threat_memory_node_db(subject_id) or {}

    memory_score = float(node.get("memory_score", 0) or 0)
    latent_risk_score = float(node.get("latent_risk_score", 0) or 0)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    contagion_score = float(node.get("contagion_score", 0) or 0)
    recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    adaptive_trust_score = float(node.get("adaptive_trust_score", 0.5) or 0.5)

    new_mutation_score = min(
        1.0,
        mutation_score * 0.65 + mutation_pressure_score * 0.35,
    )

    new_latent_risk_score = min(
        1.0,
        latent_risk_score * 0.75 + mutation_pressure_score * 0.25,
    )

    new_quarantine_pressure = min(
        1.0,
        quarantine_pressure * 0.75 + mutation_pressure_score * 0.25,
    )

    new_recovery_confidence = max(
        0.0,
        recovery_confidence - mutation_pressure_score * 0.12,
    )

    new_adaptive_trust_score = max(
        0.0,
        adaptive_trust_score - mutation_pressure_score * 0.15,
    )

    result = upsert_threat_memory_node_db(
        seller_id=subject_id,
        memory_score=round(memory_score, 6),
        latent_risk_score=round(new_latent_risk_score, 6),
        mutation_score=round(new_mutation_score, 6),
        contagion_score=round(contagion_score, 6),
        recovery_confidence=round(new_recovery_confidence, 6),
        quarantine_pressure=round(new_quarantine_pressure, 6),
        adaptive_trust_score=round(new_adaptive_trust_score, 6),
        lineage_depth=node.get("lineage_depth", 0),
        ancestor_risk_score=node.get("ancestor_risk_score", 0),
        descendant_risk_score=node.get("descendant_risk_score", 0),
        graph_position_score=node.get("graph_position_score", 0),
        metadata={
            "source": "sync_adversarial_mutation_pressure_to_memory_node_db",
            "mutation_pressure": pressure,
        },
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "mutation_pressure_score": round(mutation_pressure_score, 6),
        "dominant_evolution_family": pressure.get("dominant_evolution_family"),
        "mutation_family_count": pressure.get("mutation_family_count"),
        "node_update": result,
        "new_scores": {
            "latent_risk_score": round(new_latent_risk_score, 6),
            "mutation_score": round(new_mutation_score, 6),
            "quarantine_pressure": round(new_quarantine_pressure, 6),
            "recovery_confidence": round(new_recovery_confidence, 6),
            "adaptive_trust_score": round(new_adaptive_trust_score, 6),
        },
    }



def compute_autonomous_governance_recommendation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    node = get_threat_memory_node_db(subject_id) or {}

    mutation_pressure = compute_adversarial_mutation_pressure_db(subject_id)

    memory_score = float(node.get("memory_score", 0) or 0)
    latent_risk = float(node.get("latent_risk_score", 0) or 0)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    contagion_score = float(node.get("contagion_score", 0) or 0)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)
    graph_position = float(node.get("graph_position_score", 0) or 0)

    mutation_pressure_score = float(
        mutation_pressure.get("mutation_pressure_score", 0) or 0
    )

    governance_pressure = min(
        1.0,
        memory_score * 0.12
        + latent_risk * 0.22
        + mutation_score * 0.16
        + contagion_score * 0.16
        + quarantine_pressure * 0.18
        + mutation_pressure_score * 0.12
        + graph_position * 0.04
        + max(0.0, 0.5 - adaptive_trust) * 0.20,
    )

    if governance_pressure >= 0.82:
        recommendation = "containment_candidate"
        severity = "critical"
    elif governance_pressure >= 0.68:
        recommendation = "quarantine_review"
        severity = "high"
    elif governance_pressure >= 0.52:
        recommendation = "restrict_routing"
        severity = "medium_high"
    elif governance_pressure >= 0.38:
        recommendation = "require_more_stake"
        severity = "medium"
    elif governance_pressure >= 0.24:
        recommendation = "reduce_exposure"
        severity = "low_medium"
    elif governance_pressure >= 0.12:
        recommendation = "monitor"
        severity = "low"
    else:
        recommendation = "no_action"
        severity = "info"

    return {
        "status": "ok",
        "subject_id": subject_id,
        "governance_pressure": round(governance_pressure, 6),
        "recommendation": recommendation,
        "severity": severity,
        "dominant_evolution_family": mutation_pressure.get(
            "dominant_evolution_family"
        ),
        "mutation_family_count": mutation_pressure.get("mutation_family_count"),
        "signals": {
            "memory_score": round(memory_score, 6),
            "latent_risk_score": round(latent_risk, 6),
            "mutation_score": round(mutation_score, 6),
            "contagion_score": round(contagion_score, 6),
            "quarantine_pressure": round(quarantine_pressure, 6),
            "adaptive_trust_score": round(adaptive_trust, 6),
            "graph_position_score": round(graph_position, 6),
            "mutation_pressure_score": round(mutation_pressure_score, 6),
        },
        "advisory_only": True,
    }



def record_autonomous_governance_recommendation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    recommendation = compute_autonomous_governance_recommendation_db(subject_id)

    if recommendation.get("status") != "ok":
        return recommendation

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="autonomous_governance_recommendation",
        reviewer="autonomous_governance_engine",
        reason=recommendation.get("recommendation"),
        old_status="",
        new_status="",
        metadata=recommendation,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "recommendation": recommendation,
        "governance_event": event_result,
    }



def compute_adaptive_protocol_response_plan_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    recommendation = compute_autonomous_governance_recommendation_db(
        subject_id
    )

    if recommendation.get("status") != "ok":
        return recommendation

    governance_pressure = float(
        recommendation.get("governance_pressure", 0) or 0
    )

    recommendation_type = str(
        recommendation.get("recommendation", "no_action")
    )

    dominant_family = recommendation.get(
        "dominant_evolution_family"
    )

    actions = {
        "recommended_actions": [],
        "economic_actions": [],
        "routing_actions": [],
        "monitoring_actions": [],
        "containment_preparation": [],
        "recovery_constraints": [],
        "trust_degradation_strategy": [],
    }

    if recommendation_type == "monitor":
        actions["monitoring_actions"] += [
            "increase behavioral observation",
            "enable graph monitoring",
        ]

    elif recommendation_type == "reduce_exposure":
        actions["routing_actions"] += [
            "reduce routing exposure by 15%",
            "deprioritize low-confidence execution",
        ]

        actions["monitoring_actions"] += [
            "increase runtime validation frequency",
        ]

    elif recommendation_type == "require_more_stake":
        actions["economic_actions"] += [
            "increase minimum stake requirement by 35%",
            "increase escrow reserve requirement",
        ]

        actions["routing_actions"] += [
            "reduce routing exposure by 20%",
        ]

        actions["monitoring_actions"] += [
            "enable continuous graph monitoring",
            "increase runtime behavioral verification",
        ]

        actions["trust_degradation_strategy"] += [
            "apply progressive trust degradation",
        ]

    elif recommendation_type == "restrict_routing":
        actions["routing_actions"] += [
            "reduce routing exposure by 45%",
            "block high-value task routing",
            "limit concurrent executions",
        ]

        actions["monitoring_actions"] += [
            "activate deep runtime inspection",
            "enable high-frequency graph analysis",
        ]

        actions["economic_actions"] += [
            "increase collateral requirements",
        ]

    elif recommendation_type == "quarantine_review":
        actions["containment_preparation"] += [
            "freeze new seller agents",
            "prepare graph isolation",
            "prepare containment review",
        ]

        actions["routing_actions"] += [
            "reduce routing exposure by 75%",
        ]

        actions["monitoring_actions"] += [
            "trigger deep adversarial inspection",
            "monitor neighboring sellers",
        ]

        actions["economic_actions"] += [
            "increase escrow delay",
            "lock adaptive rewards",
        ]

    elif recommendation_type == "containment_candidate":
        actions["containment_preparation"] += [
            "prepare seller containment",
            "prepare graph quarantine",
            "prepare emergency routing isolation",
        ]

        actions["routing_actions"] += [
            "block strategic execution access",
            "restrict autonomous execution",
        ]

        actions["economic_actions"] += [
            "freeze protocol incentives",
            "increase protocol reserve protection",
        ]

        actions["monitoring_actions"] += [
            "activate maximum runtime surveillance",
            "enable mutation lineage analysis",
        ]

    if dominant_family == "infrastructure_evasion_family":
        actions["monitoring_actions"] += [
            "monitor endpoint rotation",
            "monitor infrastructure mutation velocity",
        ]

    elif dominant_family == "sybil_family":
        actions["monitoring_actions"] += [
            "monitor seller identity expansion",
            "monitor graph duplication behavior",
        ]

    elif dominant_family == "collusion_family":
        actions["monitoring_actions"] += [
            "monitor synchronized execution behavior",
            "monitor coordinated routing anomalies",
        ]

    elif dominant_family == "reputation_manipulation_family":
        actions["economic_actions"] += [
            "reduce reputation amplification",
            "increase reputation decay pressure",
        ]

    elif dominant_family == "fingerprint_evasion_family":
        actions["monitoring_actions"] += [
            "increase runtime fingerprint analysis",
            "monitor shared infrastructure fingerprints",
        ]

    actions["recommended_actions"] = sorted(set(
        actions["economic_actions"]
        + actions["routing_actions"]
        + actions["monitoring_actions"]
        + actions["containment_preparation"]
        + actions["recovery_constraints"]
        + actions["trust_degradation_strategy"]
    ))

    return {
        "status": "ok",
        "subject_id": subject_id,
        "governance_pressure": governance_pressure,
        "recommendation": recommendation_type,
        "dominant_evolution_family": dominant_family,
        "adaptive_response_plan": actions,
        "advisory_only": True,
    }



def simulate_protocol_response_impact_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    plan = compute_adaptive_protocol_response_plan_db(subject_id)

    if plan.get("status") != "ok":
        return plan

    node = get_threat_memory_node_db(subject_id) or {}

    governance_pressure = float(plan.get("governance_pressure", 0) or 0)
    recommendation = str(plan.get("recommendation", "no_action") or "no_action")

    adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)
    contagion = float(node.get("contagion_score", 0) or 0)
    graph_position = float(node.get("graph_position_score", 0) or 0)
    recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)

    action_intensity = {
        "no_action": 0.00,
        "monitor": 0.10,
        "reduce_exposure": 0.25,
        "require_more_stake": 0.35,
        "restrict_routing": 0.55,
        "quarantine_review": 0.75,
        "containment_candidate": 0.90,
    }.get(recommendation, 0.20)

    economic_impact = min(
        1.0,
        action_intensity * 0.55
        + governance_pressure * 0.25
        + mutation_score * 0.20,
    )

    routing_impact = min(
        1.0,
        action_intensity * 0.65
        + quarantine_pressure * 0.25
        + contagion * 0.10,
    )

    reputation_impact = min(
        1.0,
        action_intensity * 0.45
        + governance_pressure * 0.35
        + mutation_score * 0.20,
    )

    contagion_impact = min(
        1.0,
        contagion * 0.45
        + graph_position * 0.25
        + action_intensity * 0.30,
    )

    false_positive_risk = min(
        1.0,
        max(0.0, adaptive_trust - 0.45) * 0.45
        + recovery_confidence * 0.25
        + max(0.0, 0.45 - governance_pressure) * 0.30,
    )

    protocol_stability_risk = min(
        1.0,
        routing_impact * 0.35
        + economic_impact * 0.25
        + contagion_impact * 0.25
        + false_positive_risk * 0.15,
    )

    action_safety_score = max(
        0.0,
        min(
            1.0,
            1.0
            - protocol_stability_risk * 0.40
            - false_positive_risk * 0.35
            + governance_pressure * 0.25,
        ),
    )

    if action_safety_score >= 0.72:
        simulation_decision = "safe_to_execute_with_controls"
    elif action_safety_score >= 0.50:
        simulation_decision = "execute_cautiously"
    elif action_safety_score >= 0.32:
        simulation_decision = "human_review_recommended"
    else:
        simulation_decision = "do_not_execute"

    return {
        "status": "ok",
        "subject_id": subject_id,
        "recommendation": recommendation,
        "governance_pressure": round(governance_pressure, 6),
        "action_intensity": round(action_intensity, 6),
        "impact": {
            "economic_impact": round(economic_impact, 6),
            "routing_impact": round(routing_impact, 6),
            "reputation_impact": round(reputation_impact, 6),
            "contagion_impact": round(contagion_impact, 6),
            "false_positive_risk": round(false_positive_risk, 6),
            "protocol_stability_risk": round(protocol_stability_risk, 6),
            "action_safety_score": round(action_safety_score, 6),
        },
        "simulation_decision": simulation_decision,
        "adaptive_response_plan": plan.get("adaptive_response_plan"),
        "advisory_only": True,
    }



def record_protocol_response_simulation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    simulation = simulate_protocol_response_impact_db(subject_id)

    if simulation.get("status") != "ok":
        return simulation

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="protocol_response_impact_simulation",
        reviewer="protocol_simulation_engine",
        reason=simulation.get("simulation_decision"),
        old_status="",
        new_status="",
        metadata=simulation,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "simulation": simulation,
        "governance_event": event_result,
    }



def authorize_protocol_response_execution_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    simulation = simulate_protocol_response_impact_db(subject_id)

    if simulation.get("status") != "ok":
        return simulation

    impact = simulation.get("impact") or {}

    action_safety_score = float(
        impact.get("action_safety_score", 0) or 0
    )

    false_positive_risk = float(
        impact.get("false_positive_risk", 1) or 1
    )

    protocol_stability_risk = float(
        impact.get("protocol_stability_risk", 1) or 1
    )

    recommendation = str(
        simulation.get("recommendation", "no_action") or "no_action"
    )

    simulation_decision = str(
        simulation.get("simulation_decision", "") or ""
    )

    high_impact_actions = [
        "restrict_routing",
        "quarantine_review",
        "containment_candidate",
    ]

    auto_allowed = False
    execution_mode = "advisory_only"
    required_review = False
    reason = "default_advisory_mode"

    if recommendation == "no_action":
        auto_allowed = True
        execution_mode = "controlled_auto"
        reason = "no_action_safe"

    elif (
        simulation_decision == "safe_to_execute_with_controls"
        and action_safety_score >= 0.85
        and false_positive_risk <= 0.20
        and protocol_stability_risk <= 0.35
        and recommendation not in high_impact_actions
    ):
        auto_allowed = True
        execution_mode = "controlled_auto"
        reason = "safe_low_impact_response"

    elif (
        simulation_decision in ["safe_to_execute_with_controls", "execute_cautiously"]
        and action_safety_score >= 0.60
        and false_positive_risk <= 0.35
    ):
        auto_allowed = False
        execution_mode = "review_required"
        required_review = True
        reason = "requires_governance_review_before_execution"

    else:
        auto_allowed = False
        execution_mode = "blocked"
        required_review = True
        reason = "execution_not_safe"

    event_result = create_deduped_seller_governance_event_db(
        seller_id=subject_id,
        event_type="protocol_execution_gate_decision",
        reviewer="protocol_execution_gate",
        reason=reason,
        old_status="",
        new_status="",
        metadata={
            "simulation": simulation,
            "auto_allowed": auto_allowed,
            "execution_mode": execution_mode,
            "required_review": required_review,
            "reason": reason,
        },
        dedupe_window_seconds=900,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "auto_allowed": auto_allowed,
        "execution_mode": execution_mode,
        "required_review": required_review,
        "reason": reason,
        "recommendation": recommendation,
        "simulation_decision": simulation_decision,
        "action_safety_score": round(action_safety_score, 6),
        "false_positive_risk": round(false_positive_risk, 6),
        "protocol_stability_risk": round(protocol_stability_risk, 6),
        "governance_event": event_result,
    }



def apply_controlled_protocol_response_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    gate = authorize_protocol_response_execution_db(subject_id)

    if gate.get("status") != "ok":
        return gate

    if not gate.get("auto_allowed"):
        return {
            "status": "blocked",
            "subject_id": subject_id,
            "reason": gate.get("reason"),
            "execution_mode": gate.get("execution_mode"),
            "gate": gate,
        }

    recommendation = str(gate.get("recommendation") or "no_action")

    allowed_map = {
        "no_action": 0.0,
        "monitor": 0.03,
        "reduce_exposure": 0.08,
        "require_more_stake": 0.12,
    }

    if recommendation not in allowed_map:
        return {
            "status": "blocked",
            "subject_id": subject_id,
            "reason": "recommendation_not_allowed_for_controlled_auto",
            "recommendation": recommendation,
            "gate": gate,
        }

    severity = allowed_map[recommendation]

    if severity <= 0:
        event_result = create_seller_governance_event_db(
            seller_id=subject_id,
            event_type="controlled_protocol_response_no_action",
            reviewer="controlled_protocol_response_engine",
            reason="no_action_required",
            metadata={"gate": gate},
        )

        return {
            "status": "ok",
            "subject_id": subject_id,
            "action_applied": "no_action",
            "governance_event": event_result,
            "gate": gate,
        }

    safety = can_execute_autonomous_action_db(
        subject_id=subject_id,
        action_type=recommendation,
        window_seconds=3600,
        max_subject_actions=1,
        max_global_actions=20,
        action_severity=severity,
        max_subject_severity_budget=0.25,
        max_global_severity_budget=2.0,
    )

    if safety.get("status") != "ok" or not safety.get("allowed"):
        event_result = create_deduped_seller_governance_event_db(
            seller_id=subject_id,
            event_type="controlled_protocol_response_safety_blocked",
            reviewer="autonomous_execution_safety_layer",
            reason=safety.get("reason", "autonomous_execution_blocked"),
            metadata={
                "gate": gate,
                "safety": safety,
                "recommendation": recommendation,
                "severity": severity,
            },
            dedupe_window_seconds=3600,
        )

        return {
            "status": "blocked",
            "message": "autonomous_execution_safety_blocked",
            "subject_id": subject_id,
            "recommendation": recommendation,
            "severity": severity,
            "safety": safety,
            "governance_event": event_result,
            "gate": gate,
        }

    result = apply_seller_risk_event_db(
        seller_id=subject_id,
        event_type="controlled_protocol_response",
        severity=severity,
        reason=f"controlled_auto:{recommendation}",
    )

    if result.get("status") != "ok":
        event_result = create_seller_governance_event_db(
            seller_id=subject_id,
            event_type="controlled_protocol_response_failed",
            reviewer="controlled_protocol_response_engine",
            reason=f"controlled_auto_failed:{recommendation}",
            metadata={
                "gate": gate,
                "risk_event_result": result,
                "applied_severity": severity,
            },
        )

        return {
            "status": "error",
            "message": "controlled_protocol_response_failed",
            "subject_id": subject_id,
            "action_attempted": recommendation,
            "severity": severity,
            "risk_event_result": result,
            "governance_event": event_result,
            "gate": gate,
        }

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="controlled_protocol_response_applied",
        reviewer="controlled_protocol_response_engine",
        reason=f"controlled_auto:{recommendation}",
        metadata={
            "gate": gate,
            "risk_event_result": result,
            "applied_severity": severity,
        },
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "action_applied": recommendation,
        "severity": severity,
        "risk_event_result": result,
        "governance_event": event_result,
        "gate": gate,
    }



def compute_autonomous_recovery_recommendation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    node = get_threat_memory_node_db(subject_id) or {}

    mutation_pressure = compute_adversarial_mutation_pressure_db(subject_id)

    memory_score = float(node.get("memory_score", 0) or 0)
    latent_risk = float(node.get("latent_risk_score", 0) or 0)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    contagion_score = float(node.get("contagion_score", 0) or 0)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)
    graph_position = float(node.get("graph_position_score", 0) or 0)

    mutation_pressure_score = float(
        mutation_pressure.get("mutation_pressure_score", 0) or 0
    )

    temporal = compute_temporal_behavior_stability_db(
        subject_id,
        window_days=30,
    )

    behavior_stability = float(
        temporal.get("behavior_stability_score", 0.5) or 0.5
    )
    temporal_reliability = float(
        temporal.get("temporal_reliability", 0.5) or 0.5
    )
    risk_volatility = float(
        temporal.get("risk_volatility", 0) or 0
    )
    relapse_velocity = float(
        temporal.get("relapse_velocity", 0) or 0
    )

    recovery_score = max(
        0.0,
        min(
            1.0,
            recovery_confidence * 0.24
            + adaptive_trust * 0.18
            + behavior_stability * 0.16
            + temporal_reliability * 0.14
            + max(0.0, 1.0 - latent_risk) * 0.10
            + max(0.0, 1.0 - mutation_pressure_score) * 0.08
            + max(0.0, 1.0 - contagion_score) * 0.05
            + max(0.0, 1.0 - quarantine_pressure) * 0.05,
        ),
    )

    residual_threat_pressure = min(
        1.0,
        latent_risk * 0.22
        + mutation_score * 0.16
        + mutation_pressure_score * 0.20
        + contagion_score * 0.12
        + quarantine_pressure * 0.12
        + memory_score * 0.06
        + risk_volatility * 0.07
        + relapse_velocity * 0.05,
    )

    if residual_threat_pressure >= 0.70:
        recommendation = "no_recovery"
        severity = "high_residual_threat"
    elif recovery_score >= 0.82 and residual_threat_pressure <= 0.25:
        recommendation = "trusted_recovery_candidate"
        severity = "low"
    elif recovery_score >= 0.68 and residual_threat_pressure <= 0.40:
        recommendation = "controlled_rehabilitation_candidate"
        severity = "low_medium"
    elif recovery_score >= 0.54 and residual_threat_pressure <= 0.55:
        recommendation = "partial_rehabilitation_candidate"
        severity = "medium"
    elif recovery_score >= 0.42:
        recommendation = "monitor_recovery"
        severity = "medium_high"
    else:
        recommendation = "no_recovery"
        severity = "insufficient_recovery_confidence"

    return {
        "status": "ok",
        "subject_id": subject_id,
        "recovery_score": round(recovery_score, 6),
        "residual_threat_pressure": round(residual_threat_pressure, 6),
        "recommendation": recommendation,
        "severity": severity,
        "dominant_evolution_family": mutation_pressure.get(
            "dominant_evolution_family"
        ),
        "signals": {
            "memory_score": round(memory_score, 6),
            "latent_risk_score": round(latent_risk, 6),
            "mutation_score": round(mutation_score, 6),
            "mutation_pressure_score": round(mutation_pressure_score, 6),
            "contagion_score": round(contagion_score, 6),
            "quarantine_pressure": round(quarantine_pressure, 6),
            "recovery_confidence": round(recovery_confidence, 6),
            "adaptive_trust_score": round(adaptive_trust, 6),
            "graph_position_score": round(graph_position, 6),
            "behavior_stability_score": round(behavior_stability, 6),
            "temporal_reliability": round(temporal_reliability, 6),
            "risk_volatility": round(risk_volatility, 6),
            "relapse_velocity": round(relapse_velocity, 6),
        },
        "temporal": temporal,
        "advisory_only": True,
    }



def record_autonomous_recovery_recommendation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    recommendation = compute_autonomous_recovery_recommendation_db(subject_id)

    if recommendation.get("status") != "ok":
        return recommendation

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="autonomous_recovery_recommendation",
        reviewer="autonomous_recovery_engine",
        reason=recommendation.get("recommendation"),
        old_status="",
        new_status="",
        metadata=recommendation,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "recommendation": recommendation,
        "governance_event": event_result,
    }



def simulate_rehabilitation_impact_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    recovery = compute_autonomous_recovery_recommendation_db(subject_id)

    if recovery.get("status") != "ok":
        return recovery

    node = get_threat_memory_node_db(subject_id) or {}

    recovery_score = float(recovery.get("recovery_score", 0) or 0)
    residual_threat = float(recovery.get("residual_threat_pressure", 1) or 1)
    recommendation = str(recovery.get("recommendation", "no_recovery") or "no_recovery")

    adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)
    contagion = float(node.get("contagion_score", 0) or 0)
    mutation_score = float(node.get("mutation_score", 0) or 0)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    recovery_confidence = float(node.get("recovery_confidence", 0.5) or 0.5)
    graph_position = float(node.get("graph_position_score", 0) or 0)

    rehabilitation_intensity = {
        "no_recovery": 0.0,
        "monitor_recovery": 0.10,
        "partial_rehabilitation_candidate": 0.25,
        "controlled_rehabilitation_candidate": 0.45,
        "trusted_recovery_candidate": 0.65,
    }.get(recommendation, 0.0)

    relapse_risk = min(
        1.0,
        residual_threat * 0.35
        + mutation_score * 0.20
        + contagion * 0.15
        + quarantine_pressure * 0.15
        + max(0.0, 0.45 - adaptive_trust) * 0.15,
    )

    recovery_abuse_risk = min(
        1.0,
        mutation_score * 0.25
        + residual_threat * 0.25
        + max(0.0, 0.50 - recovery_confidence) * 0.25
        + graph_position * 0.15
        + contagion * 0.10,
    )

    trust_restoration_impact = min(
        1.0,
        rehabilitation_intensity * 0.45
        + recovery_score * 0.35
        + recovery_confidence * 0.20,
    )

    exposure_restoration_impact = min(
        1.0,
        rehabilitation_intensity * 0.50
        + recovery_score * 0.30
        - relapse_risk * 0.20,
    )

    protocol_safety_risk = min(
        1.0,
        relapse_risk * 0.35
        + recovery_abuse_risk * 0.35
        + exposure_restoration_impact * 0.15
        + contagion * 0.15,
    )

    rehabilitation_safety_score = max(
        0.0,
        min(
            1.0,
            recovery_score * 0.45
            + recovery_confidence * 0.25
            + adaptive_trust * 0.15
            - protocol_safety_risk * 0.30
            - recovery_abuse_risk * 0.20,
        ),
    )

    if recommendation == "no_recovery":
        simulation_decision = "do_not_rehabilitate"
    elif rehabilitation_safety_score >= 0.72 and protocol_safety_risk <= 0.30:
        simulation_decision = "safe_for_controlled_rehabilitation"
    elif rehabilitation_safety_score >= 0.52 and protocol_safety_risk <= 0.45:
        simulation_decision = "rehabilitate_cautiously"
    elif rehabilitation_safety_score >= 0.35:
        simulation_decision = "human_review_recommended"
    else:
        simulation_decision = "do_not_rehabilitate"

    return {
        "status": "ok",
        "subject_id": subject_id,
        "recommendation": recommendation,
        "recovery_score": round(recovery_score, 6),
        "residual_threat_pressure": round(residual_threat, 6),
        "rehabilitation_intensity": round(rehabilitation_intensity, 6),
        "impact": {
            "relapse_risk": round(relapse_risk, 6),
            "recovery_abuse_risk": round(recovery_abuse_risk, 6),
            "trust_restoration_impact": round(trust_restoration_impact, 6),
            "exposure_restoration_impact": round(exposure_restoration_impact, 6),
            "protocol_safety_risk": round(protocol_safety_risk, 6),
            "rehabilitation_safety_score": round(rehabilitation_safety_score, 6),
        },
        "simulation_decision": simulation_decision,
        "advisory_only": True,
    }



def record_rehabilitation_impact_simulation_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    simulation = simulate_rehabilitation_impact_db(subject_id)

    if simulation.get("status") != "ok":
        return simulation

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="rehabilitation_impact_simulation",
        reviewer="rehabilitation_simulation_engine",
        reason=simulation.get("simulation_decision"),
        old_status="",
        new_status="",
        metadata=simulation,
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "simulation": simulation,
        "governance_event": event_result,
    }



def compute_temporal_behavior_stability_db(subject_id, window_days=30):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())
    window_seconds = int(window_days or 30) * 86400
    since = now - window_seconds

    cur.execute(f"""
    SELECT *
    FROM seller_governance_events
    WHERE seller_id = {p}
      AND created_at >= {p}
    ORDER BY created_at ASC
    """, (
        subject_id,
        since,
    ))

    events = [dict(r) for r in cur.fetchall()]
    release_conn(conn)

    event_count = len(events)

    if event_count == 0:
        return {
            "status": "ok",
            "subject_id": subject_id,
            "window_days": window_days,
            "behavior_stability_score": 0.5,
            "risk_volatility": 0.0,
            "relapse_velocity": 0.0,
            "trust_consistency": 0.5,
            "temporal_reliability": 0.5,
            "event_count": 0,
            "reason": "insufficient_temporal_history",
            "advisory_only": True,
        }

    risk_events = 0
    recovery_events = 0
    containment_events = 0
    failed_events = 0
    simulation_events = 0

    last_event_ts = None
    event_intervals = []

    for e in events:
        event_type = str(e.get("event_type", "") or "").lower()
        reason = str(e.get("reason", "") or "").lower()
        created_at = int(e.get("created_at", 0) or 0)

        if last_event_ts:
            event_intervals.append(max(0, created_at - last_event_ts))
        last_event_ts = created_at

        if any(w in event_type for w in [
            "risk",
            "controlled_protocol_response",
            "threat",
            "containment",
        ]):
            risk_events += 1

        if any(w in event_type for w in [
            "recovery",
            "rehabilitation",
            "stable_behavior",
            "risk_decay",
        ]):
            recovery_events += 1

        if "containment" in event_type:
            containment_events += 1

        if "failed" in event_type or "failed" in reason:
            failed_events += 1

        if "simulation" in event_type:
            simulation_events += 1

    avg_interval = (
        sum(event_intervals) / len(event_intervals)
        if event_intervals else window_seconds
    )

    event_density = min(1.0, event_count / 20)
    risk_density = min(1.0, risk_events / max(event_count, 1))
    recovery_density = min(1.0, recovery_events / max(event_count, 1))
    failure_density = min(1.0, failed_events / max(event_count, 1))

    # Short intervals between many governance events imply instability.
    interval_instability = max(
        0.0,
        min(1.0, 1.0 - (avg_interval / max(window_seconds, 1)))
    )

    risk_volatility = min(
        1.0,
        risk_density * 0.45
        + event_density * 0.25
        + interval_instability * 0.20
        + failure_density * 0.10,
    )

    relapse_velocity = min(
        1.0,
        risk_events / max(window_days, 1) * 2.5
        + failed_events / max(window_days, 1) * 2.0
        + containment_events * 0.15,
    )

    trust_consistency = max(
        0.0,
        min(
            1.0,
            0.65
            + recovery_density * 0.20
            + simulation_events / max(event_count, 1) * 0.10
            - risk_density * 0.30
            - failure_density * 0.25
            - containment_events * 0.10,
        ),
    )

    behavior_stability_score = max(
        0.0,
        min(
            1.0,
            0.75
            - risk_volatility * 0.35
            - relapse_velocity * 0.25
            + trust_consistency * 0.25
            - event_density * 0.10,
        ),
    )

    temporal_reliability = max(
        0.0,
        min(
            1.0,
            behavior_stability_score * 0.55
            + trust_consistency * 0.30
            + max(0.0, 1.0 - risk_volatility) * 0.15,
        ),
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "window_days": window_days,
        "behavior_stability_score": round(behavior_stability_score, 6),
        "risk_volatility": round(risk_volatility, 6),
        "relapse_velocity": round(relapse_velocity, 6),
        "trust_consistency": round(trust_consistency, 6),
        "temporal_reliability": round(temporal_reliability, 6),
        "event_count": event_count,
        "risk_events": risk_events,
        "recovery_events": recovery_events,
        "containment_events": containment_events,
        "failed_events": failed_events,
        "simulation_events": simulation_events,
        "avg_event_interval_seconds": round(avg_interval, 2),
        "advisory_only": True,
    }



def authorize_rehabilitation_execution_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    simulation = simulate_rehabilitation_impact_db(subject_id)

    if simulation.get("status") != "ok":
        return simulation

    impact = simulation.get("impact") or {}

    rehabilitation_safety_score = float(impact.get("rehabilitation_safety_score", 0) or 0)
    protocol_safety_risk = float(impact.get("protocol_safety_risk", 1) or 1)
    relapse_risk = float(impact.get("relapse_risk", 1) or 1)
    recovery_abuse_risk = float(impact.get("recovery_abuse_risk", 1) or 1)

    recommendation = str(simulation.get("recommendation", "no_recovery") or "no_recovery")
    simulation_decision = str(simulation.get("simulation_decision", "") or "")

    auto_allowed = False
    execution_mode = "advisory_only"
    required_review = False
    reason = "default_rehabilitation_advisory_mode"

    if recommendation == "no_recovery":
        execution_mode = "blocked"
        required_review = True
        reason = "no_recovery_recommended"

    elif (
        simulation_decision == "safe_for_controlled_rehabilitation"
        and rehabilitation_safety_score >= 0.72
        and protocol_safety_risk <= 0.30
        and relapse_risk <= 0.35
        and recovery_abuse_risk <= 0.30
        and recommendation in ["partial_rehabilitation_candidate", "controlled_rehabilitation_candidate"]
    ):
        auto_allowed = True
        execution_mode = "controlled_auto"
        reason = "safe_controlled_rehabilitation"

    elif (
        simulation_decision in ["safe_for_controlled_rehabilitation", "rehabilitate_cautiously", "human_review_recommended"]
        and rehabilitation_safety_score >= 0.45
    ):
        execution_mode = "review_required"
        required_review = True
        reason = "rehabilitation_requires_governance_review"

    else:
        execution_mode = "blocked"
        required_review = True
        reason = "rehabilitation_not_safe"

    event_result = create_seller_governance_event_db(
        seller_id=subject_id,
        event_type="rehabilitation_execution_gate_decision",
        reviewer="rehabilitation_execution_gate",
        reason=reason,
        old_status="",
        new_status="",
        metadata={
            "simulation": simulation,
            "auto_allowed": auto_allowed,
            "execution_mode": execution_mode,
            "required_review": required_review,
            "reason": reason,
        },
    )

    return {
        "status": "ok",
        "subject_id": subject_id,
        "auto_allowed": auto_allowed,
        "execution_mode": execution_mode,
        "required_review": required_review,
        "reason": reason,
        "recommendation": recommendation,
        "simulation_decision": simulation_decision,
        "rehabilitation_safety_score": round(rehabilitation_safety_score, 6),
        "protocol_safety_risk": round(protocol_safety_risk, 6),
        "relapse_risk": round(relapse_risk, 6),
        "recovery_abuse_risk": round(recovery_abuse_risk, 6),
        "governance_event": event_result,
    }




def compute_protocol_systemic_risk_db(window_days=30):
    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())
    since = now - int(window_days or 30) * 86400

    cur.execute("""
    SELECT
        COUNT(*) AS node_count,
        AVG(latent_risk_score) AS avg_latent_risk,
        AVG(mutation_score) AS avg_mutation_score,
        AVG(contagion_score) AS avg_contagion_score,
        AVG(quarantine_pressure) AS avg_quarantine_pressure,
        AVG(adaptive_trust_score) AS avg_adaptive_trust,
        SUM(CASE WHEN latent_risk_score >= 0.65 THEN 1 ELSE 0 END) AS high_risk_nodes
    FROM threat_memory_nodes
    """)

    node_row = cur.fetchone()

    cur.execute("""
    SELECT
        COUNT(*) AS signature_count,
        AVG(emergence_probability) AS avg_emergence_probability,
        AVG(confidence) AS avg_mutation_confidence,
        COUNT(DISTINCT evolution_family) AS mutation_family_count
    FROM adversarial_mutation_signatures
    WHERE status = 'active'
    """)

    mutation_row = cur.fetchone()

    cur.execute(f"""
    SELECT
        COUNT(*) AS event_count,
        SUM(CASE WHEN event_type LIKE '%risk%' THEN 1 ELSE 0 END) AS risk_event_count,
        SUM(CASE WHEN event_type LIKE '%recovery%' OR event_type LIKE '%rehabilitation%' THEN 1 ELSE 0 END) AS recovery_event_count,
        SUM(CASE WHEN event_type LIKE '%simulation%' THEN 1 ELSE 0 END) AS simulation_event_count,
        SUM(CASE WHEN event_type LIKE '%failed%' THEN 1 ELSE 0 END) AS failed_event_count
    FROM seller_governance_events
    WHERE created_at >= {p}
    """, (since,))

    event_row = cur.fetchone()

    cur.execute("""
    SELECT
        COUNT(*) AS cluster_count,
        AVG(cluster_risk_score) AS avg_cluster_risk,
        AVG(coordination_probability) AS avg_coordination_probability,
        SUM(CASE WHEN cluster_risk_score >= 0.50 THEN 1 ELSE 0 END) AS high_risk_clusters
    FROM seller_clusters
    """)

    cluster_row = cur.fetchone()

    cur.execute(f"""
    SELECT
        COUNT(*) AS snapshot_count,
        AVG(cluster_risk_score) AS avg_snapshot_cluster_risk,
        AVG(coordination_probability) AS avg_snapshot_coordination
    FROM cluster_snapshots
    WHERE created_at >= {p}
    """, (since,))

    snapshot_row = cur.fetchone()

    release_conn(conn)

    node_count = int(row_get(node_row, "node_count", 0) or 0)
    high_risk_nodes = int(row_get(node_row, "high_risk_nodes", 0) or 0)

    avg_latent_risk = float(row_get(node_row, "avg_latent_risk", 0) or 0)
    avg_mutation_score = float(row_get(node_row, "avg_mutation_score", 0) or 0)
    avg_contagion_score = float(row_get(node_row, "avg_contagion_score", 0) or 0)
    avg_quarantine_pressure = float(row_get(node_row, "avg_quarantine_pressure", 0) or 0)
    avg_adaptive_trust = float(row_get(node_row, "avg_adaptive_trust", 0.5) or 0.5)

    signature_count = int(row_get(mutation_row, "signature_count", 0) or 0)
    mutation_family_count = int(row_get(mutation_row, "mutation_family_count", 0) or 0)
    avg_emergence_probability = float(row_get(mutation_row, "avg_emergence_probability", 0) or 0)
    avg_mutation_confidence = float(row_get(mutation_row, "avg_mutation_confidence", 0) or 0)

    event_count = int(row_get(event_row, "event_count", 0) or 0)
    risk_event_count = int(row_get(event_row, "risk_event_count", 0) or 0)
    recovery_event_count = int(row_get(event_row, "recovery_event_count", 0) or 0)
    simulation_event_count = int(row_get(event_row, "simulation_event_count", 0) or 0)
    failed_event_count = int(row_get(event_row, "failed_event_count", 0) or 0)

    cluster_count = int(row_get(cluster_row, "cluster_count", 0) or 0)
    high_risk_clusters = int(row_get(cluster_row, "high_risk_clusters", 0) or 0)
    avg_cluster_risk = float(row_get(cluster_row, "avg_cluster_risk", 0) or 0)
    avg_coordination_probability = float(row_get(cluster_row, "avg_coordination_probability", 0) or 0)

    snapshot_count = int(row_get(snapshot_row, "snapshot_count", 0) or 0)
    avg_snapshot_cluster_risk = float(row_get(snapshot_row, "avg_snapshot_cluster_risk", 0) or 0)
    avg_snapshot_coordination = float(row_get(snapshot_row, "avg_snapshot_coordination", 0) or 0)

    cluster_pressure = min(
        1.0,
        avg_cluster_risk * 0.45
        + avg_coordination_probability * 0.35
        + min(high_risk_clusters, 10) / 10 * 0.20,
    )

    contagion_pressure = min(
        1.0,
        avg_contagion_score * 0.60
        + min(high_risk_nodes, 20) / 20 * 0.25
        + avg_quarantine_pressure * 0.15,
    )

    mutation_pressure = min(
        1.0,
        avg_mutation_score * 0.35
        + avg_emergence_probability * 0.30
        + avg_mutation_confidence * 0.20
        + min(mutation_family_count, 8) / 8 * 0.15,
    )

    governance_load = min(
        1.0,
        min(event_count, 100) / 100 * 0.25
        + min(risk_event_count, 50) / 50 * 0.35
        + min(failed_event_count, 20) / 20 * 0.25
        + min(simulation_event_count, 100) / 100 * 0.15,
    )

    recovery_load = min(
        1.0,
        min(recovery_event_count, 50) / 50
    )

    protocol_stability = max(
        0.0,
        min(
            1.0,
            0.75
            + avg_adaptive_trust * 0.20
            - cluster_pressure * 0.18
            - contagion_pressure * 0.22
            - mutation_pressure * 0.25
            - governance_load * 0.15,
        ),
    )

    systemic_risk_score = min(
        1.0,
        cluster_pressure * 0.22
        + contagion_pressure * 0.24
        + mutation_pressure * 0.24
        + governance_load * 0.18
        + max(0.0, 1.0 - protocol_stability) * 0.12,
    )

    if systemic_risk_score >= 0.75:
        systemic_level = "critical"
    elif systemic_risk_score >= 0.55:
        systemic_level = "high"
    elif systemic_risk_score >= 0.35:
        systemic_level = "medium"
    elif systemic_risk_score >= 0.18:
        systemic_level = "low_medium"
    else:
        systemic_level = "low"

    return {
        "status": "ok",
        "window_days": window_days,
        "systemic_risk_score": round(systemic_risk_score, 6),
        "systemic_level": systemic_level,
        "cluster_pressure": round(cluster_pressure, 6),
        "contagion_pressure": round(contagion_pressure, 6),
        "mutation_pressure": round(mutation_pressure, 6),
        "governance_load": round(governance_load, 6),
        "recovery_load": round(recovery_load, 6),
        "protocol_stability": round(protocol_stability, 6),
        "counts": {
            "node_count": node_count,
            "high_risk_nodes": high_risk_nodes,
            "signature_count": signature_count,
            "mutation_family_count": mutation_family_count,
            "event_count": event_count,
            "risk_event_count": risk_event_count,
            "recovery_event_count": recovery_event_count,
            "simulation_event_count": simulation_event_count,
            "failed_event_count": failed_event_count,
            "cluster_count": cluster_count,
            "high_risk_clusters": high_risk_clusters,
            "snapshot_count": snapshot_count,
        },
        "averages": {
            "avg_latent_risk": round(avg_latent_risk, 6),
            "avg_mutation_score": round(avg_mutation_score, 6),
            "avg_contagion_score": round(avg_contagion_score, 6),
            "avg_quarantine_pressure": round(avg_quarantine_pressure, 6),
            "avg_adaptive_trust": round(avg_adaptive_trust, 6),
            "avg_emergence_probability": round(avg_emergence_probability, 6),
            "avg_mutation_confidence": round(avg_mutation_confidence, 6),
            "avg_cluster_risk": round(avg_cluster_risk, 6),
            "avg_coordination_probability": round(avg_coordination_probability, 6),
            "avg_snapshot_cluster_risk": round(avg_snapshot_cluster_risk, 6),
            "avg_snapshot_coordination": round(avg_snapshot_coordination, 6),
        },
        "advisory_only": True,
    }



def compute_protocol_systemic_response_recommendation_db(window_days=30):
    systemic = compute_protocol_systemic_risk_db(
        window_days=window_days
    )

    if systemic.get("status") != "ok":
        return systemic

    systemic_risk = float(systemic.get("systemic_risk_score", 0) or 0)
    cluster_pressure = float(systemic.get("cluster_pressure", 0) or 0)
    contagion_pressure = float(systemic.get("contagion_pressure", 0) or 0)
    mutation_pressure = float(systemic.get("mutation_pressure", 0) or 0)
    governance_load = float(systemic.get("governance_load", 0) or 0)
    recovery_load = float(systemic.get("recovery_load", 0) or 0)
    protocol_stability = float(systemic.get("protocol_stability", 0.5) or 0.5)

    if systemic_risk >= 0.78 or protocol_stability <= 0.25:
        recommendation = "emergency_containment_preparation"
        severity = "critical"

    elif systemic_risk >= 0.62:
        recommendation = "systemic_review"
        severity = "high"

    elif (
        mutation_pressure >= 0.58
        and systemic_risk >= 0.28
    ):
        recommendation = "increase_stake_pressure"
        severity = "medium_high"

    elif contagion_pressure >= 0.45 or cluster_pressure >= 0.45:
        recommendation = "tighten_routing"
        severity = "medium_high"

    elif governance_load >= 0.50:
        recommendation = "increase_monitoring"
        severity = "medium"

    elif recovery_load >= 0.40 and mutation_pressure >= 0.45:
        recommendation = "slow_recovery"
        severity = "medium"

    elif systemic_risk >= 0.18:
        recommendation = "increase_monitoring"
        severity = "low_medium"

    else:
        recommendation = "normal_operation"
        severity = "low"

    recommended_actions = []

    if recommendation == "normal_operation":
        recommended_actions = [
            "continue normal routing",
            "continue periodic systemic monitoring",
        ]

    elif recommendation == "increase_monitoring":
        recommended_actions = [
            "increase systemic telemetry frequency",
            "increase mutation family monitoring",
            "increase graph refresh cadence",
        ]

    elif recommendation == "increase_stake_pressure":
        recommended_actions = [
            "increase minimum stake pressure for risky sellers",
            "increase escrow reserve sensitivity",
            "reduce reputation amplification from new sellers",
            "monitor mutation families with higher priority",
        ]

    elif recommendation == "tighten_routing":
        recommended_actions = [
            "reduce routing exposure for graph-risk clusters",
            "increase consensus requirement for risky clusters",
            "deprioritize sellers with high contagion pressure",
        ]

    elif recommendation == "slow_recovery":
        recommended_actions = [
            "slow automatic rehabilitation",
            "increase recovery review strictness",
            "require longer stability windows before recovery",
        ]

    elif recommendation == "systemic_review":
        recommended_actions = [
            "trigger protocol-wide governance review",
            "increase global stake and escrow buffers",
            "reduce high-risk task routing",
            "increase runtime verification frequency",
        ]

    elif recommendation == "emergency_containment_preparation":
        recommended_actions = [
            "prepare systemic containment controls",
            "freeze unsafe autonomous escalation paths",
            "prepare graph quarantine of high-risk clusters",
            "increase protocol reserve protection",
            "require human governance review before severe action",
        ]

    return {
        "status": "ok",
        "window_days": window_days,
        "recommendation": recommendation,
        "severity": severity,
        "recommended_actions": recommended_actions,
        "systemic": systemic,
        "advisory_only": True,
    }



def record_protocol_systemic_response_recommendation_db(
    window_days=30
):
    recommendation = (
        compute_protocol_systemic_response_recommendation_db(
            window_days=window_days
        )
    )

    if recommendation.get("status") != "ok":
        return recommendation

    systemic = recommendation.get("systemic") or {}

    event_result = create_deduped_seller_governance_event_db(
        seller_id="__protocol_system__",
        event_type="protocol_systemic_response",
        reviewer="autonomous_systemic_governance_engine",
        reason=recommendation.get("recommendation"),
        metadata={
            "window_days": window_days,
            "recommended_actions": recommendation.get(
                "recommended_actions",
                []
            ),
            "systemic_risk_score": systemic.get(
                "systemic_risk_score"
            ),
            "systemic_level": systemic.get(
                "systemic_level"
            ),
            "cluster_pressure": systemic.get(
                "cluster_pressure"
            ),
            "contagion_pressure": systemic.get(
                "contagion_pressure"
            ),
            "mutation_pressure": systemic.get(
                "mutation_pressure"
            ),
            "governance_load": systemic.get(
                "governance_load"
            ),
            "recovery_load": systemic.get(
                "recovery_load"
            ),
            "protocol_stability": systemic.get(
                "protocol_stability"
            ),
            "severity": recommendation.get("severity"),
        },
        dedupe_window_seconds=1800,
    )

    return {
        "status": "ok",
        "event": event_result,
        "event_id": event_result.get("event_id"),
        "recommendation": recommendation,
        "advisory_only": True,
    }



def can_execute_autonomous_action_db(
    subject_id,
    action_type,
    window_seconds=3600,
    max_subject_actions=1,
    max_global_actions=20,
    action_severity=0.0,
    max_subject_severity_budget=0.25,
    max_global_severity_budget=2.0,
):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    action_type = str(action_type or "").strip()

    if not action_type:
        return {"status": "error", "message": "action_type_required"}

    threat_mode = compute_threat_correlated_execution_mode_db(subject_id)

    if threat_mode.get("status") != "ok":
        return threat_mode

    execution_mode = threat_mode.get("execution_mode")
    threat_severity = threat_mode.get("severity")

    # True confirmed threat must not be slowed by anti-loop damping.
    if execution_mode in ["emergency_block", "aggressive_containment"]:
        return {
            "status": "ok",
            "allowed": True,
            "subject_id": subject_id,
            "action_type": action_type,
            "threat_mode": threat_mode,
            "reason": "high_threat_overrides_autonomy_dampening",
        }

    # Weak/noisy signals should be dampened more strictly.
    if execution_mode == "dampened_autonomy":
        max_subject_actions = min(int(max_subject_actions or 1), 1)
        max_global_actions = min(int(max_global_actions or 20), 5)
        max_subject_severity_budget = min(
            float(max_subject_severity_budget or 0.25),
            0.10,
        )
        max_global_severity_budget = min(
            float(max_global_severity_budget or 2.0),
            0.50,
        )

    # Credible threat keeps normal bounded autonomy.
    elif execution_mode in ["controlled_restriction", "enhanced_surveillance"]:
        max_subject_actions = min(int(max_subject_actions or 1), 1)
        max_global_actions = min(int(max_global_actions or 20), 20)

    conn = get_conn()
    cur = conn.cursor()
    p = qmark()

    now = int(time.time())
    since = now - int(window_seconds or 3600)

    cur.execute(f"""
    SELECT COUNT(*) AS count
    FROM seller_governance_events
    WHERE seller_id = {p}
      AND event_type = 'controlled_protocol_response_applied'
      AND reason = {p}
      AND created_at >= {p}
    """, (
        subject_id,
        f"controlled_auto:{action_type}",
        since,
    ))

    subject_row = cur.fetchone()
    subject_count = int(row_get(subject_row, "count", 0) or 0)

    cur.execute(f"""
    SELECT COUNT(*) AS count
    FROM seller_governance_events
    WHERE event_type = 'controlled_protocol_response_applied'
      AND created_at >= {p}
    """, (
        since,
    ))

    global_row = cur.fetchone()
    global_count = int(row_get(global_row, "count", 0) or 0)

    cur.execute(f"""
    SELECT metadata
    FROM seller_governance_events
    WHERE seller_id = {p}
      AND event_type = 'controlled_protocol_response_applied'
      AND created_at >= {p}
    """, (
        subject_id,
        since,
    ))

    subject_severity_sum = 0.0

    for row in cur.fetchall():
        try:
            metadata = json.loads(row_get(row, "metadata", "{}") or "{}")
            subject_severity_sum += float(
                metadata.get("applied_severity", 0) or 0
            )
        except Exception:
            pass

    cur.execute(f"""
    SELECT metadata
    FROM seller_governance_events
    WHERE event_type = 'controlled_protocol_response_applied'
      AND created_at >= {p}
    """, (
        since,
    ))

    global_severity_sum = 0.0

    for row in cur.fetchall():
        try:
            metadata = json.loads(row_get(row, "metadata", "{}") or "{}")
            global_severity_sum += float(
                metadata.get("applied_severity", 0) or 0
            )
        except Exception:
            pass

    release_conn(conn)

    action_severity = max(
        0.0,
        min(float(action_severity or 0), 1.0)
    )

    projected_subject_severity = (
        subject_severity_sum + action_severity
    )

    projected_global_severity = (
        global_severity_sum + action_severity
    )

    if subject_count >= int(max_subject_actions or 1):
        return {
            "status": "blocked",
            "reason": "subject_action_cooldown",
            "subject_id": subject_id,
            "action_type": action_type,
            "subject_count": subject_count,
            "window_seconds": window_seconds,
        }

    if global_count >= int(max_global_actions or 20):
        return {
            "status": "blocked",
            "reason": "global_autonomous_execution_count_budget_exhausted",
            "subject_id": subject_id,
            "action_type": action_type,
            "global_count": global_count,
            "window_seconds": window_seconds,
        }

    if projected_subject_severity > float(max_subject_severity_budget or 0.25):
        return {
            "status": "blocked",
            "reason": "subject_autonomous_severity_budget_exhausted",
            "subject_id": subject_id,
            "action_type": action_type,
            "action_severity": action_severity,
            "subject_severity_sum": round(subject_severity_sum, 6),
            "projected_subject_severity": round(projected_subject_severity, 6),
            "max_subject_severity_budget": max_subject_severity_budget,
            "window_seconds": window_seconds,
        }

    if projected_global_severity > float(max_global_severity_budget or 2.0):
        return {
            "status": "blocked",
            "reason": "global_autonomous_severity_budget_exhausted",
            "subject_id": subject_id,
            "action_type": action_type,
            "action_severity": action_severity,
            "global_severity_sum": round(global_severity_sum, 6),
            "projected_global_severity": round(projected_global_severity, 6),
            "max_global_severity_budget": max_global_severity_budget,
            "window_seconds": window_seconds,
        }

    return {
        "status": "ok",
        "allowed": True,
        "subject_id": subject_id,
        "action_type": action_type,
        "action_severity": action_severity,
        "subject_count": subject_count,
        "global_count": global_count,
        "subject_severity_sum": round(subject_severity_sum, 6),
        "global_severity_sum": round(global_severity_sum, 6),
        "projected_subject_severity": round(projected_subject_severity, 6),
        "projected_global_severity": round(projected_global_severity, 6),
        "max_subject_severity_budget": max_subject_severity_budget,
        "max_global_severity_budget": max_global_severity_budget,
        "window_seconds": window_seconds,
        "threat_mode": threat_mode,
    }



def compute_threat_correlated_execution_mode_db(subject_id):
    if not subject_id:
        return {"status": "error", "message": "subject_id_required"}

    seller = get_seller_db(subject_id) or {}
    node = get_threat_memory_node_db(subject_id) or {}
    mutation = compute_adversarial_mutation_pressure_db(subject_id)
    cluster = detect_seller_cluster_db(subject_id)

    memories = get_active_threat_memory_db(
        scope="seller",
        subject_id=subject_id,
        limit=50,
    )

    seller_status = str(seller.get("seller_status", "") or "").lower()
    risk_score = float(seller.get("risk_score", 0) or 0)

    memory_score = float(node.get("memory_score", 0) or 0)
    latent_risk = float(node.get("latent_risk_score", 0) or 0)
    contagion_score = float(node.get("contagion_score", 0) or 0)
    quarantine_pressure = float(node.get("quarantine_pressure", 0) or 0)
    adaptive_trust = float(node.get("adaptive_trust_score", 0.5) or 0.5)

    mutation_pressure = float(
        mutation.get("mutation_pressure_score", 0) or 0
    )

    cluster_risk = float(
        cluster.get("cluster_risk_score", 0) or 0
    ) if cluster else 0.0

    coordination = float(
        cluster.get("coordination_probability", 0) or 0
    ) if cluster else 0.0

    max_confidence = 0.0
    critical_count = 0
    high_count = 0
    confirmed_like_count = 0

    for m in memories:
        confidence = float(m.get("confidence", 0) or 0)
        threat_level = str(m.get("threat_level", "") or "").lower()
        attack_vector = str(m.get("attack_vector", "") or "").lower()

        max_confidence = max(max_confidence, confidence)

        if threat_level == "critical":
            critical_count += 1

        if threat_level in ["high", "critical"]:
            high_count += 1

        if any(w in attack_vector for w in [
            "confirmed fraud",
            "fraud",
            "scam",
            "steal",
            "theft",
            "buyer harm",
            "malicious",
        ]):
            confirmed_like_count += 1

    threat_certainty_score = min(
        1.0,
        max_confidence * 0.30
        + memory_score * 0.16
        + latent_risk * 0.16
        + mutation_pressure * 0.16
        + cluster_risk * 0.10
        + quarantine_pressure * 0.08
        + min(high_count, 5) / 5 * 0.04,
    )

    threat_intensity_score = min(
        1.0,
        risk_score * 0.18
        + latent_risk * 0.18
        + mutation_pressure * 0.20
        + contagion_score * 0.12
        + quarantine_pressure * 0.14
        + cluster_risk * 0.10
        + coordination * 0.08,
    )

    if (
        seller_status in ["banned", "rejected", "contained"]
        or confirmed_like_count >= 2
        or (
            critical_count >= 1
            and max_confidence >= 0.85
        )
    ):
        execution_mode = "emergency_block"
        severity = "critical"
        reason = "confirmed_or_critical_threat"

    elif (
        threat_certainty_score >= 0.78
        and threat_intensity_score >= 0.70
    ):
        execution_mode = "aggressive_containment"
        severity = "high"
        reason = "high_certainty_high_intensity_threat"

    elif (
        threat_certainty_score >= 0.62
        and (
            mutation_pressure >= 0.60
            or cluster_risk >= 0.55
            or quarantine_pressure >= 0.60
        )
    ):
        execution_mode = "controlled_restriction"
        severity = "medium_high"
        reason = "correlated_mutation_or_cluster_threat"

    elif (
        threat_certainty_score >= 0.45
        or threat_intensity_score >= 0.45
        or seller_status in ["watchlist", "restricted"]
    ):
        execution_mode = "enhanced_surveillance"
        severity = "medium"
        reason = "credible_but_not_confirmed_threat"

    elif (
        max_confidence < 0.55
        and threat_intensity_score < 0.35
        and adaptive_trust >= 0.45
    ):
        execution_mode = "dampened_autonomy"
        severity = "low"
        reason = "weak_signal_prevent_autonomous_overreaction"

    else:
        execution_mode = "normal_autonomy"
        severity = "low_medium"
        reason = "normal_bounded_autonomy"

    return {
        "status": "ok",
        "subject_id": subject_id,
        "execution_mode": execution_mode,
        "severity": severity,
        "reason": reason,
        "threat_certainty_score": round(threat_certainty_score, 6),
        "threat_intensity_score": round(threat_intensity_score, 6),
        "signals": {
            "seller_status": seller_status,
            "risk_score": round(risk_score, 6),
            "memory_score": round(memory_score, 6),
            "latent_risk_score": round(latent_risk, 6),
            "mutation_pressure_score": round(mutation_pressure, 6),
            "contagion_score": round(contagion_score, 6),
            "quarantine_pressure": round(quarantine_pressure, 6),
            "adaptive_trust_score": round(adaptive_trust, 6),
            "cluster_risk_score": round(cluster_risk, 6),
            "coordination_probability": round(coordination, 6),
            "max_threat_confidence": round(max_confidence, 6),
            "critical_memory_count": critical_count,
            "high_memory_count": high_count,
            "confirmed_like_count": confirmed_like_count,
        },
        "advisory_only": True,
    }
