import hashlib
import json

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

import iat.goia.partnership_http as partnership_http


def _proposal():
    return {
        "contract_version": "goia_partnership_proposal_v1",
        "proposal_id": "gpr_" + "a" * 32,
        "opportunity_id": "gpo_" + "b" * 32,
        "prospect_id": "gpp_" + "c" * 32,
        "provider_id": "gop_provider_001",
        "request_endpoint": "https://merchant.example/goia-partnership",
        "relationship_type": "affiliate",
        "market": {"kind": "hosting", "country": "FR", "currency": "EUR"},
        "aggregate_evidence": {
            "demand_count": 10,
            "unmet_count": 8,
            "current_offer_count": 1,
            "gap_score": 82,
        },
        "created_at": 1_000,
        "expires_at": 2_000,
        "raw_queries_included": False,
        "buyer_identity_included": False,
    }


class Response:
    def __init__(self, payload, *, status_code=200, peer_ip="93.184.216.34"):
        self.body = json.dumps(payload).encode()
        self.status_code = status_code
        self.peer_ip = peer_ip
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(self.body)),
        }

    def iter_content(self, chunk_size):
        yield self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_production_transport_pins_tls_peer_before_sending(monkeypatch):
    events = []

    class RawSocket:
        def close(self):
            events.append("raw_closed")

    class TLSSocket:
        def getpeername(self):
            events.append("peer_verified")
            return ("93.184.216.34", 443)

    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            assert server_hostname == "merchant.example"
            events.append("tls_verified")
            return TLSSocket()

    class HTTPResponse:
        status = 200

        def getheader(self, name):
            return None

        def getheaders(self):
            return [("Content-Type", "application/json")]

        def read(self, maximum):
            return b'{"ok":true}'

    class Connection:
        def __init__(self, host, *, port, timeout, context):
            self.sock = None

        def request(self, method, path, *, body, headers):
            assert events == ["tcp_connected", "tls_verified", "peer_verified"]
            events.append("body_sent")

        def getresponse(self):
            return HTTPResponse()

        def close(self):
            events.append("closed")

    monkeypatch.setattr(
        partnership_http.socket,
        "create_connection",
        lambda address, timeout: events.append("tcp_connected") or RawSocket(),
    )
    monkeypatch.setattr(
        partnership_http.ssl,
        "create_default_context",
        lambda: Context(),
    )
    monkeypatch.setattr(
        partnership_http.http.client,
        "HTTPSConnection",
        Connection,
    )

    status, headers, body = partnership_http._post_pinned_https(
        "https://merchant.example/goia-partnership",
        target={"resolved_addresses": ["93.184.216.34"]},
        body=b"proposal",
        headers={"Content-Type": "application/json"},
    )

    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body == b'{"ok":true}'
    assert events.index("peer_verified") < events.index("body_sent")


def test_signed_request_is_canonical_and_ed25519_verifiable(monkeypatch):
    keypair = Keypair()
    monkeypatch.setenv(
        "IAT_GOIA_PARTNERSHIP_SIGNING_KEY",
        str(keypair),
    )

    body, headers = partnership_http.build_signed_request(_proposal(), now=1_100)

    assert headers["Idempotency-Key"] == _proposal()["proposal_id"]
    assert headers["X-GOIA-Key-Id"] == str(keypair.pubkey())
    assert headers["X-GOIA-Content-SHA256"] == hashlib.sha256(body).hexdigest()
    signing_input = (
        f"1100\n{_proposal()['proposal_id']}\n"
        f"{headers['X-GOIA-Content-SHA256']}"
    ).encode()
    assert Signature.from_string(headers["X-GOIA-Signature"]).verify(
        Pubkey.from_string(headers["X-GOIA-Key-Id"]),
        signing_input,
    )
    assert json.loads(body)["buyer_identity_included"] is False


def test_secure_adapter_accepts_only_matching_bounded_acknowledgement(monkeypatch):
    keypair = Keypair()
    monkeypatch.setenv("IAT_GOIA_PARTNERSHIP_SIGNING_KEY", str(keypair))
    monkeypatch.setattr(
        partnership_http,
        "validate_public_runtime_url",
        lambda url: {
            "hostname": "merchant.example",
            "resolved_addresses": ["93.184.216.34"],
        },
    )
    acknowledgement = {
        "contract_version": "goia_partnership_ack_v1",
        "proposal_id": _proposal()["proposal_id"],
        "status": "received",
        "received_at": 1_101,
    }
    session = Session(Response(acknowledgement))

    result = partnership_http.send_partnership_proposal(
        {"endpoint": _proposal()["request_endpoint"], "payload": _proposal()},
        session=session,
        now=1_100,
    )

    assert result["delivered"] is True
    assert result["receipt"]["status"] == "received"
    _, request = session.calls[0]
    assert request["allow_redirects"] is False
    assert request["stream"] is True
    assert request["headers"]["X-GOIA-Signature-Algorithm"] == "ed25519"


def test_secure_adapter_rejects_dns_rebinding_and_wrong_acknowledgement(monkeypatch):
    monkeypatch.setenv("IAT_GOIA_PARTNERSHIP_SIGNING_KEY", str(Keypair()))
    monkeypatch.setattr(
        partnership_http,
        "validate_public_runtime_url",
        lambda url: {
            "hostname": "merchant.example",
            "resolved_addresses": ["93.184.216.34"],
        },
    )
    acknowledgement = {
        "contract_version": "goia_partnership_ack_v1",
        "proposal_id": "gpr_" + "d" * 32,
        "status": "received",
        "received_at": 1_101,
    }
    rebound = Session(Response(acknowledgement, peer_ip="8.8.8.8"))

    rebound_result = partnership_http.send_partnership_proposal(
        {"endpoint": _proposal()["request_endpoint"], "payload": _proposal()},
        session=rebound,
        now=1_100,
    )
    mismatch = Session(Response(acknowledgement))
    mismatch_result = partnership_http.send_partnership_proposal(
        {"endpoint": _proposal()["request_endpoint"], "payload": _proposal()},
        session=mismatch,
        now=1_100,
    )

    assert rebound_result["delivered"] is False
    assert rebound_result["retryable"] is False
    assert rebound_result["error_code"] == "connected_peer_resolution_mismatch"
    assert mismatch_result["delivered"] is False
    assert mismatch_result["error_code"] == "acknowledgement_proposal_mismatch"
