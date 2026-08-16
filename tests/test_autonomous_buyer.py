import base64
import copy

import pytest
from solders.signature import Signature
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import VersionedTransaction

from iat.autonomous_buyer import (
    AutonomousBuyerError,
    AutonomousBuyerRunner,
    BuyerRunnerPolicy,
)


WALLET_KEYPAIR = Keypair.from_seed(bytes([7]) * 32)
WALLET = str(WALLET_KEYPAIR.pubkey())


def transaction_for(fee_payer=WALLET_KEYPAIR.pubkey()):
    message = Message.new_with_blockhash([], fee_payer, Hash.default())
    transaction = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(transaction)).decode()


class Response:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return copy.deepcopy(self._body)


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class Approval:
    def __init__(self, approved=True):
        self.approved = approved
        self.reviews = []

    def approve(self, review):
        self.reviews.append(dict(review))
        return self.approved


class Wallet:
    wallet_address = WALLET

    def __init__(self):
        self.calls = []

    def sign_and_broadcast(self, transaction_base64, review):
        self.calls.append((transaction_base64, dict(review)))
        return str(Signature.default())


def prepared_response(**overrides):
    prepared = {
        "status": "buyer_intent_checkout_prepared",
        "autonomous": True,
        "policy_enforced": True,
        "buyer_signature_required": True,
        "transaction_submitted": False,
        "funds_moved": False,
        "quote_id": "uq_1",
        "expires_at": 2_000_000_100,
        "transaction_base64": transaction_for(),
        "simulation": {"status": "succeeded", "units_consumed": 1000},
        "review": {
            "cluster": "solana:devnet",
            "fee_payer": WALLET,
            "input": {"asset": "USDC", "amount_minor": 1_000_000},
            "minimum_iat_output": {"asset": "IAT", "amount_minor": 10},
            "program_id": "program",
            "treasury_vault": "vault",
            "iat_destination": "destination",
            "network_fee": "estimated_by_wallet",
        },
    }
    prepared.update(overrides)
    return prepared


def runner(session, *, approval=None, wallet=None, policy=None):
    return AutonomousBuyerRunner(
        "https://iat.example",
        access_token="ias_test_access_token_long_enough",
        wallet=wallet or Wallet(),
        approval=approval or Approval(),
        policy=policy,
        session=session,
    )


def test_runner_signs_only_after_validation_and_explicit_approval():
    wallet = Wallet()
    approval = Approval()
    session = Session(
        [
            Response({"next_action": "buyer_sign_and_broadcast", "result": prepared_response()}),
            Response({"status": "buyer_intent_checkout_submitted", "quote_id": "uq_1"}),
        ]
    )
    result = runner(session, approval=approval, wallet=wallet).step("bid_test_decision")
    assert result["status"] == "buyer_intent_checkout_submitted"
    assert len(approval.reviews) == 1
    assert len(wallet.calls) == 1
    assert len(session.calls) == 2
    assert session.calls[1][2]["json"]["quote_id"] == "uq_1"
    assert "access_token" not in str(approval.reviews[0])


def test_runner_rejection_never_calls_wallet_or_submit():
    wallet = Wallet()
    session = Session(
        [Response({"next_action": "buyer_sign_and_broadcast", "result": prepared_response()})]
    )
    result = runner(session, approval=Approval(False), wallet=wallet).step("bid_test_decision")
    assert result["status"] == "buyer_signature_not_approved"
    assert wallet.calls == []
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ({"policy_enforced": False}, "prepared_transaction_safety_flags_invalid"),
        ({"transaction_submitted": True}, "prepared_transaction_safety_flags_invalid"),
        ({"simulation": {"status": "failed"}}, "transaction_simulation_not_succeeded"),
        ({"review": {"cluster": "solana:mainnet", "fee_payer": WALLET}}, "transaction_cluster_not_allowed"),
        ({"review": {"cluster": "solana:devnet", "fee_payer": "Attacker"}}, "transaction_fee_payer_mismatch"),
        ({"transaction_base64": "not-base64"}, "prepared_transaction_encoding_invalid"),
        ({"transaction_base64": transaction_for(Keypair.from_seed(bytes([8]) * 32).pubkey())}, "transaction_fee_payer_mismatch"),
    ],
)
def test_runner_fails_closed_before_wallet_call(change, code):
    wallet = Wallet()
    session = Session(
        [Response({"next_action": "buyer_sign_and_broadcast", "result": prepared_response(**change)})]
    )
    with pytest.raises(AutonomousBuyerError, match=code):
        runner(session, wallet=wallet).step("bid_test_decision")
    assert wallet.calls == []


def test_runner_returns_wait_state_without_signing():
    wallet = Wallet()
    waiting = {"status": "buyer_intent_waiting", "next_action": "wait_for_delivery"}
    result = runner(Session([Response(waiting)]), wallet=wallet).step("bid_test_decision")
    assert result == waiting
    assert wallet.calls == []


def test_runner_recovers_prepared_unsigned_intent_after_restart():
    wallet = Wallet()
    session = Session(
        [
            Response({"status": "buyer_intent_waiting", "next_action": "buyer_sign_and_broadcast"}),
            Response(prepared_response()),
            Response({"status": "buyer_intent_checkout_submitted", "quote_id": "uq_1"}),
        ]
    )
    result = runner(session, wallet=wallet).step("bid_test_decision")
    assert result["status"] == "buyer_intent_checkout_submitted"
    assert session.calls[1][1].endswith("/buyer/intents/checkout/prepare")
    assert len(wallet.calls) == 1


def test_runner_rejects_http_for_remote_api_and_mainnet_by_default():
    with pytest.raises(ValueError, match="HTTPS"):
        AutonomousBuyerRunner(
            "http://iat.example",
            access_token="ias_test_access_token_long_enough",
            wallet=Wallet(),
            approval=Approval(),
        )
    with pytest.raises(AutonomousBuyerError, match="transaction_cluster_not_allowed"):
        runner(
            Session(
                [
                    Response(
                        {
                            "next_action": "buyer_sign_and_broadcast",
                            "result": prepared_response(
                                review={"cluster": "solana:mainnet", "fee_payer": WALLET}
                            ),
                        }
                    )
                ]
            ),
            policy=BuyerRunnerPolicy(),
        ).step("bid_test_decision")


def test_runner_creates_and_commits_selected_intent_idempotently():
    session = Session(
        [
            Response(
                {
                    "intent_decision_id": "bid_test_decision",
                    "selection": {"selected": {"candidate_id": "agent_1"}},
                }
            ),
            Response({"order_id": "order_1"}),
        ]
    )
    result = runner(session).create_intent(
        service="web_research",
        goal="Produce a cited autonomous market report",
        maximum_price=2,
        idempotency_key="buyer-intent-0001",
    )
    assert result["status"] == "buyer_intent_created"
    assert result["order_id"] == "order_1"
    assert session.calls[0][2]["headers"]["Idempotency-Key"] == "buyer-intent-0001"
    assert session.calls[1][2]["json"] == {"intent_decision_id": "bid_test_decision"}


def test_runner_does_not_commit_intent_without_selection():
    session = Session(
        [Response({"intent_decision_id": "bid_no_match", "selection": {"selected": None}})]
    )
    result = runner(session).create_intent(
        service="web_research",
        goal="Produce a cited autonomous market report",
        maximum_price=2,
        idempotency_key="buyer-intent-0002",
    )
    assert result["status"] == "buyer_intent_has_no_selection"
    assert len(session.calls) == 1


def test_runner_opens_result_only_after_lifecycle_is_complete():
    waiting_session = Session(
        [Response({"next_action": "wait_for_delivery", "poll_after_seconds": 5})]
    )
    waiting = runner(waiting_session).open_result("bid_test_decision")
    assert waiting["status"] == "buyer_result_not_ready"
    assert len(waiting_session.calls) == 1

    ready_session = Session(
        [
            Response(
                {
                    "next_action": "open_delivery_inbox",
                    "checkout": {"quote_id": "uq_1"},
                }
            ),
            Response({"status": "wallet_inbox_item_opened", "inbox": {"result": "done"}}),
        ]
    )
    ready = runner(ready_session).open_result("bid_test_decision")
    assert ready["inbox"]["result"] == "done"
    assert ready_session.calls[1][0] == "GET"
