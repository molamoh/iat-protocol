import sqlite3

from iat.api import db


def test_postgres_uses_a_thread_safe_connection_pool(monkeypatch):
    connection = object()
    created = {}

    class FakeThreadedPool:
        def __init__(self, minimum, maximum, url, **kwargs):
            created.update(
                minimum=minimum,
                maximum=maximum,
                url=url,
                kwargs=kwargs,
            )

        def getconn(self):
            return connection

    monkeypatch.setattr(db, "USE_POSTGRES", True)
    monkeypatch.setattr(db, "DATABASE_URL", "postgresql://example/test")
    monkeypatch.setattr(db, "pool", None)
    monkeypatch.setattr(db, "ThreadedConnectionPool", FakeThreadedPool)

    assert db.get_conn() is connection
    assert created["minimum"] == 1
    assert created["maximum"] == 20
    assert created["url"] == "postgresql://example/test"
    assert created["kwargs"]["cursor_factory"] is db.RealDictCursor


def test_transaction_signature_claim_is_atomic(tmp_path, monkeypatch):
    database = tmp_path / "idempotency.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE processed_txs (
            tx_signature TEXT PRIMARY KEY,
            processed_at INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(db, "USE_POSTGRES", False)

    assert db.save_processed_tx_db("same-signature") is True
    assert db.save_processed_tx_db("same-signature") is False


def test_schema_initialization_records_version(tmp_path, monkeypatch):
    database = tmp_path / "schema.sqlite"
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(db, "USE_POSTGRES", False)

    db.init_db()

    connection = sqlite3.connect(database)
    version = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    connection.close()

    assert version == (db.SCHEMA_VERSION,)
