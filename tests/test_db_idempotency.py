import sqlite3

from iat.api import db


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
