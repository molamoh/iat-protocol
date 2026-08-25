import pytest

from iat.api import db
from iat.hosted_buyer_connector import (
    authenticate_hosted_buyer_connector,
    rotate_hosted_buyer_connector_key,
)
from iat.hosted_buyer_registry import register_hosted_buyer_agent


WALLET = "BSNCPxSJZqgo34xf2JfCjQ83JcuQgzs6sqAziNYyQU3Q"


@pytest.fixture()
def connector_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "hosted-connectors.sqlite")
    monkeypatch.setattr(db, "USE_POSTGRES", False)
    db.init_db()


def test_rotation_revokes_previous_key_and_never_returns_digest(connector_database):
    agent = register_hosted_buyer_agent(
        buyer_wallet=WALLET, runtime_connector_id="connector-auth", now=100
    )
    first = rotate_hosted_buyer_connector_key(agent["buyer_agent_id"], now=100)
    assert authenticate_hosted_buyer_connector(first["connector_key"], now=101)["buyer_agent_id"] == agent["buyer_agent_id"]
    second = rotate_hosted_buyer_connector_key(agent["buyer_agent_id"], now=102)
    assert authenticate_hosted_buyer_connector(first["connector_key"], now=103) is None
    assert authenticate_hosted_buyer_connector(second["connector_key"], now=103)["buyer_agent_id"] == agent["buyer_agent_id"]
    assert "key_digest" not in second

